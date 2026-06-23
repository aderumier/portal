package main

import (
	"context"
	"encoding/binary"
	"flag"
	"fmt"
	"log"
	"net"
	"net/http"
	"os"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/redis/go-redis/v9"
	"gopkg.in/yaml.v3"
)

type Config struct {
	Addr             string `yaml:"addr"`
	UDPAddr          string `yaml:"udp_addr"`
	AnnounceInterval int    `yaml:"announce_interval"`
	MinInterval      int    `yaml:"min_interval"`
	PeerTTL          int    `yaml:"peer_ttl"`
	TrustedProxy     bool   `yaml:"trusted_proxy"`
	RedisURL         string `yaml:"redis_url"`
	RedisKeyPrefix   string `yaml:"redis_key_prefix"`
	BackendURL       string `yaml:"backend_url"`
	BackendSecret    string `yaml:"backend_secret"`
}

var (
	cfg    Config
	store  *PeerStore
	apiCli *APIClient
)

func main() {
	cfgPath := flag.String("config", "config.yaml", "path to config file")
	flag.Parse()

	data, err := os.ReadFile(*cfgPath)
	if err != nil {
		log.Fatalf("reading config: %v", err)
	}
	if err := yaml.Unmarshal(data, &cfg); err != nil {
		log.Fatalf("parsing config: %v", err)
	}

	// Defaults
	if cfg.Addr == "" {
		cfg.Addr = ":6969"
	}
	if cfg.AnnounceInterval == 0 {
		cfg.AnnounceInterval = 1800
	}
	if cfg.MinInterval == 0 {
		cfg.MinInterval = 300
	}
	if cfg.PeerTTL == 0 {
		cfg.PeerTTL = 3600
	}
	if cfg.RedisURL == "" {
		cfg.RedisURL = "redis://localhost:6379/0"
	}
	if cfg.BackendURL == "" {
		log.Fatal("backend_url is required")
	}
	if cfg.BackendSecret == "" {
		log.Fatal("backend_secret is required")
	}

	// API client (passkey validation via FastAPI backend)
	apiCli = NewAPIClient(cfg.BackendURL, cfg.BackendSecret)

	// Redis (peer storage, UDP grants, connection IDs)
	rdbOpts, err := redis.ParseURL(cfg.RedisURL)
	if err != nil {
		log.Fatalf("redis URL: %v", err)
	}
	rdb := redis.NewClient(rdbOpts)
	if err := rdb.Ping(context.Background()).Err(); err != nil {
		log.Fatalf("redis ping: %v", err)
	}
	store = NewPeerStore(rdb, cfg.RedisKeyPrefix, time.Duration(cfg.PeerTTL)*time.Second)

	// Optional UDP tracker
	if cfg.UDPAddr != "" {
		if err := startUDPTracker(cfg.UDPAddr); err != nil {
			log.Fatalf("UDP tracker: %v", err)
		}
		log.Printf("UDP tracker listening on %s", cfg.UDPAddr)
	}

	http.HandleFunc("/", handleRequest)
	// Admin read API for the backend (secret-protected). More specific than "/"
	// so announce/scrape still route through handleRequest.
	http.HandleFunc("/api/swarms", handleAdminSwarms)
	http.HandleFunc("/api/swarms/", handleAdminSwarmPeers)
	log.Printf("HTTP tracker listening on %s", cfg.Addr)
	log.Fatal(http.ListenAndServe(cfg.Addr, nil))
}

func handleRequest(w http.ResponseWriter, r *http.Request) {
	parts := strings.Split(strings.Trim(r.URL.Path, "/"), "/")
	if len(parts) != 1 || parts[0] == "" {
		http.NotFound(w, r)
		return
	}
	switch parts[0] {
	case "announce":
		handleAnnounce(w, r)
	case "scrape":
		handleScrape(w, r)
	default:
		http.NotFound(w, r)
	}
}

func handleAnnounce(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	ip := clientIP(r)
	q := r.URL.Query()

	passkey, _ := q["passkey"]
	if len(passkey) == 0 || passkey[0] == "" {
		writeResponse(w, bencodeFailure("missing passkey"))
		return
	}
	if err := apiCli.CheckPasskey(ctx, passkey[0], ip); err != nil {
		writeResponse(w, bencodeFailure(err.Error()))
		return
	}
	// Grant UDP access for this IP on every successful HTTP announce.
	store.GrantUDPAccess(ctx, ip)

	ihStr := q.Get("info_hash")
	if len(ihStr) != 20 {
		writeResponse(w, bencodeFailure("invalid info_hash"))
		return
	}
	var ih InfoHash
	copy(ih[:], ihStr)

	pidStr := q.Get("peer_id")
	if len(pidStr) != 20 {
		writeResponse(w, bencodeFailure("invalid peer_id"))
		return
	}
	var peerID [20]byte
	copy(peerID[:], pidStr)

	portVal, err := strconv.ParseUint(q.Get("port"), 10, 16)
	if err != nil || portVal == 0 {
		writeResponse(w, bencodeFailure("invalid port"))
		return
	}

	left, _ := strconv.ParseUint(q.Get("left"), 10, 64)

	numWant := 50
	if nw := q.Get("numwant"); nw != "" {
		if n, err := strconv.Atoi(nw); err == nil && n > 0 {
			numWant = n
		}
	}

	peer := &Peer{
		ID:       peerID,
		IP:       net.ParseIP(ip),
		Port:     uint16(portVal),
		Complete: left == 0,
	}

	if q.Get("event") == "stopped" {
		store.Remove(ctx, ih, peerID) //nolint:errcheck
	} else {
		store.Upsert(ctx, ih, peer) //nolint:errcheck
	}

	peers, _ := store.GetPeers(ctx, ih, numWant, peerID)
	complete, incomplete := store.Stats(ctx, ih)
	peers4, peers6 := compactPeers(peers)

	writeResponse(w, bencodeAnnounce(cfg.AnnounceInterval, cfg.MinInterval, complete, incomplete, peers4, peers6))
}

