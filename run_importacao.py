#!/usr/bin/env python3
"""
Pipeline completo — rode EM CASA (o Chromium do scraper não roda na AWS):

  1. Scraper Plurall  → questoes.xlsx + imagens
  2. Importa no banco local
  3. git commit + push do questoes.xlsx / imagens
  4. Deploy remoto na AWS (roda ./deploy.sh via SSH)  [se existir deploy.local]

O passo 4 só acontece se houver um arquivo `deploy.local` nesta pasta com:

    SSH_TARGET=ubuntu@52.73.104.23
    SSH_KEY=C:\\Users\\leona\\Downloads\\bartolo.pem
    REMOTE_DIR=~/simuladoph

`deploy.local` é ignorado pelo git — só existe na sua máquina.

Uso: python -u run_importacao.py --lista PH11 [--forcar]
"""
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).parent
DEPLOY_CFG = BASE / "deploy.local"


def run(cmd, **kwargs):
    print(f"$ {' '.join(str(c) for c in cmd)}", flush=True)
    return subprocess.run(cmd, **kwargs)


def ler_deploy_cfg():
    """Lê deploy.local (KEY=VALUE por linha). Retorna dict vazio se não existir."""
    if not DEPLOY_CFG.exists():
        return {}
    cfg = {}
    for linha in DEPLOY_CFG.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        k, v = linha.split("=", 1)
        cfg[k.strip()] = v.strip()
    return cfg


def deploy_remoto():
    cfg = ler_deploy_cfg()
    if not cfg:
        print("  (deploy.local ausente — pulando deploy remoto)", flush=True)
        return
    alvo = cfg.get("SSH_TARGET")
    key = cfg.get("SSH_KEY")
    remote_dir = cfg.get("REMOTE_DIR", "~/simuladoph")
    if not alvo or not key:
        print("  ⚠ deploy.local incompleto (precisa SSH_TARGET e SSH_KEY) — pulando", flush=True)
        return

    print(f"\n=== 4/4 Deploy na AWS ({alvo}) ===", flush=True)
    r = run([
        "ssh", "-i", key,
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        alvo, f"cd {remote_dir} && ./deploy.sh",
    ])
    if r.returncode == 0:
        print("\n✓ Deploy na AWS OK — https://simulado.bartolo.website", flush=True)
    else:
        print(f"\n⚠ Deploy na AWS falhou (código {r.returncode}).", flush=True)
        print(f'  Rode manualmente:  ssh -i "{key}" {alvo} "cd {remote_dir} && ./deploy.sh"', flush=True)
        sys.exit(1)


def main():
    listas_args = sys.argv[1:]  # ex: --lista PH11 PH12 --forcar

    # 1. Scraper
    print("=== 1/4 Scraper Plurall ===", flush=True)
    result = run([sys.executable, "-u", str(BASE / "scraper_plurall.py")] + listas_args)
    if result.returncode != 0:
        print("\n⚠ Scraper terminou com erro — processo interrompido.", flush=True)
        sys.exit(1)

    # 2. Importar Excel → banco local
    print("\n=== 2/4 Importando Excel → banco local ===", flush=True)
    run([sys.executable, "-u", str(BASE / "importar_questoes.py")])

    # 3. Git commit + push do questoes.xlsx
    print("\n=== 3/4 Publicando questoes.xlsx no GitHub ===", flush=True)

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
        print("  (sem mudanças no questoes.xlsx — nada para publicar, deploy pulado)", flush=True)
        print("\n=== Concluído ===", flush=True)
        return

    run(["git", "commit", "-m", msg], cwd=BASE)
    push = run(["git", "push"], cwd=BASE)
    if push.returncode != 0:
        print("\n⚠ git push falhou — deploy remoto cancelado. Resolva o push e rode de novo.", flush=True)
        sys.exit(1)
    print("✓ questoes.xlsx publicado no GitHub.", flush=True)

    # 4. Deploy remoto (AWS)
    deploy_remoto()

    print("\n=== Concluído ===", flush=True)


if __name__ == "__main__":
    main()
