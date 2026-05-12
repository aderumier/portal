package main

// UDP BitTorrent tracker — BEP 15
// https://www.bittorrent.org/beps/bep_0015.html
//
// Security note: UDP announces bypass passkey validation (no standard mechanism
// to carry a passkey over UDP). Access is instead restricted to IPs that have
// previously completed a valid HTTP announce (GrantUDPAccess in peers.go).
// To enforce passkeys strictly, omit the UDP announce URL from torrent files.

import (
	"context"
	"encoding/binary"
	"log"
	"net"
)

const (
	udpConnectMagic = 0x41727101980 // BEP 15 magic connection_id for connect requests
	udpActConnect   = uint32(0)
	udpActAnnounce  = uint32(1)
	udpActScrape    = uint32(2)
	udpActError     = uint32(3)
)

func startUDPTracker(addr string) error {
	conn, err := net.ListenPacket("udp", addr)
	if err != nil {
		return err
	}
	go serveUDP(conn)
	return nil
}

func serveUDP(conn net.PacketConn) {
	defer conn.Close()
	buf := make([]byte, 2048)
	for {
		n, addr, err := conn.ReadFrom(buf)
		if err != nil {
			log.Printf("udp read error: %v", err)
			continue
		}
		pkt := make([]byte, n)
		copy(pkt, buf[:n])
		go handleUDPPacket(conn, addr, pkt)
	}
}

func handleUDPPacket(conn net.PacketConn, addr net.Addr, data []byte) {
	if len(data) < 16 {
		return
	}
	action := binary.BigEndian.Uint32(data[8:12])
	txID := binary.BigEndian.Uint32(data[12:16])
	ctx := context.Background()

	switch action {
	case udpActConnect:
		udpConnect(ctx, conn, addr, data, txID)
	case udpActAnnounce:
		udpAnnounce(ctx, conn, addr, data, txID)
	case udpActScrape:
		udpScrape(ctx, conn, addr, data, txID)
	default:
		udpError(conn, addr, txID, "unknown action")
	}
}

// udpConnect handles a BEP 15 connect request.
// Validates the magic connection_id, generates a new random one, stores it in
// Redis for 2 minutes, and returns it to the client.
func udpConnect(ctx context.Context, conn net.PacketConn, addr net.Addr, data []byte, txID uint32) {
	if len(data) < 16 {
		return
	}
	magic := binary.BigEndian.Uint64(data[0:8])
	if magic != udpConnectMagic {
		udpError(conn, addr, txID, "invalid magic")
		return
	}

	connID := RandomConnID()
	store.StoreConnID(ctx, connID)

	resp := make([]byte, 16)
	binary.BigEndian.PutUint32(resp[0:4], udpActConnect)
	binary.BigEndian.PutUint32(resp[4:8], txID)
	binary.BigEndian.PutUint64(resp[8:16], connID)
	conn.WriteTo(resp, addr) //nolint:errcheck
}

