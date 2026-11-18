#!/usr/bin/env python3
"""ekoproxy - etap 1: podsłuch połączenia sterownika ArgosPid Plus (Technix) z serwerem ekotlownia.pl.

Sterownik sam łączy się z serwerem producenta. Żeby zrobić własną, darmową aplikację,
trzeba najpierw poznać jego protokół. To narzędzie:

  1. udaje serwer DNS - loguje wszystkie nazwy, o które pyta sterownik, a nazwy pasujące
     do wzorców (domyślnie: ekotlownia, bolecki, technix) kieruje na ten komputer,
  2. nasłuchuje na wielu portach TCP; gdy sterownik się połączy, przekazuje ruch do
     prawdziwego serwera (sterownik dalej działa jak dotąd) i zapisuje każdy bajt
     w obie strony do pliku .jsonl.

Tylko biblioteka standardowa Pythona 3.8+. Działa na Windows, Linux i Raspberry Pi.

Użycie:
  python ekoproxy.py                     # podsłuch (DNS + proxy), zapis do logi/
  python ekoproxy.py --offline           # bez łączenia z prawdziwym serwerem
  python ekoproxy.py pokaz logi/plik.jsonl   # czytelny podgląd zapisanego logu
"""
import argparse
import asyncio
import datetime
import json
import os
import socket
import struct
import sys

DEFAULT_PATTERNS = "ekotlownia,bolecki,technix"
# Porty najczęściej używane przez małe urządzenia IoT. Zakres można zmienić opcją --ports.
DEFAULT_PORTS = ("21,23,25,80,81,88,443,502,1000,1024,1234,1883,2000,2001,2222,3000,3001,3333,"
                 "4000,4001,4040,4444,4567,5000,5001,5050,5555,6000,6001,6666,7000,7001,7777,"
                 "8000-8010,8080-8090,8443,8800,8883,8888,9000,9001,9090,9999,10000,10001,"
                 "12345,20000,30000,40000,50000")


def now():
    return datetime.datetime.now().isoformat(timespec="milliseconds")


def printable(data: bytes) -> str:
    return "".join(chr(b) if 32 <= b < 127 else "." for b in data)


def parse_ports(spec: str):
    ports = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            ports.update(range(int(a), int(b) + 1))
        else:
            ports.add(int(part))
    return sorted(p for p in ports if 0 < p < 65536)


