#!/usr/bin/env python3
"""
Wrapper chamado pelo admin: roda o scraper e, se OK, importa para o banco.
Uso: python -u run_importacao.py --lista PH11 [--forcar]
"""
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).parent

def main():
    scraper_cmd = [sys.executable, "-u", str(BASE / "scraper_plurall.py")] + sys.argv[1:]
    print(f">>> scraper: {' '.join(scraper_cmd[2:])}", flush=True)
    result = subprocess.run(scraper_cmd)

    if result.returncode != 0:
        print("\n⚠ Scraper terminou com erro — banco não atualizado.", flush=True)
        sys.exit(1)

    print("\n=== Carregando Excel no banco... ===", flush=True)
    subprocess.run([sys.executable, "-u", str(BASE / "importar_questoes.py")])
    print("=== Concluído ===", flush=True)

if __name__ == "__main__":
    main()
