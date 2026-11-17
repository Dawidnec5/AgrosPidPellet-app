@echo off
chcp 65001 >nul
cd /d "%~dp0"
net session >nul 2>&1
if errorlevel 1 (
  echo Potrzebne uprawnienia administratora ^(port DNS 53^).
  echo Kliknij ten plik prawym przyciskiem myszy i wybierz "Uruchom jako administrator".
  pause
  exit /b 1
)
where python >nul 2>&1
if errorlevel 1 (
  echo Nie znaleziono Pythona. Zainstaluj go z https://www.python.org/downloads/
  echo ^(zaznacz "Add python.exe to PATH"^).
  pause
  exit /b 1
)
python ekoproxy.py %*
pause
