"""
NETWER unit tests for pure backend helpers.

These cover the deterministic, network-free functions so we catch regressions
when adding features. Run with:  python -m pytest tests/  (or python -m unittest)
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.netwer_core as core
import core.network as net


class TestParsePortSpec(unittest.TestCase):
    def test_profile_name(self):
        self.assertEqual(core._parse_port_spec("common"),
                         core.PORT_PROFILES["common"])

    def test_empty_defaults_to_common(self):
        self.assertEqual(core._parse_port_spec(""),
                         core.PORT_PROFILES["common"])

    def test_comma_list(self):
        self.assertEqual(core._parse_port_spec("22,80,443"), [22, 80, 443])

    def test_range(self):
        self.assertEqual(core._parse_port_spec("8000-8003"),
                         [8000, 8001, 8002, 8003])

    def test_mixed_and_dedup(self):
        self.assertEqual(core._parse_port_spec("80,80,22,8000-8001"),
                         [22, 80, 8000, 8001])

    def test_reversed_range(self):
        self.assertEqual(core._parse_port_spec("443-440"),
                         [440, 441, 442, 443])

    def test_invalid(self):
        self.assertEqual(core._parse_port_spec("abc"), [])

    def test_out_of_range_clamped(self):
        # 70000 is invalid; single invalid int returns []
        self.assertEqual(core._parse_port_spec("70000"), [])


class TestParseSubnetPrefix(unittest.TestCase):
    def test_cidr(self):
        self.assertEqual(core._parse_subnet_prefix("192.168.88.0/24"),
                         "192.168.88")

    def test_bare_prefix(self):
        self.assertEqual(core._parse_subnet_prefix("192.168.88"), "192.168.88")

    def test_trailing_dot(self):
        self.assertEqual(core._parse_subnet_prefix("10.0.0."), "10.0.0")

    def test_whitespace(self):
        self.assertEqual(core._parse_subnet_prefix("  192.168.1.5/24  "),
                         "192.168.1")

    def test_invalid_octet(self):
        self.assertIsNone(core._parse_subnet_prefix("256.1.1.0/24"))

    def test_too_short(self):
        self.assertIsNone(core._parse_subnet_prefix("1.2"))

    def test_garbage(self):
        self.assertIsNone(core._parse_subnet_prefix("bad"))


class TestPortService(unittest.TestCase):
    def test_known(self):
        self.assertEqual(core.port_service(443), ("HTTPS", "TCP"))
        self.assertEqual(core.port_service(3306), ("MySQL", "TCP"))
        self.assertEqual(core.port_service(53)[0], "DNS")

    def test_unknown(self):
        self.assertEqual(core.port_service(12345), ("Unknown", "TCP"))


class TestDetectDeviceType(unittest.TestCase):
    def test_gateway_is_router(self):
        self.assertEqual(core.detect_device_type(is_gateway=True), "router")

    def test_printer_port(self):
        self.assertEqual(
            core.detect_device_type(open_ports=[80, 9100]), "printer")

    def test_camera_rtsp(self):
        self.assertEqual(core.detect_device_type(open_ports=[554]), "camera")

    def test_vendor_apple_phone(self):
        self.assertEqual(core.detect_device_type(vendor="Apple"), "phone")

    def test_vendor_synology_nas(self):
        self.assertEqual(
            core.detect_device_type(vendor="Synology Inc."), "nas")

    def test_hostname_hint(self):
        self.assertEqual(
            core.detect_device_type(hostname="DESKTOP-ABC123"), "computer")

    def test_web_only_is_computer(self):
        self.assertEqual(core.detect_device_type(open_ports=[80, 443]),
                         "computer")

    def test_generic_fallback(self):
        self.assertEqual(core.detect_device_type(), "generic")

    def test_port_beats_vendor(self):
        # A printer port should win even if vendor looks like a phone maker.
        self.assertEqual(
            core.detect_device_type(open_ports=[9100], vendor="Apple"),
            "printer")


class TestDeviceDisplayName(unittest.TestCase):
    def setUp(self):
        from ui.pages.ping_sweep_page import _device_display_name
        self.fn = _device_display_name

    def test_real_hostname(self):
        self.assertEqual(
            self.fn({"hostname": "router.lan", "vendor": "MikroTik",
                     "ip": "192.168.1.1"}), "router.lan")

    def test_unknown_falls_back_to_vendor(self):
        self.assertEqual(
            self.fn({"hostname": "Unknown", "vendor": "LG Electronics",
                     "ip": "192.168.1.254"}), "LG Electronics")

    def test_all_unknown_never_shows_a_bare_ip(self):
        self.assertEqual(
            self.fn({"hostname": "Unknown", "vendor": "Unknown",
                     "ip": "192.168.1.77"}), "Unknown device")


class TestStore(unittest.TestCase):
    """Store tests use the real file but clean up after themselves."""

    def setUp(self):
        from app.store import Store
        self.store = Store()

    def test_recent_dedup_and_order(self):
        self.store.clear_recent_hosts()
        self.store.add_recent_host("1.1.1.1", "ping")
        self.store.add_recent_host("8.8.8.8", "ping")
        self.store.add_recent_host("1.1.1.1", "ping")   # move to front
        hosts = [r["host"] for r in self.store.recent_hosts()]
        self.assertEqual(hosts[:2], ["1.1.1.1", "8.8.8.8"])

    def test_favorites(self):
        self.store.remove_favorite("9.9.9.9")
        self.store.add_favorite("9.9.9.9", "Quad9")
        self.assertTrue(self.store.is_favorite("9.9.9.9"))
        self.store.remove_favorite("9.9.9.9")
        self.assertFalse(self.store.is_favorite("9.9.9.9"))

    def test_settings_persist(self):
        self.store.set_setting("ping_timeout_ms", 1234)
        self.assertEqual(self.store.get_setting("ping_timeout_ms"), 1234)
        self.store.set_setting("ping_timeout_ms", 1000)   # restore default-ish


class TestWakeOnLan(unittest.TestCase):
    def test_valid_mac_colon(self):
        r = core.wake_on_lan("AA:BB:CC:DD:EE:FF")
        self.assertTrue(r.get("ok"))
        self.assertEqual(r["mac"], "AA:BB:CC:DD:EE:FF")

    def test_valid_mac_no_sep(self):
        self.assertTrue(core.wake_on_lan("aabbccddeeff").get("ok"))

    def test_valid_mac_dash(self):
        self.assertTrue(core.wake_on_lan("AA-BB-CC-DD-EE-FF").get("ok"))

    def test_invalid_mac(self):
        self.assertIn("error", core.wake_on_lan("nope"))

    def test_empty_mac(self):
        self.assertIn("error", core.wake_on_lan(""))


class TestGeoHelpers(unittest.TestCase):
    def test_private_ip_detection(self):
        self.assertTrue(core._is_private_ip("192.168.1.1"))
        self.assertTrue(core._is_private_ip("10.0.0.1"))
        self.assertFalse(core._is_private_ip("8.8.8.8"))

    def test_geolocate_private_returns_none(self):
        self.assertIsNone(core.geolocate_ip("192.168.1.1"))

    def test_geolocate_empty_returns_none(self):
        self.assertIsNone(core.geolocate_ip(""))


class TestGeolocateHops(unittest.TestCase):
    def test_excludes_private_ips(self):
        r = core.geolocate_hops(["192.168.1.1", "10.0.0.1"])
        self.assertNotIn("192.168.1.1", r)
        self.assertNotIn("10.0.0.1", r)

    def test_empty_input(self):
        self.assertEqual(core.geolocate_hops([]), {})

    def test_returns_entry_per_public_ip(self):
        # Offline this yields None values, but every public IP must be keyed
        # so the caller can tell "looked up and failed" from "not tried".
        r = core.geolocate_hops(["8.8.8.8", "1.1.1.1"])
        self.assertIn("8.8.8.8", r)
        self.assertIn("1.1.1.1", r)


class TestTracerouteStaysFast(unittest.TestCase):
    """The trace itself must not perform geolocation, that used to make a
    long trace take minutes when the geo provider was blocked."""

    def test_no_geolocation_during_trace(self):
        calls = []
        real_geo = core.geolocate_ip
        real_tr = core.traceroute_stream

        def fake_tr(target, max_hops=30):
            yield {"resolved": "8.8.8.8", "target": target}
            yield {"ttl": 1, "ip": "8.8.8.8", "hostname": "d", "avg": 5}
            yield {"done": True, "reached": True}

        core.geolocate_ip = lambda ip, timeout=4: calls.append(ip)
        core.traceroute_stream = fake_tr
        try:
            list(core.traceroute_geo_stream("8.8.8.8"))
        finally:
            core.geolocate_ip = real_geo
            core.traceroute_stream = real_tr
        self.assertEqual(calls, [])


class TestOfflineGeo(unittest.TestCase):
    """Offline fallback must place every public IP even with no network."""

    def test_known_ip(self):
        g = core._offline_geolocate("8.8.8.8")
        self.assertIsNotNone(g)
        self.assertAlmostEqual(g["lat"], 37.42, places=1)

    def test_regional_estimate(self):
        g = core._offline_geolocate("213.242.116.9")  # 213.x -> Frankfurt/DE
        self.assertIsNotNone(g)
        self.assertEqual(g["country"], "DE")

    def test_every_public_ip_gets_a_location(self):
        # Even an octet not explicitly mapped must return a coarse guess so
        # the map never sits blank on a real trace.
        for ip in ["21.4.1.133", "133.1.2.3", "170.0.0.1", "5.5.5.5"]:
            self.assertIsNotNone(core._offline_geolocate(ip),
                                 f"{ip} should get a fallback location")

    def test_private_none(self):
        # Offline helper still returns something for a first octet if mapped,
        # but geolocate_ip must refuse private IPs outright.
        self.assertIsNone(core.geolocate_ip("192.168.1.1"))

    def test_geolocate_ip_works_offline(self):
        # Even with no network, a public IP resolves via the offline table.
        g = core.geolocate_ip("1.1.1.1")
        self.assertIsNotNone(g)


class TestTracerouteStopsAtDest(unittest.TestCase):
    def test_stops_at_destination(self):
        import subprocess as _sp
        real_popen = _sp.Popen
        real_ghn = net.socket.gethostbyname

        class FakeProc:
            def __init__(self, lines):
                self.stdout = iter(lines)
            def terminate(self):
                pass

        lines = [" 1  10.0.0.1  1 ms",
                 " 2  203.0.113.9  10 ms",
                 " 3  8.8.8.8  20 ms",
                 " 4  1.2.3.4  30 ms"]     # must NOT be reported
        net.socket.gethostbyname = lambda t: "8.8.8.8"
        _sp.Popen = lambda *a, **k: FakeProc(lines)
        try:
            evs = list(core.traceroute_stream("8.8.8.8", max_hops=30))
        finally:
            _sp.Popen = real_popen
            net.socket.gethostbyname = real_ghn

        hop_ips = [e.get("ip") for e in evs if "ip" in e]
        self.assertIn("8.8.8.8", hop_ips)
        self.assertNotIn("1.2.3.4", hop_ips)   # stopped at destination
        self.assertTrue(evs[-1].get("done"))
        self.assertTrue(evs[-1].get("reached"))


class TestTracerouteAuto(unittest.TestCase):
    def _run(self, lines, dest, auto):
        import subprocess as _sp
        real_popen, real_ghn = _sp.Popen, net.socket.gethostbyname

        class FP:
            def __init__(self, l):
                self.stdout = iter(l)
            def terminate(self):
                pass
            def kill(self):
                pass

        net.socket.gethostbyname = lambda t: dest
        _sp.Popen = lambda *a, **k: FP(lines)
        try:
            return list(core.traceroute_stream("x", max_hops=30, auto=auto))
        finally:
            _sp.Popen, net.socket.gethostbyname = real_popen, real_ghn

    def test_auto_stops_on_consecutive_timeouts(self):
        lines = ["  1  1 ms  10.0.0.1"] + \
                ["  %d  *  Request timed out." % n for n in range(2, 10)]
        evs = self._run(lines, "9.9.9.9", auto=True)
        hops = [e for e in evs if "ttl" in e]
        self.assertLessEqual(len(hops), 6)   # 1 ok + 5 timeouts, then stop

    def test_auto_still_stops_at_destination(self):
        lines = ["  1  1 ms  10.0.0.1", "  2  9 ms  8.8.8.8",
                 "  3  9 ms  1.2.3.4"]
        evs = self._run(lines, "8.8.8.8", auto=True)
        hop_ips = [e.get("ip") for e in evs if "ip" in e]
        self.assertNotIn("1.2.3.4", hop_ips)
        self.assertTrue(evs[-1]["reached"])

    def test_non_auto_does_not_early_stop(self):
        lines = ["  1  1 ms  10.0.0.1"] + \
                ["  %d  *  Request timed out." % n for n in range(2, 9)]
        evs = self._run(lines, "9.9.9.9", auto=False)
        hops = [e for e in evs if "ttl" in e]
        self.assertEqual(len(hops), 8)   # walks the whole list


class TestMapClusterFit(unittest.TestCase):
    def test_clustered_hops_do_not_overzoom(self):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        from ui.widgets.traceroute_map import TracerouteMap
        mw = TracerouteMap()
        mw.set_hops([
            {"n": 1, "ip": "a", "city": "Zagreb", "lat": 45.8, "lon": 16.0,
             "ms": 1, "kind": "local"},
            {"n": 2, "ip": "b", "city": "Vienna", "lat": 48.2, "lon": 16.4,
             "ms": 9, "kind": "transit"},
        ])
        mw._fit()
        # a tight cluster frames both cities instead of showing the whole world
        c_lon, c_lat, span = mw._target
        self.assertTrue(45.8 <= c_lat <= 48.2)
        self.assertTrue(16.0 <= c_lon <= 16.4)
        self.assertTrue(1.5 <= span < 60)


class TestHopHostname(unittest.TestCase):
    def test_windows_hostname_bracket(self):
        r = core._parse_hop_line(
            "  1     6 ms    <1 ms    <1 ms  router.lan [192.168.88.1]")
        self.assertEqual(r["ip"], "192.168.88.1")
        self.assertEqual(r["hostname"], "router.lan")

    def test_windows_no_hostname(self):
        r = core._parse_hop_line("  5    22 ms    16 ms    16 ms  195.3.114.229")
        self.assertEqual(r["hostname"], "195.3.114.229")

    def test_linux_hostname_paren(self):
        r = core._parse_hop_line(" 1  router.lan (192.168.88.1)  1.2 ms")
        self.assertEqual(r["hostname"], "router.lan")

    def test_long_provider_hostname(self):
        r = core._parse_hop_line(
            " 18  38 ms  zrh04s07-in-f174.1e100.net [172.217.19.174]")
        self.assertEqual(r["hostname"], "zrh04s07-in-f174.1e100.net")


class TestNetworkHelpers(unittest.TestCase):
    def test_mask_to_prefix(self):
        self.assertEqual(core._mask_to_prefix("255.255.255.0"), 24)
        self.assertEqual(core._mask_to_prefix("255.255.0.0"), 16)
        self.assertEqual(core._mask_to_prefix("255.255.255.128"), 25)
        self.assertEqual(core._mask_to_prefix("garbage"), 24)

    def test_private_mac_detected(self):
        # 2nd nibble 2/6/A/E means locally administered (randomized)
        self.assertEqual(core.lookup_vendor("0A:39:82:6C:B8:B6"),
                         "Private (randomized)")
        self.assertEqual(core.lookup_vendor("2A:24:0F:55:3A:C6"),
                         "Private (randomized)")

    def test_friendly_error_timeout(self):
        msg = core.friendly_error(
            "Command '['powershell', ...]' timed out after 8 seconds")
        self.assertNotIn("powershell", msg.lower())
        self.assertNotIn("command", msg.lower())
        self.assertIn("too long", msg.lower())

    def test_friendly_error_admin(self):
        self.assertIn("administrator",
                      core.friendly_error("Access is denied").lower())


class TestWindowsAdapterConfig(unittest.TestCase):
    # ipconfig parsing was replaced by the IP Helper API in core/windows_network.py

    def test_config_comes_from_windows_api(self):
        from core import windows_network
        orig = windows_network.active_network_config
        windows_network.active_network_config = lambda: {"adapter": "Wi-Fi", "ip": "192.168.0.238"}
        try:
            cfg = core._windows_ipconfig_config()
        finally:
            windows_network.active_network_config = orig
        self.assertEqual(cfg["ip"], "192.168.0.238")
        self.assertEqual(cfg["adapter"], "Wi-Fi")

    def test_link_speed_format(self):
        from core.windows_network import _format_link_speed
        self.assertEqual(_format_link_speed(1_000_000_000), "1 Gbps")
        self.assertEqual(_format_link_speed(866_700_000, 433_300_000), "866.7 Mbps")
        self.assertEqual(_format_link_speed(0), "")


class TestNetworkRadar(unittest.TestCase):
    """The radar reuses the map's data model, check set_topology builds the
    expected nodes without a display/GPU."""

    @classmethod
    def setUpClass(cls):
        import os
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PyQt6.QtWidgets import QApplication
        cls._app = QApplication.instance() or QApplication([])

    def _radar(self):
        from ui.widgets.network_radar import NetworkRadar
        return NetworkRadar()

    def test_builds_router_plus_devices(self):
        r = self._radar()
        devs = [
            {"ip": "192.168.0.1", "hostname": "", "vendor": "MikroTik", "rtt_ms": 1},
            {"ip": "192.168.0.5", "hostname": "PC", "vendor": "Intel", "rtt_ms": 3},
            {"ip": "192.168.0.9", "hostname": "", "vendor": "Private (randomized)", "rtt_ms": 20},
        ]
        r.set_topology("192.168.0.1", devs, router_vendor="MikroTik")
        # router node + 2 non-gateway devices = 3 nodes
        self.assertEqual(len(r._nodes), 3)
        self.assertTrue(r._nodes[0].is_router)
        # the randomized-MAC device is flagged unknown (red)
        unknown = [n for n in r._nodes if n.is_unknown]
        self.assertTrue(any(n.dev["ip"] == "192.168.0.9" for n in unknown))

    def test_detailed_mode_spreads_nodes(self):
        r = self._radar()
        r.set_detailed(True)
        devs = [{"ip": "192.168.0.5", "hostname": "", "vendor": "Intel",
                 "rtt_ms": 5}]
        r.set_topology("192.168.0.1", devs)
        dev_node = [n for n in r._nodes if not n.is_router][0]
        # In the big view devices orbit further out than on the small card.
        self.assertGreater(dev_node.dist, 0.70)

    def test_caps_node_count(self):
        r = self._radar()
        many = [{"ip": f"192.168.0.{i}", "hostname": "", "vendor": "x",
                 "rtt_ms": 5} for i in range(2, 40)]
        r.set_topology("192.168.0.1", many)
        # router + at most 12 orbiting devices
        self.assertLessEqual(len(r._nodes), 13)


class TestVendorLearning(unittest.TestCase):
    def setUp(self):
        # Use an isolated temp store so tests don't touch the real DB.
        import tempfile, os
        from core import vendor_learning as vl
        self._vl = vl
        self._tmp = tempfile.mkdtemp()
        vl._LEARNED.clear()
        vl._LOADED = True   # skip disk load
        self._orig_path = vl._store_path
        vl._store_path = lambda: __import__("pathlib").Path(self._tmp) / "v.json"

    def tearDown(self):
        self._vl._store_path = self._orig_path
        self._vl._LEARNED.clear()

    def test_tplink_router_known(self):
        import core.netwer_core as core
        self.assertEqual(core.lookup_vendor("6C:4C:BC:B7:D1:48"), "TP-Link")

    def test_teach_overrides_randomized(self):
        import core.netwer_core as core
        # AA has the locally-administered bit, normally "Private (randomized)"
        self.assertEqual(core.lookup_vendor("AA:BB:CC:11:22:33"),
                         "Private (randomized)")
        core.teach_vendor("AA:BB:CC:11:22:33", "My Router")
        self.assertEqual(core.lookup_vendor("AA:BB:CC:11:22:33"), "My Router")

    def test_remember_persists_in_memory(self):
        self._vl.remember("DE:AD:BE:00:00:00", "Acme Corp")
        self.assertEqual(self._vl.lookup("DE:AD:BE:00:00:00"), "Acme Corp")

    def test_expanded_oui_covers_common_vendors(self):
        import core.netwer_core as core
        cases = {
            "98:AF:65:C0:C8:B2": "Intel",     # the dev machine's adapter
            "6C:4C:BC:B7:D1:48": "TP-Link",   # the dev machine's router
            "A4:5E:60:00:11:22": "Apple",
            "F0:5A:09:AA:BB:CC": "Samsung",
            "5C:AA:FD:01:02:03": "Sonos",
        }
        for mac, vendor in cases.items():
            self.assertEqual(core.lookup_vendor(mac), vendor, mac)

    def test_remember_ignores_placeholders(self):
        self._vl.remember("11:22:33:44:55:66", "Unknown")
        self.assertIsNone(self._vl.lookup("11:22:33:44:55:66"))


class TestStatCardTints(unittest.TestCase):
    def test_packet_loss_tint_key_matches_icon_name(self):
        import os
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PyQt6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from ui.widgets.stat_card import StatCard
        # The dashboard builds the card with icon_name="packet_loss"; the tint
        # map must have that exact key or the tile silently goes default blue.
        self.assertIn("packet_loss", StatCard.TILE_TINTS)


class TestCustomDeviceNames(unittest.TestCase):
    def setUp(self):
        import tempfile, pathlib
        from core import device_names as dn
        self._dn = dn
        self._tmp = tempfile.mkdtemp()
        dn._NAMES.clear()
        dn._LOADED = True
        self._orig = dn._store_path
        dn._store_path = lambda: pathlib.Path(self._tmp) / "n.json"

    def tearDown(self):
        self._dn._store_path = self._orig
        self._dn._NAMES.clear()

    def test_name_keyed_by_mac_survives_ip_change(self):
        dev = {"ip": "192.168.0.45", "mac": "0A:39:82:6C:B8:B6"}
        self._dn.set_name(dev, "Mum's laptop")
        moved = {"ip": "192.168.0.99", "mac": "0A:39:82:6C:B8:B6"}
        self.assertEqual(self._dn.get(moved), "Mum's laptop")

    def test_custom_name_wins_in_display(self):
        import os
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from ui.widgets.network_map import device_display_name
        dev = {"ip": "192.168.0.45", "mac": "0A:39:82:6C:B8:B6",
               "hostname": "", "vendor": "Private (randomized)"}
        self.assertEqual(device_display_name(dev), "Phone")
        self._dn.set_name(dev, "Printer")
        self.assertEqual(device_display_name(dev), "Printer")

    def test_empty_name_clears(self):
        dev = {"ip": "10.0.0.5", "mac": "AA:BB:CC:DD:EE:FF"}
        self._dn.set_name(dev, "Thing")
        self._dn.set_name(dev, "")
        self.assertIsNone(self._dn.get(dev))

    def test_falls_back_to_ip_key_without_mac(self):
        dev = {"ip": "10.0.0.7", "mac": ""}
        self.assertTrue(self._dn.set_name(dev, "No-MAC device"))
        self.assertEqual(self._dn.get({"ip": "10.0.0.7"}), "No-MAC device")


class TestDeviceFingerprint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PyQt6.QtWidgets import QApplication
        cls._app = QApplication.instance() or QApplication([])

    def _resp(self, ptr_name, qname="45.0.168.192.in-addr.arpa"):
        import struct
        def nb(n):
            return b"".join(bytes([len(l)]) + l.encode() for l in n.split(".")) + b"\x00"
        header = struct.pack(">HHHHHH", 0, 0x8400, 1, 1, 0, 0)
        q = nb(qname) + struct.pack(">HH", 12, 1)
        target = nb(ptr_name)
        ans = nb(qname) + struct.pack(">HHIH", 12, 1, 120, len(target)) + target
        return header + q + ans

    def test_reverse_query_is_valid_ptr(self):
        import struct
        from core import device_fingerprint as fp
        q = fp._build_reverse_query("192.168.0.45")
        body = q[12:]
        labels, i = [], 0
        while body[i]:
            n = body[i]
            labels.append(body[i + 1:i + 1 + n].decode())
            i += n + 1
        self.assertEqual(".".join(labels), "45.0.168.192.in-addr.arpa")
        qtype, qclass = struct.unpack(">HH", body[i + 1:i + 5])
        self.assertEqual(qtype, 12)              # PTR
        self.assertTrue(qclass & 0x8000)         # mDNS unicast-response bit

    def test_parses_ptr_answer(self):
        from core import device_fingerprint as fp
        self.assertEqual(
            fp._parse_ptr_answer(self._resp("Lukas-iPhone.local")),
            "Lukas-iPhone.local")

    def test_malformed_responses_do_not_raise(self):
        from core import device_fingerprint as fp
        for bad in (b"", b"\x00" * 5, b"\xff" * 40):
            self.assertIsNone(fp._parse_ptr_answer(bad))

    def test_clean_mdns_name(self):
        from core import device_fingerprint as fp
        self.assertEqual(fp.clean_mdns_name("Ana-iPad.local."), "Ana-iPad")

    def test_name_signatures(self):
        from core import device_fingerprint as fp
        self.assertEqual(fp.name_signature("Lukas-iPhone"), ("Apple", "dev_phone"))
        self.assertEqual(fp.name_signature("Ana-iPad"), ("Apple", "dev_tablet"))
        self.assertEqual(fp.name_signature("MacBook-Pro"), ("Apple", "dev_laptop"))
        self.assertIsNone(fp.name_signature("DESKTOP-FKRBQ25"))

    def test_needs_fingerprint_selection(self):
        import core.netwer_core as core
        randomized = {"ip": "192.168.0.45", "vendor": "Private (randomized)",
                      "hostname": "Unknown"}
        known = {"ip": "192.168.0.9", "vendor": "Intel", "hostname": "PC"}
        gateway = {"ip": "192.168.0.1", "vendor": "Unknown",
                   "hostname": "Unknown", "is_gateway": True}
        self.assertTrue(core._needs_fingerprint(randomized))
        self.assertFalse(core._needs_fingerprint(known))
        self.assertFalse(core._needs_fingerprint(gateway))

    def test_identified_private_device_is_not_unknown_on_radar(self):
        from ui.widgets.network_radar import NetworkRadar
        r = NetworkRadar()
        r.set_topology("192.168.0.1", [
            {"ip": "192.168.0.45", "vendor": "Apple (private address)",
             "kind": "dev_phone", "hostname": "Lukas-iPhone"},
            {"ip": "192.168.0.183", "vendor": "Private (randomized)",
             "hostname": "Unknown"},
        ])
        flagged = [n.dev["ip"] for n in r._nodes if n.is_unknown]
        self.assertEqual(flagged, ["192.168.0.183"])


class TestStaticMapClicks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PyQt6.QtWidgets import QApplication
        cls._app = QApplication.instance() or QApplication([])

    def test_device_node_click_emits_device(self):
        from ui.widgets.network_map import NetworkMap
        nm = NetworkMap()
        devs = [{"ip": "192.168.0.45", "hostname": "Lukas-iPhone",
                 "vendor": "Apple (private address)", "kind": "dev_phone"}]
        nm.set_topology("192.168.0.1", devs, "TP-Link", True)
        seen = {}
        nm.node_clicked.connect(lambda d: seen.update(d))
        nm.node_clicked.emit(devs[0])
        self.assertEqual(seen.get("ip"), "192.168.0.45")

    def test_map_labels_devices_by_name(self):
        from ui.widgets.network_map import NetworkMap
        nm = NetworkMap()
        nm.set_topology("192.168.0.1", [
            {"ip": "192.168.0.45", "hostname": "Lukas-iPhone",
             "vendor": "Apple (private address)", "kind": "dev_phone"}],
            "TP-Link", True)
        nm.resize(500, 300)
        titles = nm.node_titles()
        self.assertIn(("Lukas-iPhone", "192.168.0.45"), titles)


class TestPolishFixes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PyQt6.QtWidgets import QApplication
        cls._app = QApplication.instance() or QApplication([])

    def test_packet_loss_tile_defaults_to_green(self):
        from ui.widgets.stat_card import StatCard
        bg, fg = StatCard.TILE_TINTS["packet_loss"]
        self.assertEqual(fg.lower(), "#33d6a6")      # healthy = green

    def test_stat_card_tile_can_be_recoloured(self):
        from ui.widgets.stat_card import StatCard
        c = StatCard("packet_loss", "Packet Loss")
        c.set_tile_tint("#351a24", "#ff6b8a")        # must not raise
        self.assertIn("#351a24", c._icon.styleSheet())

    def test_charts_use_the_card_background(self):
        import app.theme as th
        from ui.widgets.live_chart import LiveChart
        ch = LiveChart()
        want = th.card_bg().lower().lstrip("#")
        got = ch._plot.backgroundBrush().color().name().lower().lstrip("#")
        self.assertEqual(got, want)

    def test_native_adapter_details_use_windows_api(self):
        from core import windows_network
        orig = windows_network.adapter_details
        windows_network.adapter_details = lambda name: {"name": name, "ipv4": "192.168.0.238", "dhcp": "Enabled"}
        try:
            d = core._windows_adapter_details_native("Wi-Fi")
        finally:
            windows_network.adapter_details = orig
        self.assertEqual(d["ipv4"], "192.168.0.238")
        self.assertEqual(d["dhcp"], "Enabled")


class TestDiagnosticsReasoning(unittest.TestCase):
    """The verdict logic is pure, test it without touching a network."""

    def _m(self, **kw):
        m = dict(has_ip=True, ip="192.168.0.238", gateway="192.168.0.1",
                 has_gateway=True, self_assigned=False, wifi=True, signal=85,
                 router_reachable=True,
                 router={"avg": 2, "loss": 0, "jitter": 1},
                 internet_reachable=True,
                 internet={"avg": 18, "loss": 0, "jitter": 3},
                 dns_working=True, dns_ms=25, dns_failures=0,
                 best_public_dns=None)
        m.update(kw)
        return m

    def test_healthy_network_reports_good(self):
        from core import diagnostics as d
        r = d.analyse(self._m())
        self.assertEqual(r["severity"], d.GOOD)

    def test_no_ip_stops_at_link_layer(self):
        from core import diagnostics as d
        r = d.analyse(self._m(has_ip=False))
        self.assertEqual(r["severity"], d.CRITICAL)
        self.assertEqual(r["findings"][0]["title"], "No IP address")
        # must not go on to blame DNS/ISP when the link itself is down
        self.assertEqual(len(r["findings"]), 1)

    def test_self_assigned_address_blames_dhcp(self):
        from core import diagnostics as d
        r = d.analyse(self._m(ip="169.254.4.4", self_assigned=True))
        self.assertIn("hand out an address", r["findings"][0]["title"])

    def test_router_ok_but_internet_down_blames_isp(self):
        from core import diagnostics as d
        r = d.analyse(self._m(internet_reachable=False,
                              internet={"avg": None, "loss": 100,
                                        "jitter": None}))
        titles = " ".join(f["title"] for f in r["findings"])
        self.assertIn("the internet isn't", titles)
        self.assertIn("ISP", " ".join(f["action"] for f in r["findings"]))

    def test_router_unreachable_blames_local_link(self):
        from core import diagnostics as d
        r = d.analyse(self._m(router_reachable=False,
                              router={"avg": None, "loss": 100,
                                      "jitter": None}))
        self.assertIn("router isn't responding", r["findings"][0]["title"])

    def test_weak_wifi_is_flagged(self):
        from core import diagnostics as d
        r = d.analyse(self._m(signal=20))
        titles = [f["title"] for f in r["findings"]]
        self.assertIn("Weak Wi-Fi signal", titles)

    def test_slow_dns_suggests_the_faster_resolver_by_name(self):
        from core import diagnostics as d
        r = d.analyse(self._m(dns_ms=200,
                              best_public_dns={"name": "Cloudflare", "ms": 15}))
        actions = " ".join(f["action"] for f in r["findings"])
        self.assertIn("Cloudflare", actions)

    def test_findings_are_sorted_worst_first(self):
        from core import diagnostics as d
        r = d.analyse(self._m(signal=20, dns_ms=200,
                              internet={"avg": 90, "loss": 0, "jitter": 5}))
        order = [d._SEVERITY_ORDER[f["severity"]] for f in r["findings"]]
        self.assertEqual(order, sorted(order))


class TestSearchSuggestions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PyQt6.QtWidgets import QApplication
        cls._app = QApplication.instance() or QApplication([])
        from core import netwer_core
        import main as app_main
        from ui.main_window import MainWindow
        cls._w = MainWindow(netwer_core)
        app_main._register_pages(cls._w)

    def _titles(self, q):
        return [s["title"] for s in self._w.search_suggestions(q)]

    def test_prefix_of_a_keyword_suggests_the_tool(self):
        # 'tr' should reach Traceroute (which lives on the DNS Tools page)
        self.assertIn("DNS Tools", self._titles("tr"))

    def test_title_prefix_ranks_first(self):
        self.assertEqual(self._titles("ping")[0], "Ping")

    def test_empty_query_returns_nothing(self):
        self.assertEqual(self._w.search_suggestions(""), [])

    def test_devices_are_suggested_too(self):
        dash = self._w._pages["dashboard"]
        dash._all_devices = [{"ip": "192.168.0.45",
                              "hostname": "Lukas-iPhone",
                              "vendor": "Apple", "mac": "0A:39:82:6C:B8:B6"}]
        try:
            self.assertIn("Lukas-iPhone", self._titles("iph"))
        finally:
            dash._all_devices = []


class TestSearchDropdownStability(unittest.TestCase):
    """The dropdown used to be a hand-rolled Qt.Popup that could take the app
    down; it's a QCompleter now. These cover the paths that broke."""

    @classmethod
    def setUpClass(cls):
        import os
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PyQt6.QtWidgets import QApplication
        cls._app = QApplication.instance() or QApplication([])
        from core import netwer_core
        import main as app_main
        from ui.main_window import MainWindow
        cls._w = MainWindow(netwer_core)
        app_main._register_pages(cls._w)
        cls._tb = cls._w.topbar

    def test_typing_letter_by_letter_is_safe(self):
        for word in ("traceroute", "zzzz", "192.168.0.1", ""):
            for i in range(len(word) + 1):
                self._tb._on_search_typed(word[:i])
        self.assertIsNotNone(self._tb._suggest_model)

    def test_empty_query_clears_the_list(self):
        self._tb._on_search_typed("tr")
        self.assertTrue(self._tb._suggest_model.stringList())
        self._tb._on_search_typed("")
        self.assertEqual(self._tb._suggest_model.stringList(), [])

    def test_activating_a_suggestion_navigates(self):
        self._tb._on_search_typed("speed")
        labels = self._tb._suggest_model.stringList()
        self.assertTrue(labels)
        self._tb._on_suggestion_activated(labels[0])
        self.assertEqual(self._w._current_key, "speedtest")

    def test_rebuilding_pages_while_open_does_not_break(self):
        import app.theme as th
        self._tb._on_search_typed("dns")
        self._w._reskin_all()
        th.apply_theme("Dark Blue", "Default")
        self._tb._on_search_typed("ping")     # must still work afterwards
        self.assertTrue(self._tb._suggest_model.stringList())

    def test_unknown_label_activation_is_ignored(self):
        # a stale label must not raise
        self._tb._on_suggestion_activated("no such entry")


