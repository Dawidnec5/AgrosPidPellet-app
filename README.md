# Piec: własna aplikacja do sterownika ArgosPid Plus (Technix) bez abonamentu

Cel: podglądać i zmieniać ustawienia kotła pelletowego z telefonu, tak jak w ekotlownia.pl,
ale bez opłat i bez chmury producenta.

## Jak sterownik łączy się z internetem (z instrukcji producenta)

- Moduł internetowy jest **wbudowany**: złącze RJ45 (kabel LAN) z boku obudowy.
- Sterownik **sam łączy się z serwerem ekotlownia.pl**. Nie ma własnej strony WWW w sieci domowej.
  Serwer wpuszcza go tylko przy aktywnym abonamencie.
- Menu serwisowe **kod 0104** pozwala wpisać ręcznie: **IP, BRAMA, MASKA i DNS**. Tam jest też
  numer ID urządzenia.
- Producent nie publikuje protokołu. Nie znalazłem też nikogo, kto by go już rozpracował.

Plan:

| Etap | Co | Status |
|---|---|---|
| 1 | Podsłuchać, co sterownik wysyła do serwera i co dostaje z powrotem (`ekoproxy.py`) | **gotowe narzędzie, czeka na uruchomienie u Ciebie** |
| 2 | Rozszyfrować protokół z logów: temperatury, stany, nastawy, komendy | po etapie 1 |
| 3 | Własny serwer w domu (Raspberry Pi albo stale włączony komputer), na który łączy się sterownik | po etapie 2 |
| 4 | Aplikacja na telefon (strona WWW/PWA): podgląd, wykresy, zmiana nastaw, powiadomienia o błędach | po etapie 3 |

Sztuczka polega na tym, że w kodzie 0104 ustawiamy **DNS = Twój komputer**. Kiedy sterownik
zapyta o adres ekotlownia.pl, dostanie adres Twojego komputera i połączy się z nim, a nie
z serwerem producenta. Na etapie 1 komputer tylko przekazuje ruch dalej i zapisuje go do pliku.
Sterownik pracuje wtedy dokładnie tak jak zwykle.

## Aplikacja

`piec_serwer.py` to Twój własny serwer zamiast ekotlownia.pl, a `www/` to aplikacja na telefon.
Otwierasz ją pod adresem **http://ADRES-LAPTOPA/** (adres pokazuje okno programu, np. `http://192.168.1.50/`).

Zakładki:
- **Pulpit**: temperatura kotła na pierścieniu z zaznaczoną temperaturą zadaną, wykres
  z 6 h, CWU z szybką zmianą temperatury zadanej, podajnik, zawór, opał (z paskiem i czasem
  „wystarczy do”), spalanie, cyrkulacja, sezon; alarmy Er na czerwono.
- **Wykresy**: 1 h – 30 dni; kocioł, CWU, spaliny, podajnik, zawór; praca wentylatora
  i pomp. Po dotknięciu wykresu widać wartości z danej chwili.
- **Nastawy**: wszystkie nastawy z ekotlownia.pl. Zmiany zbierają się na pasku „Zapisz”
  i idą do sterownika razem, po potwierdzeniu (i haśle, jeśli jest ustawione).
- **Harmonogram**: godziny dla kotła, pompy C.O., CWU, zaworu i cyrkulacji; osobno
  pon–pt, sobota i niedziela.
- **Zdarzenia**: historia zmian (✓ potwierdzone przez sterownik, ✗ odrzucone) i alarmów.

**Hasło:** Nastawy → Bezpieczeństwo → Ustaw. Podgląd działa bez hasła, ale zmiany już nie.

**Ikona na telefonie:** w przeglądarce wybierz menu → „Dodaj do ekranu głównego”.

Uruchamianie (Windows):
- **`START_APLIKACJA_WINDOWS.bat`** (tryb proxy): dane idą też do ekotlownia.pl.
- **`START_APLIKACJA_BEZ_EKOTLOWNI.bat`** (tryb sam): bez ekotlownia.pl i bez abonamentu.
- Najpierw zamknij okno podsłuchu, bo oba programy używają portów 53 i 80.
- Historia jest w pliku `piec.db`. Przy aktualizacji aplikacji nie kasuj go.

### Dostęp spoza domu (Tailscale, za darmo)

1. Załóż konto na tailscale.com i zainstaluj Tailscale **na laptopie** (Windows) i **na telefonie**,
   logując się tym samym kontem.
2. W aplikacji Tailscale na laptopie odczytaj jego adres `100.x.y.z`.
3. Na telefonie (także na danych komórkowych) otwórz `http://100.x.y.z/`.

Router zostaje bez zmian i nic nie jest wystawione do internetu. Aplikację widzą tylko Twoje
urządzenia zalogowane w Tailscale. Mimo to ustaw hasło.

Ograniczenia:
- laptop musi być włączony; docelowo lepiej sprawdzi się Raspberry Pi,
- stan podajnika nie jest dostępny (sterownik go nie wysyła); część pól `A*` jest jeszcze
  nienazwana (Zdarzenia → Informacje).

Opis protokołu: [PROTOKOL.md](PROTOKOL.md).

## Etap 1: podsłuch krok po kroku

Najwięcej da się zobaczyć przy **aktywnym dostępie do ekotlownia.pl**. Nowe konto ma darmowe
2 tygodnie. Wtedy serwer naprawdę wysyła komendy i widać, jak wygląda np. zmiana temperatury
zadanej. Bez abonamentu też coś zobaczymy (sterownik wysyła swoje dane przy łączeniu), ale mniej.

1. **Komputer** w tej samej sieci domowej co sterownik (Windows, Linux albo Raspberry Pi)
   z Pythonem 3.8 lub nowszym. Dobrze jest dać mu stały adres IP w routerze (rezerwacja DHCP).