// udpAnnounce handles a BEP 15 announce request.
func udpAnnounce(ctx context.Context, conn net.PacketConn, addr net.Addr, data []byte, txID uint32) {
	if len(data) < 98 {
		udpError(conn, addr, txID, "packet too short")
		return
	}

	connID := binary.BigEndian.Uint64(data[0:8])
	if !store.ValidConnID(ctx, connID) {
		udpError(conn, addr, txID, "invalid connection id")
		return
	}

	// Derive client IP from the UDP source address.
	clientHost, _, err := net.SplitHostPort(addr.String())
	if err != nil {
		udpError(conn, addr, txID, "invalid source address")
		return
	}
	// Normalize IPv4-mapped IPv6
	if ip := net.ParseIP(clientHost); ip != nil {
		if v4 := ip.To4(); v4 != nil {
			clientHost = v4.String()
		}
	}

	// UDP access requires a prior valid HTTP announce from this IP.
	if !store.CheckUDPAccess(ctx, clientHost) {
		udpError(conn, addr, txID, "access denied")
		return
	}

	var ih InfoHash
	copy(ih[:], data[16:36])

	var peerID [20]byte
	copy(peerID[:], data[36:56])

	left := binary.BigEndian.Uint64(data[64:72])
	event := binary.BigEndian.Uint32(data[80:84])
	ipField := binary.BigEndian.Uint32(data[84:88]) // 0 = use source IP
	numWant := int32(binary.BigEndian.Uint32(data[92:96]))
	port := binary.BigEndian.Uint16(data[96:98])

	if numWant <= 0 || numWant > 200 {
		numWant = 50
	}

	// Determine peer IP: honour the ipField override if set, otherwise use
	// the source address.
	var peerIP net.IP
	if ipField != 0 {
		b := make([]byte, 4)
		binary.BigEndian.PutUint32(b, ipField)
		peerIP = net.IP(b)
	} else {
		peerIP = net.ParseIP(clientHost)
	}
	if peerIP == nil {
		udpError(conn, addr, txID, "invalid IP")
		return
	}

	peer := &Peer{
		ID:       peerID,
		IP:       peerIP,
		Port:     port,
		Complete: left == 0,
	}

	// event 3 = stopped
	if event == 3 {
		store.Remove(ctx, ih, peerID) //nolint:errcheck
	} else {
		store.Upsert(ctx, ih, peer) //nolint:errcheck
	}

	peers, _ := store.GetPeers(ctx, ih, int(numWant), peerID)
	complete, incomplete := store.Stats(ctx, ih)

	// Compact IPv4 peer list (6 bytes each: 4 IP + 2 port).
	var peerBytes []byte
	var portBuf [2]byte
	for _, p := range peers {
		if ip4 := p.IP.To4(); ip4 != nil {
			peerBytes = append(peerBytes, ip4...)
			binary.BigEndian.PutUint16(portBuf[:], p.Port)
			peerBytes = append(peerBytes, portBuf[:]...)
		}
	}

	resp := make([]byte, 20+len(peerBytes))
	binary.BigEndian.PutUint32(resp[0:4], udpActAnnounce)
	binary.BigEndian.PutUint32(resp[4:8], txID)
	binary.BigEndian.PutUint32(resp[8:12], uint32(cfg.AnnounceInterval))
	binary.BigEndian.PutUint32(resp[12:16], uint32(incomplete))
	binary.BigEndian.PutUint32(resp[16:20], uint32(complete))
	copy(resp[20:], peerBytes)
	conn.WriteTo(resp, addr) //nolint:errcheck
}

// udpScrape handles a BEP 15 scrape request.
func udpScrape(ctx context.Context, conn net.PacketConn, addr net.Addr, data []byte, txID uint32) {
	if len(data) < 16 {
		return
	}
	connID := binary.BigEndian.Uint64(data[0:8])
	if !store.ValidConnID(ctx, connID) {
		udpError(conn, addr, txID, "invalid connection id")
		return
	}

	ihData := data[16:]
	numIH := len(ihData) / 20

	resp := make([]byte, 8+numIH*12)
	binary.BigEndian.PutUint32(resp[0:4], udpActScrape)
	binary.BigEndian.PutUint32(resp[4:8], txID)

	for i := 0; i < numIH; i++ {
		var ih InfoHash
		copy(ih[:], ihData[i*20:(i+1)*20])
		complete, incomplete := store.Stats(ctx, ih)
		off := 8 + i*12
		binary.BigEndian.PutUint32(resp[off:], uint32(complete))
		binary.BigEndian.PutUint32(resp[off+4:], 0) // downloaded — not tracked
		binary.BigEndian.PutUint32(resp[off+8:], uint32(incomplete))
	}
	conn.WriteTo(resp, addr) //nolint:errcheck
}

func udpError(conn net.PacketConn, addr net.Addr, txID uint32, msg string) {
	resp := make([]byte, 8+len(msg))
	binary.BigEndian.PutUint32(resp[0:4], udpActError)
	binary.BigEndian.PutUint32(resp[4:8], txID)
	copy(resp[8:], msg)
	conn.WriteTo(resp, addr) //nolint:errcheck
}
