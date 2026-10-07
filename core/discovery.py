"""Shared, bounded IPv4 device discovery for dashboard and topology views."""

from __future__ import annotations

import concurrent.futures
import ipaddress
import socket
import threading
from concurrent.futures import FIRST_COMPLETED, wait

from . import network, windows_network

MAX_DISCOVERY_HOSTS = 16_384
MAX_WORKERS = 128
ICMP_TIMEOUT_MS = 220
TCP_FALLBACK_PORTS = (443, 80, 22, 445, 135)
_EXCLUDED_INTERFACE_WORDS = (
    "loopback", "vethernet", "hyper-v", "wsl", "vmware", "virtualbox",
    "virtual adapter", "vpn", "wireguard", "tap-windows", "tun", "docker",
    "container", "bluetooth",
)
_VALID_NEIGHBOR_STATES = {4, 5, 6}  # stale, reachable, permanent


def ipv4_host_count(network_range: ipaddress.IPv4Network) -> int:
    if network_range.prefixlen >= 31:
        return network_range.num_addresses
    return max(0, network_range.num_addresses - 2)


def parse_ipv4_cidr(value: str) -> ipaddress.IPv4Network:
    try:
        parsed = ipaddress.ip_network((value or "").strip(), strict=False)
    except ValueError as exc:
        raise ValueError(f"Enter a valid IPv4 CIDR, for example 192.168.1.0/24 ({exc})") from exc
    if not isinstance(parsed, ipaddress.IPv4Network):
        raise ValueError("Only IPv4 CIDR ranges are supported")
    count = ipv4_host_count(parsed)
    if count < 1:
        raise ValueError("The subnet contains no usable hosts")
    if count > MAX_DISCOVERY_HOSTS:
        raise ValueError(f"Subnet has {count:,} hosts; the maximum is {MAX_DISCOVERY_HOSTS:,}")
    return parsed


def _eligible_interface(adapter: dict) -> bool:
    if adapter.get("status") != "Up" or adapter.get("if_type") not in (6, 71):
        return False
    text = f"{adapter.get('name', '')} {adapter.get('description', '')}".casefold()
    return not any(word in text for word in _EXCLUDED_INTERFACE_WORDS)


def default_local_subnets() -> list[dict]:
    """Build exact local network scopes from up physical Ethernet/Wi-Fi NICs."""
    if not windows_network._windows():
        config = network.get_network_config()
        if not isinstance(config, dict) or config.get("error"):
            return []
        try:
            net = ipaddress.ip_network(
                f"{config['ip']}/{int(config['prefix'])}", strict=False)
        except (KeyError, TypeError, ValueError):
            return []
        if not isinstance(net, ipaddress.IPv4Network):
            return []
        return [{"id": f"local:{config.get('adapter', 'default')}:{net}",
                 "cidr": str(net), "label": config.get("adapter", "Local adapter"),
                 "kind": "local", "enabled": True, "interface_index": None,
                 "interface_name": config.get("adapter", ""),
                 "gateway": config.get("gateway", "")}]

    try:
        adapters = windows_network._adapters()
        routes = windows_network.ipv4_route_table()
    except Exception:
        return []
    defaults = {}
    for route in routes:
        if route["destination"] == "0.0.0.0/0":
            candidate = (route["metric"], route["next_hop"])
            current = defaults.get(route["interface_index"])
            if current is None or candidate[0] < current[0]:
                defaults[route["interface_index"]] = candidate

    result = []
    for adapter in adapters:
        if not _eligible_interface(adapter):
            continue
        index = adapter["if_index"]
        gateway = defaults.get(index, (0, ""))[1]
        for address in adapter.get("addresses", []):
            raw_ip = address.get("address", "")
            if ":" in raw_ip:
                continue
            try:
                ip = ipaddress.IPv4Address(raw_ip)
                prefix = int(address["prefix"])
                net = ipaddress.IPv4Network(f"{ip}/{prefix}", strict=False)
            except (ValueError, TypeError, KeyError):
                continue
            if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
                continue
            result.append({
                "id": f"local:{index}:{net}",
                "cidr": str(net),
                "label": adapter["name"],
                "kind": "local",
                "enabled": True,
                "interface_index": index,
                "interface_name": adapter["name"],
                "gateway": gateway,
                "adapter_address": str(ip),
            })

    result.sort(key=lambda item: (not bool(item.get("gateway")), item["label"], item["cidr"]))
    return result


