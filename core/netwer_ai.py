"""Netwer AI: on-device assistant for Network Health. No network, no third-party AI."""
import difflib
import re
import unicodedata

from core.diagnostics import CRITICAL, GOOD, INFO, WARNING

_SEV_RANK = {CRITICAL: 0, WARNING: 1, INFO: 2, GOOD: 3}


# -- answer blocks --
def text(s):
    return {"type": "text", "text": s}


def steps(items):
    return {"type": "steps", "items": list(items)}


def bullets(items):
    return {"type": "bullets", "items": list(items)}


def finding(sev, title, detail="", action=""):
    return {"type": "finding", "severity": sev, "title": title, "detail": detail, "action": action}


def actions(*pairs):
    # target: page key, "health_run" or "scan:<ip>"
    return {"type": "actions", "items": [{"label": l, "target": t} for l, t in pairs]}


def _answer(intent, blocks, suggestions=()):
    return {"intent": intent, "blocks": blocks, "suggestions": list(suggestions)[:3]}


# -- context --
def _round(v, n=1):
    return None if v is None else round(float(v), n)


def traffic_summary(bandwidth_rows, conn_rows, adapter="") -> dict:
    out = {"adapter": adapter}
    if bandwidth_rows:
        n = sum(r[5] for r in bandwidth_rows)
        out["download_mbps"] = {"avg": _round(sum(r[1] * r[5] for r in bandwidth_rows) / n, 2),
                                "peak": _round(max(r[3] for r in bandwidth_rows), 2)}
        out["upload_mbps"] = {"avg": _round(sum(r[2] * r[5] for r in bandwidth_rows) / n, 2),
                              "peak": _round(max(r[4] for r in bandwidth_rows), 2)}
    if conn_rows:
        losses = [c[2] for c in conn_rows]
        pings = [c[1] for c in conn_rows if c[1] is not None]
        out["packet_loss_pct"] = {"avg": _round(sum(losses) / len(losses)), "worst": _round(max(losses))}
        if pings:
            out["latency_ms"] = {"avg": _round(sum(pings) / len(pings)), "max": _round(max(pings))}
    return out


def build_context(report=None, devices=None, port_scan=None, traffic=None, page="health") -> dict:
    ctx = {"diagnosis": None, "devices": list(devices or []), "port_scan": None,
           "traffic": traffic or {}, "page": page}
    if report:
        ctx["diagnosis"] = {
            "headline": report.get("headline", ""), "summary": report.get("summary", ""),
            "severity": report.get("severity", INFO),
            "findings": sorted(report.get("findings", []),
                               key=lambda f: _SEV_RANK.get(f.get("severity"), 2)),
            "measurements": report.get("measurements") or {}}
    if port_scan and (port_scan.get("results") or port_scan.get("target")):
        ctx["port_scan"] = {"target": port_scan.get("target", ""),
                            "target_name": port_scan.get("target_name", ""),
                            "results": port_scan.get("results", [])}
    return ctx


# -- language --
def _norm(s: str) -> str:
    s = s.replace("\u0111", "d").replace("\u0110", "d")
    s = "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c))
    s = s.lower().replace("wi-fi", "wifi").replace("wi fi", "wifi")
    return re.sub(r"[^a-z0-9 ]+", " ", s).strip()


HR_HINTS = ["sto ", "sta ", "kako", "zasto", "mi je", " moj", "moja", "moje", "mrez", "ruter", "uredaj",
            "hvala", "bok", "pomoc", "poboljs", "preporu", "sporo", "sigurn", "objasni", "rezultat",
            "koji ", "koliko", "gdje", "ima li", "trebam", "mogu ", "znaci", "radi ", "pokazi", "popravi",
            "lozink", "cemu", "spor ", "tko ", "jesam", "jesu ", "nije ", "ovo", "ovaj", "ovdje", "kaj"]

# keyword: stem, "=word" (exact), or a phrase
INTENTS = {
    "explain_results": ["explain", "result", "summar", "overview", "whats wrong", "what s wrong", "status",
                        "how is my network", "objasni", "rezultat", "sazet", "stanje", "nije u redu",
                        "ne valja", "kako je moja mreza", "analiz"],
    "fix_first": ["fix", "first", "priorit", "important", "repair", "solve", "what should i do", "popravi",
                  "rijesi", "prvo", "najvazn", "sto da radim", "sto napraviti"],
    "improve": ["improve", "better", "optimi", "recommend", "tips", "advice", "upgrade", "boost", "enhance",
                "poboljs", "preporu", "savjet", "unaprijed", "bolje", "optimiz", "ubrzat", "pojacat"],
    "slow": ["slow", "lag", "buffer", "freez", "stutter", "sporo", "spor ", "zaostaj", "koci", "seka",
             "zablokir", "ne radi dobro", "problem s internet", "pada internet", "prekid"],
    "security": ["secur", "safe", "hack", "vulnerab", "risk", "open port", "exposed", "sigurn", "opasn",
                 "ranjiv", "otvoren", "zasticen", "napad", "zastit", "virus", "lozink"],
    "wifi": ["wifi", "wireless", "signal", "channel", "bezic", "kanal", "frekvenc", "ghz"],
    "dns": ["dns", "domain", "ipv6", "ipv4", "name resolution", "domen"],
    "devices": ["device", "who is on", "connected", "unknown", "intruder", "stranger", "uredaj", "tko je",
                "spojen", "nepoznat", "uljez", "na mrezi", "tko koristi"],
    "loss_latency": ["packet", "loss", "latenc", "ping", "jitter", "gubit", "kasnjen", "odziv"],
    "traffic": ["bandwidth", "download", "upload", "traffic", "speed", "usage", "promet", "brzin",
                "preuzim", "bandwith", "potros"],
    "router": ["router", "ruter", "gateway", "mikrotik", "modem"],
    "myinfo": ["my ip", "moj ip", "ip address", "ip adres", "mac address", "adapter", "what adapter",
               "koji adapter", "moja adres"],
    "glossary": ["what is", "what does", "what are", "meaning", "define", "sto je", "sto znaci", "sto su",
                 "pojam", "sta je", "sta znaci"],
    "page": ["this page", "ova stranica", "ovu stranicu", "what is this", "sto je ovo", "sta je ovo",
             "what can i do here", "sto mogu ovdje", "ovdje", "ovo ovdje", "what is here"],
    "app_info": ["how do i", "how to", "how does", "what does", "where is", "where can i", "what is the",
                 "kako koristim", "kako se", "gdje je", "gdje mogu", "cemu sluzi", "sto radi", "sto je",
                 "sta je", "sta radi", "kako radi", "koristiti", "use "],
    "help": ["help", "who are you", "what are you", "tko si", "sto si ti", "what can you do", "pomoc", "pomozi", "sto mozes", "kako radis", "mogucnost"],
    "greet": ["=hi", "=hello", "=hey", "=bok", "=cao", "pozdrav", "dobar dan", "dobro jutro", "dobra vecer"],
    "thanks": ["thank", "=thx", "=ty", "hvala"],
}
PRIORITY = ["glossary", "page", "security", "improve", "slow", "wifi", "dns", "devices", "myinfo",
            "loss_latency", "traffic", "router", "fix_first", "explain_results", "app_info", "help",
            "greet", "thanks"]
FOLLOW_UP = ["how", "why", "more", "detail", "kako", "zasto", "jos", "detalj", "and then", "a onda", "dalje"]


def _score(q, tokens, kws):
    padded = f" {q} "
    total = 0
    for kw in kws:
        if kw.startswith("="):
            total += 2 if kw[1:] in tokens else 0
        elif " " in kw.strip():
            total += 3 if f" {kw.strip()} " in padded or kw in padded else 0
        elif kw.endswith(" "):
            total += 2 if f" {kw}" in padded else 0
        else:
            total += 2 if any(t.startswith(kw) for t in tokens) else 0
    return total


