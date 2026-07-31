"""
NETWER — unit tests for pure backend helpers.

These cover the deterministic, network-free functions so we catch regressions
when adding features. Run with:  python -m pytest tests/  (or python -m unittest)
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.netwer_core as core


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

    def test_all_unknown_falls_back_to_ip(self):
        self.assertEqual(
            self.fn({"hostname": "Unknown", "vendor": "Unknown",
                     "ip": "192.168.1.77"}), "192.168.1.77")


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
    """The trace itself must not perform geolocation — that used to make a
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
        real_ghn = core.socket.gethostbyname

        class FakeProc:
            def __init__(self, lines):
                self.stdout = iter(lines)
            def terminate(self):
                pass

        lines = [" 1  10.0.0.1  1 ms",
                 " 2  203.0.113.9  10 ms",
                 " 3  8.8.8.8  20 ms",
                 " 4  1.2.3.4  30 ms"]     # must NOT be reported
        core.socket.gethostbyname = lambda t: "8.8.8.8"
        _sp.Popen = lambda *a, **k: FakeProc(lines)
        try:
            evs = list(core.traceroute_stream("8.8.8.8", max_hops=30))
        finally:
            _sp.Popen = real_popen
            core.socket.gethostbyname = real_ghn

        hop_ips = [e.get("ip") for e in evs if "ip" in e]
        self.assertIn("8.8.8.8", hop_ips)
        self.assertNotIn("1.2.3.4", hop_ips)   # stopped at destination
        self.assertTrue(evs[-1].get("done"))
        self.assertTrue(evs[-1].get("reached"))


class TestTracerouteAuto(unittest.TestCase):
    def _run(self, lines, dest, auto):
        import subprocess as _sp
        real_popen, real_ghn = _sp.Popen, core.socket.gethostbyname

        class FP:
            def __init__(self, l):
                self.stdout = iter(l)
            def terminate(self):
                pass
            def kill(self):
                pass

        core.socket.gethostbyname = lambda t: dest
        _sp.Popen = lambda *a, **k: FP(lines)
        try:
            return list(core.traceroute_stream("x", max_hops=30, auto=auto))
        finally:
            _sp.Popen, core.socket.gethostbyname = real_popen, real_ghn

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
        mw._fit(len(mw._hops))
        # Tight cluster must stay at a comfortable regional span, not zoom in.
        self.assertFalse(mw._world_mode)
        self.assertGreaterEqual(mw._span, 30)


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
