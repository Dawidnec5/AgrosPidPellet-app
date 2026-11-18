@echo off
rem Tryb szeroki: przekierowuje WSZYSTKIE nazwy DNS i slucha na portach 1-10000.
rem Uzyj tylko, gdy zwykly START_PODSLUCH_WINDOWS.bat nic nie zlapal.
net session >nul 2>&1
if errorlevel 1 (
  echo Prosze o uprawnienia administratora ^(port DNS 53 i zapora^)...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
call "%~dp0_start.bat" --spoof "*" --ports 1-10000
