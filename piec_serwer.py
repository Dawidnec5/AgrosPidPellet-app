#!/usr/bin/env python3
"""piec_serwer - własny serwer dla sterownika ArgosPid Plus (Technix) zamiast ekotlownia.pl.

Sterownik (po ustawieniu w nim DNS = ten komputer) wysyła co ~27 s swoje dane na ten
komputer. Serwer:
  - zapisuje pomiary (temperatury, opał, spalanie) do bazy SQLite -> wykresy,
  - pokazuje stronę http://<adres-komputera>/ - otwierasz ją na telefonie w domowym Wi-Fi,
  - pozwala zmieniać nastawy (temperatury, tryby pomp, CWU...) - zmiana trafia do
    sterownika w odpowiedzi na jego następne zapytanie, tak samo jak robi to ekotlownia.pl.

Tryby:
  --tryb proxy  (domyślny) dane idą też do ekotlownia.pl - strona producenta dalej działa
  --tryb sam    tylko ten komputer, bez ekotlownia.pl (bez abonamentu)

Tylko biblioteka standardowa Pythona 3.8+.
"""
import argparse
import asyncio
import datetime
import json
import os
import sqlite3
import sys
import time
from urllib.parse import parse_qsl, urlsplit, parse_qs

import ekoproxy as ek

HERE = os.path.dirname(os.path.abspath(__file__))
CTRL_HOST = "test5.ekotlownia.pl"

# Kolejność kluczy w odpowiedzi z nastawami - skopiowana z odpowiedzi ekotlownia.pl (18.11.2026).
SETTINGS_ORDER = ("B2 B3 C1 C2 C3 C4 C5 C7 C9 E1 E2 E3 E4 E5 F2 F3 F4 G2 G3 G4 G5 H2 H3 H4 H5 H6 H7 "
                  "I2 I3 I4 J1 J2 J3 J6 J7 J8 JC JD JE J11 J12 J13 J17 J18 J19 L2 L3 J1C J1D J1E "
                  "K3 K4 K5").split()

# Pola, które ekotlownia.pl w odpowiedzi zawsze wysyła jako 0 (sterownik je ignoruje). Znaczenie
# nieznane, więc wysyłamy dokładnie to samo co oryginalny serwer.
STALE_W_ODPOWIEDZI = {"L2": "0", "L3": "0"}

TRYB3 = {0: "Stały, wyłączony", 1: "Stały, włączony", 2: "Regulator"}

# Pomiary potwierdzone porównaniem z ekotlownia.pl: klucz -> (nazwa, mnożnik, jednostka)
POMIARY = {
    "A2": ("Kocioł", 0.1, "°C"),
    "A3": ("CWU", 0.1, "°C"),
    "A15": ("Spaliny", 1, "°C"),
    "A4": ("Podajnik", 0.1, "°C"),
    "A5": ("Zawór", 0.1, "°C"),
    "A6": ("Opał w zbiorniku", 1, "kg"),
    "AA": ("Spalanie 24 h", 0.1, "kg"),
}
ZNANE_A = set(POMIARY) | {"A0", "A7", "A8", "A12"}
DNI = ["niedziela", "poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela"]

