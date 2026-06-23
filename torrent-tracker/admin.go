package main

import (
	"context"
	"encoding/json"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/redis/go-redis/v9"
)

// SwarmSummary holds seeder/leecher counts for one info_hash.
type SwarmSummary struct {
	InfoHash string `json:"info_hash"`
	Seeders  int    `json:"seeders"`
	Leechers int    `json:"leechers"`
}

// SwarmPeerInfo describes a single peer for the admin API.
type SwarmPeerInfo struct {
	PeerID string `json:"peer_id"`
	IP     string `json:"ip"`
	Port   int    `json:"port"`
	Seeder bool   `json:"seeder"`
}

// ListSwarms scans every swarm and returns active seeder/leecher counts.
// Mirrors the logic the FastAPI backend previously ran against Redis directly.
func (ps *PeerStore) ListSwarms(ctx context.Context) ([]SwarmSummary, error) {
	nowStr := strconv.FormatInt(time.Now().Unix(), 10)

	// Collect swarm sorted-set keys (skip the ":d" detail hashes).
	var swarmKeys []string
	var cursor uint64
	match := ps.prefix + "swarm:*"
	for {
		keys, next, err := ps.rdb.Scan(ctx, cursor, match, 500).Result()
		if err != nil {
			return nil, err
		}
		for _, k := range keys {
			if !strings.HasSuffix(k, ":d") {
				swarmKeys = append(swarmKeys, k)
			}
		}
		cursor = next
		if cursor == 0 {
			break
		}
	}
	if len(swarmKeys) == 0 {
		return nil, nil
	}

	// Pipeline 1: active peer IDs per swarm in one round-trip.
	pipe := ps.rdb.Pipeline()
	idCmds := make([]*redis.StringSliceCmd, len(swarmKeys))
	for i, k := range swarmKeys {
		idCmds[i] = pipe.ZRangeByScore(ctx, k, &redis.ZRangeBy{Min: nowStr, Max: "+inf"})
	}
	if _, err := pipe.Exec(ctx); err != nil && err != redis.Nil {
		return nil, err
	}

	prefixLen := len(ps.prefix) + len("swarm:")

	// Pipeline 2: peer data only for non-empty swarms.
	type pending struct {
		ihHex string
		cmd   *redis.SliceCmd
	}
	pipe = ps.rdb.Pipeline()
	var pendings []pending
	for i, k := range swarmKeys {
		pids := idCmds[i].Val()
		if len(pids) == 0 {
			continue
		}
		ihHex := k[prefixLen:]
		pendings = append(pendings, pending{
			ihHex: ihHex,
			cmd:   pipe.HMGet(ctx, ps.prefix+"swarm:"+ihHex+":d", pids...),
		})
	}
	if len(pendings) == 0 {
		return nil, nil
	}
	if _, err := pipe.Exec(ctx); err != nil && err != redis.Nil {
		return nil, err
	}

	summaries := make([]SwarmSummary, 0, len(pendings))
	for _, p := range pendings {
		var seeders, leechers int
		for _, v := range p.cmd.Val() {
			s, ok := v.(string)
			if !ok {
				continue
			}
			if strings.HasSuffix(s, "|1") {
				seeders++
			} else {
				leechers++
			}
		}
		if seeders+leechers == 0 {
			continue
		}
		summaries = append(summaries, SwarmSummary{InfoHash: p.ihHex, Seeders: seeders, Leechers: leechers})
	}
	return summaries, nil
}

// SwarmPeers returns the active peers for a single info_hash (hex-encoded).
func (ps *PeerStore) SwarmPeers(ctx context.Context, ihHex string) ([]SwarmPeerInfo, error) {
	nowStr := strconv.FormatInt(time.Now().Unix(), 10)
	swarmKey := ps.prefix + "swarm:" + ihHex
	dataKey := ps.prefix + "swarm:" + ihHex + ":d"

	pids, err := ps.rdb.ZRangeByScore(ctx, swarmKey, &redis.ZRangeBy{Min: nowStr, Max: "+inf"}).Result()
	if err != nil {
		return nil, err
	}
	if len(pids) == 0 {
		return nil, nil
	}
	vals, err := ps.rdb.HMGet(ctx, dataKey, pids...).Result()
	if err != nil {
		return nil, err
	}

	peers := make([]SwarmPeerInfo, 0, len(pids))
	for i, v := range vals {
		s, ok := v.(string)
		if !ok {
			continue
		}
		parts := strings.SplitN(s, "|", 3)
		if len(parts) != 3 {
			continue
		}
		port, _ := strconv.Atoi(parts[1])
		peers = append(peers, SwarmPeerInfo{
			PeerID: pids[i],
			IP:     parts[0],
			Port:   port,
			Seeder: parts[2] == "1",
		})
	}
	return peers, nil
}

// --- HTTP admin endpoints (consumed by the FastAPI backend, not browsers) ---

// adminAuthorized checks the shared secret. Reuses backend_secret so no extra
// configuration is required; the backend sends it as X-Tracker-Secret.
func adminAuthorized(r *http.Request) bool {
	return cfg.BackendSecret != "" && r.Header.Get("X-Tracker-Secret") == cfg.BackendSecret
}

func writeJSON(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(v) //nolint:errcheck
}

// handleAdminSwarms serves GET /api/swarms — counts for every active swarm.
func handleAdminSwarms(w http.ResponseWriter, r *http.Request) {
	if !adminAuthorized(r) {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}
	swarms, err := store.ListSwarms(r.Context())
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	if swarms == nil {
		swarms = []SwarmSummary{}
	}
	writeJSON(w, map[string]any{"swarms": swarms})
}

// handleAdminSwarmPeers serves GET /api/swarms/{info_hash_hex}/peers.
func handleAdminSwarmPeers(w http.ResponseWriter, r *http.Request) {
	if !adminAuthorized(r) {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}
	rest := strings.TrimPrefix(r.URL.Path, "/api/swarms/")
	parts := strings.Split(rest, "/")
	if len(parts) != 2 || parts[0] == "" || parts[1] != "peers" {
		http.NotFound(w, r)
		return
	}
	peers, err := store.SwarmPeers(r.Context(), parts[0])
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	if peers == nil {
		peers = []SwarmPeerInfo{}
	}
	writeJSON(w, map[string]any{"peers": peers})
}
