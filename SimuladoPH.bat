@echo off
cd /d "%~dp0"
title SimuladoPH - servidor local (feche esta janela para parar)

echo.
echo   SimuladoPH - iniciando o servidor local...
echo   Deixe esta janela aberta. Feche-a quando quiser parar o servidor.
echo.

rem --- Ja esta rodando? So abre o navegador e sai ---
curl -s -o nul -m 2 http://127.0.0.1:5000/login
if not errorlevel 1 (
    echo   O servidor ja estava no ar. Abrindo o navegador...
    start "" http://127.0.0.1:5000/admin
    timeout /t 2 >nul
    exit /b
)

rem --- Abre o navegador sozinho assim que o servidor responder ---
start "" /min powershell -NoProfile -WindowStyle Hidden -Command "for($i=0;$i -lt 60;$i++){try{[void](Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:5000/login' -TimeoutSec 1);Start-Process 'http://127.0.0.1:5000/admin';break}catch{Start-Sleep -Milliseconds 800}}"

rem --- Sobe o servidor nesta janela ---
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" app.py
) else (
    echo   ERRO: nao achei .venv\Scripts\python.exe nesta pasta.
    echo   Confirme que o SimuladoPH.bat esta dentro de C:\Users\leona\Python\simuladophv2_prod
)

echo.
echo   === Servidor parado. Pode fechar esta janela. ===
pause
