@echo off
rem Aplikacja: dane ida tez do ekotlownia.pl (strona producenta dalej dziala).
rem Zamknij wczesniej okno podsluchu - oba programy uzywaja tych samych portow.
net session >nul 2>&1
if errorlevel 1 (
  echo Prosze o uprawnienia administratora ^(port DNS 53, port 80 i zapora^)...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
call "%~dp0_start.bat" piec_serwer.py --tryb proxy
