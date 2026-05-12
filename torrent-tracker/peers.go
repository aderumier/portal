package main

import (
	"context"
	"crypto/rand"
	"encoding/binary"
	"encoding/hex"
	"fmt"
	"net"
	"strconv"
	"strings"
	"time"

	"github.com/redis/go-redis/v9"
)

// InfoHash is a 20-byte SHA1 torrent identifier.
type InfoHash [20]byte

// Peer is a single BitTorrent peer.
type Peer struct {
	ID       [20]byte
	IP       net.IP
	Port     uint16
	Complete bool // true = seeder (left == 0)
}

// PeerStore manages peers in Redis.
//
// Per info_hash two keys are used:
//
//	{prefix}swarm:{ih_hex}    sorted set  score=unix_expiry  member=peer_id_hex
//	{prefix}swarm:{ih_hex}:d  hash        field=peer_id_hex  value=ip|port|complete
//
// UDP access and connection IDs also live in Redis under the same prefix.
type PeerStore struct {
	rdb    *redis.Client
	prefix string
	ttl    time.Duration
}

func NewPeerStore(rdb *redis.Client, prefix string, ttl time.Duration) *PeerStore {
	return &PeerStore{rdb: rdb, prefix: prefix, ttl: ttl}
}

func (ps *PeerStore) swarmKey(ih InfoHash) string {
	return ps.prefix + "swarm:" + hex.EncodeToString(ih[:])
}
func (ps *PeerStore) dataKey(ih InfoHash) string {
	return ps.prefix + "swarm:" + hex.EncodeToString(ih[:]) + ":d"
}

// Upsert adds or refreshes a peer.
func (ps *PeerStore) Upsert(ctx context.Context, ih InfoHash, p *Peer) error {
	pid := hex.EncodeToString(p.ID[:])
	complete := "0"
	if p.Complete {
		complete = "1"
	}
	// Use | as separator so IPv6 addresses (which contain :) are unambiguous.
	val := fmt.Sprintf("%s|%d|%s", p.IP.String(), p.Port, complete)
	expiry := float64(time.Now().Add(ps.ttl).Unix())

	pipe := ps.rdb.TxPipeline()
	pipe.ZAdd(ctx, ps.swarmKey(ih), redis.Z{Score: expiry, Member: pid})
	pipe.HSet(ctx, ps.dataKey(ih), pid, val)
	_, err := pipe.Exec(ctx)
	return err
}

// Remove deletes a peer on a "stopped" event.
func (ps *PeerStore) Remove(ctx context.Context, ih InfoHash, peerID [20]byte) error {
	pid := hex.EncodeToString(peerID[:])
	pipe := ps.rdb.TxPipeline()
	pipe.ZRem(ctx, ps.swarmKey(ih), pid)
	pipe.HDel(ctx, ps.dataKey(ih), pid)
	_, err := pipe.Exec(ctx)
	return err
}

// GetPeers returns up to numWant active peers, excluding the requesting peer.
func (ps *PeerStore) GetPeers(ctx context.Context, ih InfoHash, numWant int, exclude [20]byte) ([]*Peer, error) {
	now := strconv.FormatInt(time.Now().Unix(), 10)
	excludePID := hex.EncodeToString(exclude[:])

	// Lazy-expire stale entries (non-blocking best-effort).
	ps.rdb.ZRemRangeByScore(ctx, ps.swarmKey(ih), "-inf", "("+now)

	pids, err := ps.rdb.ZRangeByScore(ctx, ps.swarmKey(ih), &redis.ZRangeBy{
		Min:   now,
		Max:   "+inf",
		Count: int64(numWant) + 1, // +1 to absorb the excluded peer
	}).Result()
	if err != nil {
		return nil, err
	}

	filtered := make([]string, 0, len(pids))
	for _, pid := range pids {
		if pid != excludePID {
			filtered = append(filtered, pid)
		}
	}
	if numWant > 0 && len(filtered) > numWant {
		filtered = filtered[:numWant]
	}
	if len(filtered) == 0 {
		return nil, nil
	}

	vals, err := ps.rdb.HMGet(ctx, ps.dataKey(ih), filtered...).Result()
	if err != nil {
		return nil, err
	}

	peers := make([]*Peer, 0, len(vals))
	for i, v := range vals {
		if v == nil {
			continue
		}
		p, err := decodePeer(filtered[i], v.(string))
		if err != nil {
			continue
		}
		peers = append(peers, p)
	}
	return peers, nil
}

