"""Port mapping for the P2P server, modelled on libtorrent's approach.

qBittorrent does not implement port forwarding itself - it hands a set of ports
to libtorrent, which runs UPnP IGD and NAT-PMP concurrently and keeps retrying
in the background. This module follows the same shape:

  * SSDP discovery is retried with backoff instead of being a single fast probe.
  * NAT-PMP is tried when UPnP finds nothing, so routers that ship with UPnP
    disabled still get a mapping.
  * The external port matches the internal port; a different port is only
    chosen after the router reports a genuine conflict (error 718).
  * A background task keeps the mapping alive, because "permanent" leases are
    frequently downgraded by the router and vanish on reboot.

One constraint worth knowing: the miniupnpc Python binding hardcodes a lease
duration of 0 (permanent) and gives us no way to request a finite lease, so the
UPnP path cannot do libtorrent's refresh-at-75%-of-lease trick. Instead it polls
the router and repairs the mapping when it disappears. The NAT-PMP path does
control the lifetime, so it refreshes on a real schedule.
"""
import asyncio
import html
import ipaddress
import logging
import random
import socket
from typing import Optional

logger = logging.getLogger(__name__)
# Ensure logger propagates to root logger so startup logs are captured
logger.propagate = True

try:
    import miniupnpc
    MINIUPNPC_AVAILABLE = True
except ImportError as e:
    MINIUPNPC_AVAILABLE = False
    logger.warning(f"miniupnpc not available: {e}. UPnP functionality will be limited.")

try:
    from natpmp_helper import NatPMPClient, NatPMPError
    NATPMP_AVAILABLE = True
except ImportError as e:
    NATPMP_AVAILABLE = False
    logger.warning(f"natpmp_helper not available: {e}. NAT-PMP fallback disabled.")

# libtorrent searches at least four times even after it has seen a device, and
# backs off by two seconds per round. A single 200ms probe - which is what this
# module used to do - misses routers that answer SSDP slowly.
DISCOVERY_ATTEMPTS = 5
DISCOVERY_DELAY_MS = 2000

# Requested NAT-PMP lease, and the fraction of it at which we refresh. Both
# match libtorrent's defaults.
LEASE_DURATION = 3600
LEASE_REFRESH_RATIO = 0.75

# How often the UPnP path re-checks that its mapping still exists on the router.
UPNP_VERIFY_INTERVAL = 600

# libtorrent gives up on a mapping after five consecutive failures.
MAX_FAILCOUNT = 5

# On a 718 ConflictInMappingEntry libtorrent picks a random high port and
# retries a handful of times.
CONFLICT_RETRIES = 4
CONFLICT_PORT_BASE = 40000
CONFLICT_PORT_RANGE = 10000


SSDP_PORT = 1900
SSDP_MX = 2
SSDP_TIMEOUT = 3.0

# Search targets for the direct gateway query, most specific first.
SSDP_TARGETS = (
    "urn:schemas-upnp-org:device:InternetGatewayDevice:1",
    "urn:schemas-upnp-org:device:InternetGatewayDevice:2",
    "upnp:rootdevice",
)


def _unicast_msearch(gateway: str) -> Optional[str]:
    """M-SEARCH a single host and return the device description URL, if any."""
    for search_target in SSDP_TARGETS:
        request = (
            "M-SEARCH * HTTP/1.1\r\n"
            f"HOST:{gateway}:{SSDP_PORT}\r\n"
            f"ST:{search_target}\r\n"
            f"MX:{SSDP_MX}\r\n"
            'MAN:"ssdp:discover"\r\n'
            "\r\n"
        ).encode()

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(SSDP_TIMEOUT)
        try:
            sock.sendto(request, (gateway, SSDP_PORT))
            data, _ = sock.recvfrom(2048)
        except (socket.timeout, OSError):
            continue
        finally:
            sock.close()

        for line in data.decode(errors="replace").splitlines():
            if line.lower().startswith("location:"):
                location = line.split(":", 1)[1].strip()
                if location:
                    return location
    return None


