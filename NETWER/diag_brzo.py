"""
NETWER — Brza ciljana dijagnostika (monitor adapter + vendor).
Pokreni:  python diag_brzo.py
Ne skenira cijelu mrezu — brzo je. Posalji cijeli ispis.
"""
import time
from core import netwer_core as nc

print("#"*60)
print("#  BRZA DIJAGNOSTIKA")
print("#"*60)

# 1. Koji adapter monitor bira?
print("\n--- 1. ADAPTER SELECTION ---")
try:
    from core.netwer_core import run_powershell
    # Prikazi SVE Up adaptere
    all_ad = run_powershell(
        "Get-NetAdapter | Where-Object {$_.Status -eq 'Up'} | Select-Object Name,InterfaceDescription,Virtual | Format-Table -AutoSize | Out-String",
        timeout=8)
    print("Svi 'Up' adapteri:")
    print(all_ad)

    # Koji ima default route?
    route_ad = run_powershell(
        r"""
$route = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | Sort-Object RouteMetric | Select-Object -First 1
if ($route) { (Get-NetAdapter -InterfaceIndex $route.InterfaceIndex).Name } else { 'NEMA' }
""", timeout=8)
    print(f"Adapter s default rutom (pravi internet): {route_ad.strip()}")
except Exception as e:
    print("Greska:", e)

# 2. Monitor stream - koji adapter STVARNO koristi?
print("\n--- 2. MONITOR STREAM (prva 3 uzorka) ---")
print("Pokreni download/upload necega da vidis promet!")
try:
    count = 0
    for item in nc.monitor_stream(""):
        print(f"  dl={item.get('dl')} ul={item.get('ul')} adapter={item.get('adapter')}")
        count += 1
        if count >= 3:
            break
except Exception as e:
    print("Greska:", e)

# 3. Vendor lookup - BEZ skeniranja
print("\n--- 3. VENDOR LOOKUP (bez skeniranja) ---")
for mac in ["9C-6B-00-50-01-66", "A4-E1-1A-11-22-33"]:
    print(f"  {mac} -> {nc.lookup_vendor(mac)}")
print(f"  Ukupno OUI unosa: {len(nc.OUI_TABLE)}")

# 4. get_top_devices - vidi STRUKTURU jednog uredaja
print("\n--- 4. TOP DEVICES (struktura, skeniranje ~15s) ---")
try:
    result = nc.get_top_devices(3)
    if "error" in result:
        print("  Greska:", result["error"])
    else:
        for dev in result.get("devices", []):
            print(f"  {dev}")
except Exception as e:
    print("Greska:", e)

print("\n" + "#"*60)
print("#  KRAJ — posalji sve gore")
print("#"*60)