# Nastawy, które wolno zmieniać: klucz -> (grupa, nazwa, min, max, opcje|None, jednostka)
# Zakresy i opcje skopiowane z formularza ekotlownia.pl.
NASTAWY = {
    "B3": ("Kocioł", "Temperatura kotła - dzień", 20, 79, None, "°C"),
    "B2": ("Kocioł", "Temperatura kotła - noc", 20, 79, None, "°C"),
    "G2": ("CWU", "Tryb pracy", 0, 2, TRYB3, ""),
    "G3": ("CWU", "Temperatura zadana", 41, 80, None, "°C"),
    "G4": ("CWU", "Histereza", 2, 40, None, "°C"),
    "G5": ("CWU", "Priorytet", 0, 9, {0: "WYŁ.", **{i: f"+{i} °C" for i in range(1, 10)}}, ""),
    "F2": ("Pompa C.O.", "Tryb pracy", 0, 2, TRYB3, ""),
    "F3": ("Pompa C.O.", "Temperatura włączenia", 10, 60, None, "°C"),
    "F4": ("Pompa C.O.", "Histereza", 2, 9, None, "°C"),
    "H2": ("Pompa cyrkulacji", "Tryb pracy", 0, 2,
           {0: "Stały, wyłączony", 1: "Stały, włączony", 2: "Cykliczny"}, ""),
    "H3": ("Pompa cyrkulacji", "Temperatura C.O.", 10, 70, None, "°C"),
    "H4": ("Pompa cyrkulacji", "Temperatura CWU", 10, 70, None, "°C"),
    "H5": ("Pompa cyrkulacji", "Histereza", 2, 9, None, "°C"),
    "H6": ("Pompa cyrkulacji", "Czas pracy", 1, 99, None, ""),
    "H7": ("Pompa cyrkulacji", "Czas przerwy", 1, 99, None, ""),
    "I2": ("Zawór", "Tryb pracy", 0, 1, {0: "Stały, wyłączony", 1: "Mieszacz"}, ""),
    "I3": ("Zawór", "Temperatura zadana - dzień", 20, 70, None, "°C"),
    "I4": ("Zawór", "Temperatura zadana - noc", 20, 70, None, "°C"),
    "C1": ("Podawanie i dmuchawa", "Czas podawania", 5, 20, None, "s"),
    "C2": ("Podawanie i dmuchawa", "Czas przerwy", 3, 220, None, "s"),
    "C3": ("Podawanie i dmuchawa", "Obroty maksymalne", 1, 98, None, ""),
    "C4": ("Podawanie i dmuchawa", "Obroty minimalne", 2, 80, None, ""),
    "C5": ("Podawanie i dmuchawa", "Moc minimalna", 3, 40, None, ""),
}
MAX_PROB = 3          # ile razy wysłać zmianę, zanim uznamy ją za nieudaną
SZYBKO_PRZEZ = 60     # s: po otwarciu strony sterownik raportuje co ~7 s zamiast ~27 s


def http_response(body: str) -> bytes:
    b = body.encode()
    return (b"HTTP/1.0 200 OK\r\nContent-Length: %d\r\nContent-Type: text/html; charset=UTF-8\r\n\r\n"
            % len(b)) + b


