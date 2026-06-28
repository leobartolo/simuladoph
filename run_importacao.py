#!/usr/bin/env python3
"""
Wrapper chamado pelo admin local:
  1. Roda o scraper (Plurall → questoes.xlsx)
  2. Importa para o banco local
  3. Faz git commit + push do questoes.xlsx para o GitHub

No Render, use o botão "Carregar Excel → Banco" que chama
importar_questoes.py diretamente (sem scraper nem git).

Uso: python -u run_importacao.py --lista PH11 [--forcar]
"""
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).parent


def run(cmd, **kwargs):
    print(f"$ {' '.join(str(c) for c in cmd)}", flush=True)
    return subprocess.run(cmd, **kwargs)


def main():
    listas_args = sys.argv[1:]  # ex: --lista PH11 PH12 --forcar

    # 1. Scraper
    print("=== 1/3 Scraper Plurall ===", flush=True)
    result = run([sys.executable, "-u", str(BASE / "scraper_plurall.py")] + listas_args)
    if result.returncode != 0:
        print("\n⚠ Scraper terminou com erro — processo interrompido.", flush=True)
        sys.exit(1)

    # 2. Importar Excel → banco local
    print("\n=== 2/3 Importando Excel → banco ===", flush=True)
    run([sys.executable, "-u", str(BASE / "importar_questoes.py")])

    # 3. Git commit + push do questoes.xlsx
    print("\n=== 3/3 Publicando questoes.xlsx no GitHub ===", flush=True)

    # Descobre quais listas foram passadas para a mensagem do commit
    listas = []
    capturar = False
    for arg in listas_args:
        if arg == "--lista":
            capturar = True
        elif arg.startswith("--"):
            capturar = False
        elif capturar:
            listas.append(arg)
    msg = f"update questoes.xlsx: {', '.join(listas)}" if listas else "update questoes.xlsx"

    run(["git", "add", str(BASE / "questoes.xlsx"), str(BASE / "static" / "imagens")], cwd=BASE)
    r = run(["git", "diff", "--cached", "--quiet"], cwd=BASE)
    if r.returncode == 0:
        print("  (sem mudanças — nada para commitar)", flush=True)
    else:
        run(["git", "commit", "-m", msg], cwd=BASE)
        run(["git", "push"], cwd=BASE)
        print("\n✓ Publicado. Acesse o admin no Render e clique em", flush=True)
        print('  "Carregar Excel → Banco" para atualizar a produção.', flush=True)

    print("\n=== Concluído ===", flush=True)


if __name__ == "__main__":
    main()