class TestDisplayProfiles(unittest.TestCase):
    def test_profile_thresholds(self):
        from app import display as d
        self.assertEqual(d.profile_for(1366), "compact")
        self.assertEqual(d.profile_for(1920), "standard")
        self.assertEqual(d.profile_for(2560), "large")

    def test_resolve_preset_vs_auto(self):
        from app import display as d
        self.assertEqual(d.resolve("1366x768", 1920, 1080), (1366, 768))
        self.assertEqual(d.resolve("auto", 1920, 1080), (1920, 1080))
        self.assertEqual(d.resolve("bogus-key", 1920, 1080), (1920, 1080))

    def test_window_geometry_never_exceeds_screen(self):
        from app import display as d
        for w, h in [(1280, 720), (1366, 768), (1920, 1080), (3840, 2160)]:
            ww, wh, mw, mh = d.window_geometry(w, h)
            self.assertLessEqual(ww, w)
            self.assertLessEqual(wh, h)
            self.assertLessEqual(mw, ww)
            self.assertLessEqual(mh, wh)

    def test_apply_ui_scale_round_trip(self):
        from app.theme import Theme, apply_ui_scale
        apply_ui_scale("compact")
        self.assertEqual(Theme.SIDEBAR_WIDTH, 200)
        apply_ui_scale("standard")
        self.assertEqual(Theme.SIDEBAR_WIDTH, 230)
        self.assertEqual(Theme.TOPBAR_HEIGHT, 60)

    def test_apply_ui_scale_unknown_falls_back_to_standard(self):
        from app.theme import Theme, apply_ui_scale
        apply_ui_scale("nonsense")
        self.assertEqual(Theme.UI_SCALE, "standard")
        self.assertEqual(Theme.SIDEBAR_WIDTH, 230)