def local_ip() -> str:
    """Adres tego komputera w sieci domowej (bez wysyłania czegokolwiek)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


class Log:
    def __init__(self, path):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.path = path
        self.f = open(path, "a", encoding="utf-8")

    def write(self, kind, msg=None, **rec):
        rec = {"t": now(), "typ": kind, **rec}
        if kind == "info" and msg:
            rec["opis"] = msg
        self.f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.f.flush()
        if msg:
            print(f"[{rec['t'][11:23]}] {msg}", flush=True)


# ---------------------------------------------------------------- DNS

def dns_parse_question(pkt: bytes):
    """Zwraca (nazwa, qtype, koniec_pytania) albo None."""
    if len(pkt) < 12 or struct.unpack(">H", pkt[4:6])[0] < 1:
        return None
    i, labels = 12, []
    while i < len(pkt):
        n = pkt[i]
        if n == 0:
            i += 1
            break
        if n & 0xC0:
            return None
        labels.append(pkt[i + 1:i + 1 + n].decode("ascii", "replace"))
        i += 1 + n
    if i + 4 > len(pkt):
        return None
    qtype = struct.unpack(">H", pkt[i:i + 2])[0]
    return ".".join(labels).lower(), qtype, i + 4


def dns_answer(pkt: bytes, q_end: int, ip: str, qtype: int) -> bytes:
    flags = 0x8180 | (pkt[2] & 0x01) << 8  # odpowiedź, rekursja dostępna, kopiuj RD
    ancount = 1 if qtype == 1 else 0       # na AAAA itp. odpowiadamy pusto -> sterownik użyje IPv4
    hdr = pkt[:2] + struct.pack(">HHHHH", flags, 1, ancount, 0, 0)
    ans = b""
    if ancount:
        ans = struct.pack(">HHHIH", 0xC00C, 1, 1, 60, 4) + socket.inet_aton(ip)
    return hdr + pkt[12:q_end] + ans


class DnsServer(asyncio.DatagramProtocol):
    def __init__(self, app):
        self.app = app

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        asyncio.ensure_future(self.handle(data, addr))

    async def handle(self, data, addr):
        q = dns_parse_question(data)
        if not q:
            return
        name, qtype, q_end = q
        app = self.app
        if app.should_spoof(name):
            self.transport.sendto(dns_answer(data, q_end, app.my_ip, qtype), addr)
            if qtype == 1:
                app.log.write("dns", f"DNS  {addr[0]} pyta o {name}  ->  PRZEKIEROWANO na {app.my_ip}",
                              klient=addr[0], nazwa=name, qtype=qtype, przekierowano=True)
                await app.learn_upstream(name)
            return
        app.log.write("dns", f"DNS  {addr[0]} pyta o {name} (typ {qtype}) - przekazuję dalej",
                      klient=addr[0], nazwa=name, qtype=qtype, przekierowano=False)
        reply = await app.forward_dns(data)
        if reply:
            self.transport.sendto(reply, addr)


# ---------------------------------------------------------------- TCP proxy

class App:
    def __init__(self, args):
        self.args = args
        self.my_ip = args.ip or local_ip()
        self.patterns = [p.strip().lower() for p in args.spoof.split(",") if p.strip()]
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log = Log(os.path.join(args.logdir, f"podsluch_{stamp}.jsonl"))
        self.upstream_host = args.upstream_host
        self.upstream_ip = None
        self.upstream_pref = False
        self.conn_no = 0

    def should_spoof(self, name):
        return "*" in self.patterns or any(p in name for p in self.patterns)

    async def forward_dns(self, data):
        loop = asyncio.get_running_loop()
        fut = loop.create_future()

        class P(asyncio.DatagramProtocol):
            def datagram_received(self, d, a):
                if not fut.done():
                    fut.set_result(d)

        transport, _ = await loop.create_datagram_endpoint(P, remote_addr=(self.args.dns_upstream, 53))
        try:
            transport.sendto(data)
            return await asyncio.wait_for(fut, 3)
        except asyncio.TimeoutError:
            return None
        finally:
            transport.close()

    async def learn_upstream(self, name):
        """Ustal prawdziwy adres serwera producenta (przez zwykły DNS)."""
        if self.args.upstream_host:
            return
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(name, None, family=socket.AF_INET)
        except OSError as e:
            self.log.write("info", f"Nie udało się ustalić prawdziwego IP {name}: {e}", nazwa=name)
            return
        ip = infos[0][4][0]
        # W trybie '*' sterownik może pytać też o inne nazwy (np. serwer czasu). Nazwa wyglądająca
        # na serwer producenta ma pierwszeństwo i nie zostanie nadpisana przez inną.
        preferred = any(p in name for p in DEFAULT_PATTERNS.split(","))
        if self.upstream_pref and not preferred:
            self.log.write("info", f"Inna nazwa: {name} = {ip} (zostaje {self.upstream_host})",
                           nazwa=name, ip=ip)
            return
        if ip != self.upstream_ip:
            self.upstream_ip, self.upstream_host, self.upstream_pref = ip, name, preferred
            self.log.write("info", f"Prawdziwy serwer: {name} = {ip}", nazwa=name, ip=ip)

    async def resolve_upstream(self):
        if not self.upstream_ip and self.upstream_host:
            infos = await asyncio.get_running_loop().getaddrinfo(self.upstream_host, None,
                                                                 family=socket.AF_INET)
            self.upstream_ip = infos[0][4][0]
        return self.upstream_ip

    async def handle_tcp(self, reader, writer, port):
        self.conn_no += 1
        cid = self.conn_no
        peer = writer.get_extra_info("peername")[0]
        self.log.write("polaczenie", f"TCP  #{cid} {peer} -> port {port}  (NOWE POŁĄCZENIE)",
                       id=cid, klient=peer, port=port)
        up_r = up_w = None
        if not self.args.offline:
            try:
                ip = await self.resolve_upstream()
                if ip:
                    up_r, up_w = await asyncio.wait_for(asyncio.open_connection(ip, port), 10)
                    self.log.write("info", f"TCP  #{cid} połączono z prawdziwym serwerem {ip}:{port}",
                                   id=cid, ip=ip, port=port)
                else:
                    self.log.write("info", f"TCP  #{cid} nie znam jeszcze prawdziwego serwera - tylko zapis",
                                   id=cid)
            except (OSError, asyncio.TimeoutError) as e:
                self.log.write("info", f"TCP  #{cid} prawdziwy serwer niedostępny ({e}) - tylko zapis",
                               id=cid, blad=str(e))
                up_r = up_w = None

        first = [True]

        async def pump(src, dst, direction):
            try:
                while True:
                    data = await src.read(65536)
                    if not data:
                        break
                    if first[0] and direction == "ster->serw":
                        first[0] = False
                        if data[:1] == b"\x16" and data[1:2] == b"\x03":
                            self.log.write("info", f"TCP  #{cid} UWAGA: ruch szyfrowany (TLS)", id=cid)
                    self.log.write("dane", f"TCP  #{cid} {direction} {len(data):5d} B  {printable(data[:60])}",
                                   id=cid, port=port, kier=direction, dl=len(data), hex=data.hex())
                    if dst is not None:
                        dst.write(data)
                        await dst.drain()
            except (OSError, asyncio.IncompleteReadError):
                pass
            finally:
                if dst is not None:
                    try:
                        dst.close()
                    except OSError:
                        pass

        tasks = [pump(reader, up_w, "ster->serw")]
        if up_r is not None:
            tasks.append(pump(up_r, writer, "serw->ster"))
        await asyncio.gather(*tasks)
        try:
            writer.close()
        except OSError:
            pass
        self.log.write("koniec", f"TCP  #{cid} zakończone", id=cid)


def keep_awake():
    """Windows: nie usypiaj komputera, dopóki program działa (zamknięcie klapy nadal może uśpić)."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
            print("Usypianie komputera wyłączone na czas działania programu.")
        except (OSError, AttributeError):
            pass


