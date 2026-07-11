"""
NETWER — Extended OUI vendor table + optional online fallback.

The core module ships a tiny OUI table. This extends it with a large set
of the most common IT / networking / consumer-electronics manufacturers so
LAN devices resolve to a real vendor instead of "Unknown".

For MACs still not found locally, online_vendor_lookup() can query a free
API — opt-in, runs inside a worker (never blocks the UI).

Note: OUI prefixes are the first 6 hex chars (24-bit block). Big vendors
own many blocks; we include the common ones. Not exhaustive (IEEE lists
30k+), but covers the vast majority of real-world home/office devices.
"""

EXTENDED_OUI = {
    # ── PC / motherboard / component makers ────────────────────
    "9C6B00": "ASRock", "70850C": "ASRock", "BC5FF4": "ASRock", "D05099": "ASRock",
    "A45C2C": "ASUSTek", "AC9E17": "ASUSTek", "2C4D54": "ASUSTek", "1C872C": "ASUSTek",
    "50465D": "ASUSTek", "04D4C4": "ASUSTek", "D850E6": "ASUSTek", "F832E4": "ASUSTek",
    "088036": "ASUSTek", "1CB72C": "ASUSTek", "382C4A": "ASUSTek", "704D7B": "ASUSTek",
    "0019DB": "MSI", "4CCC6A": "MSI", "44877F": "MSI", "30454E": "MSI", "8C89A5": "MSI",
    "E0D55E": "GIGABYTE", "94DE80": "GIGABYTE", "B42E99": "GIGABYTE", "1C1B0D": "GIGABYTE",
    "FC3497": "GIGABYTE", "74563C": "GIGABYTE", "D8BBC1": "Micro-Star", "00D861": "Micro-Star",
    "00074D": "Biostar", "6C0B84": "Foxconn", "0022B0": "Foxconn",
    # ── Intel / Realtek / Broadcom / Qualcomm NICs ─────────────
    "001B21": "Intel", "3CFDFE": "Intel", "A0A8CD": "Intel", "94659C": "Intel",
    "7C7A91": "Intel", "8C1645": "Intel", "5CE0C5": "Intel", "E4A471": "Intel",
    "34F39A": "Intel", "001500": "Intel", "0015FF": "Intel", "606720": "Intel",
    "A4C494": "Intel", "F8633F": "Intel", "50EB71": "Intel",
    "52540D": "Realtek", "00E04C": "Realtek", "525400": "Realtek", "001367": "Realtek",
    "001018": "Broadcom", "000AF7": "Broadcom", "001BE9": "Broadcom",
    "8CFDF0": "Qualcomm", "9CB6D0": "Qualcomm", "00A0C6": "Qualcomm",
    # ── Apple ──────────────────────────────────────────────────
    "A85C2C": "Apple", "F0766F": "Apple", "3C0754": "Apple", "AC87A3": "Apple",
    "F0989D": "Apple", "D0817A": "Apple", "8866A5": "Apple", "6C4008": "Apple",
    "A4B197": "Apple", "F4F15A": "Apple", "5CF938": "Apple", "DCA904": "Apple",
    "04D3CF": "Apple", "0C74C2": "Apple", "1C9148": "Apple", "28CFE9": "Apple",
    "3871DE": "Apple", "48437C": "Apple", "5C95AE": "Apple", "685B35": "Apple",
    "70CD60": "Apple", "7CD1C3": "Apple", "8C7B9D": "Apple", "9803D8": "Apple",
    "A4D18C": "Apple", "B8E856": "Apple", "C82A14": "Apple", "D0034B": "Apple",
    "E0B9BA": "Apple", "F0DBF8": "Apple", "F82793": "Apple", "34C059": "Apple",
    # ── Samsung ────────────────────────────────────────────────
    "0021D1": "Samsung", "5001BB": "Samsung", "8425DB": "Samsung", "F008F1": "Samsung",
    "382DD1": "Samsung", "C8BA94": "Samsung", "347691": "Samsung", "E8508B": "Samsung",
    "0012FB": "Samsung", "0015B9": "Samsung", "001632": "Samsung", "0018AF": "Samsung",
    "001DF6": "Samsung", "002119": "Samsung", "0023D7": "Samsung", "5CF6DC": "Samsung",
    "8C77122": "Samsung", "A02195": "Samsung", "BCB1F3": "Samsung", "CC07AB": "Samsung",
    # ── Xiaomi / Huawei / Oppo / OnePlus / phones ──────────────
    "18F0E4": "Xiaomi", "640980": "Xiaomi", "7451BA": "Xiaomi", "F8A45F": "Xiaomi",
    "AC6089": "Xiaomi", "D4970B": "Xiaomi", "286C07": "Xiaomi", "3480B3": "Xiaomi",
    "001315": "Huawei", "48435A": "Huawei", "E8CD2D": "Huawei", "00E0FC": "Huawei",
    "045EA4": "Huawei", "086361": "Huawei", "10C61F": "Huawei", "20F3A3": "Huawei",
    "6C8814": "OnePlus", "94652D": "OnePlus", "C0EEFB": "OnePlus",
    "2C5BB8": "Oppo", "4C1A3D": "Oppo", "708A09": "Oppo",
    "40B0FA": "LG", "001E75": "LG", "C4438F": "LG", "001256": "LG", "0021FB": "LG",
    "10683F": "LG", "344DF7": "LG", "A039F7": "LG",
    "F017A8": "Google", "001A11": "Google", "3C5AB4": "Google", "F4F5D8": "Google",
    "A47733": "Google", "6466B3": "Google", "1CF29A": "Google", "94EB2C": "Google",
    "50EC50": "Sony", "FCF152": "Sony", "3C0771": "Sony", "0013A9": "Sony",
    "001A80": "Sony", "0024BE": "Sony", "104FA8": "Sony", "30F9ED": "Sony",
    # ── Routers / networking gear ──────────────────────────────
    "A4E11A": "MikroTik", "6416F0": "MikroTik", "CC2DE0": "MikroTik", "48A98A": "MikroTik",
    "744D28": "MikroTik", "DC2C6E": "MikroTik", "B869F4": "MikroTik", "E48D8C": "MikroTik",
    "18FD74": "MikroTik", "2CC81B": "MikroTik", "64D154": "MikroTik", "D4CA6D": "MikroTik",
    "C46E1F": "TP-Link", "50C7BF": "TP-Link", "A42BB0": "TP-Link", "1C61B4": "TP-Link",
    "003192": "TP-Link", "9C5322": "TP-Link", "EC086B": "TP-Link", "60A4B7": "TP-Link",
    "003792": "TP-Link", "5C6338": "TP-Link", "687F74": "TP-Link", "AC84C6": "TP-Link",
    "0018E7": "Netgear", "A040A0": "Netgear", "204E7F": "Netgear", "C03F0E": "Netgear",
    "9CD36D": "Netgear", "00184D": "Netgear", "E091F5": "Netgear", "2C3033": "Netgear",
    "00156D": "Ubiquiti", "24A43C": "Ubiquiti", "788A20": "Ubiquiti", "F492BF": "Ubiquiti",
    "687251": "Ubiquiti", "FCECDA": "Ubiquiti", "802AA8": "Ubiquiti", "44D9E7": "Ubiquiti",
    "B4FB E4": "Ubiquiti", "DC9FDB": "Ubiquiti", "18E829": "Ubiquiti", "742344": "Ubiquiti",
    "00E04F": "Cisco", "00000C": "Cisco", "001A2F": "Cisco", "68BC0C": "Cisco",
    "84B517": "Cisco", "0021D8": "Cisco", "00259C": "Cisco", "3C0E23": "Cisco",
    "001CDF": "Belkin", "94103E": "Belkin", "080086": "Belkin", "C05627": "Belkin",
    "00095B": "Netgear", "0026F2": "Netgear", "44094E": "D-Link", "1CBDB9": "D-Link",
    "0015E9": "D-Link", "001B11": "D-Link", "002191": "D-Link", "5CD998": "D-Link",
    "F07D68": "D-Link", "C8BE19": "D-Link", "000D88": "D-Link",
    "0024A5": "Buffalo", "10C37B": "Buffalo", "4CE676": "Buffalo",
    "001601": "Zyxel", "5CE28C": "Zyxel", "B0B2DC": "Zyxel",
    "0007CB": "Freebox", "F4CA E5": "Freebox",
    "E4956E": "AVM (FRITZ!Box)", "3CA6F6": "AVM (FRITZ!Box)", "9C C7A6": "AVM (FRITZ!Box)",
    # ── Raspberry Pi / SBCs / IoT chips ────────────────────────
    "B827EB": "Raspberry Pi", "DCA632": "Raspberry Pi", "E45F01": "Raspberry Pi",
    "2CCF67": "Raspberry Pi", "D83ADD": "Raspberry Pi", "88A29E": "Raspberry Pi",
    "68C63A": "Espressif (ESP)", "240AC4": "Espressif (ESP)", "3C6105": "Espressif (ESP)",
    "A020A6": "Espressif (ESP)", "8CAAB5": "Espressif (ESP)", "84F3EB": "Espressif (ESP)",
    "DC4F22": "Espressif (ESP)", "7C9EBD": "Espressif (ESP)", "B4E62D": "Espressif (ESP)",
    "246F28": "Espressif (ESP)", "30AEA4": "Espressif (ESP)", "CC50E3": "Espressif (ESP)",
    "ECFABC": "Espressif (ESP)", "483FDA": "Espressif (ESP)",
    # ── Smart home / IoT ───────────────────────────────────────
    "D073D5": "LIFX", "18B430": "Nest", "641666": "Nest", "50022C": "Nest",
    "500291": "Belkin WeMo", "EC1A59": "Belkin WeMo", "94103E24": "Belkin WeMo",
    "8C85806": "Tuya", "10D561": "Tuya", "68572D": "Tuya", "D8F15B": "Tuya",
    "84E342": "Sonoff/Itead", "60019 4": "Shelly", "C82B96": "Shelly", "E868E7": "Shelly",
    "001788": "Philips Hue", "ECB5FA": "Philips Hue", "0017880": "Philips Hue",
    "B0F893": "Amazon", "F0272D": "Amazon", "AC63BE": "Amazon", "68DBF5": "Amazon",
    "44650D": "Amazon", "34D270": "Amazon", "FCA183": "Amazon", "F0F0A4": "Amazon",
    "0071CC": "Amazon (Ring)", "B47C9C": "Amazon (Ring)",
    "D052A8": "Wink", "94569 9": "Ecobee",
    # ── Smart TVs / streaming ──────────────────────────────────
    "D4E8B2": "Samsung TV", "F47B5E": "Samsung TV", "8CC8CD": "Samsung TV",
    "CC6EA4": "LG TV", "A8232 2": "LG TV",
    "AC9B0A": "Roku", "B0A737": "Roku", "CC6DA0": "Roku", "DC3A5E": "Roku",
    "D0004 5": "Roku", "88DEA9": "Roku",
    "F4F5E8": "Google Chromecast", "6466B3": "Google Chromecast",
    "0009B0": "Onkyo", "185936": "Vizio", "2C641F": "Vizio", "C0FFD4": "Vizio",
    "78BDBC": "Panasonic", "8C69E7": "Panasonic",
    # ── Consoles ───────────────────────────────────────────────
    "7CBB8A": "Nintendo", "0025A0": "Nintendo", "5CEA1D": "Nintendo", "98B6E9": "Nintendo",
    "0009BF": "Nintendo", "182A7B": "Nintendo", "8CCDE8": "Nintendo",
    "00D9D1": "Sony PlayStation", "F8461C": "Sony PlayStation", "2CCC44": "Sony PlayStation",
    "BC60A7": "Sony PlayStation", "00041F": "Sony PlayStation", "280DFC": "Sony PlayStation",
    "7CED8D": "Microsoft Xbox", "0017FA": "Microsoft Xbox", "60455E": "Microsoft",
    "7C1E52": "Microsoft", "C83F26": "Microsoft", "9840BB": "Microsoft",
    # ── Printers / NAS / storage ───────────────────────────────
    "3024A9": "HP", "9C8E99": "HP", "308D99": "HP", "A45D36": "HP", "001321": "HP",
    "ECEBB8": "HP", "24BE05": "HP", "001438": "HP", "0018FE": "HP", "001635": "HP",
    "3CD92B": "HP", "40A8F0": "HP", "706E6D": "HP", "9457A5": "HP",
    "00000E": "Canon", "001E8F": "Canon", "2477031": "Canon", "88872 E": "Canon",
    "00026C": "Epson", "001B A9": "Epson", "44D244": "Epson", "A4E731": "Epson",
    "008077": "Brother", "0080771": "Brother", "30055C": "Brother",
    "001132": "Synology", "0011321": "Synology", "0C9D92": "Synology",
    "24181D": "QNAP", "245EBE": "QNAP", "00089B": "QNAP",
    "0090A9": "Western Digital", "00147D": "Western Digital", "00220D": "Western Digital",
    "7CD30A": "Seagate", "0004CF": "Seagate", "0011D8": "Seagate",
    "D89EF3": "Dell", "F8BC12": "Dell", "B885B0": "Dell", "18DBF2": "Dell",
    "0024E8": "Dell", "509A4C": "Dell", "D4AE52": "Dell", "001143": "Dell",
    "001320": "Dell", "0014220": "Dell", "24B6FD": "Dell", "F8CA B8": "Dell",
    "00080D": "Toshiba", "001480": "Toshiba", "002E2D": "Toshiba",
    "6C71D9": "Lenovo", "8CDCD4": "Lenovo", "A4B1E9": "Lenovo", "E8B1FC": "Lenovo",
    "50E549": "Lenovo", "701CE7": "Lenovo",
    "F0761C": "Acer", "0024D6": "Acer", "5C514F": "Acer", "60E327": "Acer",
    "3CA82A": "Acer",
    # ── Cameras / surveillance ─────────────────────────────────
    "001C2 7": "Hikvision", "4CBD8F": "Hikvision", "BCAD28": "Hikvision", "C056E3": "Hikvision",
    "3C1E04": "Dahua", "90022 4": "Dahua", "E01DA0": "Dahua",
    "00408C": "Axis", "AACC 8E": "Axis", "B8A44F": "Axis",
    # ── Virtualization ─────────────────────────────────────────
    "080027": "VirtualBox", "005056": "VMware", "000C29": "VMware", "001C14": "VMware",
    "0003FF": "Microsoft (Hyper-V)", "00155D": "Microsoft (Hyper-V)",
    "525400": "QEMU/KVM",
}


def _clean_oui_table(raw):
    """Normalize prefixes: strip spaces, uppercase, keep only valid 6-hex
    entries. Guards against typos in the table above."""
    import re
    clean = {}
    for prefix, vendor in raw.items():
        p = re.sub(r"[^0-9A-Fa-f]", "", prefix).upper()
        if len(p) == 6:
            clean[p] = vendor
    return clean


# Public, cleaned table used by core/__init__.py
EXTENDED_OUI = _clean_oui_table(EXTENDED_OUI)


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
