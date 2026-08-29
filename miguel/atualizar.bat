@echo off
cd /d "%~dp0"
title AtualizarBanco

set "VPY=%LOCALAPPDATA%\SimuladoPH\venv\Scripts\python.exe"

if not exist "%VPY%" (
  echo.
  echo   Ainda nao instalado. Rode "instalar.bat" primeiro ^(so 1 vez^).
  echo.
  pause
  exit /b 1
)

"%VPY%" atualizar_banco.py
