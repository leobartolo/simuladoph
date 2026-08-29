@echo off
rem Atalho alternativo (o instalar.ps1 ja cria um icone na area de trabalho).
set "APP=%LOCALAPPDATA%\SimuladoPH\app"
set "VPYW=%LOCALAPPDATA%\SimuladoPH\venv\Scripts\pythonw.exe"

if not exist "%VPYW%" (
  echo.
  echo   Ainda nao instalado. Rode "instalar.bat" primeiro ^(so 1 vez^).
  echo.
  pause
  exit /b 1
)

start "" "%VPYW%" "%APP%\atualizar_gui.pyw"
