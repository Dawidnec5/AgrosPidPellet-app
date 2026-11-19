# AgrosPidPellet: lokalna aplikacja do sterownika ArgosPid Plus (pellet)

Podgląd i sterowanie kotłem z telefonu, bez abonamentu i bez chmury producenta. Działa w Twojej
sieci domowej na zwykłym komputerze (Windows albo Linux/Raspberry Pi).

> **Projekt nieoficjalny i niezależny.** Nie jest związany z firmami Technix ani Bolecki ani
> z platformą ekotlownia.pl, ani przez nie wspierany. Nazwy produktów służą wyłącznie do
> wskazania, z jakim urządzeniem projekt współpracuje. Projekt powstał przez obserwację ruchu
> sieciowego **własnego** sterownika w celu współpracy z własnym oprogramowaniem. Nie łamie
> zabezpieczeń, nie odpytuje serwerów producenta i nie zawiera kodu ani firmware producenta.
> **Używasz na własną odpowiedzialność.** Nastawy kotła zmieniaj rozważnie, w zakresach
> z instrukcji kotła. Zabezpieczenie STB działa sprzętowo, niezależnie od sterownika i aplikacji.
>
> Tryb `sam` (domyślny) w ogóle nie łączy się z ekotlownia.pl. Tryb `proxy` jedynie przekazuje
> do platformy dane wysyłane przez sterownik, tak jak bez tego programu. Jeśli korzystasz
> z ekotlownia.pl, obowiązuje Cię jej regulamin.

## Spis treści

