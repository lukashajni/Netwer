"""
NETWER — Extended OUI vendor table + optional online fallback.

The core module ships a tiny OUI table (45 entries). This extends it with
several hundred of the most common consumer/prosumer vendors so that home
and office devices resolve to a real manufacturer instead of "Unknown".

For MACs still not found locally, online_vendor_lookup() can query a free
API — but that's opt-in and runs inside a worker (never blocks the UI).
"""

# Most common consumer/network/PC vendors by OUI prefix (first 6 hex chars).
# Not exhaustive (the full IEEE registry has 30k+), but covers the vast
# majority of devices found on a typical LAN.
EXTENDED_OUI = {
    # Motherboard / PC makers
    "9C6B00": "ASRock", "70850C": "ASRock", "BC5FF4": "ASRock",
    "A45C2C": "ASUSTek", "AC9E17": "ASUSTek", "2C4D54": "ASUSTek",
    "1C872C": "ASUSTek", "50465D": "ASUSTek", "04D4C4": "ASUSTek",
    "D850E6": "ASUSTek", "F832E4": "ASUSTek", "088036": "ASUSTek",
    "0019DB": "MSI", "4CCC6A": "MSI", "44877F": "MSI", "30454E": "MSI",
    "E0D55E": "GIGABYTE", "94DE80": "GIGABYTE", "B42E99": "GIGABYTE",
    "1C1B0D": "GIGABYTE", "FC3497": "GIGABYTE",
    "D8BBC1": "Micro-Star", "00D861": "Micro-Star",
    # Apple
    "A85C2C": "Apple", "F0766F": "Apple", "3C0754": "Apple",
    "AC87A3": "Apple", "F0989D": "Apple", "D0817A": "Apple",
    "8866A5": "Apple", "6C4008": "Apple", "A4B197": "Apple",
    "F4F15A": "Apple", "5CF938": "Apple", "DCA904": "Apple",
    # Intel / Realtek / Broadcom NICs
    "001B21": "Intel", "3CFDFE": "Intel", "A0A8CD": "Intel",
    "94659C": "Intel", "7C7A91": "Intel", "8C1645": "Intel",
    "5CE0C5": "Intel", "E4A471": "Intel", "34F39A": "Intel",
    "52540D": "Realtek", "00E04C": "Realtek", "525400": "Realtek",
    # Routers / networking
    "A4E11A": "MikroTik", "6416F0": "MikroTik", "CC2DE0": "MikroTik",
    "48A98A": "MikroTik", "744D28": "MikroTik", "DC2C6E": "MikroTik",
    "B827EB": "Raspberry Pi", "DCA632": "Raspberry Pi", "E45F01": "Raspberry Pi",
    "2CCF67": "Raspberry Pi",
    "00156D": "Ubiquiti", "24A43C": "Ubiquiti", "788A20": "Ubiquiti",
    "F492BF": "Ubiquiti", "687251": "Ubiquiti", "FCECDA": "Ubiquiti",
    "001018": "Broadcom", "000AF7": "Broadcom",
    "C46E1F": "TP-Link", "50C7BF": "TP-Link", "A42BB0": "TP-Link",
    "1C61B4": "TP-Link", "003192": "TP-Link", "9C5322": "TP-Link",
    "EC086B": "TP-Link", "60A4B7": "TP-Link",
    "0018E7": "Netgear", "A040A0": "Netgear", "204E7F": "Netgear",
    "C03F0E": "Netgear", "9CD36D": "Netgear",
    "00184D": "Netgear", "E091F5": "Netgear",
    "802AA8": "Ubiquiti", "44D9E7": "Ubiquiti",
    "001CDF": "Belkin", "94103E": "Belkin",
    "000C43": "Ralink", "00E04F": "Cisco", "00000C": "Cisco",
    "001A2F": "Cisco", "68BC0C": "Cisco", "84B517": "Cisco",
    # IoT / smart home
    "D073D5": "LIFX", "18B430": "Nest", "641666": "Nest",
    "500291": "Belkin WeMo", "EC1A59": "Belkin WeMo",
    "68C63A": "Espressif", "240AC4": "Espressif", "3C6105": "Espressif",
    "A020A6": "Espressif", "8CAAB5": "Espressif", "84F3EB": "Espressif",
    "DC4F22": "Espressif", "7C9EBD": "Espressif",
    "B4E62D": "Espressif", "246F28": "Espressif",
    # Phones / consumer electronics
    "40B0FA": "LG", "001E75": "LG", "C4438F": "LG",
    "0021D1": "Samsung", "5001BB": "Samsung", "8425DB": "Samsung",
    "F008F1": "Samsung", "382DD1": "Samsung", "C8BA94": "Samsung",
    "347691": "Samsung", "E8508B": "Samsung",
    "18F0E4": "Xiaomi", "640980": "Xiaomi", "7451BA": "Xiaomi",
    "F8A45F": "Xiaomi", "AC6089": "Xiaomi", "D4970B": "Xiaomi",
    "50EC50": "Sony", "FCF152": "Sony", "3C0771": "Sony",
    "001315": "Huawei", "48435A": "Huawei", "E8CD2D": "Huawei",
    # Printers / NAS
    "3024A9": "HP", "9C8E99": "HP", "308D99": "HP", "A45D36": "HP",
    "001321": "HP", "ECEBB8": "HP", "D89EF3": "Dell",
    "F8BC12": "Dell", "B885B0": "Dell", "18DBF2": "Dell",
    "0024E8": "Dell", "509A4C": "Dell", "D4AE52": "Dell",
    "001132": "Synology", "0011D8": "ASUSTek", "24BE05": "HP",
    "00080D": "Toshiba", "001480": "Hewlett-Packard",
    "0090A9": "Western Digital", "00147D": "Western Digital",
    "7CD30A": "Seagate", "0004CF": "Seagate",
    "24181D": "QNAP", "245EBE": "QNAP",
    # Virtualization
    "080027": "VirtualBox", "005056": "VMware", "000C29": "VMware",
    "001C14": "VMware", "0003FF": "Microsoft (Hyper-V)",
    "00155D": "Microsoft (Hyper-V)", "0017FA": "Microsoft",
    "60455E": "Microsoft", "7C1E52": "Microsoft", "C83F26": "Microsoft",
}


def online_vendor_lookup(mac_address, timeout=3):
    """Query a free API for a vendor name. Returns name or None.
    ONLY call from a worker thread — it makes a network request."""
    import urllib.request
    import re
    cleaned = re.sub(r"[^0-9A-Fa-f]", "", mac_address or "")
    if len(cleaned) < 6:
        return None
    try:
        url = f"https://api.macvendors.com/{cleaned[:6]}"
        req = urllib.request.Request(url, headers={"User-Agent": "NETWER"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            name = resp.read().decode("utf-8", "ignore").strip()
            if name and "error" not in name.lower() and len(name) < 60:
                return name
    except Exception:
        return None
    return None