2. Skopiuj folder `piec/` na komputer (albo rozpakuj `Piec_Podsluch.zip`) i uruchom:
   - **Windows:** kliknij dwukrotnie **`START_PODSLUCH_WINDOWS.bat`** i zgódź się na
     uprawnienia administratora („Czy zezwolić tej aplikacji…” → Tak). Program sam:
     - znajdzie Pythona (jeśli go nie ma, poda link do instalacji),
     - doda regułę zapory, która wpuszcza **tylko urządzenia z Twojej sieci domowej**,
       i usunie ją po zakończeniu,
     - nie pozwoli laptopowi zasnąć, dopóki działa.

     **Laptop podłącz do ładowarki i nie zamykaj klapy**, bo zamknięta klapa może go uśpić.
     Laptop może być na Wi-Fi, byle w tej samej sieci co sterownik (nie w sieci „dla gości”).
   - Linux/RPi/Mac: `sudo python3 ekoproxy.py`

   Na górze okna program wypisze dużymi literami adres komputera, np. `192.168.1.50`.

3. **Na sterowniku**, menu → kod **0104**. Zapisz obecne wartości na kartce, żeby móc
   wrócić do ustawień.
   - Najpierw przy **DHCP = TAK** odczytaj, jaki adres dostał sterownik. Router zwykle
     pokazuje go na liście urządzeń.
   - Ustaw **DHCP = NIE** i wpisz:
     - **IP**: wolny adres w Twojej sieci, np. `192.168.1.60`. Najprościej wpisać ten,
       który sterownik miał z DHCP.
     - **MASKA**: `255.255.255.0`
     - **BRAMA**: adres routera, np. `192.168.1.1`
     - **DNS**: **adres komputera z punktu 2**, np. `192.168.1.50`
   - Wyłącz sterownik na chwilę z prądu albo poczekaj, aż połączy się ponownie.
4. W oknie programu powinny pojawić się linie:
   ```
   DNS  192.168.1.60 pyta o xxx.ekotlownia.pl  ->  PRZEKIEROWANO
   TCP  #1 192.168.1.60 -> port NNNN  (NOWE POŁĄCZENIE)
   TCP  #1 ster->serw ...
   TCP  #1 serw->ster ...
   ```
   Ikonka sieci na sterowniku powinna mieć taki sam kolor jak przed zmianą.
5. Zostaw program włączony na **co najmniej godzinę**. W tym czasie wejdź na ekotlownia.pl
   (jeśli masz dostęp) i zrób po kolei kilka zmian, **zapisując godzinę każdej z nich**, np.:
   - 12:05 temperatura zadana kotła 60 → 62 °C
   - 12:10 temperatura CWU 50 → 48 °C
   - 12:15 tryb lato/zima
   - 12:20 zmiana mocy dmuchawy

   Godziny pozwolą dopasować bajty w logu do konkretnych komend.
6. Wyślij mi plik z folderu `piec/logi/` (`podsluch_DATA.jsonl`) i listę zmian z godzinami.
   Podgląd logu: `python ekoproxy.py pokaz logi/podsluch_....jsonl`

**Powrót do normalnej pracy:** w kodzie 0104 ustaw z powrotem DHCP = TAK albo wpisz DNS routera.

### Gdy coś nie działa

| Objaw | Co zrobić |
|---|---|
| `nie mogę otworzyć portu 53` | Windows: zgódź się na uprawnienia administratora. Jeśli dalej to samo, coś innego zajmuje port 53 (np. „Udostępnianie połączenia internetowego”, Docker). Linux: `sudo`. |
| Brak linii `DNS ...` po restarcie sterownika | Sprawdź DNS w 0104 (adres z okna programu). Jeśli kiedyś przy pytaniu zapory kliknięto „Anuluj”, Windows mógł zablokować Pythona: Panel sterowania → Zapora Windows Defender → Zezwalaj aplikacji… → zaznacz Python (Prywatne i Publiczne). |
| Są linie `DNS`, ale żadna nie ma `PRZEKIEROWANO` | Serwer ma inną nazwę. Uruchom **`START_PODSLUCH_SZEROKI.bat`** (przekierowuje wszystkie nazwy). |
| Jest `PRZEKIEROWANO`, ale brak `NOWE POŁĄCZENIE` | Sterownik używa portu spoza listy. Uruchom **`START_PODSLUCH_SZEROKI.bat`** (porty 1–10000). |
| Sterownik stracił internet po wyłączeniu laptopa | Tak ma być: DNS wskazuje na laptopa. Przywróć w 0104 DHCP = TAK. |
| Brak jakichkolwiek pytań DNS, a sterownik dalej łączy się z serwerem | Adres serwera jest wpisany na stałe w firmware. Wtedy potrzebny jest inny sposób (np. Raspberry Pi jako brama). Napisz, a przygotuję go. |
| `UWAGA: ruch szyfrowany (TLS)` | Protokół jest szyfrowany i podsłuch będzie trudniejszy. Wyślij log, ocenię, co da się zrobić. |

## Bezpieczeństwo

- Na etapie 1 program **niczego nie wysyła do sterownika sam**. Przekazuje tylko ruch między
  sterownikiem a serwerem producenta.
- Własne sterowanie (etap 3+) będzie zmieniać tylko te parametry, które zmienia też
  ekotlownia.pl, w granicach dozwolonych przez sterownik. Termostat bezpieczeństwa STB działa
  sprzętowo, niezależnie od sterownika i od aplikacji.
- Analiza protokołu własnego urządzenia w celu współpracy z własnym oprogramowaniem jest w UE
  dozwolona. Nie łamiemy przy tym zabezpieczeń serwera producenta.
