

def run_port_scan(core, target, profile="common", target_name=""):
    """Scan one host and return the payload used by the PDF port-scan section."""
    from app.store import store

    timeout = store.get_setting("portscan_timeout_ms", 600)
    results, counts, error = [], {"open": 0, "closed": 0, "filtered": 0}, ""
    for event in core.port_scan_stream(target, profile, timeout):
        if event.get("error"):
            error = event["error"]
            break
        if "state" in event:
            counts[event["state"]] = counts.get(event["state"], 0) + 1
            if event["state"] == "open":
                results.append(event)
    results.sort(key=lambda r: r["port"])
    dtype = core.detect_device_type(open_ports=[r["port"] for r in results],
                                    hostname=target_name or target)
    payload = {"target": target, "target_name": target_name,
               "device_type": dtype, "results": results,
               "counts": counts, "error": error}
    if not error:
        store.set_last_scan("port_scanner", payload)
    return payload


def collect(core, sections, port_target="", port_profile="common",
            port_target_name=""):
    sections = set(sections)
    data = {"summary": {}}

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
            adapter_name = eth.get("adapter", "")
            if adapter_name and hasattr(core, "get_adapter_details"):
                details = core.get_adapter_details(adapter_name)
                if isinstance(details, dict) and "error" not in details:
                    net["description"] = details.get("description", "")
                    net["dhcp"] = details.get("dhcp", "")
                    net["link_speed"] = details.get("link_speed", "")
                    if not net["subnet_mask"]:
                        net["subnet_mask"] = details.get("subnet_mask", "")
            data["network"] = net

    if "system" in sections:
        sysinfo = core.get_system_info()
        if isinstance(sysinfo, dict) and "error" not in sysinfo:
            uptime = (f"{sysinfo.get('days', 0)}d "
                      f"{sysinfo.get('hours', 0)}h "
                      f"{sysinfo.get('minutes', 0)}m")
            data["system"] = {
                "computer": sysinfo.get("computer", ""),
                "os": sysinfo.get("os", ""),
                "cpu": sysinfo.get("cpu", ""),
                "ram": sysinfo.get("ram", ""),
                "uptime": uptime,
            }

    ping_results = None
    if "connectivity" in sections:
        ping_results = core.ping_quick()
        if isinstance(ping_results, list):
            data["connectivity"] = ping_results

    if "devices" in sections:
        devs = core.get_top_devices(10)
        if isinstance(devs, dict) and "devices" in devs:
            data["devices"] = devs["devices"]

    if "port_scan" in sections:
        if port_target:
            # Scan the device picked in the report options.
            try:
                data["port_scan"] = run_port_scan(
                    core, port_target, port_profile, port_target_name)
            except Exception as exc:
                data["port_scan"] = {"target": port_target,
                                     "target_name": port_target_name,
                                     "results": [], "counts": {},
                                     "error": str(exc)}
        else:
            # No device chosen: fall back to the last scan from the Port Scanner.
            try:
                from app.store import store
                last = store.get_last_scan("port_scanner")
                if last and last.get("payload"):
                    data["port_scan"] = last["payload"]
            except Exception:
                pass

    _build_summary(core, data, ping_results)
    return data


def _build_summary(core, data, ping_results):
    summary = data["summary"]

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
