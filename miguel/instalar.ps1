# Instalador do AtualizarBanco - roda UMA vez.
# Instala Python (se preciso), cria o ambiente e baixa o navegador.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# O ambiente vai numa pasta CURTA e fixa (o pacote do Playwright tem caminhos
# muito longos e estoura o limite do Windows se ficar numa pasta funda).
$HOME_APP = Join-Path $env:LOCALAPPDATA "SimuladoPH"
$VENV = Join-Path $HOME_APP "venv"
$VPY  = Join-Path $VENV "Scripts\python.exe"

Write-Host "======================================================"
Write-Host "  AtualizarBanco - instalacao (so precisa fazer 1 vez)"
Write-Host "======================================================`n"

function Check([string]$oque) {
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

if (Test-Path $VENV) { Remove-Item -Recurse -Force $VENV }
New-Item -ItemType Directory -Force -Path $HOME_APP | Out-Null

Write-Host "Criando o ambiente em $VENV ..."
& $py -m venv $VENV ; Check "criar venv"

Write-Host "Instalando bibliotecas..."
& $VPY -m pip install --upgrade pip --quiet ; Check "atualizar pip"
& $VPY -m pip install -r "$PSScriptRoot\requirements.txt" --quiet ; Check "instalar bibliotecas"

Write-Host "Baixando o navegador (Chromium ~130 MB, pode demorar)..."
& $VPY -m playwright install chromium ; Check "baixar o navegador"

Write-Host "`n======================================================"
Write-Host "  PRONTO!"
Write-Host "  Agora e so usar 'atualizar.bat' quando quiser"
Write-Host "  puxar questoes novas do Plurall pro site."
Write-Host "======================================================"