# -- glossary: key -> ((en title, en text), (hr title, hr text)) --
GLOSSARY = {
    "packet loss": (("Packet loss", "Data travels in small pieces called packets. Packet loss means some never arrive. Even 1-2% makes calls stutter and pages hang; 0% is what you want."),
                    ("Gubitak paketa", "Podaci putuju u malim komadićima zvanim paketi. Gubitak paketa znači da neki nikad ne stignu. Već 1-2% uzrokuje zastajkivanje poziva i stranica; cilj je 0%.")),
    "latency": (("Latency (ping)", "How long a tiny message takes to reach a device and come back, in milliseconds. Under 30 ms to the internet is great, over 100 ms feels laggy."),
                ("Latencija (ping)", "Koliko je milisekundi potrebno da mala poruka stigne do uređaja i vrati se. Ispod 30 ms prema internetu je odlično, preko 100 ms osjeti se zastajkivanje.")),
    "ping": (("Ping", "A tiny test message sent to a device to see if it answers and how fast. It's the quickest way to check that something is reachable."),
             ("Ping", "Mala testna poruka poslana uređaju da se vidi odgovara li i koliko brzo. Najbrži je način da provjeriš je li nešto dostupno.")),
    "jitter": (("Jitter", "How much latency changes from one message to the next. High jitter makes voice and video choppy even when the average ping looks fine."),
               ("Jitter", "Koliko se latencija mijenja od poruke do poruke. Visok jitter čini glas i video isprekidanima iako je prosječni ping dobar.")),
    "dns": (("DNS", "The internet's phone book: it turns names like google.com into addresses. If DNS is slow, pages seem to hang before they start loading."),
            ("DNS", "Telefonski imenik interneta: pretvara nazive poput google.com u adrese. Ako je DNS spor, stranice kao da zastanu prije nego se počnu učitavati.")),
    "ipv6": (("IPv6", "The newer kind of internet address. Many networks work fine on IPv4 only, so a missing IPv6 address is usually not a problem."),
             ("IPv6", "Novija vrsta internetske adrese. Mnoge mreže rade savršeno samo na IPv4, pa nedostatak IPv6 adrese obično nije problem.")),
    "ip address": (("IP address", "The address of a device on a network, like a house number. Your router has one on your home network (e.g. 192.168.1.1) and your provider gives your home one public address."),
                   ("IP adresa", "Adresa uređaja na mreži, kao kućni broj. Ruter ima jednu na tvojoj kućnoj mreži (npr. 192.168.1.1), a davatelj usluge daje tvom domu jednu javnu adresu.")),
    "gateway": (("Gateway / router", "The device your computer sends everything through to reach the internet. At home that's your router."),
                ("Gateway / ruter", "Uređaj kroz koji tvoje računalo šalje sve prema internetu. Kod kuće je to tvoj ruter.")),
    "router": (("Router", "The box that connects your devices to each other and to the internet."),
               ("Ruter", "Uređaj koji povezuje tvoje uređaje međusobno i s internetom.")),
    "port": (("Port", "Think of an IP address as a building and ports as its numbered doors. Each service (web, SSH, file sharing) listens on its own door. Open doors you don't need are a risk."),
             ("Port", "IP adresa je kao zgrada, a portovi su njezina numerirana vrata. Svaka usluga (web, SSH, dijeljenje datoteka) sluša na svojim vratima. Otvorena vrata koja ti ne trebaju su rizik.")),
    "telnet": (("Telnet (port 23)", "An old way to log into a device remotely that sends everything, including your password, as plain text. Use SSH instead."),
               ("Telnet (port 23)", "Stari način udaljene prijave na uređaj koji sve, uključujući lozinku, šalje kao običan tekst. Koristi SSH umjesto njega.")),
    "ssh": (("SSH (port 22)", "A secure, encrypted way to log into a device remotely. Open SSH is normal if the password is strong."),
            ("SSH (port 22)", "Siguran, šifriran način udaljene prijave na uređaj. Otvoren SSH je normalan ako je lozinka jaka.")),
    "ftp": (("FTP (port 21)", "An old file-transfer protocol that sends passwords unencrypted. SFTP is the safe replacement."),
            ("FTP (port 21)", "Stari protokol za prijenos datoteka koji šalje lozinke nešifrirano. SFTP je siguran nasljednik.")),
    "smb": (("SMB (port 445)", "Windows file and printer sharing. Fine inside your home, dangerous if reachable from the internet."),
            ("SMB (port 445)", "Windows dijeljenje datoteka i pisača. U redu unutar doma, opasno ako je dostupno s interneta.")),
    "winbox": (("Winbox (port 8291)", "MikroTik's tool for configuring the router. It should only be reachable from your local network."),
               ("Winbox (port 8291)", "MikroTikov alat za podešavanje rutera. Treba biti dostupan samo iz lokalne mreže.")),
    "dhcp": (("DHCP", "The router's job of handing each device an address when it joins the network."),
             ("DHCP", "Zadatak rutera da svakom uređaju dodijeli adresu kad se spoji na mrežu.")),
    "mac": (("MAC address", "A hardware ID burned into a network card. It identifies the device on your local network and its first half reveals the manufacturer."),
            ("MAC adresa", "Hardverski ID upisan u mrežnu karticu. Identificira uređaj na lokalnoj mreži, a prva polovica otkriva proizvođača.")),
    "upnp": (("UPnP", "Lets devices ask the router to open ports automatically. Convenient, but malware can abuse it, so turn it off if you don't need it."),
             ("UPnP", "Dopušta uređajima da traže od rutera automatsko otvaranje portova. Praktično, ali zlonamjerni softver to može zloupotrijebiti, pa ga isključi ako ti ne treba.")),
    "bandwidth": (("Bandwidth", "How much data per second your connection can carry, in Mbps. More bandwidth doesn't fix high latency or packet loss."),
                  ("Propusnost (bandwidth)", "Koliko podataka u sekundi tvoja veza može prenijeti, u Mbps. Veća propusnost ne rješava visoku latenciju ni gubitak paketa.")),
    "subnet": (("Subnet / mask", "A subnet is your local network's address range, like 192.168.88.0/24. Devices inside it talk directly; everything else goes through the router."),
               ("Podmreža (subnet)", "Podmreža je raspon adresa tvoje lokalne mreže, npr. 192.168.88.0/24. Uređaji unutar nje komuniciraju izravno, a sve ostalo ide preko rutera.")),
    "firewall": (("Firewall", "A filter that decides which connections may reach a device or network. It blocks unwanted traffic from outside."),
                 ("Vatrozid (firewall)", "Filter koji odlučuje koje veze smiju doći do uređaja ili mreže. Blokira neželjeni promet izvana.")),
    "vpn": (("VPN", "An encrypted tunnel to another network. It hides your traffic from the local network, but adds a little latency."),
            ("VPN", "Šifrirani tunel prema drugoj mreži. Skriva promet od lokalne mreže, ali dodaje malo latencije.")),
    "isp": (("ISP", "Your internet service provider, the company that connects your home to the internet."),
            ("ISP (davatelj usluge)", "Tvoj davatelj internetskih usluga, tvrtka koja povezuje tvoj dom s internetom.")),
    "ssid": (("SSID", "The name of a Wi-Fi network, the one you pick from the list when connecting."),
             ("SSID", "Naziv Wi-Fi mreže, onaj koji biraš s popisa pri spajanju.")),
    "channel": (("Wi-Fi channel", "A slice of the Wi-Fi frequency band. If neighbours use the same channel, networks interfere. Switching to a quieter one can speed things up."),
                ("Wi-Fi kanal", "Dio Wi-Fi frekvencijskog pojasa. Ako susjedi koriste isti kanal, mreže si smetaju. Prelazak na mirniji kanal može ubrzati vezu.")),
    "ghz": (("2.4 vs 5 GHz", "2.4 GHz reaches further through walls but is slower and crowded. 5 GHz is faster but has shorter range. Use 5 GHz when you're close to the router."),
            ("2,4 i 5 GHz", "2,4 GHz dalje prodire kroz zidove, ali je sporiji i zagušeniji. 5 GHz je brži, ali kraćeg dometa. Koristi 5 GHz kad si blizu rutera.")),
    "ttl": (("TTL", "A counter on every packet that drops by one at each hop. It stops packets from looping forever, and traceroute uses it to discover the path."),
            ("TTL", "Brojač na svakom paketu koji se smanji za jedan na svakom skoku. Sprječava vječno kruženje paketa, a traceroute ga koristi za otkrivanje puta.")),
    "hop": (("Hop", "One step on the path a packet takes: each router it passes through is one hop."),
            ("Skok (hop)", "Jedan korak na putu paketa: svaki ruter kroz koji prođe je jedan skok.")),
    "traceroute": (("Traceroute", "Shows every router your data passes on the way to a destination and how long each step takes. Handy for finding where a slowdown happens."),
                   ("Traceroute", "Prikazuje svaki ruter kroz koji tvoji podaci prolaze do odredišta i koliko traje svaki korak. Koristan za pronalaženje mjesta gdje nastaje usporenje.")),
    "nat": (("NAT", "How your router lets many devices share one public address by translating between them. It also hides your devices from direct access from outside."),
            ("NAT", "Način na koji ruter omogućuje mnogim uređajima dijeljenje jedne javne adrese. Usput skriva uređaje od izravnog pristupa izvana.")),
    "mtu": (("MTU", "The largest packet size your connection sends in one piece. The usual value is 1500; a wrong value can cause odd slowdowns."),
            ("MTU", "Najveća veličina paketa koju veza šalje odjednom. Uobičajena vrijednost je 1500; pogrešna može uzrokovati čudna usporenja.")),
}
GLOSSARY_ALIASES = {"paket": "packet loss", "gubitak": "packet loss", "kasnjenje": "latency", "ruter": "router",
                    "usmjernik": "router", "vrata": "port", "propusnost": "bandwidth", "mac adres": "mac",
                    "pristupnik": "gateway", "ip6": "ipv6", "ip adres": "ip address", "podmrez": "subnet",
                    "vatrozid": "firewall", "kanal": "channel", "skok": "hop", "davatelj": "isp",
                    "mreza ime": "ssid", "5ghz": "ghz", "2 4": "ghz"}
TERM_PAGE = {"ping": ("Open Ping", "Otvori Ping", "ping"), "dns": ("Open DNS Tools", "Otvori DNS alate", "dns_tools"),
             "port": ("Open Port Scanner", "Otvori Port Scanner", "port_scanner"),
             "traceroute": ("Open Traceroute", "Otvori Traceroute", "dns_tools"),
             "hop": ("Open Traceroute", "Otvori Traceroute", "dns_tools"),
             "ttl": ("Open Traceroute", "Otvori Traceroute", "dns_tools"),
             "packet loss": ("Open Ping", "Otvori Ping", "ping"), "latency": ("Open Ping", "Otvori Ping", "ping"),
             "channel": ("Wi-Fi details", "Wi-Fi detalji", "wifi"), "ssid": ("Wi-Fi details", "Wi-Fi detalji", "wifi"),
             "ghz": ("Wi-Fi details", "Wi-Fi detalji", "wifi"), "mac": ("Network info", "Mrežne informacije", "network"),
             "ip address": ("Network info", "Mrežne informacije", "network"),
             "bandwidth": ("Run speed test", "Pokreni test brzine", "speedtest")}


def _glossary_term(q):
    for key in sorted(GLOSSARY, key=len, reverse=True):
        if re.search(rf"\b{re.escape(key)}\b", q):
            return key
    for alias, key in GLOSSARY_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}", q):
            return key
    return None