def all_ipv4():
    try:
        ips = {i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
    except OSError:
        ips = set()
    return sorted(ip for ip in ips if not ip.startswith("127."))


async def run(args):
    app = App(args)
    loop = asyncio.get_running_loop()
    print("=" * 70)
    print(f"  ADRES TEGO KOMPUTERA (wpisz go jako DNS w sterowniku, kod 0104):  {app.my_ip}")
    print("=" * 70)
    others = [ip for ip in all_ipv4() if ip != app.my_ip]
    if others:
        print(f"  (inne karty sieciowe: {', '.join(others)} - jeśli sterownik jest w innej")
        print("   podsieci niż adres powyżej, uruchom ponownie z --ip WŁAŚCIWY_ADRES)")
    print(f"Log: {app.log.path}")
    keep_awake()
    print(f"Przekierowywane nazwy: {', '.join(app.patterns)}   (inne pytania -> {args.dns_upstream})")

    if not args.no_dns:
        try:
            await loop.create_datagram_endpoint(lambda: DnsServer(app), local_addr=(args.bind, 53))
            print("DNS: nasłuch UDP 53 - OK")
        except OSError as e:
            print(f"DNS: nie mogę otworzyć portu 53 ({e}).\n"
                  "     Windows: uruchom jako administrator. Linux/RPi: sudo.")
            return

    if hasattr(os, "getuid"):
        try:
            import resource
            soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
            resource.setrlimit(resource.RLIMIT_NOFILE, (hard, hard))
        except (ImportError, ValueError, OSError):
            pass

    ok, failed = [], []
    for port in parse_ports(args.ports):
        try:
            await asyncio.start_server(lambda r, w, p=port: app.handle_tcp(r, w, p), args.bind, port)
            ok.append(port)
        except OSError:
            failed.append(port)
    print(f"TCP: nasłuch na {len(ok)} portach" + (f" (zajęte/niedostępne: {len(failed)})" if failed else ""))
    app.log.write("start", ip=app.my_ip, porty=ok, porty_bledy=failed, wzorce=app.patterns)
    print("Czekam na sterownik... (Ctrl+C kończy)\n")
    await asyncio.Event().wait()


# ---------------------------------------------------------------- podgląd logu

def show(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            t = r["t"][11:23]
            if r["typ"] == "dane":
                data = bytes.fromhex(r["hex"])
                arrow = ">>" if r["kier"] == "ster->serw" else "<<"
                print(f"{t} #{r['id']} {arrow} {r['kier']} {r['dl']} B")
                for i in range(0, len(data), 16):
                    chunk = data[i:i + 16]
                    print(f"      {i:04x}  {chunk.hex(' '):<47}  {printable(chunk)}")
            elif r["typ"] == "dns":
                print(f"{t} DNS {r['nazwa']}" + ("  [przekierowano]" if r.get("przekierowano") else ""))
            elif r["typ"] == "polaczenie":
                print(f"{t} #{r['id']} połączenie {r['klient']} -> port {r['port']}")
            elif r["typ"] == "info":
                print(f"{t} info: {r.get('opis', r)}")


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "pokaz":
        show(sys.argv[2])
        return
    ap = argparse.ArgumentParser(description="Podsłuch protokołu sterownik <-> ekotlownia.pl")
    ap.add_argument("--spoof", default=DEFAULT_PATTERNS,
                    help="fragmenty nazw do przekierowania, po przecinku; '*' = wszystkie")
    ap.add_argument("--ports", default=DEFAULT_PORTS, help="porty TCP, np. 80,443,8000-8100 lub 1-65535")
    ap.add_argument("--dns-upstream", default="8.8.8.8", help="prawdziwy DNS dla pozostałych pytań")
    ap.add_argument("--upstream-host", help="ręcznie podany prawdziwy serwer (nazwa lub IP)")
    ap.add_argument("--ip", help="adres tego komputera (domyślnie wykrywany)")
    ap.add_argument("--bind", default="0.0.0.0", help="adres nasłuchu (domyślnie wszystkie)")
    ap.add_argument("--offline", action="store_true", help="nie łącz się z prawdziwym serwerem")
    ap.add_argument("--no-dns", action="store_true", help="bez serwera DNS (np. gdy przekierowujesz w routerze)")
    ap.add_argument("--logdir", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "logi"))
    args = ap.parse_args()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nKoniec.")


if __name__ == "__main__":
    main()
