#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Monta o pacote que vai pro PC do Miguel.

Uso:
    python miguel/montar.py <UPLOAD_TOKEN>
    (ou define a env UPLOAD_TOKEN)

Gera:  pacote_miguel/            (pasta pronta)
       AtualizarBanco.zip        (a mesma pasta, zipada, pra enviar)
"""
import os
import shutil
import sys
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
MIGUEL = RAIZ / "miguel"
SAIDA = RAIZ / "pacote_miguel"
ZIP = RAIZ / "AtualizarBanco.zip"

SITE = os.environ.get("SIMULADOPH_SITE", "https://simulado.bartolo.website")


def main():
    token = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("UPLOAD_TOKEN", "")).strip()
    if not token:
        sys.exit("Passe o UPLOAD_TOKEN:  python miguel/montar.py <token>")

    if SAIDA.exists():
        shutil.rmtree(SAIDA)
    SAIDA.mkdir()

    for nome in ("instalar.bat", "instalar.ps1", "atualizar.bat", "requirements.txt", "LEIA-ME.txt"):
        shutil.copy(MIGUEL / nome, SAIDA / nome)
    for nome in ("scraper_plurall.py", "atualizar_banco.py", "atualizar_gui.pyw"):
        shutil.copy(RAIZ / nome, SAIDA / nome)

    (SAIDA / "config.ini").write_text(
        f"[site]\nurl = {SITE}\ntoken = {token}\n", encoding="utf-8"
    )

    if ZIP.exists():
        ZIP.unlink()
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(SAIDA.rglob("*")):
            z.write(p, Path("AtualizarBanco") / p.relative_to(SAIDA))

    print(f"OK -> {SAIDA}")
    print(f"OK -> {ZIP}  ({ZIP.stat().st_size // 1024} KB)")
    print("\nEnvie o AtualizarBanco.zip pro Miguel.")


if __name__ == "__main__":
    main()
