# Instalador do AtualizarBanco - roda UMA vez.
# Instala Python (se preciso), monta o ambiente, baixa o navegador e cria
# o atalho "Atualizar Banco - SimuladoPH" na area de trabalho.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# Tudo numa pasta CURTA e fixa (o Playwright tem caminhos longos).
$HOME_APP = Join-Path $env:LOCALAPPDATA "SimuladoPH"
$APP  = Join-Path $HOME_APP "app"
$VENV = Join-Path $HOME_APP "venv"
$VPY  = Join-Path $VENV "Scripts\python.exe"
$VPYW = Join-Path $VENV "Scripts\pythonw.exe"

Write-Host "======================================================"
Write-Host "  AtualizarBanco - instalacao (so precisa fazer 1 vez)"
Write-Host "======================================================`n"

function Check($oque) {
  if ($LASTEXITCODE -ne 0) { Write-Host "`nERRO em: $oque (codigo $LASTEXITCODE)"; Read-Host "ENTER para sair"; exit 1 }
}

function Find-Python {
  foreach ($c in @(
      "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
      "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
      "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe")) {
    if (Test-Path $c) { return $c }
  }
  $p = (Get-Command python -ErrorAction SilentlyContinue).Source
  if ($p -and $p -notlike "*WindowsApps*") { return $p }
  return $null
}

$py = Find-Python
if (-not $py) {
  Write-Host "Python nao encontrado - instalando pela loja do Windows (winget)..."
  Write-Host "(se aparecer um aviso pedindo permissao, aceite)`n"
  winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
  Start-Sleep -Seconds 3
  $py = Find-Python
}
if (-not $py) {
  Write-Host "`nERRO: nao consegui instalar o Python."
  Write-Host "Instale de https://www.python.org/downloads/ e rode de novo."
  Read-Host "ENTER para sair"; exit 1
}
Write-Host "Python: $py`n"

# ambiente
if (Test-Path $VENV) { Remove-Item -Recurse -Force $VENV }
New-Item -ItemType Directory -Force -Path $HOME_APP | Out-Null
Write-Host "Criando o ambiente..."
& $py -m venv $VENV ; Check "criar venv"
Write-Host "Instalando bibliotecas..."
& $VPY -m pip install --upgrade pip --quiet ; Check "atualizar pip"
& $VPY -m pip install -r "$PSScriptRoot\requirements.txt" --quiet ; Check "instalar bibliotecas"
Write-Host "Baixando o navegador (Chromium ~130 MB, pode demorar)..."
& $VPY -m playwright install chromium ; Check "baixar o navegador"

# copia os arquivos do app pra uma pasta estavel
New-Item -ItemType Directory -Force -Path $APP | Out-Null
foreach ($f in @("atualizar_gui.pyw", "atualizar_banco.py", "scraper_plurall.py", "config.ini")) {
  Copy-Item (Join-Path $PSScriptRoot $f) (Join-Path $APP $f) -Force
}

# atalho na area de trabalho + menu iniciar
$alvo = Join-Path $APP "atualizar_gui.pyw"
$ws = New-Object -ComObject WScript.Shell
foreach ($destino in @(
    (Join-Path ([Environment]::GetFolderPath('Desktop')) "Atualizar Banco - SimuladoPH.lnk"),
    (Join-Path ([Environment]::GetFolderPath('Programs')) "Atualizar Banco - SimuladoPH.lnk"))) {
  $lnk = $ws.CreateShortcut($destino)
  $lnk.TargetPath = $VPYW
  $lnk.Arguments = "`"$alvo`""
  $lnk.WorkingDirectory = $APP
  $lnk.IconLocation = "$env:SystemRoot\System32\shell32.dll,13"
  $lnk.Description = "Puxa questoes novas do Plurall pro site SimuladoPH"
  $lnk.Save()
}

Write-Host "`n======================================================"
Write-Host "  PRONTO!"
Write-Host "  Um atalho 'Atualizar Banco - SimuladoPH' foi criado"
Write-Host "  na area de trabalho. E so dar 2 cliques nele."
Write-Host "======================================================"
