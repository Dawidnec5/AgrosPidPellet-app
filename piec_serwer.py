#!/usr/bin/env python3
"""piec_serwer - własny serwer dla sterownika ArgosPid Plus (Technix) zamiast ekotlownia.pl.

Sterownik (po ustawieniu w nim DNS = ten komputer) wysyła co ~27 s swoje dane na ten
komputer. Serwer:
  - zapisuje pomiary do bazy SQLite (wykresy, historia zdarzeń),
  - wystawia aplikację http://<adres-komputera>/ (telefon w domowym Wi-Fi / Tailscale),
  - zmienia nastawy i harmonogramy - zmiana trafia do sterownika w odpowiedzi na jego
    następne zapytanie, w tym samym formacie co z ekotlownia.pl, i jest potwierdzana.

Tryby:
  --tryb proxy  (domyślny) dane idą też do ekotlownia.pl - strona producenta dalej działa
  --tryb sam    tylko ten komputer, bez ekotlownia.pl (bez abonamentu)

Tylko biblioteka standardowa Pythona 3.8+.
"""
import argparse
import asyncio
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import sys
import time
from urllib.parse import parse_qsl, urlsplit, parse_qs

import ekoproxy as ek

HERE = os.path.dirname(os.path.abspath(__file__))
WWW = os.path.join(HERE, "www")
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
# Pompy: 0 = pracuje, 1 = stoi (odwrócona logika; github.com/ImixVega/argos-pid-esphome,
# zgodne z ekotlownia.pl z 18.11.2026)
POMPY = {"AC": "Pompa C.O.", "AD": "Pompa CWU", "AE": "Pompa cyrkulacji"}
BLEDY = {0: "OK", 1: "Błąd czujnika kotła", 2: "Błąd czujnika podajnika", 3: "Błąd czujnika CWU",
         4: "Błąd czujnika zaworu mieszającego", 5: "Błąd zapisanych ustawień", 6: "Błąd zegara RTC",
         7: "Błąd zapisanych ustawień", 8: "Piec przegrzany", 9: "Przegrzanie podajnika",
         10: "STB - zadziałało zabezpieczenie", 11: "Kocioł wygaszony", 12: "Kończy się opał w zasobniku",
         13: "Błąd synchronizacji z siecią", 14: "Otwarta klapa zasobnika", 15: "Błąd czujnika zewnętrznego",
         16: "Błąd czujnika spalin", 17: "Trwa rozpalanie/wygaszanie"}
ZNANE_A = set(POMIARY) | set(POMPY) | {"A0", "A7", "A8", "A12", "AB", "AF"}
DNI = ["niedziela", "poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela"]