class TestStartupSidebarBuild(unittest.TestCase):
    """Regression test: apply_resolution() used to trigger a full page
    rebuild even before pages were registered, so main.py's normal startup
    sequence (apply_resolution -> _register_pages) built the sidebar twice."""

    @classmethod
    def setUpClass(cls):
        import os
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PyQt6.QtWidgets import QApplication
        cls._app = QApplication.instance() or QApplication([])

    def test_startup_sequence_does_not_duplicate_sidebar(self):
        from PyQt6.QtWidgets import QLabel
        from core import netwer_core
        import main as app_main
        from ui.main_window import MainWindow

        w = MainWindow(netwer_core)
        w.apply_resolution("auto", persist=False)   # runs BEFORE pages exist
        app_main._register_pages(w)
        w.start("dashboard")

        titles = [lbl.text() for lbl in w.sidebar.findChildren(QLabel)
                  if lbl.text() == "Ping Sweep"]
        self.assertEqual(len(titles), 1)

    def test_live_resolution_change_does_not_accumulate(self):
        from PyQt6.QtWidgets import QLabel
        from core import netwer_core
        import main as app_main
        from ui.main_window import MainWindow

        w = MainWindow(netwer_core)
        w.apply_resolution("auto", persist=False)
        app_main._register_pages(w)
        w.start("dashboard")

        for key in ("1366x768", "1920x1080", "2560x1440"):
            w.apply_resolution(key)

        titles = [lbl.text() for lbl in w.sidebar.findChildren(QLabel)
                  if lbl.text() == "Port Scanner"]
        self.assertEqual(len(titles), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
class TestDeviceNamesAndKinds(unittest.TestCase):
    """Discovery naming and type detection (pure parts, no network)."""

    def _kind(self, **dev):
        from core import device_fingerprint as fp
        dev.setdefault("ip", "192.168.88.50")
        return fp.classify_kind(dev)

    def test_lg_electronics_is_a_tv(self):
        self.assertEqual(self._kind(vendor="LG Electronics"), "dev_tv")

    def test_hostname_beats_vendor(self):
        self.assertEqual(self._kind(vendor="Samsung Electronics",
                                    hostname="Galaxy-S23"), "dev_phone")
        self.assertEqual(self._kind(vendor="Unknown",
                                    hostname="Living-Room-TV"), "dev_tv")

    def test_computers_servers_and_phones(self):
        self.assertEqual(self._kind(vendor="ASRock", hostname="DESKTOP-FKRBQ25"),
                         "dev_pc")
        self.assertEqual(self._kind(vendor="Unknown", hostname="LAPTOP-8DK2"),
                         "dev_laptop")
        self.assertEqual(self._kind(vendor="Unknown", hostname="ubuntu-server"),
                         "dev_server")
        self.assertEqual(self._kind(vendor="Raspberry Pi"), "dev_server")
        self.assertEqual(self._kind(vendor="Private (randomized)"), "dev_phone")

    def test_gateway_is_router_and_self_is_a_computer(self):
        self.assertEqual(self._kind(vendor="Unknown", is_gateway=True),
                         "dev_router")
        self.assertIn(self._kind(is_self=True), ("dev_pc", "dev_laptop"))

    def test_word_matching_avoids_false_hits(self):
        self.assertEqual(self._kind(vendor="Unknown", hostname="banana"),
                         "dev_generic")
        self.assertEqual(self._kind(vendor="Unknown", hostname="network-switch"),
                         "dev_generic")
        self.assertEqual(self._kind(vendor="Unknown", hostname="octv"),
                         "dev_generic")

    def test_ports_identify_devices(self):
        from core import device_fingerprint as fp
        self.assertEqual(fp.classify_kind({"ip": "x", "vendor": "Apple"},
                                          ports={62078}), "dev_phone")
        self.assertEqual(fp.classify_kind({"ip": "x", "vendor": "Unknown"},
                                          ports={3001}), "dev_tv")
        self.assertEqual(fp.classify_kind({"ip": "x", "vendor": "Unknown"},
                                          ports={9100}), "dev_printer")

    def test_upnp_description_identifies_tv(self):
        from core import device_fingerprint as fp
        xml = (b'<root xmlns="urn:schemas-upnp-org:device-1-0"><device>'
               b'<deviceType>urn:schemas-upnp-org:device:MediaRenderer:1'
               b'</deviceType><friendlyName>[LG] webOS TV OLED55C1'
               b'</friendlyName><manufacturer>LG Electronics</manufacturer>'
               b'</device></root>')
        info = fp._parse_upnp_description(xml)
        self.assertEqual(info["friendly_name"], "[LG] webOS TV OLED55C1")
        self.assertEqual(fp.classify_kind({"ip": "x", "vendor": "Unknown"},
                                          upnp=info), "dev_tv")

    def test_upnp_description_rejects_entities(self):
        from core import device_fingerprint as fp
        self.assertEqual(fp._parse_upnp_description(
            b'<!DOCTYPE a [<!ENTITY b "c">]><root/>'), {})

    def test_usable_name_drops_useless_names(self):
        from core import device_fingerprint as fp
        ip = "192.168.88.1"
        self.assertEqual(fp.usable_name("lgwebostv.lan", ip), "lgwebostv")
        self.assertEqual(fp.usable_name("DESKTOP-ABC.local.", ip), "DESKTOP-ABC")
        for useless in ("", "router", "192-168-88-1", ip,
                        "1.88.168.192.in-addr.arpa"):
            self.assertEqual(fp.usable_name(useless, ip), "")

    def test_netbios_reply_gives_computer_name(self):
        import struct
        from core import device_fingerprint as fp
        self.assertEqual(len(fp._nbstat_query()), 50)
        reply = (struct.pack(">HHHHHH", 0x4E57, 0x8400, 0, 1, 0, 0)
                 + b"\x20" + b"CK" + b"A" * 30 + b"\x00"
                 + struct.pack(">HHIH", 0x21, 1, 0, 38) + bytes([2])
                 + b"MYPC-NAME".ljust(15) + b"\x00" + struct.pack(">H", 0x0400)
                 + b"WORKGROUP".ljust(15) + b"\x00" + struct.pack(">H", 0x8400)
                 + b"\x00" * 6)
        self.assertEqual(fp._parse_nbstat(reply), "MYPC-NAME")
        self.assertIsNone(fp._parse_nbstat(b"\xff" * 30))
        self.assertIsNone(fp._parse_nbstat(b""))

    def test_open_ports_sees_a_listener(self):
        import socket
        from core import device_fingerprint as fp
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(5)
        try:
            port = srv.getsockname()[1]
            self.assertIn(port, fp.open_ports("127.0.0.1", (port, 1), 0.5))
        finally:
            srv.close()

    def test_enrich_device_uses_name_lookup_and_kind(self):
        from core import device_fingerprint as fp
        orig = (fp._lookup_name, fp.upnp_info, fp.open_ports)
        fp._lookup_name = lambda ip: ("lgwebostv", "mdns")
        fp.upnp_info = lambda ip: {}
        fp.open_ports = lambda ip: set()
        try:
            out = fp.enrich_device({"ip": "192.168.88.254",
                                    "vendor": "LG Electronics"})
        finally:
            fp._lookup_name, fp.upnp_info, fp.open_ports = orig
        self.assertEqual(out["hostname"], "lgwebostv")
        self.assertEqual(out["kind"], "dev_tv")

    def test_display_name_never_falls_back_to_a_bare_ip(self):
        import os
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from ui.widgets.network_map import device_display_name
        self.assertEqual(device_display_name(
            {"ip": "192.168.88.253", "hostname": "192.168.88.253",
             "vendor": "Unknown", "is_self": True}) in
            ("Computer", "Laptop"), True)
        self.assertEqual(device_display_name(
            {"ip": "192.168.88.9", "hostname": "", "vendor": "Unknown"}),
            "Unknown device")
        self.assertEqual(device_display_name(
            {"ip": "192.168.88.254", "hostname": "lgwebostv",
             "vendor": "LG Electronics"}), "lgwebostv")


class TestDiscoveryEnrichment(unittest.TestCase):
    def test_enrichment_publishes_names_and_keeps_counts(self):
        import threading
        from core import device_fingerprint as fp
        from core.discovery import DiscoveryService
        svc = DiscoveryService()
        for ip, src in (("192.168.88.254", "icmp"), ("192.168.88.253", "icmp")):
            svc._record({"segment_id": "s", "ip": ip, "hostname": ip,
                         "mac": "", "vendor": "Unknown", "source": src,
                         "reachability": "reachable", "kind": ""})
        orig = fp.enrich_device
        fp.enrich_device = lambda d: {"hostname": "name-" + d["ip"].split(".")[-1],
                                      "kind": "dev_tv"}
        try:
            events = list(svc._enrich_devices(threading.Event(), 254, 254))
        finally:
            fp.enrich_device = orig
        self.assertEqual(events[0]["event"], "enriching")
        by_ip = {d["ip"]: d for d in svc.snapshot()["devices"]}
        self.assertEqual(by_ip["192.168.88.254"]["hostname"], "name-254")
        self.assertEqual(by_ip["192.168.88.253"]["kind"], "dev_tv")
        self.assertEqual(by_ip["192.168.88.253"]["reachability"], "reachable")
        self.assertEqual(svc.snapshot()["summary"]["source_counts"]["icmp"], 2)

    def test_own_pc_gets_its_name_and_mac(self):
        from core.discovery import DiscoveryService
        svc = DiscoveryService()
        seg = {"id": "s", "label": "Ethernet", "cidr": "192.168.88.0/24",
               "kind": "local"}
        dev = svc._make_device(seg, "192.168.88.253", "", 1.0, "icmp",
                               "reachable", "192.168.88.1",
                               local_ips={"192.168.88.253"},
                               local_macs={"192.168.88.253": "00:1A:2B:3C:4D:5E"})
        self.assertTrue(dev["is_self"])
        self.assertEqual(dev["mac"], "00:1A:2B:3C:4D:5E")
        self.assertNotEqual(dev["hostname"], "192.168.88.253")
        self.assertIn(dev["kind"], ("dev_pc", "dev_laptop"))


class TestTopDevicesList(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PyQt6.QtWidgets import QApplication
        cls._app = QApplication.instance() or QApplication([])

    def _page(self):
        # The module-level activity log is a QObject; earlier tests that tear
        # down their QApplication delete it. Recreate it if that happened.
        from PyQt6 import sip
        import app.activity as act
        import ui.widgets.recent_activity as recent
        if sip.isdeleted(act.activity):
            act.activity = act.ActivityLog()
            recent.activity = act.activity
        from ui.pages.dashboard_page import DashboardPage
        import core.netwer_core as nc
        page = DashboardPage(nc)

        class Stub:
            def __init__(self):
                self.devices = []
            def snapshot(self):
                return {"status": "complete", "segments": [{"id": "s"}],
                        "devices": [dict(d) for d in self.devices],
                        "summary": {}, "active": False}
        page._discovery_service = Stub()
        return page

    @staticmethod
    def _rows(page):
        from PyQt6.QtWidgets import QLabel
        lay = page._devices_container
        count = 0
        for i in range(lay.count()):
            w = lay.itemAt(i).widget()
            if w is not None and w is not page._devices_placeholder:
                count += 1
        return count

    def test_resync_does_not_leave_duplicate_rows(self):
        page = self._page()
        devs = [
            {"segment_id": "s", "ip": "192.168.88.1", "mac": "AA", "vendor": "MikroTik",
             "reachability": "reachable", "hostname": "MikroTik", "is_gateway": True},
            {"segment_id": "s", "ip": "192.168.88.254", "mac": "BB",
             "vendor": "LG Electronics", "reachability": "reachable",
             "hostname": "lgwebostv"},
            {"segment_id": "s", "ip": "192.168.88.253", "mac": "CC",
             "vendor": "Unknown", "reachability": "reachable",
             "hostname": "DESKTOP-ABC", "is_self": True},
        ]
        stub = page._discovery_service
        # Several syncs while devices trickle in, like a real scan.
        for n in (1, 2, 3, 3):
            stub.devices = devs[:n]
            page._sync_discovery_snapshot()
        self.assertEqual(self._rows(page), 3)
        stub.devices = devs[:2] + [dict(devs[2], hostname="renamed")]
        page._sync_discovery_snapshot()
        self.assertEqual(self._rows(page), 3)

    def test_list_is_router_first_then_by_ip(self):
        page = self._page()
        devs = [{"ip": "192.168.88.254"}, {"ip": "192.168.88.9"},
                {"ip": "192.168.88.1", "is_gateway": True}]
        ordered = sorted(devs, key=page._device_sort_key)
        self.assertEqual([d["ip"] for d in ordered],
                         ["192.168.88.1", "192.168.88.9", "192.168.88.254"])

    def test_startup_scan_is_silent_and_manual_rescan_is_not(self):
        page = self._page()
        started = []
        page._rescan_network = lambda: started.append(page._silent_scan)
        page._start_startup_scan()
        page._on_rescan_clicked()
        self.assertEqual(started, [True, False])


class TestIPv6Health(unittest.TestCase):
    def _m(self, **kw):
        m = dict(has_ip=True, ip="192.168.88.253", gateway="192.168.88.1",
                 has_gateway=True, self_assigned=False, wifi=False,
                 router_reachable=True,
                 router={"avg": 2, "loss": 0, "jitter": 1},
                 internet_reachable=True,
                 internet={"avg": 18, "loss": 0, "jitter": 3},
                 dns_working=True, dns_ms=25, dns_failures=0,
                 dns_ipv4_failures=0, dns_ipv6_failures=0,
                 best_public_dns=None)
        m.update(kw)
        return m

    def test_scope_classification(self):
        from core import diagnostics as d
        self.assertEqual(d._ipv6_scope("2a01:598:abcd::1"), "global")
        self.assertEqual(d._ipv6_scope("fd00:1234::5"), "ula")
        self.assertEqual(d._ipv6_scope("fe80::1%12"), "link-local")
        self.assertEqual(d._ipv6_scope(""), "none")
        self.assertEqual(d._ipv6_scope("::1"), "none")

    def test_real_ipv6_failure_mentions_the_address(self):
        from core import diagnostics as d
        r = d.analyse(self._m(dns_ipv6_failures=3, ipv6="2a01:598::7",
                              ipv6_scope="global", ipv6_internet=True))
        f = [x for x in r["findings"] if "IPv6 DNS" in x["title"]]
        self.assertEqual(len(f), 1)
        self.assertIn("2a01:598::7", f[0]["detail"])

    def test_missing_aaaa_without_usable_ipv6_is_not_a_problem(self):
        from core import diagnostics as d
        for scope in ("link-local", "ula", "none"):
            r = d.analyse(self._m(dns_ipv6_failures=3, ipv6="",
                                  ipv6_scope=scope))
            self.assertEqual(r["severity"], d.GOOD, scope)

    def test_ipv6_address_that_cannot_reach_internet_is_info_only(self):
        from core import diagnostics as d
        r = d.analyse(self._m(ipv6="2a01:598::7", ipv6_scope="global",
                              ipv6_internet=False))
        self.assertEqual(r["severity"], d.INFO)

    def test_old_measurements_without_ipv6_info_still_warn(self):
        from core import diagnostics as d
        r = d.analyse(self._m(dns_ipv6_failures=3))
        self.assertTrue(any("IPv6 DNS" in x["title"] for x in r["findings"]))

    def test_aaaa_falls_back_to_the_adapters_own_resolver(self):
        from core import diagnostics as d
        calls = []
        orig = d._time_dns

        def fake(domain, server=None, timeout=1.0, record_type=1,
                 allow_empty=False):
            calls.append((server, allow_empty))
            return None if server is None else 4.2
        d._time_dns = fake
        try:
            self.assertEqual(d._time_aaaa("github.com", ["192.168.88.1"]), 4.2)
        finally:
            d._time_dns = orig
        self.assertEqual(calls, [(None, False), ("192.168.88.1", True)])

    def test_empty_aaaa_answer_counts_as_resolver_working(self):
        import socket, struct, threading
        from core import diagnostics as d
        srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        srv.bind(("127.0.0.1", 0))
        port = srv.getsockname()[1]

        def serve():
            data, addr = srv.recvfrom(512)
            # echo id + question, flags: response, NOERROR, zero answers
            srv.sendto(data[:2] + struct.pack(">HHHHH", 0x8180, 1, 0, 0, 0)
                       + data[12:], addr)
        threading.Thread(target=serve, daemon=True).start()
        try:
            self.assertTrue(d._query_dns("github.com", "127.0.0.1", 1.0, 28,
                                         allow_empty=True, port=port))
        finally:
            srv.close()
        # and the strict mode still treats it as a failure
        srv2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        srv2.bind(("127.0.0.1", 0))
        port2 = srv2.getsockname()[1]

        def serve2():
            data, addr = srv2.recvfrom(512)
            srv2.sendto(data[:2] + struct.pack(">HHHHH", 0x8180, 1, 0, 0, 0)
                        + data[12:], addr)
        threading.Thread(target=serve2, daemon=True).start()
        try:
            with self.assertRaises(ValueError):
                d._query_dns("github.com", "127.0.0.1", 1.0, 28, port=port2)
        finally:
            srv2.close()

    def test_preferred_ipv6_prefers_global_over_link_local(self):
        from core import windows_network as wn
        addrs = [{"address": "fe80::1%12", "prefix": 64},
                 {"address": "fd00::5", "prefix": 64},
                 {"address": "2a01:598::7", "prefix": 64},
                 {"address": "192.168.88.253", "prefix": 24}]
        self.assertEqual(wn._preferred_ipv6(addrs)["address"], "2a01:598::7")
        self.assertEqual(wn._preferred_ipv6(addrs[:2])["address"], "fd00::5")
        self.assertEqual(wn._preferred_ipv6(addrs[:1])["address"], "fe80::1%12")
        self.assertIsNone(wn._preferred_ipv6(addrs[3:]))