def is_publicly_routable(ip: str) -> bool:
    """True if `ip` is a globally routable address.

    False for RFC1918, loopback, link-local and - importantly - the 100.64/10
    carrier-grade NAT range. A router behind CGNAT will happily accept a port
    mapping and report success while inbound connections remain impossible, so
    this is the difference between "mapped" and "actually reachable".
    """
    try:
        return ipaddress.ip_address(ip).is_global
    except ValueError:
        return False


class PortMapper:
    """Maps a port via UPnP IGD, falling back to NAT-PMP, and keeps it alive."""

    def __init__(self):
        self.upnp = None
        self.natpmp = None
        self.backend = None            # "upnp", "natpmp", or None
        self.external_ip = None
        self.local_ip = None
        self.port_mapped = False
        self.internal_port = None
        self.external_port = None
        self.description = None
        self.behind_cgnat = False
        self._keepalive_task = None
        self._lease_lifetime = LEASE_DURATION
        self._failcount = 0
        self._on_mapping_changed = None

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    async def discover_router(self) -> bool:
        """Find a gateway that can map ports. Returns True if one was found."""
        if await self._discover_upnp():
            self.backend = "upnp"
        elif await self._discover_natpmp():
            self.backend = "natpmp"
        else:
            await self._log_discovery_failure()
            return False

        if self.external_ip and not is_publicly_routable(self.external_ip):
            self.behind_cgnat = True
            logger.warning(
                f"Gateway reports external IP {self.external_ip}, which is not publicly "
                "routable (private or carrier-grade NAT). A port mapping here will look "
                "like it succeeded but will not accept inbound connections - the P2P "
                "server will only be reachable to peers that can already route to it."
            )
        return True

    async def _log_discovery_failure(self):
        """Explain which network we searched, so a dead end is diagnosable.

        The usual cause of a total miss is that the default route points
        somewhere other than the LAN - an active VPN tunnel swallows both the
        SSDP multicast and the NAT-PMP probe, and the symptom is identical to a
        router with UPnP switched off.
        """
        gateway = None
        if NATPMP_AVAILABLE:
            try:
                from natpmp_helper import discover_gateway
                gateway = await asyncio.to_thread(discover_gateway)
            except Exception:
                pass
        local_ip = await self._local_ip_towards(gateway or "8.8.8.8")

        logger.warning(
            f"No UPnP IGD or NAT-PMP gateway found (searched from {local_ip or 'unknown'} "
            f"towards gateway {gateway or 'unknown'}). Check that UPnP is enabled on the "
            "router; if a VPN is connected, the default route may be sending discovery "
            "into the tunnel instead of the LAN."
        )

    async def _discover_upnp(self) -> bool:
        if not MINIUPNPC_AVAILABLE:
            logger.info("miniupnpc not installed, skipping UPnP discovery")
            return False

        # Ask the default gateway directly before falling back to a multicast
        # search. It is fast, it is right in the overwhelmingly common case
        # where the gateway is the IGD, and crucially it still works when a
        # host firewall drops the multicast replies: an M-SEARCH sent to
        # 239.255.255.250 is answered from the router's own address, which
        # conntrack cannot match to the outgoing packet, so stateful firewalls
        # (ufw's default profile among them) silently discard it. Talking to
        # the gateway directly keeps source and destination consistent.
        if await self._discover_upnp_unicast():
            return True

        def _discover_once(delay_ms):
            upnp = miniupnpc.UPnP()
            upnp.discoverdelay = delay_ms
            num_devices = upnp.discover()
            if num_devices <= 0:
                return None, num_devices
            upnp.selectigd()
            return upnp, num_devices

        for attempt in range(1, DISCOVERY_ATTEMPTS + 1):
            try:
                upnp, num_devices = await asyncio.to_thread(_discover_once, DISCOVERY_DELAY_MS)
            except Exception as e:
                # selectigd() raises when devices answered SSDP but none of them
                # is a usable IGD. Worth another round: on multi-interface hosts
                # a later probe often reaches the real gateway.
                logger.debug(
                    f"UPnP discovery attempt {attempt}/{DISCOVERY_ATTEMPTS} failed: "
                    f"{type(e).__name__}: {e}"
                )
                upnp = None
                num_devices = 0

            if upnp:
                logger.info(
                    f"Found UPnP IGD on attempt {attempt}/{DISCOVERY_ATTEMPTS} "
                    f"({num_devices} device(s) answered)"
                )
                self.upnp = upnp
                self._read_upnp_addresses()
                return True

            if attempt < DISCOVERY_ATTEMPTS:
                # libtorrent's backoff: two seconds per elapsed round.
                backoff = 2 * attempt
                logger.debug(f"No IGD yet, retrying UPnP discovery in {backoff}s")
                await asyncio.sleep(backoff)

        logger.info(f"No UPnP IGD found after {DISCOVERY_ATTEMPTS} attempts")
        return False

    async def _discover_upnp_unicast(self) -> bool:
        """Find the IGD by asking the default gateway directly over SSDP."""
        if not NATPMP_AVAILABLE:
            return False
        try:
            from natpmp_helper import discover_gateway
        except ImportError:
            return False

        gateway = await asyncio.to_thread(discover_gateway)
        if not gateway:
            return False

        location = await asyncio.to_thread(_unicast_msearch, gateway)
        if not location:
            logger.debug(f"Gateway {gateway} did not answer a unicast M-SEARCH")
            return False

        logger.info(f"Gateway {gateway} advertised an IGD at {location}")

        def _select():
            upnp = miniupnpc.UPnP()
            # Older miniupnpc bindings have a no-argument selectigd(); if this
            # raises we simply fall through to the multicast search.
            upnp.selectigd(location)
            return upnp

        try:
            upnp = await asyncio.to_thread(_select)
        except Exception as e:
            logger.debug(f"Could not select IGD at {location}: {type(e).__name__}: {e}")
            return False

        self.upnp = upnp
        self._read_upnp_addresses()
        logger.info("Found UPnP IGD via a direct query to the gateway")
        return True

    def _read_upnp_addresses(self):
        """Pull the external and LAN addresses off a freshly selected IGD."""
        try:
            external_ip = self.upnp.externalipaddress()
            if external_ip:
                self.external_ip = external_ip
                logger.info(f"UPnP gateway external IP: {external_ip}")
            else:
                logger.warning("UPnP gateway did not report an external IP")
        except Exception as e:
            logger.warning(f"Could not get external IP from UPnP gateway: {e}")

        try:
            if getattr(self.upnp, "lanaddr", None):
                self.local_ip = self.upnp.lanaddr
                logger.info(f"Local address on the gateway's LAN: {self.local_ip}")
        except Exception as e:
            logger.debug(f"Could not read lanaddr: {e}")

    async def _discover_natpmp(self) -> bool:
        if not NATPMP_AVAILABLE:
            return False

        logger.info("Falling back to NAT-PMP")
        client = NatPMPClient()
        try:
            if not await client.discover():
                return False
        except Exception as e:
            logger.warning(f"NAT-PMP discovery failed: {type(e).__name__}: {e}")
            return False

        self.natpmp = client
        self.external_ip = client.external_ip
        self.local_ip = await self._local_ip_towards(client.gateway)
        return True

    async def _local_ip_towards(self, host: str) -> Optional[str]:
        """Local address the kernel would use to reach `host`."""
        def _probe():
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.connect((host, 9))
                return sock.getsockname()[0]
            finally:
                sock.close()

        try:
            return await asyncio.to_thread(_probe)
        except Exception as e:
            logger.debug(f"Could not determine local IP towards {host}: {e}")
            return None

    async def get_external_ip(self) -> Optional[str]:
        if self.external_ip:
            return self.external_ip
        if self.backend == "upnp" and self.upnp:
            try:
                self.external_ip = self.upnp.externalipaddress()
                return self.external_ip
            except Exception as e:
                logger.warning(f"Could not get external IP from UPnP: {e}")
        return None

    # ------------------------------------------------------------------
    # Mapping
    # ------------------------------------------------------------------

    async def add_port_mapping(
        self,
        internal_port: int,
        external_port: Optional[int] = None,
        description: str = "P2P File Sharing",
    ) -> bool:
        """Map `internal_port` on the gateway.

        The external port defaults to the internal one and only changes if the
        router reports a conflict, so the advertised port stays stable across
        restarts instead of hopping around at random.
        """
        if not self.backend:
            logger.warning("No port mapping backend available")
            return False
        if not self.local_ip:
            logger.error("Cannot map a port without knowing our local address")
            return False

        # Escape XML special characters so the description is safe in SOAP.
        self.description = html.escape(description, quote=False)
        self.internal_port = internal_port

        if self.backend == "upnp":
            await self._reclaim_stale_upnp_mappings()

        wanted = external_port or internal_port
        for attempt in range(CONFLICT_RETRIES + 1):
            try:
                granted = await self._map_once(internal_port, wanted)
            except Exception as e:
                logger.error(f"Port mapping failed: {type(e).__name__}: {e}", exc_info=True)
                return False

            if granted is not None:
                self.external_port = granted
                self.port_mapped = True
                self._failcount = 0
                logger.info(
                    f"Port mapping active via {self.backend.upper()}: "
                    f"{self.external_ip}:{granted} -> {self.local_ip}:{internal_port} (TCP+UDP)"
                )
                return True

            if attempt < CONFLICT_RETRIES:
                wanted = CONFLICT_PORT_BASE + random.randrange(CONFLICT_PORT_RANGE)
                logger.info(f"Port in use on the router, retrying on port {wanted}")

        logger.error(f"Failed to map a port after {CONFLICT_RETRIES + 1} attempts")
        return False

    async def _map_once(self, internal_port: int, external_port: int) -> Optional[int]:
        """Try one external port. Returns the granted port, or None on conflict.

        Raises for errors that retrying on another port will not fix.
        """
        if self.backend == "natpmp":
            try:
                granted_port, granted_lifetime = await self.natpmp.add_mapping(
                    internal_port, external_port, LEASE_DURATION
                )
            except NatPMPError as e:
                # Out of resources is the NAT-PMP equivalent of a conflict.
                if e.result_code == 4:
                    return None
                raise
            self._lease_lifetime = granted_lifetime or LEASE_DURATION
            if granted_lifetime and granted_lifetime < LEASE_DURATION:
                logger.info(
                    f"Router granted a {granted_lifetime}s lease "
                    f"(asked for {LEASE_DURATION}s); refreshing accordingly"
                )
            return granted_port

        return await self._map_once_upnp(internal_port, external_port)

    async def _map_once_upnp(self, internal_port: int, external_port: int) -> Optional[int]:
        """Add the TCP and UDP mappings, rolling back if only one lands."""
        def _add(protocol, port):
            return self.upnp.addportmapping(
                port, protocol, self.local_ip, internal_port, self.description, ""
            )

        def _is_conflict(error):
            text = str(error)
            return "ConflictInMappingEntry" in text or "718" in text or "Conflict" in text

        try:
            tcp_ok = await asyncio.to_thread(_add, "TCP", external_port)
        except Exception as e:
            if _is_conflict(e):
                return None
            raise
        if not tcp_ok:
            return None

        try:
            udp_ok = await asyncio.to_thread(_add, "UDP", external_port)
        except Exception as e:
            # Leaving the TCP half behind is what used to happen here: the
            # orphaned entries pile up on the router across restarts and cause
            # the very conflicts that push us onto another port.
            await self._delete_upnp(external_port, protocols=("TCP",))
            if _is_conflict(e):
                return None
            raise
        if not udp_ok:
            await self._delete_upnp(external_port, protocols=("TCP",))
            return None

        return external_port

    async def _reclaim_stale_upnp_mappings(self):
        """Delete mappings this host left behind on a previous run.

        Only entries whose description matches ours and which point at our own
        LAN address are touched, so other devices' mappings are left alone.
        """
        if not self.description or not self.local_ip:
            return
        if not hasattr(self.upnp, "getgenericportmapping"):
            logger.debug("miniupnpc build has no getgenericportmapping, skipping cleanup")
            return

        def _collect():
            stale = []
            index = 0
            while True:
                try:
                    entry = self.upnp.getgenericportmapping(index)
                except Exception:
                    break
                if not entry:
                    break
                # (extPort, protocol, (internalHost, internalPort), desc, enabled, remoteHost, lease)
                try:
                    ext_port, protocol, (internal_host, _), desc = entry[0], entry[1], entry[2], entry[3]
                except (IndexError, TypeError, ValueError):
                    index += 1
                    continue
                if desc == self.description and internal_host == self.local_ip:
                    stale.append((ext_port, protocol))
                index += 1
            return stale

        try:
            stale = await asyncio.to_thread(_collect)
        except Exception as e:
            logger.debug(f"Could not enumerate existing port mappings: {e}")
            return

        for ext_port, protocol in stale:
            try:
                await asyncio.to_thread(self.upnp.deleteportmapping, ext_port, protocol, "")
                logger.info(f"Reclaimed stale {protocol} mapping on port {ext_port}")
            except Exception as e:
                logger.debug(f"Could not delete stale mapping {protocol}/{ext_port}: {e}")

    async def _delete_upnp(self, external_port, protocols=("TCP", "UDP")) -> bool:
        deleted = False
        for protocol in protocols:
            try:
                if await asyncio.to_thread(
                    self.upnp.deleteportmapping, external_port, protocol, ""
                ):
                    deleted = True
            except Exception as e:
                logger.debug(f"Could not delete {protocol} mapping on {external_port}: {e}")
        return deleted

    async def delete_port_mapping(self, external_port: int) -> bool:
        """Remove the mapping from the router."""
        if not self.backend:
            return False

        logger.info(f"Removing port mapping on {external_port} (TCP+UDP)")
        try:
            if self.backend == "natpmp":
                result = await self.natpmp.delete_mapping(self.internal_port, external_port)
            else:
                result = await self._delete_upnp(external_port)
        except Exception as e:
            logger.error(f"Error removing port mapping: {e}", exc_info=True)
            return False

        self.port_mapped = False
        self.external_port = None
        return bool(result)

    # ------------------------------------------------------------------
    # Keepalive
    # ------------------------------------------------------------------

    def start_keepalive(self, on_mapping_changed=None):
        """Keep the mapping alive in the background.

        `on_mapping_changed` is awaited whenever the mapping had to be rebuilt
        on a different external port, so the caller can re-advertise it.
        """
        if self._keepalive_task and not self._keepalive_task.done():
            return
        self._on_mapping_changed = on_mapping_changed
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())

    async def stop_keepalive(self):
        if not self._keepalive_task:
            return
        self._keepalive_task.cancel()
        try:
            await self._keepalive_task
        except asyncio.CancelledError:
            pass
        self._keepalive_task = None

    def _keepalive_interval(self) -> float:
        if self.backend == "natpmp":
            return max(60.0, self._lease_lifetime * LEASE_REFRESH_RATIO)
        return UPNP_VERIFY_INTERVAL

    async def _keepalive_loop(self):
        """Refresh NAT-PMP leases, and repair UPnP mappings that disappeared."""
        while True:
            try:
                await asyncio.sleep(self._keepalive_interval())
                await self._keepalive_tick()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Port mapping keepalive error: {e}", exc_info=True)

    async def _keepalive_tick(self):
        if not self.port_mapped:
            return

        previous_port = self.external_port
        if await self._refresh_mapping():
            self._failcount = 0
            return

        self._failcount += 1
        logger.warning(
            f"Port mapping on {previous_port} is gone "
            f"(failure {self._failcount}/{MAX_FAILCOUNT}), rebuilding"
        )

        if self._failcount > MAX_FAILCOUNT:
            logger.error("Giving up on port mapping after repeated failures")
            await self._mark_unmapped()
            return

        if not await self._rediscover_and_remap(previous_port):
            # Nothing is listening on that port any more, so stop advertising
            # it. Continuing to report it would send peers to a dead address.
            await self._mark_unmapped()

    async def _rediscover_and_remap(self, previous_port) -> bool:
        """Re-run discovery and rebuild the mapping from scratch.

        The gateway may have rebooted or changed address, so the old control
        URL is dropped rather than reused.
        """
        self.upnp = None
        self.natpmp = None
        self.backend = None

        if not await self.discover_router():
            return False
        if not await self.add_port_mapping(
            self.internal_port, self.internal_port, self.description or "P2P File Sharing"
        ):
            return False

        if self.external_port != previous_port:
            logger.info(f"Port mapping moved from {previous_port} to {self.external_port}")
        # Notify even when the port is unchanged: the WAN address may have
        # moved, which matters just as much to peers trying to reach us.
        await self._notify_changed()
        return True

    async def _mark_unmapped(self):
        """Record that we no longer hold a mapping, and tell the caller."""
        if not self.port_mapped:
            return
        self.port_mapped = False
        self.external_port = None
        await self._notify_changed()

    async def _refresh_mapping(self) -> bool:
        """Renew (NAT-PMP) or verify (UPnP) the current mapping."""
        if self.backend == "natpmp":
            try:
                granted_port, granted_lifetime = await self.natpmp.add_mapping(
                    self.internal_port, self.external_port, LEASE_DURATION
                )
            except Exception as e:
                logger.debug(f"NAT-PMP lease refresh failed: {e}")
                return False
            self._lease_lifetime = granted_lifetime or LEASE_DURATION
            if granted_port != self.external_port:
                logger.info(
                    f"NAT-PMP refresh returned port {granted_port} "
                    f"(was {self.external_port})"
                )
                self.external_port = granted_port
                await self._notify_changed()
            return True

        if not self.upnp:
            # Lost the gateway handle entirely - treat as a failure so the
            # caller rediscovers instead of trusting a mapping we can't see.
            return False

        if not hasattr(self.upnp, "getspecificportmapping"):
            # No way to check on this miniupnpc build; assume the mapping held
            # rather than tearing down a working one on a hunch.
            return True

        def _check(protocol):
            try:
                return self.upnp.getspecificportmapping(self.external_port, protocol)
            except Exception:
                return None

        try:
            tcp = await asyncio.to_thread(_check, "TCP")
            udp = await asyncio.to_thread(_check, "UDP")
        except Exception as e:
            logger.debug(f"Could not verify UPnP mapping: {e}")
            return True

        return bool(tcp) and bool(udp)

    async def _notify_changed(self):
        if not self._on_mapping_changed:
            return
        try:
            result = self._on_mapping_changed(self)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:
            logger.error(f"Port mapping change callback failed: {e}", exc_info=True)

    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        return MINIUPNPC_AVAILABLE or NATPMP_AVAILABLE

    async def close(self):
        await self.stop_keepalive()
        if self.port_mapped and self.external_port:
            await self.delete_port_mapping(self.external_port)


# The service imports these names; keep them working.
UPnPHelper = PortMapper


def get_upnp_helper() -> PortMapper:
    """Get a port mapper instance."""
    return PortMapper()