1. [Jak to działa](#1-jak-to-działa)
2. [Co jest potrzebne](#2-co-jest-potrzebne)
3. [Instalacja na Windows](#3-instalacja-na-windows)
4. [Instalacja na Linux / Raspberry Pi](#4-instalacja-na-linux--raspberry-pi)
5. [Ustawienie sterownika (kod 0104)](#5-ustawienie-sterownika-kod-0104)
6. [Sprawdzenie, czy działa](#6-sprawdzenie-czy-działa)
7. [Korzystanie z aplikacji](#7-korzystanie-z-aplikacji)
8. [Dostęp spoza domu](#8-dostęp-spoza-domu)
9. [Bezpieczeństwo](#9-bezpieczeństwo)
10. [Rozwiązywanie problemów](#10-rozwiązywanie-problemów)
11. [Powrót do poprzednich ustawień / ekotlownia.pl](#11-powrót-do-poprzednich-ustawień--ekotlowniapl)
12. [Narzędzia diagnostyczne](#12-narzędzia-diagnostyczne)
13. [Pliki w repozytorium](#13-pliki-w-repozytorium)

---

## 1. Jak to działa

Sterownik ArgosPid Plus ma wbudowany moduł sieciowy (gniazdo RJ45). Co ~27 sekund sam łączy
się z serwerem producenta `test5.ekotlownia.pl` i wysyła wszystkie swoje dane: temperatury,
stany pomp, nastawy i harmonogramy. W odpowiedzi może dostać nowe nastawy. Połączenie to zwykłe,
nieszyfrowane HTTP (szczegóły: [PROTOKOL.md](PROTOKOL.md)).

Ten projekt zastępuje serwer producenta programem na Twoim komputerze:

```text
                        (1) "gdzie jest test5.ekotlownia.pl?"
  ┌────────────┐  LAN   ┌──────────────────────────┐
  │ Sterownik  │ ─────► │ Twój komputer            │
  │ ArgosPid + │ ◄───── │  • DNS: "to ja"          │      (tylko w trybie proxy)
  └────────────┘  (2)   │  • serwer HTTP :80       │ ───► ekotlownia.pl
       dane co ~27 s,   │  • baza pomiarów         │
       nastawy w odp.   │  • aplikacja WWW         │
                        └────────────┬─────────────┘
                                     │ http://ADRES-KOMPUTERA/
                                  📱 telefon / przeglądarka
```

1. W sterowniku (menu serwisowe, kod 0104) ustawiasz **DNS = adres Twojego komputera**.
2. Gdy sterownik pyta o adres serwera producenta, Twój komputer odpowiada „to ja”.
3. Sterownik wysyła dane do Twojego komputera, a ten je zapisuje i pokazuje w aplikacji.
4. Gdy zmienisz nastawę w aplikacji, komputer odsyła ją sterownikowi w odpowiedzi, w tym samym
   formacie co serwer producenta. Sterownik potwierdza zmianę w następnym raporcie.

Na sterowniku nic nie jest przerabiane: zmieniasz tylko jedno ustawienie sieciowe, które
w każdej chwili można przywrócić.

## 2. Co jest potrzebne

| Co | Szczegóły |
|---|---|
| Sterownik | ArgosPid Plus / Pellet z wbudowanym modułem internetowym (LAN). Testowane na oprogramowaniu **2.99** (menu → kod 0109). Inne wersje mogą mieć pola w innych miejscach, zob. [rozdział 10](#10-rozwiązywanie-problemów). |
| Kabel sieciowy | Sterownik podłączony kablem LAN do Twojego routera. |
| Komputer, **stale włączony** | Windows 10/11, Linux albo Raspberry Pi, w **tej samej sieci** co sterownik (kablem lub przez Wi-Fi tego samego routera, nie przez sieć „dla gości”). Gdy komputer jest wyłączony, piec grzeje normalnie, tylko nie ma podglądu. |
| Python | 3.8 lub nowszy ([python.org](https://www.python.org/downloads/)). Inne biblioteki nie są potrzebne. |
| Telefon / przeglądarka | Dowolna nowoczesna przeglądarka. |
| (opcjonalnie) Tailscale | Do bezpiecznego dostępu spoza domu ([rozdział 8](#8-dostęp-spoza-domu)). |

Najlepiej sprawdza się **Raspberry Pi**: pobiera kilka watów i może działać ciągle.

## 3. Instalacja na Windows

1. **Zainstaluj Pythona** z [python.org/downloads](https://www.python.org/downloads/). Przy
   instalacji zaznacz **„Add python.exe to PATH”**.
2. **Pobierz projekt**: na stronie repozytorium kliknij **Code → Download ZIP** i rozpakuj go
   np. do `C:\Piec`.
3. **Ustal komputerowi stały adres w sieci.** Sterownik będzie go miał wpisany jako DNS, więc
   adres nie może się zmieniać. Najprościej ustawić w routerze **rezerwację DHCP** (zwaną też
   „statycznym DHCP” albo „przypisaniem adresu IP”) dla tego komputera.
4. **Uruchom** dwuklikiem **`START_APLIKACJA.bat`** i zgódź się na uprawnienia administratora.
   Są potrzebne do portu DNS 53, portu 80 i reguły zapory. Plik:
   - znajdzie Pythona,
   - doda regułę Zapory Windows, która wpuszcza do programu **tylko urządzenia z Twojej
     podsieci lokalnej**, i usunie ją po zamknięciu okna,
   - nie pozwoli komputerowi zasnąć, dopóki program działa. Zamknięta klapa laptopa może go
     jednak uśpić, więc zostaw ją otwartą albo zmień w Windows akcję zamknięcia klapy.
5. Na górze okna zobaczysz **adres komputera**. Zapisz go, będzie potrzebny w rozdziale 5.

Pliki startowe:

| Plik | Do czego |
|---|---|
| `START_APLIKACJA.bat` | **Aplikacja, tryb `sam`** (zalecany): bez łączenia z ekotlownia.pl. |
| `START_APLIKACJA_Z_EKOTLOWNIA.bat` | Aplikacja, tryb `proxy`: dane idą też do ekotlownia.pl (dla posiadaczy abonamentu). |
| `START_PODSLUCH_WINDOWS.bat` | Diagnostyka: zapis ruchu sterownik ↔ serwer ([rozdział 12](#12-narzędzia-diagnostyczne)). |
| `START_PODSLUCH_SZEROKI.bat` | Diagnostyka: jak wyżej, ale łapie wszystkie nazwy i porty. |
| `SKAN_STEROWNIKA.bat` | Diagnostyka: sprawdza, czy sterownik ma otwarte porty. |

W danej chwili może działać tylko jeden program z tej listy, bo wszystkie używają tych samych
portów.

## 4. Instalacja na Linux / Raspberry Pi

```bash
sudo apt install -y python3 git
sudo git clone https://github.com/Dawidnec5/AgrosPidPellet.git /opt/piec

# test ręczny (Ctrl+C kończy):
sudo python3 /opt/piec/piec_serwer.py

# autostart po włączeniu (bez roota, z ograniczonymi uprawnieniami):
sudo cp /opt/piec/linux/piec.service /etc/systemd/system/piec.service
sudo systemctl daemon-reload
sudo systemctl enable --now piec
journalctl -u piec -f        # podgląd
```

- Baza z historią przy autostarcie leży w `/var/lib/piec/`.
- **Ubuntu i inne systemy z `systemd-resolved`** mają już coś na porcie 53. Dopisz wtedy
  `--bind ADRES_TEGO_KOMPUTERA` (w `piec.service`, w linii `ExecStart`).
- Jeśli używasz zapory `ufw`, wpuść porty tylko z sieci lokalnej, np.
  `sudo ufw allow from 192.168.1.0/24 to any port 80 proto tcp` oraz
  `sudo ufw allow from 192.168.1.0/24 to any port 53`. Wpisz tam **swoją** sieć.
- Raspberry Pi też powinno mieć stały adres (rezerwacja DHCP w routerze).

## 5. Ustawienie sterownika (kod 0104)

### 5.1 Odczytaj parametry swojej sieci

Na komputerze, na którym działa program:

- **Windows:** `Win + R` → `cmd` → wpisz `ipconfig`. Przy karcie, przez którą komputer łączy się
  z routerem, odczytaj:
  - `Adres IPv4`, czyli **adres komputera** (ten sam, który pokazuje okno programu),
  - `Maska podsieci`, czyli **maskę**,
  - `Brama domyślna`, czyli **adres routera**.
- **Linux:** `ip -4 addr` (adres i maska w zapisie `/24` = `255.255.255.0`) oraz `ip route`
  (adres routera po słowie `default via`).

Przykład (**Twoje wartości będą inne!**):

| Parametr | Przykład | Skąd |
|---|---|---|
| Adres komputera | `192.168.1.50` | `ipconfig` → Adres IPv4 |
| Maska | `255.255.255.0` | `ipconfig` → Maska podsieci |
| Router (brama) | `192.168.1.1` | `ipconfig` → Brama domyślna |
| Adres dla sterownika | `192.168.1.60` | **wolny** adres z tej samej podsieci (zob. niżej) |

**Wolny adres dla sterownika:**
- najlepiej ten, który sterownik dostawał dotąd automatycznie (lista urządzeń w routerze),
- albo dowolny adres z tej samej podsieci **spoza zakresu DHCP routera**, żeby router nie dał
  go innemu urządzeniu,
- pierwsze trzy liczby muszą być takie same jak u komputera i routera (przy masce
  `255.255.255.0`).

### 5.2 Wpisz je w sterowniku

1. Wejdź w menu sterownika i wpisz kod **0104** (Ustawienia internetowe).
2. **Zapisz na kartce obecne ustawienia**, żeby móc do nich wrócić.
3. Ustaw:

| Pole | Wartość |
|---|---|
| DHCP | **Nie** |
| IP | wolny adres dla sterownika (np. `192.168.1.60`) |
| BRAMA | adres routera (np. `192.168.1.1`) |
| MASKA | maska (zwykle `255.255.255.0`) |
| DNS | **adres komputera z programem** (np. `192.168.1.50`) |

4. Wyłącz sterownik na ~10 s z prądu i włącz ponownie.

> Pola IP, BRAMA i MASKA przy „DHCP: Tak” mogą pokazywać stare lub fabryczne wartości, które
> nie mają nic wspólnego z Twoją siecią. Po przełączeniu na „DHCP: Nie” **trzeba je poprawić**,
> inaczej sterownik nie połączy się z niczym.

Na ekranie zobaczysz też **ID urządzenia**. Nikomu go nie podawaj ([rozdział 9](#9-bezpieczeństwo)).

## 6. Sprawdzenie, czy działa

1. W oknie programu po starcie powinno być: `DNS: OK` (autotest) i `HTTP: port 80 - OK`.
2. Po 1–2 minutach od restartu sterownika w aplikacji pojawi się zielona kropka „… s temu”.
3. Otwórz w przeglądarce komputera `http://ADRES-KOMPUTERA/`, a potem to samo na telefonie
   **podłączonym do domowego Wi-Fi**. Wpisz adres w całości, z `http://`.
4. Pierwszy test zmiany zrób na czymś niegroźnym, np. temperatura CWU +1 °C. W zakładce
   **Zdarzenia** powinno pojawić się „✓ …”, a nowa wartość na ekranie sterownika. Potem przywróć.

Test samego DNS (Windows, drugie okno `cmd`, program działa):
```
nslookup test.ekotlownia.pl ADRES-KOMPUTERA
```
W odpowiedzi powinien pojawić się adres Twojego komputera.

## 7. Korzystanie z aplikacji

| Zakładka | Co zawiera |
|---|---|
| **Pulpit** | Temperatura kotła (pierścień z zaznaczoną temperaturą zadaną), wykres z 6 h, CWU z szybką zmianą temperatury zadanej, podajnik, zawór, opał (kg, pasek, „wystarczy do”), spalanie 24 h, cyrkulacja, sezon. Alarmy Er na czerwono. |
| **Wykresy** | 1 h – 30 dni: kocioł, CWU, spaliny, podajnik, zawór; praca wentylatora i pomp. Dotknij wykresu, żeby zobaczyć wartości z danej chwili. |
| **Nastawy** | Wszystkie nastawy dostępne na ekotlownia.pl, w tych samych zakresach. Zmiany zbierają się na pasku **„Zapisz”** i idą razem, po potwierdzeniu. Tu też ustawisz **hasło**. |
| **Harmonogram** | Godziny dla kotła, pompy C.O., CWU, zaworu i cyrkulacji; osobno pon–pt, sobota, niedziela. |
| **Zdarzenia** | Historia: zlecone zmiany, potwierdzenia ✓, odrzucenia ✗, alarmy. |

- **Ikona na ekranie głównym:** menu przeglądarki → „Dodaj do ekranu głównego”.
- Gdy aplikacja jest otwarta, sterownik raportuje co ~7 s zamiast ~27 s.
- Historia jest w pliku `piec.db`, około 150 MB na rok. Przy aktualizacji programu **nie kasuj go**.

**Tryby serwera:**
- `sam` (domyślny): wszystko lokalnie, bez ekotlownia.pl.
- `proxy`: dane sterownika idą też do ekotlownia.pl, a zmiany ze strony producenta trafiają do
  sterownika. Do użycia tylko z aktywnym abonamentem.

## 8. Dostęp spoza domu

**Nie przekierowuj portów 80 ani 53 na routerze** i nie wystawiaj aplikacji do internetu
(zob. [rozdział 9](#9-bezpieczeństwo)). Zamiast tego użyj prywatnej, szyfrowanej sieci VPN.
Najprościej przez darmowy **Tailscale**:

1. Załóż konto na [tailscale.com](https://tailscale.com).
2. Zainstaluj Tailscale **na komputerze z programem** i **na telefonie**, logując się tym samym kontem.
3. W aplikacji Tailscale na komputerze odczytaj jego adres (zaczyna się od `100.`).
4. Na telefonie, także na danych komórkowych, otwórz `http://100.x.y.z/`.

Ruch jest szyfrowany, router zostaje bez zmian, a aplikację widzą tylko Twoje urządzenia.

> Na Windows reguła zapory dodawana przez `_start.bat` wpuszcza tylko „podsieć lokalną”.
> Jeśli przez Tailscale strona się nie otwiera, dodaj w Zaporze Windows regułę przychodzącą dla
> portu TCP 80, ograniczoną do zakresu adresów `100.64.0.0/10` (adresy Tailscale).

## 9. Bezpieczeństwo

Czego program **nie** robi:
- nie wystawia niczego do internetu (słucha tylko w sieci lokalnej),
- nie wysyła nigdzie Twoich danych (w trybie `sam` łączy się tylko ze sterownikiem),
- nie zbiera danych o Tobie.

Co **Ty** powinieneś zrobić:

| Zasada | Dlaczego |
|---|---|
| **Ustaw hasło do zmian** (Nastawy → Bezpieczeństwo) | Bez hasła każdy w Twojej sieci (goście w Wi-Fi, zainfekowane urządzenie) może zmieniać nastawy kotła. Podgląd zostaje bez hasła. |
| **Nie przekierowuj portów** 53/80 na routerze | Program nie ma szyfrowania (HTTP) i działa też jako serwer DNS. Wystawiony do internetu zostałby wykorzystany przez obcych. Do dostępu z zewnątrz używaj Tailscale. |
| **Goście w osobnej sieci** | Jeśli router ma „sieć dla gości”, dawaj ją gościom. Oddziela ich od pieca i komputera. |
| **Nie publikuj ID sterownika** | ID z ekranu 0104 służy do rejestracji na ekotlownia.pl. Regulamin platformy prosi, by go nie udostępniać. |
| **Nie publikuj plików `logi/` ani `piec.db`** | Zawierają ID sterownika i pełną historię pracy Twojego kotła. W repozytorium wyklucza je `.gitignore`. |
| **Zgłaszając problem, maskuj dane** | Zrzuty ekranu i logi: zakryj ID sterownika, adresy z Twojej sieci, nazwę użytkownika Windows i miejscowość. |
| **Nie aktualizuj sterownika bez potrzeby** | Nowe oprogramowanie może przenieść pola w inne miejsca. Po aktualizacji sprawdź działanie ([rozdział 12](#12-narzędzia-diagnostyczne)). |
| **Aktualizuj komputer** | Windows Update / `apt upgrade`: komputer jest teraz częścią instalacji grzewczej. |

Jak program chroni się sam:
- Zapora Windows: dostęp tylko z podsieci lokalnej; reguła jest usuwana po zamknięciu programu.
- Hasło przechowywane jako skrót PBKDF2 z solą, nigdy otwartym tekstem. Złe hasło spowalnia
  kolejne próby.
- Każda nastawa jest sprawdzana pod kątem dozwolonego zakresu (takiego jak na ekotlownia.pl)
  przed wysłaniem do sterownika. Zmieniać można tylko znane, opisane nastawy.
- Do sterownika trafia zawsze **pełny zestaw nastaw w dokładnie tym samym formacie** co
  z serwera producenta. Program nie wysyła niczego, czego oryginalny serwer by nie wysłał.
- Linux: usługa działa bez roota (`DynamicUser`), z prawem tylko do portów 53 i 80.

## 10. Rozwiązywanie problemów

| Objaw | Co zrobić |
|---|---|
| `nie mogę otworzyć portu 53` | Windows: zgódź się na uprawnienia administratora. Jeśli dalej to samo, port zajmuje coś innego (Udostępnianie połączenia internetowego, Docker, inny serwer DNS). Linux: `sudo` albo `--bind ADRES` przy `systemd-resolved`. |
| `nie mogę otworzyć portu 80` | Port zajmuje inny program (np. IIS, Skype, inny serwer WWW) albo drugie okno tego programu. Zamknij go. |
| Aplikacja: „czekam na sterownik” | Sprawdź w 0104: DNS = adres komputera, IP/BRAMA/MASKA z Twojej sieci. Zrestartuj sterownik. Sprawdź `nslookup` z rozdziału 6. |
| Na komputerze działa, na telefonie nie | Telefon musi być w Wi-Fi tego samego routera (nie na danych komórkowych, nie w sieci gości). Wpisz adres z `http://`. Niektóre routery mają „izolację klientów Wi-Fi”, którą trzeba wyłączyć. |
| Ikona sieci na sterowniku czerwona | Sterownik nie dosięga komputera: zły adres IP/BRAMA/MASKA albo komputer wyłączony. |
| Zmiana kończy się „✗ nie przyjął” | Wartość mogła zostać odrzucona przez sterownik albo sterownik ma inną wersję oprogramowania. Sprawdź na ekranie sterownika, zrób podsłuch (rozdział 12). |
| Dziwne wartości po aktualizacji sterownika | Inna wersja oprogramowania może mieć inną mapę pól. Zrób podsłuch i porównaj z [PROTOKOL.md](PROTOKOL.md). |
| Komputer zmienił adres | Ustaw rezerwację DHCP w routerze i popraw DNS w sterowniku. |

## 11. Powrót do poprzednich ustawień / ekotlownia.pl

W sterowniku, kod 0104: ustaw **DHCP = Tak** (albo wpisz zapisane na kartce wartości) i wyłącz
sterownik na chwilę z prądu. Sterownik znowu łączy się bezpośrednio z ekotlownia.pl. Na
komputerze wystarczy zamknąć program.

## 12. Narzędzia diagnostyczne

- **Podsłuch** (`START_PODSLUCH_WINDOWS.bat` albo `sudo python3 ekoproxy.py`): przekazuje ruch
  sterownik ↔ ekotlownia.pl bez zmian i zapisuje go do `logi/podsluch_*.jsonl`. Podgląd
  zapisu: `python ekoproxy.py pokaz logi/podsluch_....jsonl`. Przydaje się po aktualizacji
  sterownika albo przy rozpoznawaniu nowych pól. **Log zawiera ID sterownika, więc nie
  publikuj go.**
- **Skan** (`SKAN_STEROWNIKA.bat` albo `python ekoproxy.py skan ADRES-STEROWNIKA`): delikatnie
  (16 połączeń naraz) sprawdza porty TCP 1–10000 sterownika. Niczego nie zmienia.

## 13. Pliki w repozytorium

| Plik | Opis |
|---|---|
| `piec_serwer.py` | Serwer: DNS, odbiór danych sterownika, zapis do bazy, API aplikacji, wysyłanie nastaw. |
| `www/` | Aplikacja (jedna strona HTML, bez zewnętrznych bibliotek) i ikony. |
| `ekoproxy.py` | Podsłuch, autotest DNS, skan portów; wspólne funkcje DNS. |
| `linux/piec.service` | Autostart na Linux / Raspberry Pi (systemd). |
| `*.bat` | Uruchamianie na Windows (`_start.bat` = część wspólna). |
| [PROTOKOL.md](PROTOKOL.md) | Opis protokołu: format, mapa pól, sposób zapisu nastaw. |

Podziękowania: część pól (pompy, kody błędów, lato/zima) potwierdził niezależnie projekt
[ImixVega/argos-pid-esphome](https://github.com/ImixVega/argos-pid-esphome).
