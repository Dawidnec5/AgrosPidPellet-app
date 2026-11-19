@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Skan sterownika
set "PY="
py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
if not defined PY (python -c "import sys" >nul 2>&1 && set "PY=python")
if not defined PY (echo Nie znaleziono Pythona. & pause & exit /b 1)
set "IP="
set /p "IP=Adres sterownika (np. 192.168.1.60): "
if "%IP%"=="" (echo Nie podano adresu. & pause & exit /b 1)
%PY% ekoproxy.py skan %IP% 1-10000
pause