# Nastawy, które wolno zmieniać: klucz -> (grupa, nazwa, min, max, opcje|None, jednostka)
# Zakresy i opcje skopiowane z formularza ekotlownia.pl.
NASTAWY = {
    "B3": ("Kocioł", "Temperatura dzienna", 20, 79, None, "°C"),
    "B2": ("Kocioł", "Temperatura nocna", 20, 79, None, "°C"),
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
    "H6": ("Pompa cyrkulacji", "Czas pracy", 1, 99, None, "min"),
    "H7": ("Pompa cyrkulacji", "Czas przerwy", 1, 99, None, "min"),
    "I2": ("Zawór mieszający", "Tryb pracy", 0, 1, {0: "Stały, wyłączony", 1: "Mieszacz"}, ""),
    "I3": ("Zawór mieszający", "Temperatura dzienna", 20, 70, None, "°C"),
    "I4": ("Zawór mieszający", "Temperatura nocna", 20, 70, None, "°C"),
    "K3": ("Lato / zima", "Tryb", 0, 2, {0: "Stały, zima", 1: "Automatyczny", 2: "Stały, lato"}, ""),
    "K4": ("Lato / zima", "Czas wymuszenia zimy", 2, 20, None, "h"),
    "K5": ("Lato / zima", "Wymuszenie zimy", 0, 1, {0: "Zatrzymane", 1: "Odliczanie"}, ""),
    "C1": ("Podawanie i dmuchawa", "Czas podawania", 5, 20, None, "s"),
    "C2": ("Podawanie i dmuchawa", "Czas przerwy", 3, 220, None, "s"),
    "C3": ("Podawanie i dmuchawa", "Obroty maksymalne", 1, 98, None, "%"),
    "C4": ("Podawanie i dmuchawa", "Obroty minimalne", 2, 80, None, "%"),
    "C5": ("Podawanie i dmuchawa", "Moc minimalna", 3, 40, None, "%"),
}
# Harmonogramy: 24 bity = godziny 0-23 (bit 0 = 0:00-1:00), potwierdzone wartościami ze strony.
HARMONOGRAMY = {
    "kociol": ("Kocioł", "zaznaczone = temperatura dzienna", ["J1", "J2", "J3"]),
    "co": ("Pompa C.O.", "zaznaczone = pompa może pracować", ["J6", "J7", "J8"]),
    "cwu": ("CWU", "zaznaczone = grzanie CWU dozwolone", ["JC", "JD", "JE"]),
    "zawor": ("Zawór mieszający", "zaznaczone = temperatura dzienna", ["J11", "J12", "J13"]),
    "cyrkulacja": ("Pompa cyrkulacji", "zaznaczone = pompa może pracować", ["J17", "J18", "J19"]),
}
for _strefa, (_n, _o, _keys) in HARMONOGRAMY.items():
    for _k, _dzien in zip(_keys, ("pon-pt", "sobota", "niedziela")):
        NASTAWY[_k] = ("Harmonogram " + _n, _dzien, 0, 0xFFFFFF, None, "maska")

MAX_PROB = 3          # ile razy wysłać zmianę, zanim uznamy ją za nieudaną
SZYBKO_PRZEZ = 60     # s: gdy ktoś ogląda aplikację, sterownik raportuje co ~7 s zamiast ~27 s
ZAPIS_CO = 55         # s: jak często zapisywać pomiar do bazy (wykresy)
TRZYMAJ_DNI = 400     # tyle dni historii zostaje w bazie
STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/index.html": ("index.html", "text/html; charset=utf-8"),
          "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
          "/ikona.svg": ("ikona.svg", "image/svg+xml"),
          "/ikona-180.png": ("ikona-180.png", "image/png")}


def http_response(body: str) -> bytes:
    b = body.encode()
    return (b"HTTP/1.0 200 OK\r\nContent-Length: %d\r\nContent-Type: text/html; charset=UTF-8\r\n\r\n"
            % len(b)) + b


def godziny(mask):
    """Maska 24 bitów -> czytelne przedziały, np. '5:00-21:00'."""
    runs, h = [], 0
    while h < 24:
        if mask >> h & 1:
            a = h
            while h < 24 and mask >> h & 1:
                h += 1
            runs.append(f"{a}:00-{h}:00")
        h += 1
    return ", ".join(runs) if runs else "wyłączone"


def hexint(v):
    try:
        return int(str(v).strip(), 16)
    except ValueError:
        return None