# -- app knowledge --
TOPICS = [
    {"key": "dashboard", "page": "dashboard", "kw": ["dashboard", "home page", "pocetn", "nadzorn", "kontrolna"],
     "title": ("Dashboard", "Dashboard"),
     "desc": ("The overview screen: connection status, live download and upload, packet loss, devices online, a network map, system resources and recent activity, all updating by themselves.",
              "Pregledni ekran: status veze, trenutni download i upload, gubitak paketa, uređaji na mreži, mapa mreže, resursi sustava i nedavna aktivnost, sve se osvježava samo."),
     "steps": (["Click the live graph or Detailed analysis for a deeper look.", "Click a device on the map to see its open ports.", "Use Rescan to refresh the device list."],
               ["Klikni na živi graf ili Detailed analysis za dublji pregled.", "Klikni uređaj na mapi da vidiš njegove otvorene portove.", "Koristi Rescan za osvježavanje popisa uređaja."])},
    {"key": "monitor", "page": "dashboard", "kw": ["live network monitor", "live monitor", "live graph", "live chart", "graf", "monitor", "zivi graf"],
     "title": ("Live Network Monitor", "Live Network Monitor"),
     "desc": ("The graph on the Dashboard showing your download (blue) and upload (purple) every second for the last minute. Pick which adapter to watch from the drop-down.",
              "Graf na Dashboardu koji svake sekunde prikazuje tvoj download (plavo) i upload (ljubičasto) za zadnju minutu. Iz izbornika biraš koji adapter pratiš."),
     "steps": (["Hover the graph to see exact values.", "Click it, or press Detailed analysis, for history and packet loss.", "Change the adapter in the drop-down if you have more than one."],
               ["Prijeđi mišem preko grafa za točne vrijednosti.", "Klikni ga, ili pritisni Detailed analysis, za povijest i gubitak paketa.", "Promijeni adapter u izborniku ako ih imaš više."])},
    {"key": "analysis", "page": "dashboard", "kw": ["detailed analysis", "continuous", "analysis", "detaljna analiza", "detaljn", "analiza grafa"],
     "title": ("Detailed analysis", "Detaljna analiza"),
     "desc": ("A window opened from the live graph with download, upload, latency and packet loss over time, stats, peaks and highlights. Ranges: 5 min, 1 hour, 24 hours, and Continuous, which shows everything recorded since Netwer started.",
              "Prozor koji se otvara s grafa uživo, s downloadom, uploadom, latencijom i gubitkom paketa kroz vrijeme, statistikom, vrhovima i zaključcima. Rasponi: 5 min, 1 sat, 24 sata i Continuous, koji prikazuje sve snimljeno otkako je Netwer pokrenut."),
     "steps": (["Pick a range at the top right.", "Hover any graph for the values at that moment.", "Read Highlights at the bottom for spikes and drops."],
               ["Odaberi raspon gore desno.", "Prijeđi mišem preko grafa za vrijednosti u tom trenutku.", "Pročitaj Highlights dolje za skokove i padove."])},
    {"key": "netmap", "page": "dashboard", "kw": ["network map", "topology", "mapa mreze", "mapa", "topolog", "radar"],
     "title": ("Network Map", "Mapa mreže"),
     "desc": ("A picture of your network: Internet at the top, your router below it and your devices underneath. Expand opens a bigger radar view.",
              "Slika tvoje mreže: Internet na vrhu, ispod njega ruter, a pod njim tvoji uređaji. Expand otvara veći radarski prikaz."),
     "steps": (["Click the router or any device to see its details and open ports.", "Press Expand for the full radar view."],
               ["Klikni ruter ili bilo koji uređaj za detalje i otvorene portove.", "Pritisni Expand za puni radarski prikaz."])},
    {"key": "devices", "page": "ping_sweep", "kw": ["connected devices", "top devices", "device list", "popis uredaja"],
     "title": ("Connected devices", "Povezani uređaji"),
     "desc": ("The list of devices Netwer found on your network, with name, address and manufacturer. Click one for details and a port scan.",
              "Popis uređaja koje je Netwer pronašao na tvojoj mreži, s imenom, adresom i proizvođačem. Klikni jedan za detalje i skeniranje portova."),
     "steps": (["Press Rescan on the Dashboard to refresh.", "Click a device, then edit its name or vendor if it's wrong."],
               ["Pritisni Rescan na Dashboardu za osvježavanje.", "Klikni uređaj pa mu promijeni ime ili proizvođača ako nije točno."])},
    {"key": "network", "page": "network", "kw": ["network information", "network info", "adapter page", "mrezne informacije", "mrezni podaci", "ip page"],
     "title": ("Network Information", "Mrežne informacije"),
     "desc": ("Details of your network adapters: IP address, subnet mask, gateway, DNS servers, MAC address, DHCP and link speed.",
              "Detalji tvojih mrežnih adaptera: IP adresa, maska podmreže, gateway, DNS poslužitelji, MAC adresa, DHCP i brzina veze."),
     "steps": (["Pick an adapter in the drop-down.", "Use it when support asks for your IP, gateway or MAC."],
               ["Odaberi adapter u izborniku.", "Koristi ga kad podrška traži tvoj IP, gateway ili MAC."])},
    {"key": "wifi", "page": "wifi", "kw": ["wifi information", "wifi info", "wifi page", "wifi informacije", "bezicne informacije"],
     "title": ("Wi-Fi Information", "Wi-Fi informacije"),
     "desc": ("Details of your wireless link: network name, signal strength, band, channel, speed and security type, plus nearby networks.",
              "Detalji tvoje bežične veze: naziv mreže, jačina signala, pojas, kanal, brzina i vrsta zaštite, plus obližnje mreže."),
     "steps": (["Check the signal percentage and channel.", "Compare with nearby networks to find a quieter channel."],
               ["Provjeri postotak signala i kanal.", "Usporedi s obližnjim mrežama da nađeš mirniji kanal."])},
    {"key": "system", "page": "system", "kw": ["system information", "system info", "sistemske informacije", "informacije o sustavu", "hardver", "hardware"],
     "title": ("System Information", "Informacije o sustavu"),
     "desc": ("Details about your computer: Windows version, processor, memory and uptime.",
              "Podaci o tvom računalu: verzija Windowsa, procesor, memorija i vrijeme rada."),
     "steps": (["Open it to see CPU, RAM and OS at a glance."], ["Otvori ga za pregled CPU-a, RAM-a i OS-a."])},
    {"key": "health", "page": "health", "kw": ["network health", "diagnose", "diagnosis", "health page", "dijagnoz", "zdravlje mreze"],
     "title": ("Network Health", "Network Health"),
     "desc": ("Runs a set of tests on your adapter, router, internet and DNS, then lists what's wrong in plain language with how to fix it. Ask AI, the button next to Diagnose, opens me.",
              "Pokreće niz testova na tvom adapteru, ruteru, internetu i DNS-u, pa jednostavnim jezikom navodi što nije u redu i kako to popraviti. Ask AI, gumb pored Diagnose, otvara mene."),
     "steps": (["Press Diagnose my network and wait a few seconds.", "Read What we found.", "Press Ask AI on a finding for help fixing it."],
               ["Pritisni Diagnose my network i pričekaj nekoliko sekundi.", "Pročitaj What we found.", "Pritisni Ask AI uz nalaz za pomoć pri popravku."])},
    {"key": "ping", "page": "ping", "kw": ["ping tool", "ping page", "ping alat", "ping stranica"],
     "title": ("Ping", "Ping"),
     "desc": ("Sends test messages to a host and shows how fast they come back, how much is lost and how steady it is.",
              "Šalje testne poruke prema računalu ili stranici i prikazuje koliko brzo se vraćaju, koliko se izgubi i koliko je stabilno."),
     "steps": (["Type a host (e.g. google.com or your router) and press Start.", "Watch average, jitter and loss.", "Use it to check the router first, then the internet."],
               ["Upiši host (npr. google.com ili svoj ruter) i pritisni Start.", "Prati prosjek, jitter i gubitak.", "Koristi ga prvo za ruter, pa za internet."])},
    {"key": "ping_sweep", "page": "ping_sweep", "kw": ["ping sweep", "sweep", "discover devices", "pronadi uredaje", "skeniranje mreze", "pretrazivanje mreze"],
     "title": ("Ping Sweep", "Ping Sweep"),
     "desc": ("Checks every address in your network range to find which devices are alive. It's how you discover who is connected.",
              "Provjerava svaku adresu u rasponu tvoje mreže da nađe koji su uređaji aktivni. Tako otkrivaš tko je spojen."),
     "steps": (["Press Scan and wait for the list to fill.", "Click a device to inspect it."], ["Pritisni Scan i pričekaj da se popis popuni.", "Klikni uređaj da ga pregledaš."])},
    {"key": "port_scanner", "page": "port_scanner", "kw": ["port scanner", "port scan", "scanning ports", "skener portova", "skeniranje portova", "portovi", "nmap"],
     "title": ("Port Scanner", "Port Scanner"),
     "desc": ("Checks which ports are open on a device, which services run on them and any banner they reveal. It's the main security check for your router.",
              "Provjerava koji su portovi otvoreni na uređaju, koje usluge rade na njima i koji banner otkrivaju. Glavna je sigurnosna provjera tvog rutera."),
     "steps": (["Enter the router address, pick a profile (Common is fastest) and press Scan.", "Look at the open ports in the results.", "Close the risky ones in the router settings."],
               ["Upiši adresu rutera, odaberi profil (Common je najbrži) i pritisni Scan.", "Pogledaj otvorene portove u rezultatima.", "Zatvori rizične u postavkama rutera."])},
    {"key": "dns_tools", "page": "dns_tools", "kw": ["dns tools", "dns lookup", "reverse dns", "dns alati", "dns upit", "reverse lookup"],
     "title": ("DNS Tools", "DNS alati"),
     "desc": ("Three tools in one: DNS Lookup (name to address), Reverse DNS (address to name) and Traceroute (the path to a destination, drawn on a map).",
              "Tri alata u jednom: DNS Lookup (ime u adresu), Reverse DNS (adresa u ime) i Traceroute (put do odredišta, nacrtan na karti)."),
     "steps": (["Pick a tab at the top.", "Enter a domain or address and run it."], ["Odaberi karticu gore.", "Upiši domenu ili adresu i pokreni."])},
    {"key": "traceroute", "page": "dns_tools", "kw": ["traceroute", "trace route", "path map", "karta puta", "trasiranje"],
     "title": ("Traceroute", "Traceroute"),
     "desc": ("Lists every router between you and a destination with the time to each, and draws the route on a map. Numbered markers are hops, a dashed ring means the location is only approximate, and the line colour shows latency: green is fast, amber slower, red slow.",
              "Navodi svaki ruter između tebe i odredišta s vremenom do njega i crta rutu na karti. Numerirani markeri su skokovi, iscrtkani krug znači da je lokacija samo približna, a boja linije pokazuje latenciju: zeleno je brzo, žuto sporije, crveno sporo."),
     "steps": (["Open DNS Tools and pick Traceroute.", "Enter a destination and press Start.", "Scroll the map to zoom, drag to move, double-click to fit."],
               ["Otvori DNS Tools i odaberi Traceroute.", "Upiši odredište i pritisni Start.", "Kotačićem zumiraj kartu, povuci za pomicanje, dvostruki klik za prilagodbu."])},
    {"key": "speedtest", "page": "speedtest", "kw": ["speed test", "speedtest", "internet speed", "test brzine", "brzina interneta"],
     "title": ("Speed Test", "Test brzine"),
     "desc": ("Measures your real download and upload speed and latency to a test server.",
              "Mjeri tvoju stvarnu brzinu downloada i uploada te latenciju prema testnom poslužitelju."),
     "steps": (["Close heavy downloads first.", "Press Start and wait for the result.", "Compare it with what your provider promises."],
               ["Prvo zatvori teška preuzimanja.", "Pritisni Start i pričekaj rezultat.", "Usporedi ga s onim što obećava davatelj."])},
    {"key": "report", "page": "report", "kw": ["save report", "report", "pdf", "izvjestaj", "izvjesce", "spremi izvjestaj"],
     "title": ("Save Report", "Spremi izvještaj"),
     "desc": ("Builds a PDF report of your network. Pick the sections to include, choose which device the port scan covers, preview it and save.",
              "Izrađuje PDF izvještaj o tvojoj mreži. Odaberi dijelove, uređaj za port scan, pregledaj ga i spremi."),
     "steps": (["Tick the sections you want.", "Choose the device for the port scan.", "Press Generate Preview, then Save PDF."],
               ["Označi dijelove koje želiš.", "Odaberi uređaj za port scan.", "Pritisni Generate Preview, pa Save PDF."])},
    {"key": "notifications", "page": "dashboard", "kw": ["notification", "bell", "obavijest", "zvono", "poruke"],
     "title": ("Notifications", "Obavijesti"),
     "desc": ("The bell at the top shows events like new devices and connection changes. Mark all read clears the list.",
              "Zvono gore prikazuje događaje poput novih uređaja i promjena veze. Mark all read briše popis."),
     "steps": (["Click the bell to open the list.", "Press Mark all read to clear everything."], ["Klikni zvono za popis.", "Pritisni Mark all read da sve očistiš."])},
    {"key": "settings", "page": "dashboard", "kw": ["settings", "theme", "accent", "dark mode", "postavke", "tema", "temu", "temi", "boju", "boja", "rezolucij", "resolution"],
     "title": ("Settings", "Postavke"),
     "desc": ("The gear at the top opens theme, accent colour, glass effect and display resolution options.",
              "Zupčanik gore otvara teme, boju naglaska, glass efekt i opcije rezolucije prikaza."),
     "steps": (["Click the gear at the top.", "Pick a theme or accent; the app restyles instantly."], ["Klikni zupčanik gore.", "Odaberi temu ili boju; aplikacija se odmah prilagodi."])},
    {"key": "search", "page": "dashboard", "kw": ["search bar", "search", "pretraga", "trazi", "trazilica"],
     "title": ("Search", "Pretraga"),
     "desc": ("The search box at the top finds pages and devices; pick a result to jump straight to it.",
              "Okvir za pretragu gore pronalazi stranice i uređaje; odaberi rezultat da odmah skočiš na njega."),
     "steps": (["Type a page or device name.", "Pick a result."], ["Upiši ime stranice ili uređaja.", "Odaberi rezultat."])},
    {"key": "ai", "page": "health", "kw": ["netwer ai", "ask ai", "assistant", "asistent", "this ai", "ai chat"],
     "title": ("Netwer AI", "Netwer AI"),
     "desc": ("Me. I run on your PC from Netwer's own measurements, so nothing is sent anywhere. I can explain results, rank fixes, check security, explain terms and open the right tool.",
              "Ja. Radim na tvom računalu iz Netwerovih vlastitih mjerenja, pa se ništa nigdje ne šalje. Mogu objasniti rezultate, poredati popravke, provjeriti sigurnost, objasniti pojmove i otvoriti pravi alat."),
     "steps": (["Press Ask AI on Network Health.", "Pick a suggestion or type a question, in English or Croatian."], ["Pritisni Ask AI na Network Healthu.", "Odaberi prijedlog ili upiši pitanje, na engleskom ili hrvatskom."])},
    {"key": "about", "page": "about", "kw": ["about page", "about", "version", "verzija", "o aplikaciji"],
     "title": ("About", "O aplikaciji"),
     "desc": ("Shows the Netwer version and credits.", "Prikazuje verziju Netwera i zasluge."),
     "steps": (["Open About from the sidebar."], ["Otvori About iz bočne trake."])},
]
_PAGE_NAMES = {"health": ("Network Health", "Network Health"), "dashboard": ("Dashboard", "Dashboard")}

