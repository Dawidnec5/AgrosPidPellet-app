# Protokół ArgosPid Plus ↔ ekotlownia.pl (z podsłuchu 18.11.2026)

Stan: **wstępny**. Format jest pewny, a znaczenie pól to hipotezy, dopóki nie porównamy ich
z ekranem sterownika.

## Transport

- DNS: sterownik pyta o `test5.ekotlownia.pl` (serwer 109.95.148.71). Do przekierowania
  wystarczy własny DNS (kod 0104 → DNS).
- **Zwykłe HTTP/1.0 na porcie 80, bez szyfrowania i bez podpisu.** Każde zapytanie to nowe
  połączenie (`Connection: close`).
- Częstotliwość: około **27 s**. Gdy serwer odpowie `A35=8`, sterownik przechodzi na około **7 s**
  (prawdopodobnie tryb „ktoś ogląda stronę”).

## Zapytanie sterownika

```
POST /sz/ster7.php HTTP/1.0
Host: test5.ekotlownia.pl
Connection: close
Content-Type: application/x-www-form-urlencoded
Content-Length: 714

A0=<ID>&A1=7&A2=1A0&A3=1E0&...&L3=14
```

- 112 par `KLUCZ=wartość`, **wszystkie wartości szesnastkowo**.
- `A0` = ID urządzenia (to samo co na ekranie 0104, bez myślników).
- Grupa `A*` zmienia się w czasie, więc to pomiary i stany. Grupy `B*`–`L*` są stałe, więc to nastawy.
- `J*` wyglądają na **harmonogramy godzinowe**: 24 bity = 24 godziny (`FFFFFF` = cała doba,
  `1FFFE0` = 5:00–21:00, `1FF80` = 7:00–17:00).

## Odpowiedź serwera

```
HTTP/1.0 200 OK
Content-Length: 23
Content-Type: text/html; charset=UTF-8

OK
A35=28
A36=0
A37=15
```

- Treść to `OK`, a po nim linie `KLUCZ=wartość` (hex, małe litery), oddzielone `\n`.
- Zwykle są tylko `A35`, `A36` i `A37`. `A35`: `28` → wolno (27 s), `8` → szybko (7 s).
  Znaczenie `A36` i `A37` jest nieznane (`A37=15` hex = 21).
- **Zapis nastaw:** czasem serwer odsyła pełny zestaw nastaw (`B2=3b`, `C1=14` … `K5=0`,
  56 linii). Sterownik je **przyjmuje**. O 14:45:19 serwer wysłał `G2=0`, a w następnym zapytaniu
  sterownik raportuje `G2=0` i przez jeden cykl `A12=1` (prawdopodobnie potwierdzenie zmiany).
  O 14:45:55 serwer wysłał `G2=2` i sytuacja się powtórzyła.
- Serwer wysłał też `L2=0` i `L3=0`, ale sterownik ich nie zmienił (raportuje dalej 16 i 14).
  Albo są tylko do odczytu, albo sterownik odrzuca wartości spoza zakresu.

## Wartości z pierwszego zapytania (do zidentyfikowania)

| Klucz | hex | dzies. | hipoteza |
|---|---|---|---|
| A1 | 7 | 7 | stan pracy / tryb |
| A2 | 1A0–1A2 | 416–418 | temperatura ×0,1 °C? (wolno się zmienia) |
| A3 | 1E0 | 480 | temperatura ×0,1? |
| A4 | 12C | 300 | temperatura ×0,1? |
| A5 | 122→10E | 290→270 | spada co 10, spaliny lub podajnik ×0,1? |
| A6 | 26 | 38 | |
| A13 | 12B | 299 | |
| A15 | 2B/2A | 43/42 | temperatura kotła? |
| A19 | 7D | 125 | |
| B2 / B3 | 3B / 34 | 59 / 52 | temperatura zadana kotła / CWU? |
| C1–C5 | 14,4B,2E,14,14 | 20,75,46,20,20 | |
| F3 / G3 / H3 / I3 | 2E/2D/2E/23 | 46/45/46/35 | temperatury zadane obiegów? |
| F2 / G2 / H2 / I2 | 2/2/2/1 | | tryb obiegu (0/1/2)? `G2` zmieniono ze strony |
| L2 / L3 | 16 / 14 | 22 / 20 | temperatury pokojowe dzień/noc? |
