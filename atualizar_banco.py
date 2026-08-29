#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AtualizarBanco — raspa questoes novas do Plurall e envia pro site SimuladoPH.

Fluxo:
  1. baixa o questoes.xlsx atual do site
  2. raspa as listas pedidas do Plurall (Chromium local, via Playwright)
  3. envia o questoes.xlsx novo + imagens novas de volta pro site
  4. o site reimporta o banco sozinho

Uso:
  - interface grafica:  atualizar_gui.pyw  (chama executar() abaixo)
  - linha de comando:   python atualizar_banco.py

Config: arquivo `config.ini` na mesma pasta (secao [site]).
"""
import asyncio
import configparser
import contextlib
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


class _Erro(Exception):
    pass


class _EmitWriter(io.TextIOBase):
    """Redireciona print() do scraper para a funcao emit (linha a linha)."""
    def __init__(self, emit):
        self._emit = emit
        self._buf = ""
        self._dentro = False  # evita recursao se o emit tambem imprimir

    def _envia(self, linha):
        if self._dentro:
            return
        self._dentro = True
        try:
            self._emit(linha)
        finally:
            self._dentro = False

    def write(self, s):
        self._buf += s
        while "\n" in self._buf:
            linha, self._buf = self._buf.split("\n", 1)
            self._envia(linha)
        return len(s)

    def flush(self):
        if self._buf:
            self._envia(self._buf)
            self._buf = ""


def executar(usuario, senha, turma, listas, emit=print):
    """Roda o pipeline completo. `turma` = '7ano'/'8ano', `listas` = lista de str.
    Retorna (ok: bool, mensagem_final: str). Lanca _Erro em falhas conhecidas."""
    usuario = (usuario or "").strip()
    senha = senha or ""
    listas = [x.strip().upper() for x in listas if x and x.strip()]
    if turma not in ("7ano", "8ano"):
        turma = "7ano"

    if not usuario or not senha:
        raise _Erro("Informe o login e a senha do Plurall.")
    if not listas:
        raise _Erro("Informe pelo menos uma lista (ex: PH14).")

    site, token = carregar_config()
    if not token:
        raise _Erro("Falta o token no config.ini (secao [site], campo token).")
    headers = {"X-Upload-Token": token}

    work = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "SimuladoPH"
    (work / "static" / "imagens").mkdir(parents=True, exist_ok=True)
    os.environ["SCRAPER_BASE"] = str(work)
    os.environ["PLURALL_USUARIO"] = usuario
    os.environ["PLURALL_SENHA"] = senha
    os.environ["SCRAPER_TURMA"] = turma

    # 1. baixa o xlsx atual
    emit(f"[1/4] Baixando questoes atuais de {site} ...")
    try:
        r = requests.get(f"{site}/admin/xlsx", headers=headers, timeout=60)
        r.raise_for_status()
        (work / "questoes.xlsx").write_bytes(r.content)
        emit(f"      ok ({len(r.content) // 1024} KB)")
    except Exception as e:
        raise _Erro(f"Nao consegui baixar do site: {e}")

    # 2. raspa
    emit("")
    emit(f"[2/4] Raspando {', '.join(listas)} ({turma}) do Plurall...")
    import scraper_plurall

    imgs_dir = work / "static" / "imagens"
    antes = {p.name for p in imgs_dir.glob("*")}
    try:
        with contextlib.redirect_stdout(_EmitWriter(emit)):
            asyncio.run(scraper_plurall.main(listas, False, True, turma))
    except SystemExit:
        pass
    except Exception as e:
        raise _Erro(f"A raspagem falhou: {e}")

    novas_imgs = sorted(p for p in imgs_dir.glob("*") if p.name not in antes)
    emit(f"      {len(novas_imgs)} imagens novas")

    # 3. zip das imagens novas
    zip_bytes = b""
    if novas_imgs:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for p in novas_imgs:
                z.write(p, p.name)
        zip_bytes = buf.getvalue()

    # 4. envia
    emit("")
    emit("[3/4] Enviando pro site...")
    files = {"xlsx": ("questoes.xlsx", (work / "questoes.xlsx").read_bytes())}
    if zip_bytes:
        files["imagens"] = ("imagens.zip", zip_bytes, "application/zip")
    try:
        r = requests.post(f"{site}/admin/xlsx", headers=headers, files=files, timeout=300)
    except Exception as e:
        raise _Erro(f"O envio falhou: {e}")

    emit("")
    emit(f"[4/4] Site respondeu HTTP {r.status_code}")
    try:
        j = r.json()
        emit(f"      importado: {'SIM' if j.get('ok') else 'NAO'} | imagens: {j.get('imagens', 0)}")
        for ln in j.get("log", "").splitlines()[-6:]:
            emit("      " + ln)
    except Exception:
        emit("      " + r.text[:500])

    if r.status_code == 200:
        return True, f"PRONTO! As questoes ja estao no ar em {site}"
    return False, "Algo deu errado no envio (veja o log acima)."


# ---- Linha de comando -----------------------------------------------------
def _pausa():
    if not os.environ.get("ATUALIZAR_NOPAUSE") and sys.stdin.isatty():
        try:
            input("Pressione ENTER para fechar...")
        except EOFError:
            pass


def main():
    print("=" * 52)
    print("  AtualizarBanco — SimuladoPH")
    print("=" * 52)

    usuario = os.environ.get("PLURALL_USUARIO") or input("\nLogin do Plurall: ").strip()
    senha = os.environ.get("PLURALL_SENHA") or getpass("Senha do Plurall: ")
    turma = os.environ.get("ATUALIZAR_TURMA", "").replace("ano", "").strip()
    while turma not in ("7", "8"):
        turma = input("Turma (7 ou 8): ").strip()
    turma = "7ano" if turma == "7" else "8ano"
    listas_raw = os.environ.get("ATUALIZAR_LISTAS", "") or input("Listas (ex: PH14 PH15): ")
    listas = listas_raw.replace(",", " ").split()

    print()
    _real = sys.stdout
    def _emit(s):
        print(s, file=_real, flush=True)
    try:
        ok, msg = executar(usuario, senha, turma, listas, emit=_emit)
    except _Erro as e:
        print(f"\n[ERRO] {e}")
        _pausa()
        sys.exit(1)
    print(f"\n  {msg}")
    _pausa()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelado.")