class Piec(ek.App):
    def __init__(self, args):
        super().__init__(args, prefix="serwer")
        self.db = sqlite3.connect(args.baza)
        self.db.execute("CREATE TABLE IF NOT EXISTS pomiary (ts INTEGER, dane TEXT)")
        self.db.execute("CREATE INDEX IF NOT EXISTS pomiary_ts ON pomiary(ts)")
        self.db.execute("CREATE TABLE IF NOT EXISTS ustawienia (klucz TEXT PRIMARY KEY, wartosc TEXT)")
        self.db.commit()
        row = self.db.execute("SELECT ts, dane FROM pomiary ORDER BY ts DESC LIMIT 1").fetchone()
        self.state, self.state_ts = (json.loads(row[1]), row[0]) if row else ({}, 0)
        self.extra = {"A36": "0", "A37": "15"}  # ostatnie wartości od ekotlownia.pl
        for k, v in self.db.execute("SELECT klucz, wartosc FROM ustawienia"):
            if k in self.extra:
                self.extra[k] = v
        self.pending = {}   # klucz -> {"wartosc": int, "proby": int}
        self.history = []   # ostatnie zdarzenia dla strony
        self.viewer_ts = 0

    def event(self, msg, **kw):
        self.log.write("info", msg, **kw)
        self.history.insert(0, {"t": ek.now()[11:19], "msg": msg})
        del self.history[30:]

    # ------------------------------------------------------------ sterownik
    async def controller(self, head: bytes, body: bytes):
        data = dict(parse_qsl(body.decode("latin1").strip()))
        if not data.get("A0"):
            return http_response("OK\n")
        now = int(time.time())
        self.state, self.state_ts = data, now
        self.db.execute("INSERT INTO pomiary VALUES (?, ?)", (now, json.dumps(data)))
        self.db.commit()
        self.check_pending(data)

        upstream = None
        if self.args.tryb == "proxy":
            upstream = await self.forward(head, body)
            if upstream:
                ub = upstream.split(b"\r\n\r\n", 1)[-1].decode("latin1")
                for line in ub.split("\n"):
                    k, _, v = line.partition("=")
                    if k in self.extra and v and self.extra[k] != v:
                        self.extra[k] = v
                        self.db.execute("INSERT OR REPLACE INTO ustawienia VALUES (?, ?)", (k, v))
                        self.db.commit()
                if "\nB2=" in ub and not self.pending:
                    self.event("Zmiana nastaw z ekotlownia.pl - przekazano do sterownika")
                    return upstream
        return http_response(self.response_body())

    def fast(self):
        return time.time() - self.viewer_ts < SZYBKO_PRZEZ

    def response_body(self):
        lines = ["OK", f"A35={'8' if self.fast() or self.pending else '28'}", f"A36={self.extra['A36']}"]
        if self.pending:
            for k in SETTINGS_ORDER:
                if k in STALE_W_ODPOWIEDZI:
                    lines.append(f"{k}={STALE_W_ODPOWIEDZI[k]}")
                elif k in self.pending:
                    lines.append(f"{k}={self.pending[k]['wartosc']:x}")
                elif k in self.state:
                    lines.append(f"{k}={self.state[k].strip().lower()}")
            for k, p in self.pending.items():
                p["proby"] += 1
            self.log.write("wyslano", zmiany={k: p["wartosc"] for k, p in self.pending.items()})
        else:
            lines.append(f"A37={self.extra['A37']}")
        return "\n".join(lines) + "\n"

    def check_pending(self, data):
        for k in list(self.pending):
            p = self.pending[k]
            try:
                cur = int(data.get(k, "x").strip(), 16)
            except ValueError:
                cur = None
            name = f"{NASTAWY[k][0]}: {NASTAWY[k][1]}"
            if cur == p["wartosc"]:
                self.event(f"✓ Sterownik potwierdził: {name} = {self.fmt(k, cur)}", klucz=k, wartosc=cur)
                del self.pending[k]
            elif p["proby"] >= MAX_PROB:
                self.event(f"✗ Sterownik NIE przyjął zmiany: {name} (dalej {self.fmt(k, cur)})",
                           klucz=k, wartosc=p["wartosc"])
                del self.pending[k]

    async def forward(self, head, body):
        try:
            ip = await self.resolve_upstream()
            r, w = await asyncio.wait_for(asyncio.open_connection(ip, 80), 8)
            w.write(head + body)
            await w.drain()
            resp = await asyncio.wait_for(r.read(65536 * 4), 10)
            w.close()
            return resp
        except (OSError, asyncio.TimeoutError, TypeError, IndexError) as e:
            self.log.write("info", f"ekotlownia.pl niedostępna ({e}) - odpowiadam sam")
            return None

    # ------------------------------------------------------------ dane dla strony
    @staticmethod
    def fmt(k, v):
        if v is None:
            return "?"
        _, _, _, _, opts, unit = NASTAWY[k]
        return opts.get(v, str(v)) if opts else f"{v} {unit}".strip()

    def val(self, k):
        try:
            return int(self.state[k].strip(), 16)
        except (KeyError, ValueError):
            return None

    def api_stan(self):
        self.viewer_ts = time.time()
        pomiary = []
        for k, (name, mult, unit) in POMIARY.items():
            v = self.val(k)
            pomiary.append({"klucz": k, "nazwa": name, "jedn": unit,
                            "wartosc": None if v is None else round(v * mult, 1)})
        d, h = self.val("A7"), self.val("A8")
        opal_do = f"{DNI[d]} godz. {h}" if d is not None and h is not None and 0 <= d <= 7 else None
        nastawy = []
        for k, (grp, name, lo, hi, opts, unit) in NASTAWY.items():
            nastawy.append({"klucz": k, "grupa": grp, "nazwa": name, "min": lo, "max": hi,
                            "opcje": opts, "jedn": unit, "wartosc": self.val(k),
                            "oczekuje": self.pending.get(k, {}).get("wartosc")})
        nieznane = {k: self.val(k) for k in self.state if k.startswith("A") and k not in ZNANE_A}
        return {"czas": self.state_ts, "teraz": int(time.time()), "tryb": self.args.tryb,
                "pomiary": pomiary, "opal_do": opal_do, "nastawy": nastawy,
                "nieznane": nieznane, "zdarzenia": self.history}

    def api_historia(self, godz):
        od = int(time.time() - godz * 3600)
        rows = self.db.execute("SELECT ts, dane FROM pomiary WHERE ts >= ? ORDER BY ts", (od,)).fetchall()
        step = max(1, len(rows) // 500)
        out = {"ts": [], "A2": [], "A3": [], "A15": []}
        for ts, dane in rows[::step]:
            d = json.loads(dane)
            out["ts"].append(ts)
            for k in ("A2", "A3", "A15"):
                try:
                    out[k].append(round(int(d[k].strip(), 16) * POMIARY[k][1], 1))
                except (KeyError, ValueError):
                    out[k].append(None)
        return out

    def api_ustaw(self, payload):
        k = payload.get("klucz")
        if k not in NASTAWY:
            return 400, {"blad": "Tej nastawy nie można zmieniać."}
        try:
            v = int(payload.get("wartosc"))
        except (TypeError, ValueError):
            return 400, {"blad": "Zła wartość."}
        grp, name, lo, hi, opts, unit = NASTAWY[k]
        if not lo <= v <= hi or (opts and v not in opts):
            return 400, {"blad": f"Dozwolony zakres: {lo}-{hi}."}
        if not self.state:
            return 409, {"blad": "Sterownik jeszcze się nie połączył."}
        if self.val(k) == v:
            self.pending.pop(k, None)
            return 200, {"ok": True, "info": "Bez zmian."}
        self.pending[k] = {"wartosc": v, "proby": 0}
        self.event(f"Zlecono: {grp}: {name} {self.fmt(k, self.val(k))} → {self.fmt(k, v)}", klucz=k, wartosc=v)
        return 200, {"ok": True}

    # ------------------------------------------------------------ HTTP
    async def handle_http(self, reader, writer):
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 15)
            lines = head.decode("latin1").split("\r\n")
            method, target = lines[0].split(" ")[:2]
            headers = {}
            for line in lines[1:]:
                k, _, v = line.partition(":")
                headers[k.strip().lower()] = v.strip()
            n = int(headers.get("content-length") or 0)
            body = await asyncio.wait_for(reader.readexactly(n), 15) if n else b""
            url = urlsplit(target)
            if url.path.startswith("/sz/"):
                resp = await self.controller(head, body)
            else:
                resp = self.ui(method, url, body)
            writer.write(resp)
            await writer.drain()
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError,
                ValueError, OSError):
            pass
        finally:
            try:
                writer.close()
            except OSError:
                pass

    def ui(self, method, url, body):
        if url.path == "/" or url.path == "/index.html":
            return self.raw(200, "text/html; charset=utf-8", PAGE.encode())
        if url.path == "/api/stan":
            return self.json(200, self.api_stan())
        if url.path == "/api/historia":
            godz = float(parse_qs(url.query).get("h", ["24"])[0])
            return self.json(200, self.api_historia(min(max(godz, 0.1), 24 * 31)))
        if url.path == "/api/ustaw" and method == "POST":
            try:
                payload = json.loads(body or b"{}")
            except ValueError:
                return self.json(400, {"blad": "Zły format."})
            return self.json(*self.api_ustaw(payload))
        return self.raw(404, "text/plain; charset=utf-8", b"404")

    @staticmethod
    def raw(code, ctype, data):
        reason = {200: "OK", 400: "Bad Request", 404: "Not Found", 409: "Conflict"}.get(code, "OK")
        return (f"HTTP/1.1 {code} {reason}\r\nContent-Type: {ctype}\r\nContent-Length: {len(data)}\r\n"
                "Cache-Control: no-store\r\nConnection: close\r\n\r\n").encode() + data

    def json(self, code, obj):
        return self.raw(code, "application/json; charset=utf-8", json.dumps(obj, ensure_ascii=False).encode())