# port -> (name, severity, why (en, hr), fix (en, hr))
PORT_RISKS = {
    21: ("FTP", WARNING, ("FTP sends passwords and files unencrypted, so anyone on the network can read them.", "FTP šalje lozinke i datoteke nešifrirano, pa ih svatko na mreži može pročitati."),
         ("Turn FTP off, or use SFTP instead.", "Isključi FTP ili koristi SFTP.")),
    23: ("Telnet", CRITICAL, ("Telnet sends everything, including your admin password, as plain text.", "Telnet sve šalje kao običan tekst, uključujući admin lozinku."),
         ("Turn Telnet off and log in with SSH instead.", "Isključi Telnet i prijavljuj se putem SSH-a.")),
    69: ("TFTP", WARNING, ("TFTP has no login at all.", "TFTP nema nikakvu prijavu."),
         ("Disable it unless you use it for firmware transfers.", "Isključi ga osim ako ga koristiš za prijenos firmwarea.")),
    135: ("Windows RPC", WARNING, ("Used by Windows internals and a common attack target.", "Koristi se u Windowsu i čest je cilj napada."),
          ("Block it in the firewall unless you need it.", "Blokiraj ga u vatrozidu ako ti ne treba.")),
    139: ("Windows file sharing", WARNING, ("Old Windows sharing port, often probed by malware.", "Stari Windows port za dijeljenje, često ga ispituje zlonamjerni softver."),
          ("Disable file sharing on devices that don't need it.", "Isključi dijeljenje datoteka na uređajima kojima ne treba.")),
    445: ("Windows file sharing (SMB)", WARNING, ("File sharing is fine at home but must never be reachable from the internet.", "Dijeljenje je u redu kod kuće, ali nikad ne smije biti dostupno s interneta."),
          ("Make sure it's blocked on the router's internet side.", "Provjeri da je blokirano na internetskoj strani rutera.")),
    161: ("SNMP", WARNING, ("SNMP can leak details about the device with default settings.", "SNMP s tvorničkim postavkama može otkriti detalje o uređaju."),
          ("Disable it or change the default community string.", "Isključi ga ili promijeni zadani community string.")),
    1900: ("UPnP", INFO, ("UPnP lets devices open ports on the router by themselves.", "UPnP dopušta uređajima da sami otvaraju portove na ruteru."),
           ("Turn it off if you don't need it.", "Isključi ga ako ti ne treba.")),
    3306: ("MySQL database", WARNING, ("Databases shouldn't be reachable from other devices.", "Baze podataka ne bi trebale biti dostupne drugim uređajima."),
           ("Bind it to localhost or firewall it.", "Veži je na localhost ili zaštiti vatrozidom.")),
    3389: ("Remote Desktop", CRITICAL, ("Remote Desktop is a frequent ransomware entry point.", "Remote Desktop je čest ulaz za ransomware."),
           ("Turn it off, or put it behind a VPN.", "Isključi ga ili stavi iza VPN-a.")),
    5900: ("VNC remote control", CRITICAL, ("VNC is often weakly protected.", "VNC je često slabo zaštićen."),
           ("Turn it off or tunnel it via SSH/VPN.", "Isključi ga ili ga tuneliraj preko SSH-a/VPN-a.")),
    8291: ("MikroTik Winbox", WARNING, ("Winbox is the router's management port; it should only be reachable from your local network.", "Winbox je upravljački port rutera; treba biti dostupan samo iz lokalne mreže."),
           ("Restrict it to the LAN (IP > Services > Winbox > Available From).", "Ograniči ga na LAN (IP > Services > Winbox > Available From).")),
    8728: ("MikroTik API", WARNING, ("The router's management API.", "Upravljački API rutera."),
           ("Disable it or restrict it to the LAN.", "Isključi ga ili ograniči na LAN.")),
    80: ("HTTP web page", INFO, ("An unencrypted web page, often the router login. Fine at home with a strong admin password.", "Nešifrirana web stranica, često prijava na ruter. Kod kuće je u redu uz jaku admin lozinku."),
         ("Use HTTPS if the device offers it.", "Koristi HTTPS ako ga uređaj nudi.")),
}
SAFE_PORTS = {22: "SSH", 443: "HTTPS", 53: "DNS", 8729: "API-SSL"}

# diagnosis findings in Croatian: title -> (title, detail with {n} numbers, action)
FINDING_HR = {
    "No IP address": ("Nema IP adrese", "Tvoje računalo nije dobilo adresu na mreži pa još ne može komunicirati ni s čim.", "Provjeri je li Wi-Fi uključen (ili kabel utaknut), pa se ponovno spoji."),
    "Router didn't hand out an address": ("Ruter nije dodijelio adresu", "Uređaj si je sam dao zamjensku adresu (169.254.x.x), što znači da je nikad nije dobio od rutera.", "Restartaj ruter pa se ponovno spoji. Ako se ponavlja, provjeri je li DHCP uključen na ruteru."),
    "No gateway configured": ("Gateway nije postavljen", "Nije postavljen ruter kao izlaz prema internetu.", "Ponovno se spoji na mrežu ili ručno postavi gateway ako koristiš statičku konfiguraciju."),
    "Your router isn't responding": ("Ruter ne odgovara", "Ruter uopće nije dostupan. Problem je između ovog uređaja i rutera, ništa iza njega neće raditi.", "Restartaj ruter. Ako si na Wi-Fi-ju, približi se ili probaj kabel da isključiš bežičnu vezu."),
    "Losing packets to your own router": ("Gubitak paketa prema vlastitom ruteru", "{0}% paketa prema ruteru se nikad nije vratilo. To je problem lokalne veze, ne tvog davatelja.", "Na Wi-Fi-ju: približi se ili promijeni kanal. Na kabelu: probaj drugi kabel ili port."),
    "Some packet loss on the local link": ("Nešto gubitka paketa na lokalnoj vezi", "{0}% paketa prema ruteru je izgubljeno, dovoljno da uzrokuje zastajkivanje u pozivima i igrama.", "Vrijedi provjeriti Wi-Fi signal ili kabel."),
    "Slow response from the router": ("Spor odgovor rutera", "Ruteru treba {0} ms da odgovori, što je puno za uređaj u tvom domu.", "Obično je kriva slaba Wi-Fi veza ili zauzet ruter."),
    "Weak Wi-Fi signal": ("Slab Wi-Fi signal", "Jačina signala je {0}%. Na toj razini brzina pada, a veza ispada pod opterećenjem.", "Približi se ruteru ili razmisli o mesh/repeateru za tu sobu."),
    "Wi-Fi signal is just okay": ("Wi-Fi signal je tek u redu", "Jačina signala je {0}%, upotrebljivo, ali ne odlično.", "Postavljanje rutera više ili središnje obično pomaže."),
    "Your network is fine — the internet isn't": ("Mreža je u redu, internet nije", "Ruter normalno odgovara, ali ništa iza njega ne. To upućuje na davatelja ili modem, ne na tvoje uređaje.", "Restartaj modem/ruter. Ako ne pomogne, javi se davatelju, kvar je na njihovoj strani."),
    "Heavy packet loss to the internet": ("Velik gubitak paketa prema internetu", "{0}% paketa se gubi iza rutera. Pozivi, igre i video će se raspadati.", "Lokalna mreža izgleda dobro, pa je vjerojatno kriv davatelj. Prijavi mu."),
    "Some packet loss to the internet": ("Nešto gubitka paketa prema internetu", "{0}% paketa se nije vratilo.", "Prati situaciju: povremeni gubitak može biti normalan, a dugotrajan treba prijaviti."),
    "High latency": ("Visoka latencija", "Putovanje do interneta u prosjeku traje {0} ms, što je trome i šteti video pozivima i igrama.", "Provjeri da ništa ne zagušuje vezu (velika preuzimanja, backupi)."),
    "Latency is a bit high": ("Latencija je malo visoka", "Prosječno putovanje traje {0} ms.", ""),
    "Unstable latency (jitter)": ("Nestabilna latencija (jitter)", "Vrijeme odgovora varira za oko {0} ms između pingova. Zbog toga pozivi zvuče robotski.", "Često je uzrok zagušen Wi-Fi kanal ili preopterećena veza."),
    "IPv4 DNS lookups are failing": ("IPv4 DNS upiti ne uspijevaju", "A-upiti nisu uspjeli ni za jednu testnu domenu, ali IPv6 DNS odgovara.", "Provjeri IPv4 konfiguraciju DNS poslužitelja."),
    "Names aren't resolving": ("Imena se ne razrješavaju", "A-upiti nisu uspjeli ni za jednu testnu domenu, a ni IPv6 DNS nije dostupan.", "Prebaci DNS na 1.1.1.1 ili 8.8.8.8 u postavkama adaptera."),
    "IPv6 DNS lookups are failing": ("IPv6 DNS upiti ne uspijevaju", "AAAA upiti ne uspijevaju.", "Provjeri IPv6 konfiguraciju DNS poslužitelja."),
    "IPv6 isn't reaching the internet": ("IPv6 ne dolazi do interneta", "Računalo ima IPv6 adresu, ali testna veza preko IPv6 nije uspjela. Stranice se vraćaju na IPv4 pa većina stvari radi.", "Ako tvoj davatelj nudi IPv6, provjeri IPv6 postavke na ruteru."),
    "Some lookups failed": ("Neki upiti nisu uspjeli", "{0} od {1} testnih domena nije se razriješilo iz prvog pokušaja.", "Nepouzdan poslužitelj imena; javni DNS je obično stabilniji."),
    "Slow DNS": ("Spor DNS", "Traženje imena traje {0} ms u prosjeku, pa svako novo web mjesto zastane prije nego se počne učitavati.", "Razmisli o prelasku na brži DNS."),
    "A faster DNS is available": ("Dostupan je brži DNS", "Tvoj trenutni poslužitelj treba {0} ms, a drugi je puno brži.", "Prelazak na brži DNS malo ubrzava svako učitavanje stranice."),
    "Everything looks healthy": ("Sve izgleda zdravo", "Adapter, ruter, internet i DNS odgovaraju normalno, bez gubitka paketa vrijednog spomena.", ""),
}
HEADLINE_HR = {"Working, but with problems": "Radi, ali s problemima", "Working well": "Radi dobro",
               "Your network is healthy": "Tvoja mreža je zdrava"}
