#!/usr/bin/env bash
#
# Deploy na AWS. Puxa o questoes.xlsx novo do GitHub e ressincroniza o banco.
#
# Fluxo:
#   1. Em casa:  python run_importacao.py --lista PHxx   (scrape + import local + push)
#   2. Na AWS:   ./deploy.sh
#
# O scraper (Chromium/Playwright) NAO roda bem nesta instancia (RAM baixa);
# por isso o scrape e feito em casa e aqui so importamos a planilha.
#
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

echo "== git pull =="
git pull --ff-only

echo "== dependencias =="
venv/bin/pip install -q -r requirements.txt

echo "== backup do banco =="
mkdir -p backups
cp instance/simuladoph.db "backups/simuladoph.db.$(date +%Y%m%d_%H%M%S)"
# mantem apenas os 10 backups mais recentes
ls -t backups/simuladoph.db.* 2>/dev/null | tail -n +11 | xargs -r rm

echo "== importar questoes.xlsx -> banco =="
echo "   (recria as tabelas de questoes e ZERA o historico de respostas dos simulados)"
venv/bin/python3 importar_questoes.py

echo "== reiniciar servico =="
sudo systemctl restart simuladoph
sleep 1
systemctl is-active simuladoph

echo "== deploy OK -> https://simulado.bartolo.website =="