async def run(args):
    app = Piec(args)
    loop = asyncio.get_running_loop()
    print("=" * 70)
    print(f"  ADRES TEGO KOMPUTERA (DNS w sterowniku, kod 0104):  {app.my_ip}")
    print(f"  APLIKACJA - otwórz na telefonie w domowym Wi-Fi:      http://{app.my_ip}/")
    print("=" * 70)
    print(f"Tryb: {'proxy - dane idą też do ekotlownia.pl' if args.tryb == 'proxy' else 'sam - bez ekotlownia.pl'}")
    print(f"Baza: {args.baza}\nLog:  {app.log.path}")
    ek.keep_awake()
    if not args.no_dns:
        try:
            ek.DnsServer(app, loop, args.bind).start()
        except OSError as e:
            print(f"DNS: nie mogę otworzyć portu 53 ({e}). Uruchom jako administrator / sudo.")
            return
        ok, err = await loop.run_in_executor(None, ek.dns_selftest, app.my_ip)
        print("DNS: OK" if ok else f"DNS: BŁĄD autotestu ({err})")
    try:
        await asyncio.start_server(app.handle_http, args.bind, args.port)
    except OSError as e:
        print(f"HTTP: nie mogę otworzyć portu {args.port} ({e}). Czy coś innego go używa?")
        return
    print(f"HTTP: port {args.port} - OK\nCzekam na sterownik... (Ctrl+C kończy)\n")
    await asyncio.Event().wait()


