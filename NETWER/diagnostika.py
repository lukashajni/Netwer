"""
NETWER — Dijagnostika backenda.

Pokreni s:  python diagnostika.py

Provjerava svaku backend funkciju i ispisuje sto vraca. Posalji cijeli
ispis nazad da vidimo tocno gdje sto puca.
"""
import time
import traceback
from core import netwer_core as nc


def probe(name, func, *args, **kwargs):
    print(f"\n{'='*60}")
    print(f"  {name}")
    print('='*60)
    t0 = time.time()
    try:
        result = func(*args, **kwargs)
        dt = time.time() - t0
        print(f"  Trajanje: {dt:.2f}s")
        if isinstance(result, dict):
            if "error" in result:
                print(f"  >>> GRESKA: {result['error']}")
            else:
                for k, v in result.items():
                    print(f"    {k}: {v}")
        elif isinstance(result, list):
            print(f"  Lista s {len(result)} elemenata:")
            for item in result[:5]:
                print(f"    {item}")
        else:
            print(f"  Rezultat: {result}")
    except Exception as e:
        dt = time.time() - t0
        print(f"  Trajanje: {dt:.2f}s")
        print(f"  >>> IZNIMKA: {e}")
        traceback.print_exc()


def probe_stream(name, gen_func, *args, max_items=4, **kwargs):
    print(f"\n{'='*60}")
    print(f"  {name} (stream)")
    print('='*60)
    t0 = time.time()
    try:
        count = 0
        for item in gen_func(*args, **kwargs):
            print(f"    [{count}] {item}")
            count += 1
            if count >= max_items:
                print(f"    ... (prekinuto nakon {max_items})")
                break
        print(f"  Ukupno primljeno: {count}, trajanje: {time.time()-t0:.2f}s")
    except Exception as e:
        print(f"  >>> IZNIMKA: {e}")
        traceback.print_exc()


print("\n" + "#"*60)
print("#  NETWER BACKEND DIJAGNOSTIKA")
print("#  Posalji CIJELI ovaj ispis nazad")
print("#"*60)

import platform, sys
print(f"\nOS: {platform.system()} {platform.release()}")
print(f"Python: {sys.version.split()[0]}")
try:
    import psutil
    print(f"psutil: {psutil.__version__}")
except ImportError:
    print("psutil: NIJE INSTALIRAN  <-- ovo je problem!")

# System resources (gaugevi)
probe("get_system_resources() [CPU/RAM/Disk gaugevi]", nc.get_system_resources)

# Ping (Internet Status + Packet Loss)
probe("ping_quick() [Internet Status + Packet Loss]", nc.ping_quick)

# Ethernet (Network Summary)
probe("get_ethernet_info() [Network Summary]", nc.get_ethernet_info)

# WiFi
probe("get_wifi_info() [WiFi kartica]", nc.get_wifi_info)

# System info (uptime)
probe("get_system_info() [Uptime]", nc.get_system_info)

# Monitor stream (Download/Upload live + graf)
print("\n  NAPOMENA: monitor_stream traje ~4s (mjeri promet svake sekunde)")
probe_stream("monitor_stream() [Download/Upload + Live Monitor graf]",
             nc.monitor_stream, "", max_items=4)

# Top devices (vendor)
print("\n  NAPOMENA: get_top_devices skenira mrezu, moze potrajati 10-30s")
probe("get_top_devices(6) [Top Devices + vendor]", nc.get_top_devices, 6)

# Vendor lookup (brzo, bez skeniranja mreze)
print(f"\n{'='*60}")
print("  Vendor lookup test (bez skeniranja)")
print('='*60)
for mac in ["9C-6B-00-50-01-66", "A4-E1-1A-00-00-00"]:
    print(f"    {mac} -> {nc.lookup_vendor(mac)}")
print(f"    Ukupno OUI unosa u tablici: {len(nc.OUI_TABLE)}")

print("\n" + "#"*60)
print("#  KRAJ DIJAGNOSTIKE — posalji sve gore nazad")
print("#"*60)