def configured_subnets() -> list[dict]:
    """Refresh interface-derived local rows while retaining user-routed CIDRs."""
    from app.store import store

    local = default_local_subnets()
    saved = store.get_discovery_subnets()
    if saved is None:
        merged = local
    else:
        prior_local = {entry.get("id"): entry for entry in saved if entry.get("kind") == "local"}
        merged = []
        for entry in local:
            previous = prior_local.get(entry["id"])
            if previous is not None:
                entry["enabled"] = bool(previous.get("enabled", True))
            merged.append(entry)
        merged.extend(entry for entry in saved if entry.get("kind") == "routed")
    if saved != merged:
        store.set_discovery_subnets(merged)
    return [dict(entry) for entry in merged]


def validate_subnet_list(entries: list[dict]) -> list[dict]:
    """Normalize configured entries and enforce overlap and aggregate limits."""
    clean = []
    seen = set()
    enabled_networks = []
    for raw in entries:
        net = parse_ipv4_cidr(raw.get("cidr", ""))
        kind = raw.get("kind") or "routed"
        if kind not in ("local", "routed"):
            raise ValueError("Subnet type must be local or routed")
        unique_key = (str(net), raw.get("interface_index") if kind == "local" else None)
        if unique_key in seen:
            raise ValueError(f"{net} is already configured")
        seen.add(unique_key)
        enabled = bool(raw.get("enabled", True))
        if enabled:
            for previous, previous_kind in enabled_networks:
                if net.overlaps(previous) and (kind != "local" or previous_kind != "local"):
                    raise ValueError(f"{net} overlaps configured subnet {previous}")
            enabled_networks.append((net, kind))
        entry = dict(raw)
        entry.update({"cidr": str(net), "kind": kind, "enabled": enabled})
        entry.setdefault("id", f"{kind}:{entry.get('interface_index', '')}:{net}")
        entry.setdefault("label", str(net) if kind == "routed" else "Local network")
        entry.setdefault("interface_index", None)
        entry.setdefault("interface_name", "")
        entry.setdefault("gateway", "")
        clean.append(entry)

    total = sum(ipv4_host_count(parse_ipv4_cidr(item["cidr"]))
                for item in clean if item["enabled"])
    if total > MAX_DISCOVERY_HOSTS:
        raise ValueError(
            f"Enabled subnets contain {total:,} hosts; the combined maximum is "
            f"{MAX_DISCOVERY_HOSTS:,}")
    return clean


def save_configured_subnets(entries: list[dict]) -> list[dict]:
    from app.store import store

    clean = validate_subnet_list(entries)
    store.set_discovery_subnets(clean)
    return clean


def add_routed_subnet(cidr: str, label: str = "") -> list[dict]:
    net = parse_ipv4_cidr(cidr)
    entries = configured_subnets()
    if any(net.overlaps(parse_ipv4_cidr(entry["cidr"])) for entry in entries):
        raise ValueError(f"{net} overlaps an existing discovery subnet")
    route = best_route_for_ip(str(net.network_address))
    entries.append({
        "id": f"routed:{net}", "cidr": str(net),
        "label": (label or f"Routed {net}").strip(), "kind": "routed",
        "enabled": True,
        "interface_index": route.get("interface_index") if route else None,
        "interface_name": route.get("interface_name", "") if route else "",
        "gateway": route.get("next_hop", "") if route else "",
    })
    return save_configured_subnets(entries)


def manual_subnet(cidr: str) -> dict:
    """Build a one-off segment for the legacy Ping Sweep CIDR field."""
    net = parse_ipv4_cidr(cidr)
    route = best_route_for_ip(str(net.network_address))
    return {"id": f"adhoc:{net}", "cidr": str(net),
            "label": f"Custom {net}", "kind": "routed", "enabled": True,
            "interface_index": route.get("interface_index") if route else None,
            "interface_name": route.get("interface_name", "") if route else "",
            "gateway": route.get("next_hop", "") if route else ""}