SUMMARY_HR = {"Everything essential is fine; a couple of small things could be better.":
              "Sve bitno radi; nekoliko sitnica moglo bi biti bolje."}

_TOOLS = [("dns", ("Open DNS Tools", "Otvori DNS alate", "dns_tools")), ("ipv6", ("Open DNS Tools", "Otvori DNS alate", "dns_tools")),
          ("wifi", ("Wi-Fi details", "Wi-Fi detalji", "wifi")), ("signal", ("Wi-Fi details", "Wi-Fi detalji", "wifi")),
          ("port", ("Open Port Scanner", "Otvori Port Scanner", "port_scanner")),
          ("telnet", ("Open Port Scanner", "Otvori Port Scanner", "port_scanner")),
          ("speed", ("Run speed test", "Pokreni test brzine", "speedtest")),
          ("router", ("Ping the router", "Pinguj ruter", "ping")), ("gateway", ("Ping the router", "Pinguj ruter", "ping")),
          ("loss", ("Open Ping", "Otvori Ping", "ping")), ("internet", ("Open Ping", "Otvori Ping", "ping"))]


def _vocabulary():
    words = set()
    for kws in INTENTS.values():
        for kw in kws:
            words.update(w for w in _norm(kw.lstrip("=")).split() if len(w) >= 5)
    for t in TOPICS:
        for kw in t["kw"]:
            words.update(w for w in _norm(kw).split() if len(w) >= 5)
    words.update(k for k in GLOSSARY if len(k) >= 5 and " " not in k)
    return sorted(words)


VOCAB = _vocabulary()


def _fix_typos(tokens):
    out = []
    for t in tokens:
        if len(t) >= 6 and not any(v.startswith(t) or t.startswith(v[:5]) for v in VOCAB):
            close = [c for c in difflib.get_close_matches(t, VOCAB, n=1, cutoff=0.84) if c[0] == t[0]]
            out.append(close[0] if close else t)
        else:
            out.append(t)
    return out


