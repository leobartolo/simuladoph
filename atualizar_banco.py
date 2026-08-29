#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AtualizarBanco — raspa questoes novas do Plurall e envia pro site SimuladoPH.

Roda no PC de quem atualiza o banco (ex: Miguel), dentro da .venv criada
pelo instalar.bat. Fluxo:

  1. baixa o questoes.xlsx atual do site
  2. raspa as listas pedidas do Plurall (Chromium local, via Playwright)
  3. envia o questoes.xlsx novo + imagens novas de volta pro site
  4. o site reimporta o banco sozinho

Config: arquivo `config.ini` na mesma pasta (secao [site]).
O login do Plurall e perguntado na hora (ou vem das env PLURALL_USUARIO/SENHA).
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

SITE_PADRAO = "https://simulado.bartolo.website"
AQUI = Path(__file__).parent


def carregar_config():
    site, token = SITE_PADRAO, ""
    cfg = AQUI / "config.ini"
    if cfg.exists():
        cp = configparser.ConfigParser()
        cp.read(cfg, encoding="utf-8")
        if cp.has_section("site"):
            site = cp["site"].get("url", site)
            token = cp["site"].get("token", token)
    return site.rstrip("/"), token.strip()


def pausa_e_sai(codigo=0):
    print()
    if not os.environ.get("ATUALIZAR_NOPAUSE") and sys.stdin.isatty():
        try:
            input("Pressione ENTER para fechar...")
        except EOFError:
            pass
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

    usuario = os.environ.get("PLURALL_USUARIO") or input("\nLogin do Plurall: ").strip()
    senha = os.environ.get("PLURALL_SENHA") or getpass("Senha do Plurall: ")

    turma = os.environ.get("ATUALIZAR_TURMA", "").replace("ano", "").strip()
    while turma not in ("7", "8"):
        turma = input("Turma (7 ou 8): ").strip()
    turma = "7ano" if turma == "7" else "8ano"

    listas_raw = os.environ.get("ATUALIZAR_LISTAS", "").strip().upper()
    if not listas_raw:
        listas_raw = input("Listas (ex: PH14  ou  PH14 PH15): ").strip().upper()
    listas = [x for x in listas_raw.replace(",", " ").split() if x]
    if not listas:
        print("Nenhuma lista informada.")
        pausa_e_sai(1)

    work = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "SimuladoPH"
    (work / "static" / "imagens").mkdir(parents=True, exist_ok=True)
    os.environ["SCRAPER_BASE"] = str(work)
    os.environ["PLURALL_USUARIO"] = usuario
    os.environ["PLURALL_SENHA"] = senha
    os.environ["SCRAPER_TURMA"] = turma

    # 1. baixa o xlsx atual
    print(f"\n[1/4] Baixando questoes.xlsx atual de {site} ...")
    try:
        r = requests.get(f"{site}/admin/xlsx", headers=headers, timeout=60)
        r.raise_for_status()
        (work / "questoes.xlsx").write_bytes(r.content)
        print(f"      ok ({len(r.content)//1024} KB)")
    except Exception as e:
        print(f"      [ERRO] nao consegui baixar: {e}")
        pausa_e_sai(1)

    # 2. raspa
    print(f"\n[2/4] Raspando {', '.join(listas)} ({turma}) do Plurall...")
    import scraper_plurall

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

    # 3. zip das imagens novas
    zip_bytes = b""
    if novas_imgs:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for p in novas_imgs:
                z.write(p, p.name)
        zip_bytes = buf.getvalue()

    # 4. envia
    print(f"\n[3/4] Enviando pro site...")
    files = {"xlsx": ("questoes.xlsx", (work / "questoes.xlsx").read_bytes())}
    if zip_bytes:
        files["imagens"] = ("imagens.zip", zip_bytes, "application/zip")
    try:
        r = requests.post(f"{site}/admin/xlsx", headers=headers, files=files, timeout=300)
    except Exception as e:
        print(f"      [ERRO] envio falhou: {e}")
        pausa_e_sai(1)

    print(f"\n[4/4] Resposta do site: HTTP {r.status_code}")
    try:
        j = r.json()
        print(f"      importado: {'SIM' if j.get('ok') else 'NAO'} | imagens recebidas: {j.get('imagens', 0)}")
        for ln in j.get("log", "").splitlines()[-6:]:
            print("      " + ln)
    except Exception:
        print("      " + r.text[:500])

    if r.status_code == 200:
        print(f"\n  PRONTO! As questoes ja estao no ar em {site}")
        pausa_e_sai(0)
    else:
        print("\n  Algo deu errado no envio (veja acima).")
        pausa_e_sai(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelado.")
        pausa_e_sai(1)
