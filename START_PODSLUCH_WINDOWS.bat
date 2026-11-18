@echo off
net session >nul 2>&1
if errorlevel 1 (
  echo Prosze o uprawnienia administratora ^(port DNS 53 i zapora^)...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
call "%~dp0_start.bat"
