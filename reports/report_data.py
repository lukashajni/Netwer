"""
NETWER report data collector.

Gathers everything the PDF report needs by calling the backend, based on
which sections were requested. Runs inside a worker (it makes network
calls and a device scan, which take seconds), so it must NOT be called
on the UI thread directly.

Returns a dict shaped for reports.pdf_report.build_report().
"""


def collect(core, sections):
    """Collect report data for the requested sections.

    core: the netwer_core backend module
    sections: iterable of section keys ("network", "system", "devices",
              "connectivity")
    """
    sections = set(sections)
    data = {"summary": {}}

    # Network configuration (also feeds the summary strip)
    if "network" in sections or "connectivity" in sections:
        eth = core.get_ethernet_info()
        if isinstance(eth, dict) and "error" not in eth:
            net = {
                "name": eth.get("adapter", ""),
                "description": "",
                "ipv4": eth.get("ip", ""),
                "subnet_mask": eth.get("subnet_mask", ""),
                "gateway": eth.get("gateway", ""),
                "dns": eth.get("dns", ""),
                "public_ip": eth.get("public_ip", ""),
                "mac": eth.get("mac", ""),
                "dhcp": "",
                "link_speed": "",
            }
            # Enrich with full adapter details (description, DHCP, link speed)
            adapter_name = eth.get("adapter", "")
            if adapter_name and hasattr(core, "get_adapter_details"):
                details = core.get_adapter_details(adapter_name)
                if isinstance(details, dict) and "error" not in details:
                    net["description"] = details.get("description", "")
                    net["dhcp"] = details.get("dhcp", "")
                    net["link_speed"] = details.get("link_speed", "")
                    # Prefer detailed subnet if base was empty
                    if not net["subnet_mask"]:
                        net["subnet_mask"] = details.get("subnet_mask", "")
            data["network"] = net

    # System information
    if "system" in sections:
        sysinfo = core.get_system_info()
        if isinstance(sysinfo, dict) and "error" not in sysinfo:
            uptime = (f"{sysinfo.get('days',0)}d "
                      f"{sysinfo.get('hours',0)}h "
                      f"{sysinfo.get('minutes',0)}m")
            data["system"] = {
                "computer": sysinfo.get("computer", ""),
                "os": sysinfo.get("os", ""),
                "cpu": sysinfo.get("cpu", ""),
                "ram": sysinfo.get("ram", ""),
                "uptime": uptime,
            }

    # Connectivity test (ping), also feeds summary
    ping_results = None
    if "connectivity" in sections:
        ping_results = core.ping_quick()
        if isinstance(ping_results, list):
            data["connectivity"] = ping_results

    # Connected devices
    if "devices" in sections:
        devs = core.get_top_devices(10)
        if isinstance(devs, dict) and "devices" in devs:
            data["devices"] = devs["devices"]

    if "port_scan" in sections:
        # Pull the most recent port scan from the persistent store.
        try:
            from app.store import store
            last = store.get_last_scan("port_scanner")
            if last and last.get("payload"):
                data["port_scan"] = last["payload"]
        except Exception:
            pass

    # Build the summary strip from whatever we have
    _build_summary(core, data, ping_results)
    return data


def _build_summary(core, data, ping_results):
    summary = data["summary"]

    # If we didn't already ping for connectivity, do a quick one for summary
    if ping_results is None:
        ping_results = core.ping_quick()

    if isinstance(ping_results, list) and ping_results:
        reachable = [r for r in ping_results if not r.get("unreachable")]
        if reachable:
            avg_ping = round(sum(r["avg"] for r in reachable) / len(reachable))
            avg_loss = round(sum(r["loss"] for r in reachable) / len(reachable), 1)
            summary["internet"] = "Connected"
            summary["ping"] = f"{avg_ping} ms"
            summary["loss"] = f"{avg_loss}%"
        else:
            summary["internet"] = "Offline"
            summary["ping"] = "—"
            summary["loss"] = "100%"

    devs = data.get("devices")
    if devs is not None:
        summary["devices"] = f"{len(devs)} online"