# -- engine --
class NetwerAI:
    def __init__(self):
        self._last = None
        self.hr = False

    def reset(self):
        self._last = None

    def _t(self, en, hr):
        return hr if self.hr else en

    def welcome_suggestions(self):
        return ["Explain these results", "What should I fix first?", "How can I improve my network?",
                "Is my network secure?", "Who is on my network?"]

    def _suggest(self, *pairs):
        return [self._t(en, hr) for en, hr in pairs]

    def _base_suggestions(self):
        return self._suggest(("Explain these results", "Objasni rezultate"), ("How can I improve my network?", "Kako mogu poboljšati mrežu?"),
                             ("Is my network secure?", "Je li mreža sigurna?"))

    def answer(self, question: str, ctx: dict) -> dict:
        raw = question.lower()
        q = _norm(question)
        if any(c in raw for c in "\u0161\u0111\u010d\u0107\u017e") or sum(h in f" {q} " for h in HR_HINTS) >= 1:
            self.hr = True
        elif q.split() and not any(h in f" {q} " for h in HR_HINTS):
            if re.search(r"[a-z]{3,}", q) and sum(w in q.split() for w in
                                                  ("what", "how", "why", "is", "my", "the", "can", "i", "do", "are", "to", "a")) >= 1:
                self.hr = False
        tokens = _fix_typos(q.split())
        q = " ".join(tokens)
        if not tokens:
            return _answer("empty", [text(self._t("Ask me something about your network.", "Pitaj me nešto o svojoj mreži."))],
                           self.welcome_suggestions())

        intent, best = None, 0
        term = _glossary_term(q)
        if term and _score(q, tokens, INTENTS["glossary"]):
            intent, best = "glossary", 99
        for name in PRIORITY:
            if name == "glossary":
                continue
            s = _score(q, tokens, INTENTS[name])
            if s > best:
                intent, best = name, s
        topic = self._topic(q, tokens)
        if topic and intent == "glossary" and self._topic_score >= 4:
            intent = "app_info"      # "ping sweep" or "port scanner" name a page, not just a term
            best = 0
        if topic and intent in (None, "app_info", "help", "explain_results", "router", "traffic", "devices", "wifi", "dns", "loss_latency") \
                and (_score(q, tokens, INTENTS["app_info"]) or intent is None or best <= 4):
            self._topic_hit = topic
            intent = "app_info"
        if best == 0 and intent is None and self._last and any(f in q for f in FOLLOW_UP):
            intent = "security_steps" if self._last == "security" else "fix_first"
        if intent is None:
            return self._unknown(q)
        result = getattr(self, "_" + intent)(q, ctx)
        if intent not in ("greet", "thanks", "help", "glossary", "security_steps", "app_info", "page"):
            self._last = intent
        return result

    def _topic(self, q, tokens):
        best, score = None, 0
        for t in TOPICS:
            s = 0
            for kw in t["kw"]:
                k = _norm(kw)
                if " " in k:
                    s += 4 if f" {k} " in f" {q} " else 0
                else:
                    s += 3 if k in tokens or any(x.startswith(k) for x in tokens) else 0
            if s > score:
                best, score = t, s
        self._topic_score = score
        return best if score >= 3 else None

    def _unknown(self, q):
        return _answer("unknown", [text(self._t(
            "I'm not sure I understood that. I can explain your diagnosis, rank what to fix, suggest improvements, "
            "check security, devices, Wi-Fi, DNS and traffic, explain terms like \u201cpacket loss\u201d and show how any part of Netwer works.",
            "Nisam sigurna da sam razumjela. Mogu objasniti dijagnozu, poredati što popraviti, predložiti poboljšanja, "
            "provjeriti sigurnost, uređaje, Wi-Fi, DNS i promet, objasniti pojmove poput \u201egubitak paketa\u201c i pokazati kako radi bilo koji dio Netwera."))],
            self._base_suggestions())

    # -- helpers --
    def _loc(self, f):
        # (title, detail, action) in the answer's language
        if self.hr and f.get("title") in FINDING_HR:
            title, detail, action = FINDING_HR[f["title"]]
            nums = re.findall(r"\d+(?:\.\d+)?", f.get("detail", ""))
            try:
                detail = detail.format(*nums)
            except (IndexError, KeyError):
                pass
            return title, detail, action
        return f.get("title", ""), f.get("detail", ""), f.get("action", "")

    def _split(self, action):
        return [p.strip() for p in re.split(r"(?<=[.!?])\s+", action or "") if p.strip()]

    def _tools_for(self, blob, limit=2):
        blob = _norm(blob)
        out = []
        for key, (en, hr, target) in _TOOLS:
            pair = (self._t(en, hr), target)
            if key in blob and pair not in out:
                out.append(pair)
        return out[:limit]

    def _need_diagnosis(self):
        return _answer("need_diagnosis", [
            text(self._t("I don't have fresh measurements yet. Run a diagnosis and I'll explain what it finds in plain language.",
                         "Još nemam svježa mjerenja. Pokreni dijagnozu i objasnit ću ti što je našla jednostavnim jezikom.")),
            actions((self._t("Diagnose my network", "Dijagnosticiraj mrežu"), "health_run"))])

    def _m(self, ctx):
        return (ctx.get("diagnosis") or {}).get("measurements") or {}

    def _gateway_ip(self, ctx):
        for d in ctx.get("devices", []):
            if d.get("is_gateway"):
                return d.get("ip", "")
        return self._m(ctx).get("gateway", "")

    def _device_name(self, ctx, ip):
        for d in ctx.get("devices", []):
            if d.get("ip") == ip and d.get("name"):
                return d["name"]
        return ip

    # -- single finding (Ask AI on a card) --
    def explain_finding(self, f, ctx):
        self.hr = self.hr or False
        self._last = "fix_first"
        title, detail, action = self._loc(f)
        blocks = [finding(f.get("severity", INFO), title, detail)]
        todo = self._split(action)
        if todo:
            blocks += [text(self._t("Here's what to do:", "Evo što napraviti:")), steps(todo)]
        tools = self._tools_for(f"{f.get('title', '')} {f.get('detail', '')} {f.get('action', '')}")
        if tools:
            blocks.append(actions(*tools))
        return _answer("finding", blocks, self._suggest(("What should I fix first?", "Što prvo popraviti?"),
                                                        ("Explain these results", "Objasni rezultate")))

    # -- intents --
    def _greet(self, q, ctx):
        return _answer("greet", [text(self._t(
            "Hi! I'm Netwer AI. I read your latest diagnosis, devices and traffic and explain them in plain language. What would you like to know?",
            "Bok! Ja sam Netwer AI. Čitam tvoju zadnju dijagnozu, uređaje i promet i objašnjavam ih jednostavnim jezikom. Što te zanima?"))],
            self.welcome_suggestions())

    def _thanks(self, q, ctx):
        return _answer("thanks", [text(self._t("Happy to help! Ask me anything else about your network or about Netwer.",
                                              "Drago mi je! Pitaj me što god još o mreži ili o Netweru."))], self._base_suggestions())

    def _help(self, q, ctx):
        return _answer("help", [
            text(self._t("I work entirely on your PC, from NETWER's own measurements. I can:", "Radim isključivo na tvom računalu, iz Netwerovih vlastitih mjerenja. Mogu:")),
            bullets(self._t(
                ["Explain your diagnosis and rank what to fix first", "Suggest how to improve your network", "Work out why the internet feels slow",
                 "Check your port scan for security risks", "List who is on your network and flag unknown devices",
                 "Explain Wi-Fi, DNS, ping, packet loss and 25+ other terms", "Explain any page or feature of Netwer and how to use it"],
                ["Objasniti dijagnozu i poredati što prvo popraviti", "Predložiti kako poboljšati mrežu", "Otkriti zašto je internet spor",
                 "Provjeriti port scan za sigurnosne rizike", "Navesti tko je na mreži i označiti nepoznate uređaje",
                 "Objasniti Wi-Fi, DNS, ping, gubitak paketa i još 25+ pojmova", "Objasniti bilo koju stranicu ili funkciju Netwera i kako se koristi"])),
            text(self._t("You can ask in English or Croatian and I'll answer in the same language.",
                         "Možeš pitati na engleskom ili hrvatskom, a ja odgovaram na istom jeziku."))],
            self.welcome_suggestions())

    def _page(self, q, ctx):
        key = ctx.get("page", "health")
        topic = next((t for t in TOPICS if t["key"] == key), TOPICS[8])
        return self._topic_answer(topic)

    def _app_info(self, q, ctx):
        topic = getattr(self, "_topic_hit", None) or self._topic(q, q.split())
        self._topic_hit = None
        if topic is None:
            return self._help(q, ctx)
        return self._topic_answer(topic)

    def _topic_answer(self, t):
        i = 1 if self.hr else 0
        blocks = [text(f"**{t['title'][i]}**"), text(t["desc"][i]),
                  text(self._t("How to use it:", "Kako ga koristiti:")), steps(t["steps"][i])]
        blocks.append(actions((self._t(f"Open {t['title'][0]}", f"Otvori {t['title'][1]}"), t["page"])))
        return _answer("app_info", blocks, self._base_suggestions())

    def _glossary(self, q, ctx):
        term = _glossary_term(q)
        if term is None:
            return _answer("glossary", [text(self._t(
                "Which term should I explain? I know packet loss, latency, jitter, DNS, IPv6, ports, SSH, Telnet, DHCP, UPnP, subnet, firewall, VPN, TTL and more.",
                "Koji pojam da objasnim? Znam gubitak paketa, latenciju, jitter, DNS, IPv6, portove, SSH, Telnet, DHCP, UPnP, podmrežu, vatrozid, VPN, TTL i još mnogo toga."))],
                self._suggest(("What is packet loss?", "Što je gubitak paketa?"), ("What is DNS?", "Što je DNS?"), ("What is a port?", "Što je port?")))
        en, hr = GLOSSARY[term]
        title, body = hr if self.hr else en
        blocks = [text(f"**{title}**"), text(body)]
        if term in TERM_PAGE:
            e, h, target = TERM_PAGE[term]
            blocks.append(actions((self._t(e, h), target)))
        return _answer("glossary", blocks, self._base_suggestions())

    def _explain_results(self, q, ctx):
        d = ctx.get("diagnosis")
        if not d:
            return self._need_diagnosis()
        findings = d["findings"]
        issues = [f for f in findings if f["severity"] in (CRITICAL, WARNING)]
        notes = [f for f in findings if f["severity"] == INFO]
        head, summ = d["headline"], d["summary"]
        if self.hr and findings:
            top = self._loc(findings[0])
            head = top[0] if d["severity"] == CRITICAL else HEADLINE_HR.get(head, head)
            summ = top[1] if d["severity"] in (CRITICAL, WARNING, GOOD) else SUMMARY_HR.get(summ, summ)
        blocks = [text(f"**{head}** {summ}")]
        for f in (issues + notes)[:4]:
            title, detail, _a = self._loc(f)
            blocks.append(finding(f["severity"], title, detail))
        if not issues:
            blocks.append(text(self._t("Nothing needs fixing right now.", "Trenutno ništa ne treba popravljati.")))
        tr = ctx.get("traffic") or {}
        if tr.get("download_mbps"):
            dl, ul = tr["download_mbps"], tr.get("upload_mbps", {})
            blocks.append(text(self._t(
                f"Recent traffic: download averaging {dl['avg']} Mbps (peak {dl['peak']}), upload averaging {ul.get('avg', 0)} Mbps.",
                f"Nedavni promet: download u prosjeku {dl['avg']} Mbps (vrh {dl['peak']}), upload u prosjeku {ul.get('avg', 0)} Mbps.")))
        sug = ([self._t("What should I fix first?", "Što prvo popraviti?")] if issues
               else [self._t("How can I improve my network?", "Kako mogu poboljšati mrežu?")])
        return _answer("explain_results", blocks, sug + [self._t("Is my network secure?", "Je li mreža sigurna?")])

    def _fix_first(self, q, ctx):
        d = ctx.get("diagnosis")
        if not d:
            return self._need_diagnosis()
        issues = [f for f in d["findings"] if f["severity"] in (CRITICAL, WARNING)]
        if not issues:
            blocks = [text(self._t("Nothing urgent. Your connection looks healthy.", "Ništa hitno. Tvoja veza izgleda zdravo."))]
            best = self._m(ctx).get("best_public_dns")
            if best:
                blocks.append(text(self._t(
                    f"One optional tweak: {best['name']} DNS answered fastest ({best['ms']} ms) if you want snappier page loads.",
                    f"Jedna neobavezna promjena: {best['name']} DNS je odgovorio najbrže ({best['ms']} ms) ako želiš brže učitavanje stranica.")))
            return _answer("fix_first", blocks, self._suggest(("How can I improve my network?", "Kako mogu poboljšati mrežu?"),
                                                               ("Is my network secure?", "Je li mreža sigurna?")))
        top = issues[0]
        title, detail, action = self._loc(top)
        blocks = [text(self._t("Start with this one:", "Počni s ovim:")), finding(top["severity"], title, detail)]
        todo = self._split(action)
        if todo:
            blocks.append(steps(todo))
        tools = self._tools_for(f"{top['title']} {top['detail']} {top.get('action', '')}")
        if tools:
            blocks.append(actions(*tools))
        if len(issues) > 1:
            names = ", ".join(self._loc(i)[0] for i in issues[1:3])
            blocks.append(text(self._t(f"After that there {'is' if len(issues) == 2 else 'are'} {len(issues) - 1} more: {names}.",
                                       f"Nakon toga ima još {len(issues) - 1}: {names}.")))
        return _answer("fix_first", blocks, self._suggest(("Explain these results", "Objasni rezultate"),
                                                           ("Is my network secure?", "Je li mreža sigurna?")))

    def _improve(self, q, ctx):
        t, m = self._t, self._m(ctx)
        recs = []   # (priority, lead, detail)
        ps = ctx.get("port_scan")
        if ps:
            risky = [PORT_RISKS[r["port"]] for r in ps["results"] if r["port"] in PORT_RISKS and PORT_RISKS[r["port"]][1] in (CRITICAL, WARNING)]
            for nm, sev, why, fix in risky[:3]:
                recs.append((0 if sev == CRITICAL else 1, t(f"Close {nm} on your router", f"Zatvori {nm} na ruteru"), t(fix[0], fix[1])))
        d = ctx.get("diagnosis")
        if d:
            for f in d["findings"]:
                if f["severity"] in (CRITICAL, WARNING):
                    title, _d, action = self._loc(f)
                    recs.append((1 if f["severity"] == CRITICAL else 2, title, " ".join(self._split(action)[:1])))
        best = m.get("best_public_dns")
        if best and (m.get("dns_ipv4_ms") or 0) > best["ms"] * 1.5:
            recs.append((3, t(f"Switch DNS to {best['name']}", f"Prebaci DNS na {best['name']}"),
                         t(f"It answered in {best['ms']} ms against your {m.get('dns_ipv4_ms')} ms, so pages start loading sooner.",
                           f"Odgovorio je za {best['ms']} ms naspram tvojih {m.get('dns_ipv4_ms')} ms, pa se stranice brže počinju učitavati.")))
        if m.get("wifi"):
            sig = m.get("signal") or 0
            if sig < 70:
                recs.append((4, t("Strengthen your Wi-Fi", "Pojačaj Wi-Fi"),
                             t("Move the router higher and more central, or use a mesh/repeater for far rooms.",
                               "Postavi ruter više i središnje ili koristi mesh/repeater za udaljene sobe.")))
            recs.append((6, t("Use 5 GHz and a quiet channel", "Koristi 5 GHz i mirniji kanal"),
                         t("5 GHz is faster at short range; check Wi-Fi Information for a less crowded channel.",
                           "5 GHz je brži na kratkoj udaljenosti; u Wi-Fi Information potraži manje zagušen kanal.")))
        elif (m.get("internet") or {}).get("jitter", 0) > 15:
            recs.append((5, t("Prefer a cable for calls and games", "Za pozive i igre koristi kabel"),
                         t("A cable removes Wi-Fi jitter.", "Kabel uklanja Wi-Fi jitter.")))
        ul = ((ctx.get("traffic") or {}).get("upload_mbps") or {}).get("avg") or 0
        if ul > 3:
            recs.append((5, t("Schedule big uploads", "Rasporedi velike uploade"),
                         t("Cloud backups and sync saturate your upload; run them at night.", "Cloud backupi i sinkronizacija zasite tvoj upload; pokreni ih noću.")))
        unnamed = [x for x in ctx.get("devices", []) if (x.get("name") or "").lower() in ("", "device", "unknown device", "device (private)")]
        if unnamed:
            recs.append((5, t("Review unknown devices", "Pregledaj nepoznate uređaje"),
                         t(f"{len(unnamed)} device(s) have no recognisable name; check them in Connected Devices.",
                           f"{len(unnamed)} uređaj(a) nema prepoznatljivo ime; provjeri ih u Connected Devices.")))
        habits = [(8, t("Keep the router firmware up to date", "Održavaj firmware rutera ažurnim"),
                   t("Updates close security holes and often improve speed.", "Ažuriranja zatvaraju sigurnosne rupe i često poboljšavaju brzinu.")),
                  (9, t("Use a strong Wi-Fi and admin password", "Koristi jaku Wi-Fi i admin lozinku"),
                   t("WPA2/WPA3 with a long passphrase, and change the router's default admin login.",
                     "WPA2/WPA3 s dugom lozinkom te promijeni zadanu admin prijavu rutera.")),
                  (9, t("Turn off what you don't use", "Isključi što ne koristiš"),
                   t("WPS, UPnP and remote administration are common weak spots.", "WPS, UPnP i udaljena administracija česta su slaba mjesta."))]
        recs.sort(key=lambda r: r[0])
        picked = recs[:5]
        if len(picked) < 4:
            picked += habits[:4 - len(picked)]
        if not d and not ps:
            lead = t("I'd get better advice from a diagnosis, but here's what helps most networks:", "Uz dijagnozu bih mogla bolje savjetovati, ali ovo pomaže većini mreža:")
        else:
            lead = t("Based on your data, in order of impact:", "Prema tvojim podacima, redom po važnosti:")
        blocks = [text(lead), steps([f"**{a}.** {b}" if b else f"**{a}.**" for _p, a, b in picked])]
        pairs = []
        if not d:
            pairs.append((t("Diagnose my network", "Dijagnosticiraj mrežu"), "health_run"))
        gw = self._gateway_ip(ctx)
        if not ps and gw:
            pairs.append((t("Scan my router", "Skeniraj ruter"), f"scan:{gw}"))
        if pairs:
            blocks.append(actions(*pairs))
        return _answer("improve", blocks, self._suggest(("What should I fix first?", "Što prvo popraviti?"), ("Is my network secure?", "Je li mreža sigurna?")))

    def _slow(self, q, ctx):
        d = ctx.get("diagnosis")
        if not d:
            return self._need_diagnosis()
        t, m, tr = self._t, self._m(ctx), ctx.get("traffic") or {}
        router, inet = m.get("router") or {}, m.get("internet") or {}
        causes = []
        if router.get("loss") or (router.get("avg") or 0) > 25:
            causes.append((0, t("The problem is between your computer and your router", "Problem je između računala i rutera"),
                           t(f"Router ping {router.get('avg')} ms with {router.get('loss')}% loss.", f"Ping do rutera {router.get('avg')} ms uz {router.get('loss')}% gubitka."),
                           t(["If you use Wi-Fi, move closer to the router or switch to a cable to test.", "Restart the router and wait two minutes.",
                              "Check that nothing else is saturating the link (backups, streaming)."],
                             ["Ako koristiš Wi-Fi, približi se ruteru ili probaj kabel.", "Restartaj ruter i pričekaj dvije minute.", "Provjeri da ništa drugo ne zasićuje vezu (backupi, streaming)."])))
        elif m.get("router_reachable") and (inet.get("loss") or 0) >= 1:
            causes.append((1, t("Your router is fine, but the connection beyond it loses data", "Ruter je u redu, ali veza iza njega gubi podatke"),
                           t(f"Internet packet loss is {inet.get('loss')}%.", f"Gubitak paketa prema internetu je {inet.get('loss')}%."),
                           t(["Restart the router and modem.", "Test again with a cable to rule out Wi-Fi.", "If it keeps happening, contact your provider and quote the packet loss."],
                             ["Restartaj ruter i modem.", "Testiraj ponovno kabelom da isključiš Wi-Fi.", "Ako se ponavlja, javi se davatelju i navedi gubitak paketa."])))
        if (inet.get("avg") or 0) > 80:
            causes.append((2, t("The route to the internet is slow", "Put do interneta je spor"),
                           t(f"Internet ping averages {inet.get('avg')} ms.", f"Ping do interneta u prosjeku je {inet.get('avg')} ms."),
                           t(["Run the speed test to see your real speed.", "Try at a different time of day; evening congestion is common.", "Contact your provider if it stays high."],
                             ["Pokreni test brzine da vidiš stvarnu brzinu.", "Probaj u drugo doba dana; večernja zagušenja su česta.", "Javi se davatelju ako ostane visoko."])))
        if (inet.get("jitter") or 0) > 30:
            causes.append((3, t("Your connection is unstable (high jitter)", "Veza je nestabilna (visok jitter)"),
                           t(f"Jitter is {inet.get('jitter')} ms, which makes calls and games choppy.", f"Jitter je {inet.get('jitter')} ms, zbog čega pozivi i igre zastajkuju."),
                           t(["Use a cable instead of Wi-Fi if possible.", "Pause large downloads and uploads while you need it stable."],
                             ["Koristi kabel umjesto Wi-Fi-ja ako možeš.", "Pauziraj velika preuzimanja i uploade dok ti treba stabilnost."])))
        if m.get("dns_failures") or (m.get("dns_ms") or 0) > 100:
            bd = m.get("best_public_dns")
            fix = t(["Switch your DNS server to a faster one in the adapter settings."], ["Prebaci DNS poslužitelj na brži u postavkama adaptera."])
            if bd:
                fix.insert(0, t(f"{bd['name']} DNS answered fastest at {bd['ms']} ms; use it.", f"{bd['name']} DNS je odgovorio najbrže ({bd['ms']} ms); koristi ga."))
            causes.append((4, t("Name lookups are slow, so pages hang before loading", "Traženje imena je sporo, pa stranice zastanu prije učitavanja"),
                           t(f"DNS takes {m.get('dns_ms')} ms.", f"DNS traje {m.get('dns_ms')} ms."), fix))
        if m.get("wifi") and (m.get("signal") or 100) < 50:
            causes.append((5, t("Your Wi-Fi signal is weak", "Wi-Fi signal je slab"), t(f"Signal strength is {m.get('signal')}%.", f"Jačina signala je {m.get('signal')}%."),
                           t(["Move closer to the router or remove obstacles between you.", "Try the 5 GHz band if your router has it, or change the Wi-Fi channel."],
                             ["Približi se ruteru ili ukloni prepreke između.", "Probaj 5 GHz pojas ako ga ruter ima ili promijeni Wi-Fi kanal."])))
        ul = (tr.get("upload_mbps") or {}).get("avg") or 0
        if ul > 3:
            causes.append((6, t("Something on your PC is uploading a lot", "Nešto na računalu puno uploada"),
                           t(f"Upload is averaging {ul} Mbps, which can slow everything else.", f"Upload u prosjeku iznosi {ul} Mbps, što može usporiti sve ostalo."),
                           t(["Pause cloud backups and sync tools (OneDrive, Google Drive).", "Check the Dashboard graph to see when it happens."],
                             ["Pauziraj cloud backupe i sinkronizaciju (OneDrive, Google Drive).", "Pogledaj graf na Dashboardu da vidiš kad se događa."])))
        causes.sort(key=lambda c: c[0])
        if not causes:
            return _answer("slow", [text(t(
                "Your measurements look healthy: low latency, no packet loss and fast DNS. So the slowness is probably the website or service itself, or something temporary.",
                "Tvoja mjerenja izgledaju zdravo: niska latencija, bez gubitka paketa i brz DNS. Spor je vjerojatno sama web stranica ili usluga, ili je nešto privremeno.")),
                text(t("A speed test will show whether your line delivers what you pay for.", "Test brzine pokazat će daje li veza ono što plaćaš.")),
                actions((t("Run speed test", "Pokreni test brzine"), "speedtest"))],
                self._suggest(("How can I improve my network?", "Kako mogu poboljšati mrežu?"), ("Is my network secure?", "Je li mreža sigurna?")))
        top = causes[0]
        blocks = [text(f"**{top[1]}.**"), bullets([c[2] for c in causes[:3]]), text(t("What to try:", "Što probati:")), steps(top[3])]
        tools = self._tools_for(top[1] + " " + top[2])
        if tools:
            blocks.append(actions(*tools))
        return _answer("slow", blocks, self._suggest(("What should I fix first?", "Što prvo popraviti?"), ("Explain these results", "Objasni rezultate")))

    def _security(self, q, ctx, steps_only=False):
        t = self._t
        ps = ctx.get("port_scan")
        if not ps:
            gw = self._gateway_ip(ctx)
            blocks = [text(t("I haven't seen a port scan yet. Scanning your router shows which services it exposes, which is the most useful security check at home.",
                             "Još nisam vidjela port scan. Skeniranje rutera pokazuje koje usluge izlaže, što je najkorisnija sigurnosna provjera kod kuće."))]
            blocks.append(actions(*([(t("Scan my router", "Skeniraj ruter"), f"scan:{gw}")] if gw else []),
                                  (t("Open Port Scanner", "Otvori Port Scanner"), "port_scanner")))
            return _answer("security", blocks, self._suggest(("Who is on my network?", "Tko je na mojoj mreži?"), ("Explain these results", "Objasni rezultate")))
        name = ps.get("target_name") or self._device_name(ctx, ps["target"])
        label = f"{name} ({ps['target']})" if name and name != ps["target"] else ps["target"]
        open_ports = [r["port"] for r in ps["results"]]
        risky = sorted(((p, PORT_RISKS[p]) for p in open_ports if p in PORT_RISKS), key=lambda x: (_SEV_RANK[x[1][1]], x[0]))
        serious = [r for r in risky if r[1][1] in (CRITICAL, WARNING)]
        if not open_ports:
            return _answer("security", [text(t(f"The last scan found no open ports on {label}. That's the safest result.",
                                               f"Zadnji sken nije našao otvorenih portova na {label}. To je najsigurniji ishod."))],
                           self._suggest(("Who is on my network?", "Tko je na mojoj mreži?")))
        blocks = [text(t(f"Last scan of **{label}**: {len(open_ports)} open port{'s' if len(open_ports) != 1 else ''}, {len(serious)} worth closing.",
                         f"Zadnji sken **{label}**: {len(open_ports)} otvorenih portova, {len(serious)} vrijedno zatvaranja."))]
        todo = []
        if not steps_only:
            for p, (nm, sev, why, fix) in risky[:4]:
                blocks.append(finding(sev, t(f"{nm} (port {p}) is open", f"{nm} (port {p}) je otvoren"), t(why[0], why[1])))
        for p, (nm, sev, why, fix) in risky:
            if sev in (CRITICAL, WARNING):
                todo.append(f"{nm}: {t(fix[0], fix[1])}")
        fine = [f"{SAFE_PORTS[p]} ({p})" for p in open_ports if p in SAFE_PORTS]
        if fine and not steps_only:
            blocks.append(text(t("These are encrypted or harmless: ", "Ovi su šifrirani ili bezopasni: ") + ", ".join(fine) + "."))
        if todo:
            blocks.append(text(t("How to close them:", "Kako ih zatvoriti:")))
            hint = "mikrotik" in _norm(f"{name} {' '.join(str(r.get('banner', '')) for r in ps['results'])}")
            first = t("Open your router's admin page" + (" (WinBox or WebFig on MikroTik)" if hint else "") + " and note the current settings first.",
                      "Otvori admin stranicu rutera" + (" (WinBox ili WebFig na MikroTiku)" if hint else "") + " i prvo zapiši trenutne postavke.")
            blocks.append(steps([first] + todo[:4] + [t("Run the port scan again to confirm they're closed.", "Ponovno pokreni port scan da potvrdiš da su zatvoreni.")]))
        else:
            blocks.append(text(t("Nothing alarming here. Keep the router firmware up to date and use a strong admin password.",
                                 "Ništa alarmantno. Održavaj firmware rutera ažurnim i koristi jaku admin lozinku.")))
        blocks.append(actions((t("Scan again", "Skeniraj ponovno"), f"scan:{ps['target']}")))
        return _answer("security", blocks, self._suggest(("What should I fix first?", "Što prvo popraviti?"), ("Who is on my network?", "Tko je na mojoj mreži?")))

    def _security_steps(self, q, ctx):
        return self._security(q, ctx, steps_only=True)

    def _wifi(self, q, ctx):
        t = self._t
        if not ctx.get("diagnosis"):
            return self._need_diagnosis()
        m = self._m(ctx)
        if not m.get("wifi"):
            return _answer("wifi", [text(t(f"You're not on Wi-Fi right now ({m.get('adapter') or 'wired adapter'}), so Wi-Fi isn't affecting your connection.",
                                           f"Trenutno nisi na Wi-Fi-ju ({m.get('adapter') or 'žični adapter'}), pa Wi-Fi ne utječe na tvoju vezu.")),
                                      actions((t("Wi-Fi details", "Wi-Fi detalji"), "wifi"))], self._suggest(("Why is my internet slow?", "Zašto je internet spor?")))
        sig = m.get("signal") or 0
        rating = (t("excellent", "odličan") if sig >= 80 else t("good", "dobar") if sig >= 60 else t("fair", "osrednji") if sig >= 40 else t("weak", "slab"))
        blocks = [text(t(f"Your Wi-Fi signal is **{rating}** ({sig}%)", f"Tvoj Wi-Fi signal je **{rating}** ({sig}%)")
                       + (t(f" on {m['band']}", f" na {m['band']}") if m.get("band") else "")
                       + (t(f", channel {m['channel']}", f", kanal {m['channel']}") if m.get("channel") else "") + ".")]
        if sig < 60:
            blocks += [text(t("To improve it:", "Za poboljšanje:")),
                       steps(t(["Move closer to the router or remove walls and metal objects between you.", "Use the 5 GHz band for speed at short range, 2.4 GHz for range.", "Try a less crowded channel in the router settings."],
                               ["Približi se ruteru ili ukloni zidove i metalne predmete između.", "Koristi 5 GHz za brzinu na kratkoj udaljenosti, 2,4 GHz za domet.", "Probaj manje zagušen kanal u postavkama rutera."]))]
        blocks.append(actions((t("Wi-Fi details", "Wi-Fi detalji"), "wifi")))
        return _answer("wifi", blocks, self._suggest(("Why is my internet slow?", "Zašto je internet spor?"), ("How can I improve my network?", "Kako mogu poboljšati mrežu?")))

    def _dns(self, q, ctx):
        t = self._t
        if not ctx.get("diagnosis"):
            return self._need_diagnosis()
        m = self._m(ctx)
        lines = [t(f"DNS lookups succeed and average {m.get('dns_ipv4_ms')} ms.", f"DNS upiti uspijevaju i u prosjeku traju {m.get('dns_ipv4_ms')} ms.")
                 if m.get("dns_working") else t("DNS lookups are failing, so names like google.com can't be resolved.", "DNS upiti ne uspijevaju, pa se nazivi poput google.com ne mogu razriješiti.")]
        scope = m.get("ipv6_scope")
        lines.append({"global": t("IPv6 is active.", "IPv6 je aktivan."),
                      "ula": t("IPv6 works on your local network only.", "IPv6 radi samo na lokalnoj mreži."),
                      "link-local": t("IPv6 is link-local only (no internet over IPv6).", "IPv6 je samo link-local (bez interneta preko IPv6).")}.get(
            scope, t("You have no IPv6 address, which is normal on many networks.", "Nemaš IPv6 adresu, što je normalno na mnogim mrežama.")))
        blocks = [bullets(lines)]
        best = m.get("best_public_dns")
        if best and (m.get("dns_ipv4_ms") or 0) > best["ms"] * 1.5:
            blocks.append(text(t(f"{best['name']} DNS answered in {best['ms']} ms, noticeably faster than yours. Switching your DNS server can make pages feel snappier.",
                                 f"{best['name']} DNS je odgovorio za {best['ms']} ms, osjetno brže od tvog. Promjena DNS poslužitelja može ubrzati učitavanje stranica.")))
        blocks.append(actions((t("Open DNS Tools", "Otvori DNS alate"), "dns_tools")))
        return _answer("dns", blocks, self._suggest(("Why is my internet slow?", "Zašto je internet spor?"), ("What is DNS?", "Što je DNS?")))

    def _devices(self, q, ctx):
        t = self._t
        devs = ctx.get("devices") or []
        if not devs:
            return _answer("devices", [text(t("I haven't discovered any devices yet. Run a network scan from the Dashboard or Ping Sweep.",
                                              "Još nisam otkrila nijedan uređaj. Pokreni skeniranje mreže s Dashboarda ili Ping Sweepa.")),
                                       actions((t("Open Ping Sweep", "Otvori Ping Sweep"), "ping_sweep"))], self._suggest(("Explain these results", "Objasni rezultate")))
        unnamed = [d for d in devs if (d.get("name") or "").lower() in ("", "device", "unknown device", "device (private)")]
        items = [f"{d.get('name') or t('Unnamed', 'Bez imena')} - {d.get('ip', '')}" + (t(" (router)", " (ruter)") if d.get("is_gateway") else "") for d in devs[:8]]
        n = len(devs)
        blocks = [text(t(f"There {'is' if n == 1 else 'are'} **{n} device{'s' if n != 1 else ''}** on your network:", f"Na tvojoj mreži je **{n} uređaja**:")), bullets(items)]
        if n > 8:
            blocks.append(text(t(f"...and {n - 8} more.", f"...i još {n - 8}.")))
        if unnamed:
            blocks.append(text(t(f"{len(unnamed)} of them {'has' if len(unnamed) == 1 else 'have'} no recognisable name. If you don't know what they are, check them in Connected Devices, or change your Wi-Fi password if something looks off.",
                                 f"{len(unnamed)} od njih nema prepoznatljivo ime. Ako ne znaš što su, provjeri ih u Connected Devices ili promijeni Wi-Fi lozinku ako nešto izgleda sumnjivo.")))
        else:
            blocks.append(text(t("Every device has a recognisable name, which is a good sign.", "Svaki uređaj ima prepoznatljivo ime, što je dobar znak.")))
        blocks.append(actions((t("Rescan network", "Ponovno skeniraj mrežu"), "ping_sweep")))
        return _answer("devices", blocks, self._suggest(("Is my network secure?", "Je li mreža sigurna?"), ("What should I fix first?", "Što prvo popraviti?")))

    def _myinfo(self, q, ctx):
        t, m = self._t, self._m(ctx)
        if not m:
            return self._need_diagnosis()
        lines = [t(f"Computer address: {m.get('ip')}", f"Adresa računala: {m.get('ip')}"), t(f"Router (gateway): {m.get('gateway')}", f"Ruter (gateway): {m.get('gateway')}"),
                 t(f"Adapter: {m.get('adapter')}", f"Adapter: {m.get('adapter')}")]
        return _answer("myinfo", [bullets(lines), text(t("Full details, including MAC address, DNS servers and link speed, are in Network Information.",
                                                           "Svi detalji, uključujući MAC adresu, DNS poslužitelje i brzinu veze, nalaze se u Network Information.")),
                                  actions((t("Network info", "Mrežne informacije"), "network"))], self._base_suggestions())

    def _loss_latency(self, q, ctx):
        t, m, tr = self._t, self._m(ctx), ctx.get("traffic") or {}
        router, inet = m.get("router") or {}, m.get("internet") or {}
        if not ctx.get("diagnosis") and not tr.get("latency_ms"):
            return self._need_diagnosis()
        lines = []
        if router:
            lines.append(t(f"Router: {router.get('avg')} ms, {router.get('loss')}% loss", f"Ruter: {router.get('avg')} ms, {router.get('loss')}% gubitka"))
        if inet:
            lines.append(t(f"Internet: {inet.get('avg')} ms, {inet.get('loss')}% loss, jitter {inet.get('jitter')} ms", f"Internet: {inet.get('avg')} ms, {inet.get('loss')}% gubitka, jitter {inet.get('jitter')} ms"))
        if tr.get("packet_loss_pct"):
            pl = tr["packet_loss_pct"]
            lines.append(t(f"Last few minutes: loss averaging {pl['avg']}% (worst {pl['worst']}%)", f"Zadnjih nekoliko minuta: gubitak u prosjeku {pl['avg']}% (najgore {pl['worst']}%)"))
        loss = max([inet.get("loss") or 0, (tr.get("packet_loss_pct") or {}).get("avg") or 0])
        lat = inet.get("avg") or (tr.get("latency_ms") or {}).get("avg") or 0
        verdict = (t("No packet loss and low latency: this is as good as it gets.", "Bez gubitka paketa i s niskom latencijom: bolje od ovoga ne ide.") if loss < 1 and lat < 50 else
                   t("Some packet loss: you may notice stutter in calls and games.", "Nešto gubitka paketa: možda primijetiš zastajkivanje u pozivima i igrama.") if loss < 5 else
                   t("Heavy packet loss: this will definitely cause problems.", "Velik gubitak paketa: ovo će sigurno uzrokovati probleme."))
        blocks = [bullets(lines or [t("No measurements yet.", "Još nema mjerenja.")]), text(verdict)]
        if loss >= 1:
            blocks += [text(t("What to try:", "Što probati:")), steps(t(["Restart the router.", "Test with a cable instead of Wi-Fi.", "If it persists, contact your provider."],
                                                                     ["Restartaj ruter.", "Testiraj kabelom umjesto Wi-Fi-ja.", "Ako se nastavi, javi se davatelju."]))]
        blocks.append(actions((t("Open Ping", "Otvori Ping"), "ping")))
        return _answer("loss_latency", blocks, self._suggest(("Why is my internet slow?", "Zašto je internet spor?"), ("What is jitter?", "Što je jitter?")))

    def _traffic(self, q, ctx):
        t, tr = self._t, ctx.get("traffic") or {}
        if not tr.get("download_mbps"):
            return _answer("traffic", [text(t("I don't have traffic samples yet. Keep Netwer open for a minute and I'll have something to work with.",
                                              "Još nemam uzoraka prometa. Ostavi Netwer otvoren minutu i imat ću s čime raditi.")),
                                       actions((t("Open Dashboard", "Otvori Dashboard"), "dashboard"))], self._suggest(("Explain these results", "Objasni rezultate")))
        dl, ul = tr["download_mbps"], tr.get("upload_mbps", {})
        blocks = [bullets([t(f"Download: averaging {dl['avg']} Mbps, peak {dl['peak']} Mbps", f"Download: u prosjeku {dl['avg']} Mbps, vrh {dl['peak']} Mbps"),
                           t(f"Upload: averaging {ul.get('avg', 0)} Mbps, peak {ul.get('peak', 0)} Mbps", f"Upload: u prosjeku {ul.get('avg', 0)} Mbps, vrh {ul.get('peak', 0)} Mbps")])]
        blocks.append(text(t("Your upload is unusually busy. A backup, cloud sync or file upload is likely running and can slow other things down.",
                             "Tvoj upload je neobično zauzet. Vjerojatno radi backup, cloud sinkronizacija ili upload datoteka, što može usporiti ostalo.")
                           if (ul.get("avg") or 0) > 3 else t("Nothing unusual in your traffic.", "Ništa neobično u tvom prometu.")))
        blocks.append(actions((t("Detailed analysis", "Detaljna analiza"), "dashboard"), (t("Run speed test", "Pokreni test brzine"), "speedtest")))
        return _answer("traffic", blocks, self._suggest(("Why is my internet slow?", "Zašto je internet spor?"), ("Explain these results", "Objasni rezultate")))

    def _router(self, q, ctx):
        t, m = self._t, self._m(ctx)
        gw = self._gateway_ip(ctx)
        if not ctx.get("diagnosis") and not gw:
            return self._need_diagnosis()
        name = self._device_name(ctx, gw) if gw else t("your router", "tvoj ruter")
        router = m.get("router") or {}
        lines = [t(f"Address: {gw}", f"Adresa: {gw}") if gw else t("Address unknown", "Adresa nepoznata")]
        if router.get("avg") is not None:
            lines.append(t(f"Response: {router['avg']} ms, {router.get('loss')}% loss", f"Odgovor: {router['avg']} ms, {router.get('loss')}% gubitka"))
        ps = ctx.get("port_scan")
        if ps and ps.get("target") == gw:
            risky = [PORT_RISKS[r["port"]][0] for r in ps["results"] if r["port"] in PORT_RISKS and PORT_RISKS[r["port"]][1] in (CRITICAL, WARNING)]
            lines.append((t("Exposed: ", "Izloženo: ") + ", ".join(risky)) if risky else t("Last port scan found nothing risky", "Zadnji port scan nije našao ništa rizično"))
        blocks = [text(f"**{name}**"), bullets(lines)]
        blocks.append(actions((t("Scan my router", "Skeniraj ruter"), f"scan:{gw}")) if gw else actions((t("Open Ping", "Otvori Ping"), "ping")))
        return _answer("router", blocks, self._suggest(("Is my network secure?", "Je li mreža sigurna?"), ("How can I improve my network?", "Kako mogu poboljšati mrežu?")))
