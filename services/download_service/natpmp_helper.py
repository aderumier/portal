"""NAT-PMP (RFC 6886) client built on the standard library only.

Used as a fallback when UPnP IGD discovery turns up nothing. A lot of routers
- Apple base stations, stock OpenWrt, a fair number of ISP boxes - speak
NAT-PMP while shipping with UPnP IGD switched off, so probing both is how
libtorrent (and therefore qBittorrent) still gets a mapping on hardware where
either protocol alone would fail.

Unlike the miniupnpc Python binding, NAT-PMP lets us request a finite lease and
learn the lifetime the router actually granted, so mappings made through this
backend are refreshed on a real schedule rather than polled for survival.
"""
import asyncio
import logging
import platform
import re
import socket
import struct
import subprocess

logger = logging.getLogger(__name__)
logger.propagate = True

NATPMP_PORT = 5351

_OP_EXTERNAL_ADDRESS = 0
_OP_MAP_UDP = 1
_OP_MAP_TCP = 2

# RFC 6886 section 3.2.1: start at 250ms and double on each retransmit. Nine
# tries is the spec's recommendation but takes ~2 minutes; five keeps the probe
# under 8 seconds, which matters because this runs on the startup path.
_INITIAL_TIMEOUT = 0.25
_MAX_ATTEMPTS = 5

RESULT_CODES = {
    0: "success",
    1: "unsupported protocol version",
    2: "not authorized (port mapping disabled on the router)",
    3: "network failure (router has no external connectivity)",
    4: "out of resources",
    5: "unsupported opcode",
}


class NatPMPError(Exception):
    """A NAT-PMP request failed or the gateway did not answer."""

    def __init__(self, message, result_code=None):
        super().__init__(message)
        self.result_code = result_code


def _parse_default_gateway_linux():
    """Read the IPv4 default gateway out of /proc/net/route."""
    try:
        with open("/proc/net/route", "r") as handle:
            for line in handle.readlines()[1:]:
                fields = line.split()
                if len(fields) < 4:
                    continue
                destination, gateway, flags = fields[1], fields[2], int(fields[3], 16)
                # Default route, and the route actually has a gateway (RTF_GATEWAY).
                if destination != "00000000" or not (flags & 0x2):
                    continue
                # The gateway is little-endian hex in this file.
                packed = struct.pack("<I", int(gateway, 16))
                return socket.inet_ntoa(packed)
    except Exception as e:
        logger.debug(f"NAT-PMP: could not read /proc/net/route: {e}")
    return None


def _parse_default_gateway_command():
    """Fall back to parsing the platform's routing table command."""
    system = platform.system()
    if system == "Windows":
        # "route print -4" lists the default route as 0.0.0.0 mask 0.0.0.0.
        command = ["route", "print", "-4"]
        pattern = re.compile(r"^\s*0\.0\.0\.0\s+0\.0\.0\.0\s+(\d+\.\d+\.\d+\.\d+)")
    elif system == "Darwin":
        command = ["route", "-n", "get", "default"]
        pattern = re.compile(r"gateway:\s*(\d+\.\d+\.\d+\.\d+)")
    else:
        command = ["ip", "route", "show", "default"]
        pattern = re.compile(r"default via (\d+\.\d+\.\d+\.\d+)")

    # Console programs on Windows write in the OEM codepage while Python
    # decodes with the ANSI one, so tolerate undecodable bytes instead of
    # raising. The route line we want is pure ASCII either way.
    kwargs = {"capture_output": True, "text": True, "timeout": 5, "errors": "replace"}
    if system == "Windows":
        # Without this the service (or a windowed PyInstaller build) flashes up
        # a console window every time it looks for the gateway.
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        output = subprocess.run(command, **kwargs).stdout
    except Exception as e:
        logger.debug(f"NAT-PMP: routing table command {command[0]} failed: {e}")
        return None

    for line in output.splitlines():
        match = pattern.search(line)
        if match:
            return match.group(1)
    return None


def discover_gateway():
    """Return the IPv4 default gateway address, or None if it can't be found."""
    gateway = None
    if platform.system() not in ("Windows", "Darwin"):
        gateway = _parse_default_gateway_linux()
    if not gateway:
        gateway = _parse_default_gateway_command()
    if gateway:
        logger.debug(f"NAT-PMP: default gateway is {gateway}")
    else:
        logger.debug("NAT-PMP: could not determine the default gateway")
    return gateway