class Piec(ek.App):
    def __init__(self, args):
        super().__init__(args, prefix="serwer")
        self.db = sqlite3.connect(args.baza)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS pomiary (ts INTEGER, dane TEXT);
            CREATE INDEX IF NOT EXISTS pomiary_ts ON pomiary(ts);
            CREATE TABLE IF NOT EXISTS ustawienia (klucz TEXT PRIMARY KEY, wartosc TEXT);
            CREATE TABLE IF NOT EXISTS zdarzenia (ts INTEGER, typ TEXT, msg TEXT);""")
        self.db.commit()
        self.extra = {"A36": "0", "A37": "15"}  # ostatnie wartości od ekotlownia.pl
        self.state, self.state_ts = {}, 0
        for k, v in self.db.execute("SELECT klucz, wartosc FROM ustawienia"):
            if k in self.extra:
                self.extra[k] = v
            elif k == "ostatni_stan":
                d = json.loads(v)
                self.state, self.state_ts = d["dane"], d["ts"]
        self.pending = {}   # klucz -> {"wartosc": int, "proby": int}
        self.viewer_ts = 0
        self.saved_ts = 0
        self.last_alarm = hexint(self.state.get("AB", "0")) or 0
        self.bad_pw = 0
        self.db.execute("DELETE FROM pomiary WHERE ts < ?", (int(time.time()) - TRZYMAJ_DNI * 86400,))
        self.db.commit()

    # ------------------------------------------------------------ pomocnicze
    def setting(self, k, v=None):
        if v is None:
            row = self.db.execute("SELECT wartosc FROM ustawienia WHERE klucz=?", (k,)).fetchone()
            return row[0] if row else None
        self.db.execute("INSERT OR REPLACE INTO ustawienia VALUES (?, ?)", (k, v))
        self.db.commit()

    def event(self, msg, typ="info", **kw):
        self.log.write("info", msg, **kw)
        self.db.execute("INSERT INTO zdarzenia VALUES (?, ?, ?)", (int(time.time()), typ, msg))
        self.db.commit()

    def val(self, k):
        return hexint(self.state[k]) if k in self.state else None

    @staticmethod
    def fmt(k, v):
        if v is None:
            return "?"
        grp, name, lo, hi, opts, unit = NASTAWY[k]
        if unit == "maska":
            return godziny(v)
        return opts.get(v, str(v)) if opts else f"{v} {unit}".strip()

    # ------------------------------------------------------------ sterownik
    async def controller(self, head: bytes, body: bytes):
        data = dict(parse_qsl(body.decode("latin1").strip()))
        if not data.get("A0"):
            return http_response("OK\n")
        data = {k: v.strip() for k, v in data.items()}
        now = int(time.time())
        self.state, self.state_ts = data, now
        if now - self.saved_ts >= ZAPIS_CO:
            self.saved_ts = now
            compact = {k: v for k, v in data.items() if k.startswith("A") and k != "A0"}
            self.db.execute("INSERT INTO pomiary VALUES (?, ?)", (now, json.dumps(compact)))
            self.setting("ostatni_stan", json.dumps({"ts": now, "dane": data}))
        self.check_pending(data)
        kod = hexint(data.get("AB", "0")) or 0
        if kod != self.last_alarm:
            if kod:
                self.event(f"⚠ Alarm Er{kod}: {BLEDY.get(kod, 'nieznany')}", "alarm")
            else:
                self.event("Alarm skasowany", "ok")
            self.last_alarm = kod

        if self.args.tryb == "proxy":
            upstream = await self.forward(head, body)
            if upstream:
                ub = upstream.split(b"\r\n\r\n", 1)[-1].decode("latin1")
                for line in ub.split("\n"):
                    k, _, v = line.partition("=")
                    if k in self.extra and v and self.extra[k] != v:
                        self.extra[k] = v
                        self.setting(k, v)
                if "\nB2=" in ub and not self.pending:
                    self.event("Zmiana nastaw z ekotlownia.pl - przekazano do sterownika", "zmiana")
                    return upstream
        return http_response(self.response_body())

    def response_body(self):
        fast = time.time() - self.viewer_ts < SZYBKO_PRZEZ or self.pending
        lines = ["OK", f"A35={'8' if fast else '28'}", f"A36={self.extra['A36']}"]
        if self.pending:
            for k in SETTINGS_ORDER:
                if k in STALE_W_ODPOWIEDZI:
                    lines.append(f"{k}={STALE_W_ODPOWIEDZI[k]}")
                elif k in self.pending:
                    lines.append(f"{k}={self.pending[k]['wartosc']:x}")
                elif k in self.state:
                    lines.append(f"{k}={self.state[k].lower()}")
            for p in self.pending.values():
                p["proby"] += 1
            self.log.write("wyslano", zmiany={k: p["wartosc"] for k, p in self.pending.items()})
        else:
            lines.append(f"A37={self.extra['A37']}")
        return "\n".join(lines) + "\n"

    def check_pending(self, data):
        for k in list(self.pending):
            p = self.pending[k]
            cur = hexint(data.get(k, "x"))
            name = f"{NASTAWY[k][0]}: {NASTAWY[k][1]}"
            if cur == p["wartosc"]:
                self.event(f"✓ {name} = {self.fmt(k, cur)}", "ok", klucz=k, wartosc=cur)
                del self.pending[k]
            elif p["proby"] >= MAX_PROB:
                self.event(f"✗ Sterownik nie przyjął: {name} (zostaje {self.fmt(k, cur)})", "blad",
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

    # ------------------------------------------------------------ API aplikacji
    def api_stan(self):
        self.viewer_ts = time.time()
        pomiary = {}
        for k, (name, mult, unit) in POMIARY.items():
            v = self.val(k)
            pomiary[k] = None if v is None else round(v * mult, 1)
        d, h = self.val("A7"), self.val("A8")
        opal_do = f"{DNI[d]}, godz. {h}" if d is not None and h is not None and 0 <= d <= 7 else None
        nastawy = {k: {"grupa": grp, "nazwa": name, "min": lo, "max": hi, "opcje": opts, "jedn": unit,
                       "wartosc": self.val(k), "oczekuje": self.pending.get(k, {}).get("wartosc")}
                   for k, (grp, name, lo, hi, opts, unit) in NASTAWY.items()}
        pompy = {k: (None if self.val(k) is None else self.val(k) == 0) for k in POMPY}
        c9, af = self.val("C9"), self.val("AF")
        kod = self.val("AB")
        return {
            "czas": self.state_ts, "teraz": int(time.time()), "tryb": self.args.tryb,
            "pomiary": pomiary, "opal_do": opal_do, "pompy": pompy,
            "wentylator": None if c9 is None or af is None else (af if c9 else 0),
            "alarm": None if not kod else {"kod": kod, "opis": BLEDY.get(kod, "Nieznany błąd")},
            "nastawy": nastawy, "harmonogramy": HARMONOGRAMY,
            "haslo": bool(self.setting("haslo")),
            "nieznane": {k: self.val(k) for k in self.state if k.startswith("A") and k not in ZNANE_A},
        }

    def api_zdarzenia(self):
        rows = self.db.execute("SELECT ts, typ, msg FROM zdarzenia ORDER BY ts DESC, rowid DESC LIMIT 100")
        return [{"ts": ts, "typ": typ, "msg": msg} for ts, typ, msg in rows]

    def api_historia(self, godz):
        od = int(time.time() - godz * 3600)
        rows = self.db.execute("SELECT ts, dane FROM pomiary WHERE ts >= ? ORDER BY ts", (od,)).fetchall()
        step = max(1, len(rows) // 600)
        keys = ("A2", "A3", "A15", "A4", "A5")
        out = {"ts": [], **{k: [] for k in keys}, "AF": [], "AC": [], "AD": []}
        for ts, dane in rows[::step]:
            d = json.loads(dane)
            out["ts"].append(ts)
            for k in keys:
                v = hexint(d.get(k, "x"))
                out[k].append(None if v is None else round(v * POMIARY[k][1], 1))
            out["AF"].append(hexint(d.get("AF", "x")))
            for k in ("AC", "AD"):
                v = hexint(d.get(k, "x"))
                out[k].append(None if v is None else int(v == 0))
        return out

    def check_pw(self, given):
        stored = self.setting("haslo")
        if not stored:
            return True
        salt, h = stored.split("$", 1)
        calc = hashlib.pbkdf2_hmac("sha256", str(given or "").encode(), bytes.fromhex(salt), 100_000).hex()
        return hmac.compare_digest(calc, h)

    def api_haslo(self, payload):
        if not self.check_pw(payload.get("stare")):
            return 403, {"blad": "Złe obecne hasło."}
        nowe = str(payload.get("nowe") or "")
        if nowe and len(nowe) < 4:
            return 400, {"blad": "Hasło musi mieć co najmniej 4 znaki."}
        if not nowe:
            self.db.execute("DELETE FROM ustawienia WHERE klucz='haslo'")
            self.db.commit()
            self.event("Hasło do zmian usunięte", "zmiana")
            return 200, {"ok": True}
        salt = secrets.token_bytes(16)
        h = hashlib.pbkdf2_hmac("sha256", nowe.encode(), salt, 100_000).hex()
        self.setting("haslo", f"{salt.hex()}${h}")
        self.event("Ustawiono hasło do zmian", "zmiana")
        return 200, {"ok": True}

    async def api_ustaw(self, payload):
        if not self.check_pw(payload.get("haslo")):
            self.bad_pw += 1
            await asyncio.sleep(min(10, self.bad_pw))   # spowolnij zgadywanie
            return 403, {"blad": "Złe hasło.", "haslo": True}
        self.bad_pw = 0
        zmiany = payload.get("zmiany")
        if zmiany is None and "klucz" in payload:
            zmiany = {payload["klucz"]: payload.get("wartosc")}
        if not isinstance(zmiany, dict) or not zmiany:
            return 400, {"blad": "Brak zmian."}
        if not self.state:
            return 409, {"blad": "Sterownik jeszcze się nie połączył."}
        ok = {}
        for k, v in zmiany.items():
            if k not in NASTAWY:
                return 400, {"blad": f"Nastawy {k} nie można zmieniać."}
            try:
                v = int(v)
            except (TypeError, ValueError):
                return 400, {"blad": f"Zła wartość dla {k}."}
            grp, name, lo, hi, opts, unit = NASTAWY[k]
            if not lo <= v <= hi or (opts and v not in opts):
                return 400, {"blad": f"{grp}: {name} - dozwolony zakres {lo}-{hi}."}
            ok[k] = v
        for k, v in ok.items():
            grp, name = NASTAWY[k][:2]
            if self.val(k) == v:
                self.pending.pop(k, None)
                continue
            self.pending[k] = {"wartosc": v, "proby": 0}
            self.event(f"Zlecono: {grp}: {name} {self.fmt(k, self.val(k))} → {self.fmt(k, v)}", "zmiana",
                       klucz=k, wartosc=v)
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
            if n > 100_000:
                raise ValueError("za duże zapytanie")
            body = await asyncio.wait_for(reader.readexactly(n), 15) if n else b""
            url = urlsplit(target)
            if url.path.startswith("/sz/"):
                resp = await self.controller(head, body)
            else:
                resp = await self.ui(method, url, body)
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

    async def ui(self, method, url, body):
        p = url.path
        if p in STATIC:
            fname, ctype = STATIC[p]
            try:
                with open(os.path.join(WWW, fname), "rb") as f:
                    return self.raw(200, ctype, f.read())
            except OSError:
                return self.raw(404, "text/plain; charset=utf-8", b"brak pliku " + fname.encode())
        if p == "/api/stan":
            return self.json(200, self.api_stan())
        if p == "/api/zdarzenia":
            return self.json(200, self.api_zdarzenia())
        if p == "/api/historia":
            try:
                godz = float(parse_qs(url.query).get("h", ["24"])[0])
            except ValueError:
                godz = 24
            return self.json(200, self.api_historia(min(max(godz, 0.1), 24 * TRZYMAJ_DNI)))
        if p in ("/api/ustaw", "/api/haslo") and method == "POST":
            try:
                payload = json.loads(body or b"{}")
                assert isinstance(payload, dict)
            except (ValueError, AssertionError):
                return self.json(400, {"blad": "Zły format."})
            if p == "/api/ustaw":
                return self.json(*(await self.api_ustaw(payload)))
            return self.json(*self.api_haslo(payload))
        return self.raw(404, "text/plain; charset=utf-8", b"404")

    @staticmethod
    def raw(code, ctype, data):
        reason = {200: "OK", 400: "Bad Request", 403: "Forbidden", 404: "Not Found",
                  409: "Conflict"}.get(code, "OK")
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


if __name__ == "__main__":
    main()
