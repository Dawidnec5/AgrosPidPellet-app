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

## Nastawy: mapa POTWIERDZONA (strona ekotlownia.pl ↔ dane sterownika)

Wartości ze strony z 18.11 zgadzają się 1:1 z polami wysyłanymi przez sterownik.

| Klucz | Znaczenie (nazwa pola na stronie) | Wartość | Zakres / opcje |
|---|---|---|---|
| B2 | temperatura kotła **nocna** (`kociol_temperatura_nocna`) | 59 | 20–79 °C |
| B3 | temperatura kotła **dzienna** (`kociol_temperatura_dzienna`) | 52 | 20–79 °C |
| C1 | czas podawania [s] | 20 | 5–20 |
| C2 | czas przerwy [s] | 75 | 3–220 |
| C3 | obroty dmuchawy maks. | 46 | 1–98 |
| C4 | obroty dmuchawy min. | 20 | 2–80 |
| C5 | moc minimalna | 20 | 3–40 |
| C6 | parametr paliwa (przesyp) | 59840 | |
| C9 | tryb palnika (prawdopodobnie) | 1 | 0 zatrzymany, 1 pracuje |
| F2 | pompa C.O. tryb pracy | 2 | 0 stały wył., 1 stały wł., 2 regulator |
| F3 | pompa C.O. temperatura włączenia | 46 | 10–60 °C |
| F4 | pompa C.O. histereza | 3 | 2–9 °C |
| G2 | CWU tryb pracy | 2 | 0 stały wył., 1 stały wł., 2 regulator |
| G3 | CWU temperatura zadana | 45 | 41–80 °C |
| G4 | CWU histereza | 8 | 2–40 °C |
| G5 | CWU priorytet | 0 | 0 wył., 1–9 = +1…+9 °C |
| H2 | pompa cyrkulacji tryb | 2 | 0 stały wył., 1 stały wł., 2 cykliczny |
| H3 | cyrkulacja: temperatura C.O. | 46 | 10–70 °C |
| H4 | cyrkulacja: temperatura CWU | 40 | 10–70 °C |
| H5 | cyrkulacja: histereza | 4 | 2–9 °C |
| H6 | cyrkulacja: czas pracy | 10 | 1–99 |
| H7 | cyrkulacja: czas przerwy | 2 | 1–99 |
| I2 | zawór tryb | 1 | 0 stały wył., 1 mieszacz |
| I3 | zawór temperatura zadana dzień | 35 | 20–70 °C |
| I4 | zawór temperatura zadana noc | 35 | 20–70 °C |
| K1–K5 | lato/zima (K4 = czas wymuszenia trybu zimowego = 2?) | 0,0,0,2,0 | do potwierdzenia |
| L0–L3 | strefa regulatora pokojowego (L0 aktywność, L1 wskaźnik?, L2/L3 22/20 °C?) | 0,1,22,20 | do potwierdzenia |

`X0` i `X1` w każdej grupie (np. `G0=1`, `G1=1`) to prawdopodobnie znaczniki „grupa obecna/aktywna”.

### Harmonogramy (24 bity = godziny 0–23, potwierdzone wartościami ze strony)

| Klucze | Strefa | pon–pt, sobota, niedziela |
|---|---|---|
| J1, J2, J3 | kocioł (dzień/noc) | 3B1C66, 3318C6, 3B18C6 |
| J6, J7, J8 | pompa C.O. | FFFFFF ×3 |
| JC, JD, JE | CWU | 1FFFE0 ×3 |
| J11, J12, J13 | zawór | 1FF80 ×3 |
| J17, J18, J19 | cyrkulacja | FFFFFF ×3 |
| J1C, J1D, J1E | regulator pokojowy (`J1B` = aktywność 0, `J1F` = wskaźnik 1) | FFFFFF ×3 |

## Pomiary (grupa A): do potwierdzenia

Strona pobiera stan z `/sterownik-7-status/<nr>` (JSON z nazwami). Pokazuje: temperatury
kotła, spalin, CWU, zewnętrzną, wewnętrzną, podajnika i zaworu; moc %, moc kW; pompy C.O.,
CWU i cyrkulacji; spalanie 24 h i chwilowe; opał w zbiorniku; numer błędu.

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