func handleScrape(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	ip := clientIP(r)
	q := r.URL.Query()

	passkey, _ := q["passkey"]
	if len(passkey) == 0 || passkey[0] == "" {
		writeResponse(w, bencodeFailure("missing passkey"))
		return
	}
	if err := apiCli.CheckPasskey(ctx, passkey[0], ip); err != nil {
		writeResponse(w, bencodeFailure(err.Error()))
		return
	}

	infoHashes := q["info_hash"]
	sort.Strings(infoHashes)

	var b []byte
	b = append(b, 'd')
	b = append(b, bstr("files")...)
	b = append(b, 'd')
	for _, ihStr := range infoHashes {
		if len(ihStr) != 20 {
			continue
		}
		var ih InfoHash
		copy(ih[:], ihStr)
		complete, incomplete := store.Stats(ctx, ih)
		b = append(b, braw([]byte(ihStr))...)
		b = append(b, 'd')
		b = append(b, bstr("complete")...)
		b = append(b, bint(complete)...)
		b = append(b, bstr("downloaded")...)
		b = append(b, bint(0)...)
		b = append(b, bstr("incomplete")...)
		b = append(b, bint(incomplete)...)
		b = append(b, 'e')
	}
	b = append(b, 'e')
	b = append(b, 'e')
	writeResponse(w, b)
}

func writeResponse(w http.ResponseWriter, body []byte) {
	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	w.Write(body) //nolint:errcheck
}

// clientIP extracts and normalises the client IP.
// IPv4-mapped IPv6 addresses (::ffff:x.x.x.x) are returned as plain IPv4.
func clientIP(r *http.Request) string {
	var raw string
	if cfg.TrustedProxy {
		if v := r.Header.Get("X-Real-IP"); v != "" {
			raw = v
		}
	}
	if raw == "" {
		host, _, err := net.SplitHostPort(r.RemoteAddr)
		if err != nil {
			raw = r.RemoteAddr
		} else {
			raw = host
		}
	}
	if ip := net.ParseIP(raw); ip != nil {
		if v4 := ip.To4(); v4 != nil {
			return v4.String()
		}
	}
	return raw
}

// compactPeers encodes peers in BitTorrent compact format.
// IPv4: 4-byte IP + 2-byte port. IPv6: 16-byte IP + 2-byte port.
func compactPeers(peers []*Peer) (v4, v6 []byte) {
	var port [2]byte
	for _, p := range peers {
		binary.BigEndian.PutUint16(port[:], p.Port)
		if ip4 := p.IP.To4(); ip4 != nil {
			v4 = append(v4, ip4...)
			v4 = append(v4, port[:]...)
		} else if ip6 := p.IP.To16(); ip6 != nil {
			v6 = append(v6, ip6...)
			v6 = append(v6, port[:]...)
		}
	}
	return
}

// --- bencode helpers (keys must be in lexicographic order per spec) ---

func bstr(s string) []byte { return []byte(fmt.Sprintf("%d:%s", len(s), s)) }
func braw(d []byte) []byte  { return append([]byte(fmt.Sprintf("%d:", len(d))), d...) }
func bint(n int) []byte     { return []byte(fmt.Sprintf("i%de", n)) }

// bencodeAnnounce builds the announce response.
// Key order: complete, incomplete, interval, min interval, peers, peers6.
func bencodeAnnounce(interval, minInterval, complete, incomplete int, peers4, peers6 []byte) []byte {
	var b []byte
	b = append(b, 'd')
	b = append(b, bstr("complete")...)
	b = append(b, bint(complete)...)
	b = append(b, bstr("incomplete")...)
	b = append(b, bint(incomplete)...)
	b = append(b, bstr("interval")...)
	b = append(b, bint(interval)...)
	b = append(b, bstr("min interval")...)
	b = append(b, bint(minInterval)...)
	b = append(b, bstr("peers")...)
	b = append(b, braw(peers4)...)
	if len(peers6) > 0 {
		b = append(b, bstr("peers6")...)
		b = append(b, braw(peers6)...)
	}
	b = append(b, 'e')
	return b
}

func bencodeFailure(reason string) []byte {
	var b []byte
	b = append(b, 'd')
	b = append(b, bstr("failure reason")...)
	b = append(b, bstr(reason)...)
	b = append(b, 'e')
	return b
}
