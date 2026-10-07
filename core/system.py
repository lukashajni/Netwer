"""System helpers, information, and resource-monitoring operations."""

import json
import os
import platform
import socket
import subprocess
import time

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None
    PSUTIL_AVAILABLE = False


def _no_window():
    """Keep Windows from flashing a console window for each subprocess."""
    if platform.system() == "Windows":
        return {"creationflags": 0x08000000}   # CREATE_NO_WINDOW
    return {}


def friendly_error(exc):
    """Turn an exception or message into a short, user-facing message."""
    msg = str(exc) if not isinstance(exc, str) else exc
    low = msg.lower()
    if "timed out" in low or "timeout" in low:
        return ("This took too long to respond. It usually works on the next "
                "try — check that you're connected and try again.")
    if "powershell" in low or "get-net" in low:
        return ("Couldn't read your network adapter details. Try running the "
                "scan again.")
    if "no active network" in low or "no network" in low:
        return "No active network connection was found."
    if "wireless interface" in low or "no wifi" in low:
        return "No Wi-Fi adapter was found, or Wi-Fi is turned off."
    if "permission" in low or "access is denied" in low or "denied" in low:
        return ("This action needs administrator rights. Try running NETWER "
                "as administrator.")
    if "invalid mac" in low:
        return "This device doesn't have a MAC address we can use for this."
    clean = msg.strip()
    if len(clean) > 140:
        clean = clean[:137] + "…"
    return clean or "Something went wrong. Please try again."


def run_powershell(command, timeout=10):
    """Run PowerShell and return stdout; return empty on non-Windows."""
    if platform.system() != "Windows":
        return ""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True, text=True, timeout=timeout, **_no_window()
    )
    return result.stdout.strip()


def get_system_info():
    try:
        ps_cmd = """
$cpu  = (Get-CimInstance Win32_Processor).Name
$ram  = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 2)
$os   = (Get-CimInstance Win32_OperatingSystem).Caption
$boot = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime
$up   = New-TimeSpan -Start $boot -End (Get-Date)
[pscustomobject]@{
    computer = $env:COMPUTERNAME
    cpu      = $cpu
    ram      = $ram
    os       = $os
    days     = $up.Days
    hours    = $up.Hours
    minutes  = $up.Minutes
} | ConvertTo-Json
"""
        raw = run_powershell(ps_cmd, timeout=15)
        if raw:
            return json.loads(raw)

        if PSUTIL_AVAILABLE:
            boot = psutil.boot_time()
            uptime_s = time.time() - boot
            return {
                "computer": socket.gethostname(),
                "cpu": platform.processor() or "Unknown",
                "ram": round(psutil.virtual_memory().total / (1024 ** 3), 2),
                "os": f"{platform.system()} {platform.release()}",
                "days": int(uptime_s // 86400),
                "hours": int((uptime_s % 86400) // 3600),
                "minutes": int((uptime_s % 3600) // 60),
            }
        return {"error": "psutil not available and not on Windows"}
    except Exception as e:
        return {"error": str(e)}


def get_system_details():
    """Return extended system information for the System Information page."""
    details = {}
    base = get_system_info()
    if isinstance(base, dict) and "error" not in base:
        details.update(base)

    try:
        details["architecture"] = platform.machine() or "Unknown"
        details["python_version"] = platform.python_version()
        details["hostname"] = socket.gethostname()
        details["os_build"] = platform.version() or "Unknown"
        details["os_release"] = platform.release() or ""

        if PSUTIL_AVAILABLE:
            details["cores_physical"] = psutil.cpu_count(logical=False) or 0
            details["cores_logical"] = psutil.cpu_count(logical=True) or 0
            freq = psutil.cpu_freq()
            if freq:
                details["cpu_freq_current"] = round(freq.current)
                details["cpu_freq_max"] = round(freq.max) if freq.max else 0
            mem = psutil.virtual_memory()
            details["ram_total_gb"] = round(mem.total / (1024 ** 3), 2)
            details["ram_used_gb"] = round(mem.used / (1024 ** 3), 2)
            details["ram_available_gb"] = round(mem.available / (1024 ** 3), 2)

            disks = []
            for part in psutil.disk_partitions(all=False):
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    disks.append({
                        "device": part.device,
                        "mountpoint": part.mountpoint,
                        "fstype": part.fstype,
                        "total_gb": round(usage.total / (1024 ** 3), 2),
                        "used_gb": round(usage.used / (1024 ** 3), 2),
                        "percent": round(usage.percent, 1),
                    })
                except (PermissionError, OSError):
                    continue
            details["disks"] = disks
            details["boot_time"] = psutil.boot_time()

        return details
    except Exception as e:
        details["error"] = str(e)
        return details


def get_system_resources():
    """Return a live CPU, RAM, and disk-usage snapshot."""
    if not PSUTIL_AVAILABLE:
        return {"error": "psutil is required for system resource monitoring. pip install psutil"}
    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage(os.path.abspath(os.sep))
        return {
            "cpu_percent": round(cpu_percent, 1),
            "ram_percent": round(mem.percent, 1),
            "ram_used_gb": round(mem.used / (1024 ** 3), 2),
            "ram_total_gb": round(mem.total / (1024 ** 3), 2),
            "disk_percent": round(disk.percent, 1),
            "disk_used_gb": round(disk.used / (1024 ** 3), 2),
            "disk_total_gb": round(disk.total / (1024 ** 3), 2),
        }
    except Exception as e:
        return {"error": str(e)}


def stream_system_resources(interval_s=1.5, max_samples=600):
    """Yield resource snapshots until the limit is reached or iteration stops."""
    for _ in range(max_samples):
        yield get_system_resources()
        time.sleep(interval_s)
