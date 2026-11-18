@echo off
rem Wspolna czesc startowa - uruchamiaj START_PODSLUCH_*.bat, nie ten plik.
chcp 65001 >nul
cd /d "%~dp0"
title Piec

set "PY="
py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
if not defined PY (python -c "import sys" >nul 2>&1 && set "PY=python")
if not defined PY (
  echo.
  echo Nie znaleziono Pythona.
  echo Zainstaluj go ze strony https://www.python.org/downloads/
  echo ^(przy instalacji zaznacz "Add python.exe to PATH"^), potem uruchom ten plik ponownie.
  echo.
  pause
  exit /b 1
)
for /f "delims=" %%i in ('%PY% -c "import sys;print(sys.executable)"') do set "PYEXE=%%i"

rem Zapora: wpuszczaj do Pythona tylko urzadzenia z sieci domowej (localsubnet).
netsh advfirewall firewall delete rule name="ekoproxy piec" >nul 2>&1
netsh advfirewall firewall add rule name="ekoproxy piec" dir=in action=allow program="%PYEXE%" enable=yes profile=any remoteip=localsubnet >nul
if errorlevel 1 (echo Uwaga: nie udalo sie dodac reguly zapory.) else (echo Zapora: regula "ekoproxy piec" dodana - tylko siec domowa.)

%PY% %*

netsh advfirewall firewall delete rule name="ekoproxy piec" >nul 2>&1
echo Regula zapory usunieta.
pause