def _request(gateway, payload, expected_length, expected_opcode):
    """Send a NAT-PMP request, retransmitting with exponential backoff.

    Returns the raw response body, or raises NatPMPError.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        timeout = _INITIAL_TIMEOUT
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            sock.settimeout(timeout)
            try:
                sock.sendto(payload, (gateway, NATPMP_PORT))
                data, addr = sock.recvfrom(64)
            except socket.timeout:
                timeout *= 2
                continue
            except OSError as e:
                # ICMP port-unreachable surfaces here: the gateway is up but has
                # nothing listening on 5351, so retrying is pointless.
                raise NatPMPError(f"gateway refused the NAT-PMP request: {e}")

            if addr[0] != gateway:
                logger.debug(f"NAT-PMP: ignoring response from unexpected host {addr[0]}")
                continue
            if len(data) < expected_length:
                logger.debug(f"NAT-PMP: short response ({len(data)} bytes), ignoring")
                continue

            version, opcode = data[0], data[1]
            result_code = struct.unpack("!H", data[2:4])[0]
            if opcode != expected_opcode:
                logger.debug(f"NAT-PMP: opcode mismatch (got {opcode}), ignoring")
                continue
            if result_code != 0:
                description = RESULT_CODES.get(result_code, f"unknown code {result_code}")
                raise NatPMPError(
                    f"gateway returned result {result_code}: {description}",
                    result_code=result_code,
                )
            if version != 0:
                logger.debug(f"NAT-PMP: gateway answered with version {version}")
            return data[:expected_length]

        raise NatPMPError(f"gateway {gateway} did not answer after {_MAX_ATTEMPTS} attempts")
    finally:
        sock.close()


def _get_external_address_sync(gateway):
    data = _request(gateway, struct.pack("!BB", 0, _OP_EXTERNAL_ADDRESS), 12, 128)
    _, _, _, _, address = struct.unpack("!BBHI4s", data)
    return socket.inet_ntoa(address)


def _map_port_sync(gateway, protocol, internal_port, external_port, lifetime):
    """Create (or with lifetime=0, destroy) one mapping.

    Returns (external_port, lifetime) as granted by the router, which may differ
    from what we asked for - RFC 6886 requires us to honour whatever comes back.
    """
    opcode = _OP_MAP_TCP if protocol.upper() == "TCP" else _OP_MAP_UDP
    payload = struct.pack("!BBHHHI", 0, opcode, 0, internal_port, external_port, lifetime)
    data = _request(gateway, payload, 16, 128 + opcode)
    _, _, _, _, _, granted_port, granted_lifetime = struct.unpack("!BBHIHHI", data)
    return granted_port, granted_lifetime


class NatPMPClient:
    """Async wrapper around the blocking NAT-PMP calls above."""

    def __init__(self):
        self.gateway = None
        self.external_ip = None

    async def discover(self):
        """Find a NAT-PMP capable gateway. Returns True on success."""
        gateway = await asyncio.to_thread(discover_gateway)
        if not gateway:
            return False

        try:
            external_ip = await asyncio.to_thread(_get_external_address_sync, gateway)
        except NatPMPError as e:
            if e.result_code == 1:
                # The gateway speaks PCP but has dropped NAT-PMP compatibility.
                # We do not implement PCP, so say so plainly rather than looking
                # like a generic timeout.
                logger.info(
                    f"NAT-PMP: gateway {gateway} rejected protocol version 0 - it is "
                    "probably PCP-only (RFC 6887), which this client does not speak"
                )
            else:
                logger.info(f"NAT-PMP: gateway {gateway} is not usable: {e}")
            return False

        self.gateway = gateway
        self.external_ip = external_ip
        logger.info(f"NAT-PMP: gateway {gateway} responded, external IP {external_ip}")
        return True

    async def add_mapping(self, internal_port, external_port, lifetime):
        """Map both TCP and UDP. Returns (external_port, granted_lifetime).

        Both protocols must land on the same external port; if the router hands
        back a different port for UDP than for TCP, the pair is rolled back and
        NatPMPError is raised so the caller can retry on another port.
        """
        tcp_port, tcp_lifetime = await asyncio.to_thread(
            _map_port_sync, self.gateway, "TCP", internal_port, external_port, lifetime
        )
        try:
            udp_port, udp_lifetime = await asyncio.to_thread(
                _map_port_sync, self.gateway, "UDP", internal_port, tcp_port, lifetime
            )
        except NatPMPError:
            await self._delete_one("TCP", internal_port, tcp_port)
            raise

        if udp_port != tcp_port:
            await self._delete_one("TCP", internal_port, tcp_port)
            await self._delete_one("UDP", internal_port, udp_port)
            raise NatPMPError(
                f"router split the mapping across ports (TCP {tcp_port}, UDP {udp_port})"
            )

        return tcp_port, min(tcp_lifetime, udp_lifetime)

    async def _delete_one(self, protocol, internal_port, external_port):
        try:
            # RFC 6886 section 3.4: lifetime 0 and external port 0 deletes.
            await asyncio.to_thread(
                _map_port_sync, self.gateway, protocol, internal_port, 0, 0
            )
        except NatPMPError as e:
            logger.debug(f"NAT-PMP: failed to delete {protocol} mapping: {e}")

    async def delete_mapping(self, internal_port, external_port):
        await self._delete_one("TCP", internal_port, external_port)
        await self._delete_one("UDP", internal_port, external_port)
        return True