// Stats returns seeder and leecher counts for an info_hash.
func (ps *PeerStore) Stats(ctx context.Context, ih InfoHash) (complete, incomplete int) {
	now := strconv.FormatInt(time.Now().Unix(), 10)
	pids, err := ps.rdb.ZRangeByScore(ctx, ps.swarmKey(ih), &redis.ZRangeBy{
		Min: now, Max: "+inf",
	}).Result()
	if err != nil || len(pids) == 0 {
		return
	}
	vals, err := ps.rdb.HMGet(ctx, ps.dataKey(ih), pids...).Result()
	if err != nil {
		return
	}
	for _, v := range vals {
		if v == nil {
			continue
		}
		if strings.HasSuffix(v.(string), "|1") {
			complete++
		} else {
			incomplete++
		}
	}
	return
}

// GrantUDPAccess marks an IP as allowed for UDP announces for 24 h.
// Called after every successful HTTP announce so UDP stays in sync.
func (ps *PeerStore) GrantUDPAccess(ctx context.Context, ip string) {
	ps.rdb.Set(ctx, ps.prefix+"udp:"+ip, "1", 24*time.Hour)
}

// CheckUDPAccess returns true if the IP has a valid UDP access grant.
func (ps *PeerStore) CheckUDPAccess(ctx context.Context, ip string) bool {
	n, _ := ps.rdb.Exists(ctx, ps.prefix+"udp:"+ip).Result()
	return n > 0
}

// StoreConnID persists a UDP connection_id for 2 minutes (BEP 15 validity window).
func (ps *PeerStore) StoreConnID(ctx context.Context, connID uint64) {
	ps.rdb.Set(ctx, fmt.Sprintf("%sconn:%016x", ps.prefix, connID), "1", 2*time.Minute)
}

// ValidConnID returns true if the connection_id was issued by this tracker and
// has not yet expired.
func (ps *PeerStore) ValidConnID(ctx context.Context, connID uint64) bool {
	n, _ := ps.rdb.Exists(ctx, fmt.Sprintf("%sconn:%016x", ps.prefix, connID)).Result()
	return n > 0
}

// RandomConnID generates a cryptographically random 64-bit connection_id.
func RandomConnID() uint64 {
	var b [8]byte
	rand.Read(b[:]) //nolint:errcheck — crypto/rand.Read never errors on Linux
	return binary.BigEndian.Uint64(b[:])
}

// decodePeer rebuilds a Peer from the pidHex key and "ip|port|complete" value.
func decodePeer(pidHex, data string) (*Peer, error) {
	pidBytes, err := hex.DecodeString(pidHex)
	if err != nil || len(pidBytes) != 20 {
		return nil, fmt.Errorf("invalid peer_id hex")
	}
	// SplitN(3) is safe for IPv6 addresses because | is not used in IP notation.
	parts := strings.SplitN(data, "|", 3)
	if len(parts) != 3 {
		return nil, fmt.Errorf("invalid peer data: %q", data)
	}
	ip := net.ParseIP(parts[0])
	if ip == nil {
		return nil, fmt.Errorf("invalid IP: %s", parts[0])
	}
	port, err := strconv.ParseUint(parts[1], 10, 16)
	if err != nil {
		return nil, fmt.Errorf("invalid port: %s", parts[1])
	}
	p := &Peer{IP: ip, Port: uint16(port), Complete: parts[2] == "1"}
	copy(p.ID[:], pidBytes)
	return p, nil
}
