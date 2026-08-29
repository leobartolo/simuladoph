#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AtualizarBanco — raspa questoes novas do Plurall e envia pro site SimuladoPH.

Roda no PC do usuario (ex: Miguel). Empacotado com PyInstaller vira um .exe
unico que NAO precisa de Python nem bibliotecas instaladas.

Fluxo:
  1. baixa o questoes.xlsx atual do site
  2. raspa as listas pedidas do Plurall (Chromium local, via Playwright)
  3. envia o questoes.xlsx novo + imagens novas de volta pro site
  4. o site reimporta o banco sozinho

Config: arquivo `config.ini` ao lado do .exe (secao [site]) OU as constantes
abaixo. O login do Plurall e sempre perguntado na hora.
"""
import asyncio
import configparser
import io
import os
import sys
import zipfile
from getpass import getpass
from pathlib import Path

import requests

# ---- Padroes (podem ser sobrescritos pelo config.ini) ----------------------
SITE_PADRAO = "https://simulado.bartolo.website"
TOKEN_PADRAO = ""  # preenchido no config.ini enviado pro Miguel


def base_do_exe() -> Path:
    """Pasta onde esta o .exe (ou o .py em desenvolvimento)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def carregar_config():
    site, token = SITE_PADRAO, TOKEN_PADRAO
    cfg_path = base_do_exe() / "config.ini"
    if cfg_path.exists():
        cp = configparser.ConfigParser()
        cp.read(cfg_path, encoding="utf-8")
        if cp.has_section("site"):
            site = cp["site"].get("url", site).rstrip("/")
            token = cp["site"].get("token", token)
    return site.rstrip("/"), token


def pausa_e_sai(codigo=0):
    print()
    input("Pressione ENTER para fechar...")
    sys.exit(codigo)


def main():
    print("=" * 52)
    print("  AtualizarBanco — SimuladoPH")
    print("=" * 52)

    site, token = carregar_config()
    if not token:
        print("\n[ERRO] Falta o token no config.ini (secao [site], campo token).")
        pausa_e_sai(1)

    headers = {"X-Upload-Token": token}

    # --- Perguntas ---------------------------------------------------------
    usuario = input("\nLogin do Plurall: ").strip()
    senha = getpass("Senha do Plurall: ")
    turma = ""
    while turma not in ("7", "8"):
        turma = input("Turma (7 ou 8): ").strip()
    turma = "7ano" if turma == "7" else "8ano"
    listas_raw = input("Listas (ex: PH14  ou  PH14 PH15): ").strip().upper()
    listas = [x for x in listas_raw.replace(",", " ").split() if x]
    if not listas:
        print("Nenhuma lista informada.")
        pausa_e_sai(1)

    # --- Pasta de trabalho ----------------------------------------------
    work = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "SimuladoPH"
    (work / "static" / "imagens").mkdir(parents=True, exist_ok=True)
    os.environ["SCRAPER_BASE"] = str(work)
    os.environ["PLURALL_USUARIO"] = usuario
    os.environ["PLURALL_SENHA"] = senha
    os.environ.setdefault("SCRAPER_TURMA", turma)

    # --- 1. Baixa o xlsx atual do site -----------------------------------
    print(f"\n[1/4] Baixando questoes.xlsx atual de {site} ...")
    try:
        r = requests.get(f"{site}/admin/xlsx", headers=headers, timeout=60)
        r.raise_for_status()
        (work / "questoes.xlsx").write_bytes(r.content)
        print(f"      ok ({len(r.content)//1024} KB)")
    except Exception as e:
        print(f"      [ERRO] nao consegui baixar: {e}")
        pausa_e_sai(1)

    # --- 2. Raspa ------------------------------------------------------
    print(f"\n[2/4] Raspando {', '.join(listas)} ({turma}) do Plurall...")
    print("      (a primeira vez baixa o navegador ~130 MB, tenha paciencia)")
    _garantir_chromium()

    import scraper_plurall  # importado so agora (ja com SCRAPER_BASE setado)

    imgs_dir = work / "static" / "imagens"
    antes = {p.name for p in imgs_dir.glob("*")}

    try:
        asyncio.run(scraper_plurall.main(listas, False, True, turma))
    except SystemExit:
        pass
    except Exception as e:
        print(f"\n      [ERRO] a raspagem falhou: {e}")
        pausa_e_sai(1)

    novas_imgs = sorted(p for p in imgs_dir.glob("*") if p.name not in antes)
    print(f"      {len(novas_imgs)} imagens novas")

    # --- 3. Monta o zip de imagens novas -------------------------------
    zip_buf = io.BytesIO()
    if novas_imgs:
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as z:
            for p in novas_imgs:
                z.write(p, p.name)
        zip_buf.seek(0)

    # --- 4. Envia pro site --------------------------------------------
    print(f"\n[3/4] Enviando pro site...")
    files = {"xlsx": ("questoes.xlsx", (work / "questoes.xlsx").read_bytes())}
    if novas_imgs:
        files["imagens"] = ("imagens.zip", zip_buf.getvalue(), "application/zip")
    try:
        r = requests.post(f"{site}/admin/xlsx", headers=headers, files=files, timeout=300)
    except Exception as e:
        print(f"      [ERRO] envio falhou: {e}")
        pausa_e_sai(1)

    print(f"\n[4/4] Resposta do site: HTTP {r.status_code}")
    try:
        j = r.json()
        print(f"      importado: {'SIM' if j.get('ok') else 'NAO'} | imagens: {j.get('imagens', 0)}")
        cauda = "\n".join(j.get("log", "").splitlines()[-6:])
        if cauda:
            print("      --- log do site ---")
            for ln in cauda.splitlines():
                print("      " + ln)
    except Exception:
        print("      " + r.text[:500])

    if r.status_code == 200:
        print("\n  PRONTO! As questoes ja estao no ar em " + site)
    else:
        print("\n  Algo deu errado no envio. Veja a mensagem acima.")
    pausa_e_sai(0 if r.status_code == 200 else 1)


def _garantir_chromium():
    """Instala o Chromium do Playwright na primeira execucao."""
    try:
        from playwright._impl._driver import compute_driver_executable, get_driver_env
    except Exception:
        return
    try:
        import subprocess
        exe = compute_driver_executable()
        cmd = list(exe) if isinstance(exe, (list, tuple)) else [str(exe)]
        subprocess.run(cmd + ["install", "chromium"], env=get_driver_env(), check=False)
    except Exception as e:
        print(f"      (aviso: nao consegui checar o navegador: {e})")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelado.")
        pausa_e_sai(1)