def best_route_for_ip(ip: str) -> dict | None:
    try:
        address = ipaddress.IPv4Address(ip)
        routes = windows_network.ipv4_route_table()
        matches = [route for route in routes
                   if address in ipaddress.ip_network(route["destination"], strict=False)]
        if not matches:
            return None
        route = max(matches, key=lambda item: (
            ipaddress.ip_network(item["destination"]).prefixlen,
            -item["metric"]))
        adapter = next((a for a in windows_network._adapters()
                        if a["if_index"] == route["interface_index"]), None)
        if route.get("next_hop") == "0.0.0.0":
            route = {**route, "next_hop": ""}
        return {**route, "interface_name": adapter["name"] if adapter else ""}
    except (OSError, ValueError):
        return None


def _valid_mac(mac: str) -> bool:
    clean = (mac or "").replace(":", "").replace("-", "").upper()
    return (len(clean) == 12 and clean != "000000000000"
            and clean != "FFFFFFFFFFFF" and int(clean[:2], 16) & 1 == 0)


def _neighbor_state_name(state: int) -> str:
    return {4: "cached", 5: "reachable", 6: "permanent"}.get(state, "unknown")


def _tcp_probe(ip: str, timeout: float) -> tuple[bool, int | None]:
    for port in TCP_FALLBACK_PORTS:
        try:
            with socket.create_connection((ip, port), timeout=timeout):
                return True, port
        except OSError:
            continue
    return False, None