def main():
    ap = argparse.ArgumentParser(description="Własny serwer dla sterownika ArgosPid Plus")
    ap.add_argument("--tryb", choices=["proxy", "sam"], default="proxy")
    ap.add_argument("--ip", help="adres tego komputera (domyślnie wykrywany)")
    ap.add_argument("--bind", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=80)
    ap.add_argument("--no-dns", action="store_true")
    ap.add_argument("--dns-upstream", default="8.8.8.8")
    ap.add_argument("--upstream-host", default=CTRL_HOST, help="prawdziwy serwer (tryb proxy)")
    ap.add_argument("--baza", default=os.path.join(HERE, "piec.db"))
    ap.add_argument("--logdir", default=os.path.join(HERE, "logi"))
    args = ap.parse_args()
    args.spoof = ek.DEFAULT_PATTERNS
    args.offline = args.tryb == "sam"
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nKoniec.")


PAGE = r"""<!doctype html>
<html lang="pl"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#1b1f24">
<title>Mój piec</title>
<style>
:root{--bg:#f4f5f7;--card:#fff;--fg:#1b1f24;--mut:#69707a;--line:#e3e5e8;--acc:#d9480f;--ok:#2b8a3e;--warn:#e67700;--bad:#c92a2a;
--c1:#d9480f;--c2:#1c7ed6;--c3:#7048e8}
@media (prefers-color-scheme:dark){:root{--bg:#121417;--card:#1d2126;--fg:#e9ecef;--mut:#9aa1a9;--line:#2c3138;--acc:#ff8a4c;--c1:#ff8a4c;--c2:#4dabf7;--c3:#9775fa}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.4 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
header{position:sticky;top:0;z-index:2;background:var(--bg);padding:14px 16px 8px;display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
h1{font-size:20px;margin:0}#status{font-size:13px;color:var(--mut)}#status b{color:var(--ok)}#status.stary b{color:var(--bad)}
main{max-width:900px;margin:0 auto;padding:0 16px 40px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px}
.tile .n{font-size:13px;color:var(--mut)}.tile .v{font-size:28px;font-weight:600;font-variant-numeric:tabular-nums}.tile .v small{font-size:14px;color:var(--mut);font-weight:400}
.tile.main{border-color:var(--acc)}
h2{font-size:16px;margin:22px 0 8px}
.tabs button,.btn{border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:8px;padding:6px 12px;font:inherit;cursor:pointer}
.tabs button.on{background:var(--fg);color:var(--bg)}
svg{width:100%;height:220px;display:block}.leg{display:flex;gap:14px;font-size:13px;color:var(--mut);margin-top:6px}.leg i{display:inline-block;width:12px;height:3px;margin-right:5px;vertical-align:middle}
.grp{margin-bottom:10px}.grp h3{font-size:14px;margin:0 0 6px;color:var(--mut);font-weight:600}
.row{display:flex;align-items:center;gap:8px;padding:8px 0;border-top:1px solid var(--line)}.row:first-of-type{border-top:0}
.row label{flex:1}.row select{font:inherit;padding:6px;border-radius:8px;border:1px solid var(--line);background:var(--bg);color:var(--fg);max-width:48%}
.pend{font-size:12px;color:var(--warn)}
details summary{cursor:pointer;color:var(--mut)}
#ev{font-size:13px;color:var(--mut);margin:0;padding-left:18px}
#toast{position:fixed;left:16px;right:16px;bottom:16px;max-width:600px;margin:auto;background:var(--fg);color:var(--bg);padding:10px 14px;border-radius:10px;display:none}
.note{font-size:12px;color:var(--mut)}
</style></head><body>
<header><h1>🔥 Mój piec</h1><span id="status">łączenie…</span></header>
<main>
<div class="grid" id="tiles"></div>
<p class="note" id="opal"></p>
<h2>Wykres</h2>
<div class="card"><div class="tabs" id="rng"><button data-h="1">1 h</button> <button data-h="6">6 h</button> <button data-h="24" class="on">24 h</button> <button data-h="168">7 dni</button></div>
<svg id="ch" viewBox="0 0 600 220" preserveAspectRatio="none"></svg>
<div class="leg"><span><i style="background:var(--c1)"></i>Kocioł</span><span><i style="background:var(--c2)"></i>CWU</span><span><i style="background:var(--c3)"></i>Spaliny</span></div></div>
<h2>Nastawy</h2>
<p class="note">Zmiana trafia do sterownika przy jego następnym połączeniu (kilka sekund) i jest potwierdzana.</p>
<div id="set"></div>
<h2>Zdarzenia</h2><div class="card"><ul id="ev"></ul></div>
<h2></h2><details class="card"><summary>Inne wartości ze sterownika (jeszcze nienazwane)</summary><p class="note" id="unk"></p></details>
</main><div id="toast"></div>
<script>
let H=24, sel={};
const $=s=>document.querySelector(s);
function toast(t){const e=$('#toast');e.textContent=t;e.style.display='block';clearTimeout(e._t);e._t=setTimeout(()=>e.style.display='none',3500)}
async function stan(){
 let d; try{d=await (await fetch('/api/stan')).json()}catch(e){$('#status').textContent='brak połączenia z serwerem';return}
 const age=d.czas?d.teraz-d.czas:null, st=$('#status');
 st.className=age===null||age>120?'stary':'';
 st.innerHTML=age===null?'<b>●</b> sterownik jeszcze się nie połączył':`<b>●</b> odczyt ${age<60?age+' s':Math.round(age/60)+' min'} temu · tryb ${d.tryb}`;
 $('#tiles').innerHTML=d.pomiary.map((p,i)=>`<div class="card tile${i<2?' main':''}"><div class="n">${p.nazwa}</div><div class="v">${p.wartosc===null?'–':p.wartosc}<small> ${p.jedn}</small></div></div>`).join('');
 $('#opal').textContent=d.opal_do?`Opał wystarczy do: ${d.opal_do}`:'';
 const box=$('#set'); const groups={};
 d.nastawy.forEach(n=>(groups[n.grupa]=groups[n.grupa]||[]).push(n));
 if(!box.dataset.built||document.activeElement.tagName!=='SELECT'){
  box.innerHTML=Object.entries(groups).map(([g,list])=>`<div class="card grp"><h3>${g}</h3>${list.map(n=>{
    const opts=[];for(let v=n.min;v<=n.max;v++){if(n.opcje&&!(v in n.opcje))continue;opts.push(`<option value="${v}"${v===n.wartosc?' selected':''}>${n.opcje?n.opcje[v]:v+(n.jedn?' '+n.jedn:'')}</option>`)}
    const pend=n.oczekuje!==null&&n.oczekuje!==undefined?`<div class="pend">⏳ wysyłam: ${n.opcje?n.opcje[n.oczekuje]:n.oczekuje+' '+n.jedn}</div>`:'';
    return `<div class="row"><label for="s_${n.klucz}">${n.nazwa}${pend}</label><select id="s_${n.klucz}" data-k="${n.klucz}"${n.wartosc===null?' disabled':''}>${n.wartosc===null?'<option>–</option>':''}${opts.join('')}</select></div>`}).join('')}</div>`).join('');
  box.dataset.built=1;
 }
 $('#ev').innerHTML=d.zdarzenia.length?d.zdarzenia.map(e=>`<li>${e.t} ${e.msg}</li>`).join(''):'<li>brak</li>';
 $('#unk').textContent=Object.entries(d.nieznane).map(([k,v])=>k+'='+v).join(', ');
}
document.addEventListener('change',async e=>{
 const k=e.target.dataset.k;if(!k)return;
 const label=e.target.closest('.row').querySelector('label').firstChild.textContent;
 const txt=e.target.options[e.target.selectedIndex].text;
 if(!confirm(`Zmienić „${label}” na ${txt}?`)){stan();return}
 const r=await fetch('/api/ustaw',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({klucz:k,wartosc:+e.target.value})});
 const j=await r.json(); toast(j.ok?(j.info||'Wysłano - czekam na potwierdzenie sterownika'):j.blad); e.target.blur(); stan();
});
async function wykres(){
 const d=await (await fetch('/api/historia?h='+H)).json(), svg=$('#ch');
 if(d.ts.length<2){svg.innerHTML='<text x="300" y="110" text-anchor="middle" fill="currentColor" opacity=".5">za mało danych</text>';return}
 const all=[...d.A2,...d.A3,...d.A15].filter(v=>v!==null);let lo=Math.floor(Math.min(...all)/10)*10,hi=Math.ceil(Math.max(...all)/10)*10;if(hi-lo<20)hi=lo+20;
 const t0=d.ts[0],t1=d.ts[d.ts.length-1],X=t=>(t-t0)/(t1-t0||1)*560+34,Y=v=>200-(v-lo)/(hi-lo)*185;
 let g='';for(let v=lo;v<=hi;v+=10){g+=`<line x1="34" x2="600" y1="${Y(v)}" y2="${Y(v)}" stroke="currentColor" opacity=".12"/><text x="0" y="${Y(v)+4}" font-size="11" fill="currentColor" opacity=".6">${v}°</text>`}
 const line=(k,c)=>{let p='';d[k].forEach((v,i)=>{if(v!==null)p+=(p?'L':'M')+X(d.ts[i]).toFixed(1)+','+Y(v).toFixed(1)});return `<path d="${p}" fill="none" stroke="var(${c})" stroke-width="2" vector-effect="non-scaling-stroke"/>`};
 const f=t=>{const x=new Date(t*1000);return H>24?x.toLocaleDateString('pl',{day:'numeric',month:'numeric'}):x.toLocaleTimeString('pl',{hour:'2-digit',minute:'2-digit'})};
 g+=`<text x="34" y="216" font-size="11" fill="currentColor" opacity=".6">${f(t0)}</text><text x="600" y="216" font-size="11" text-anchor="end" fill="currentColor" opacity=".6">${f(t1)}</text>`;
 svg.innerHTML=g+line('A15','--c3')+line('A3','--c2')+line('A2','--c1');
}
$('#rng').onclick=e=>{if(!e.target.dataset.h)return;H=+e.target.dataset.h;document.querySelectorAll('#rng button').forEach(b=>b.classList.toggle('on',b===e.target));wykres()};
stan();wykres();setInterval(stan,5000);setInterval(wykres,60000);
</script></body></html>"""

if __name__ == "__main__":
    main()