class DiscoveryService:
    """Serializes scans and owns the shared latest snapshot for all UI views."""

    def __init__(self):
        self._state_lock = threading.RLock()
        self._scan_lock = threading.Lock()
        self._active = False
        self._cancel_event = None
        self._status = "idle"
        self._generation = 0
        self._segments = []
        self._devices = {}
        self._device_sources = {}
        self._summary = {"scanned": 0, "total": 0, "found": 0,
                         "source_counts": {"icmp": 0, "tcp": 0, "neighbor": 0}}

    def snapshot(self) -> dict:
        with self._state_lock:
            summary = dict(self._summary)
            summary["source_counts"] = dict(self._summary.get("source_counts", {}))
            return {"status": self._status, "generation": self._generation,
                    "segments": [dict(s) for s in self._segments],
                    "devices": [dict(d) for d in self._devices.values()],
                    "summary": summary, "active": self._active}

    def set_segments(self, segments):
        """Publish current configuration to idle views without starting a scan."""
        with self._state_lock:
            if not self._active:
                self._segments = [dict(segment) for segment in (segments or [])]

    def cancel(self):
        with self._state_lock:
            event = self._cancel_event
        if event is not None:
            event.set()

    def _record(self, device: dict) -> None:
        key = (device["segment_id"], device["ip"])
        with self._state_lock:
            previous_source = self._device_sources.get(key)
            new_source = device.get("source", "neighbor")
            if previous_source != new_source:
                if previous_source in self._summary["source_counts"]:
                    self._summary["source_counts"][previous_source] -= 1
                if new_source in self._summary["source_counts"]:
                    self._summary["source_counts"][new_source] += 1
                self._device_sources[key] = new_source
            current = self._devices.get(key, {})
            current.update(device)
            self._devices[key] = current
            self._summary["found"] = len(self._devices)

    def _publish(self, event: dict) -> dict:
        with self._state_lock:
            if "scanned" in event:
                self._summary["scanned"] = event["scanned"]
            if "total" in event:
                self._summary["total"] = event["total"]
        return event

    def scan_stream(self, subnets=None, timeout_ms=ICMP_TIMEOUT_MS,
                    cancel_event=None):
        """Yield seeded neighbors, active probe results, and bounded progress."""
        if not self._scan_lock.acquire(blocking=False):
            yield {"error": "A discovery scan is already running"}
            return
        if cancel_event is None:
            cancel_event = threading.Event()
        try:
            entries = ([dict(item) for item in subnets] if subnets is not None
                       else configured_subnets())
            entries = validate_subnet_list(
                [item for item in entries if item.get("enabled", True)])
            entries = [item for item in entries if item.get("enabled", True)]
            if not entries:
                yield {"error": "Enable at least one discovery subnet"}
                return
            parsed = [(item, parse_ipv4_cidr(item["cidr"])) for item in entries]
            total = sum(ipv4_host_count(net) for _, net in parsed)
            if total > MAX_DISCOVERY_HOSTS:
                yield {"error": f"Discovery is limited to {MAX_DISCOVERY_HOSTS:,} hosts per scan"}
                return

            with self._state_lock:
                self._active = True
                self._cancel_event = cancel_event
                self._status = "scanning"
                self._generation += 1
                self._segments = [dict(item) for item, _ in parsed]
                self._devices = {}
                self._device_sources = {}
                self._summary = {"scanned": 0, "total": total, "found": 0,
                                 "source_counts": {"icmp": 0, "tcp": 0, "neighbor": 0}}
                generation = self._generation
            try:
                local_ips = {address["address"]
                             for adapter in windows_network._adapters()
                             for address in adapter.get("addresses", [])}
            except Exception:
                local_ips = set()

            yield self._publish({"event": "started", "generation": generation,
                                 "segments": [dict(item) for item, _ in parsed],
                                 "current_subnet": "", "scanned": 0,
                                 "total": total, "found": 0})
            neighbors = windows_network.neighbor_table()
            if not isinstance(neighbors, list):
                neighbors = []
            seeded = set()
            for item, net in parsed:
                if cancel_event is not None and cancel_event.is_set():
                    break
                route = best_route_for_ip(str(net.network_address)) if item["kind"] == "routed" else None
                interface_index = (item.get("interface_index") if item["kind"] == "local"
                                   else (route or {}).get("interface_index", item.get("interface_index")))
                gateway = item.get("gateway") or (route or {}).get("next_hop", "")
                item["gateway"] = gateway
                if interface_index is not None:
                    item["interface_index"] = interface_index
                yield self._publish({"event": "segment", "segment": dict(item),
                                     "current_subnet": item["cidr"], "scanned": 0,
                                     "total": total, "found": self.snapshot()["summary"]["found"]})
                for row in neighbors:
                    try:
                        ip = ipaddress.IPv4Address(row.get("ip", ""))
                    except ValueError:
                        continue
                    if ip not in net or not _valid_mac(row.get("mac", "")):
                        continue
                    if interface_index is not None and row.get("interface_index") != interface_index:
                        continue
                    if row.get("state") not in _VALID_NEIGHBOR_STATES:
                        continue
                    ip_text = str(ip)
                    seeded.add((item["id"], ip_text))
                    device = self._make_device(
                        item, ip_text, row.get("mac", ""), None, "neighbor",
                        _neighbor_state_name(row.get("state", -1)), gateway,
                        local_ips=local_ips)
                    self._record(device)
                    yield self._publish({**device, "online": True,
                                         "found": self.snapshot()["summary"]["found"],
                                         "total": total, "scanned": 0})

            scanned = 0
            cancelled = False
            emit_every = max(1, min(32, total // 150 or 1))
            for item, net in parsed:
                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
                    break
                gateway = item.get("gateway", "")
                route_interface = item.get("interface_index")
                host_count = ipv4_host_count(net)
                if host_count > MAX_DISCOVERY_HOSTS:
                    yield {"error": f"Subnet {net} exceeds the {MAX_DISCOVERY_HOSTS:,}-host limit"}
                    cancelled = True
                    break
                pool = concurrent.futures.ThreadPoolExecutor(
                    max_workers=min(MAX_WORKERS, max(1, host_count)))
                pending = {}
                host_iter = iter(str(ip) for ip in net.hosts())

                def probe(address):
                    if cancel_event is not None and cancel_event.is_set():
                        return None
                    try:
                        rtt = windows_network.icmp_probe(address, timeout_ms)
                    except Exception:
                        rtt = network.ping_host(address, timeout_ms)
                    if rtt is not None:
                        return "icmp", float(rtt), None
                    # Echo is frequently filtered. A small set of TCP connects
                    # still elicits ARP locally and can identify routed hosts
                    # exposing common services, without subprocess-per-host.
                    found, port = _tcp_probe(address, min(timeout_ms / 1000.0, 0.12))
                    if found:
                        return "tcp", None, port
                    return None

                try:
                    exhausted = False
                    while pending or not exhausted:
                        if cancel_event is not None and cancel_event.is_set():
                            cancelled = True
                            for future in pending:
                                future.cancel()
                            break
                        while not exhausted and len(pending) < MAX_WORKERS * 2:
                            try:
                                address = next(host_iter)
                            except StopIteration:
                                exhausted = True
                                break
                            pending[pool.submit(probe, address)] = address
                        done, _ = wait(tuple(pending), timeout=0.1,
                                       return_when=FIRST_COMPLETED)
                        if not done:
                            continue
                        for future in done:
                            address = pending.pop(future)
                            scanned += 1
                            try:
                                result = future.result()
                            except Exception:
                                result = None
                            if result:
                                method, rtt, port = result
                                device = self._make_device(
                                    item, address, "", rtt, method,
                                    "reachable", gateway, port,
                                    local_ips=local_ips)
                                self._record(device)
                                yield self._publish({**device, "online": True,
                                                     "scanned": scanned,
                                                     "total": total,
                                                     "found": self.snapshot()["summary"]["found"]})
                            if scanned % emit_every == 0:
                                yield self._publish({"event": "progress",
                                                     "segment": dict(item),
                                                     "current_subnet": item["cidr"],
                                                     "scanned": scanned, "total": total,
                                                     "found": self.snapshot()["summary"]["found"]})
                finally:
                    pool.shutdown(wait=True, cancel_futures=True)
                if cancelled:
                    break

                # ICMP requests populate the local ARP cache even for endpoints
                # that do not answer echo. Reconcile it after each L2 segment.
                fresh = windows_network.neighbor_table()
                if isinstance(fresh, list):
                    for row in fresh:
                        try:
                            ip = ipaddress.IPv4Address(row.get("ip", ""))
                        except ValueError:
                            continue
                        if (ip not in net or not _valid_mac(row.get("mac", ""))
                                or row.get("state") not in _VALID_NEIGHBOR_STATES
                                or (route_interface is not None
                                    and row.get("interface_index") != route_interface)):
                            continue
                        address = str(ip)
                        key = (item["id"], address)
                        previous = self.snapshot()["devices"]
                        current = next((d for d in previous
                                        if d["segment_id"] == item["id"] and d["ip"] == address), None)
                        if current and current.get("reachability") == "reachable":
                            current["mac"] = row["mac"]
                            current["vendor"] = self._vendor(row["mac"])
                            self._record(current)
                            continue
                        if key not in seeded and current is None:
                            device = self._make_device(
                                item, address, row["mac"], None, "neighbor",
                                _neighbor_state_name(row.get("state", -1)), gateway,
                                local_ips=local_ips)
                            self._record(device)
                            yield self._publish({**device, "online": True,
                                                 "scanned": scanned, "total": total,
                                                 "found": self.snapshot()["summary"]["found"]})

            with self._state_lock:
                self._active = False
                self._status = "partial" if cancelled else "complete"
            snapshot = self.snapshot()
            yield {"done": True, "cancelled": cancelled, "partial": cancelled,
                   "scanned": scanned, "total": total,
                   "found": len(snapshot["devices"]),
                   "source_counts": snapshot["summary"]["source_counts"],
                   "segments": snapshot["segments"], "devices": snapshot["devices"]}
        finally:
            with self._state_lock:
                if self._status == "scanning":
                    self._status = "partial"
                self._active = False
                self._cancel_event = None
            self._scan_lock.release()

    @staticmethod
    def _vendor(mac: str) -> str:
        try:
            from .scan import lookup_vendor
            return lookup_vendor(mac, allow_online=False)
        except Exception:
            return "Unknown"

    def _make_device(self, segment, ip, mac, rtt, method, reachability,
                     gateway, open_port=None, local_ips=None):
        vendor = self._vendor(mac) if _valid_mac(mac) else "Unknown"
        local_ips = local_ips or set()
        device = {
            "ip": ip, "hostname": ip, "mac": mac or "", "vendor": vendor,
            "rtt_ms": rtt, "is_gateway": bool(gateway and ip == gateway),
            "is_self": ip in local_ips, "kind": "", "online": True,
            "reachability": reachability, "source": method,
            "segment_id": segment["id"], "segment": segment.get("label", segment["cidr"]),
            "cidr": segment["cidr"], "scope": segment["kind"],
            "interface_name": segment.get("interface_name", ""),
            "interface_index": segment.get("interface_index"),
            "gateway": gateway or "", "open_port": open_port,
        }
        return device


_SERVICE = None
_SERVICE_LOCK = threading.Lock()


def get_discovery_service() -> DiscoveryService:
    global _SERVICE
    with _SERVICE_LOCK:
        if _SERVICE is None:
            _SERVICE = DiscoveryService()
        return _SERVICE
