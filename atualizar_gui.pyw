#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Interface grafica do AtualizarBanco.
Duplo-clique (ou pelo atalho criado no instalar). Nao abre janela preta.
"""
import queue
import threading
import tkinter as tk
from configparser import ConfigParser
from pathlib import Path
from tkinter import messagebox, ttk

import atualizar_banco as ab

APP_DIR = Path(ab.os.environ.get("LOCALAPPDATA", Path.home())) / "SimuladoPH"
PREFS = APP_DIR / "ultimo.ini"

INDIGO = "#4338ca"
BG = "#f1f5f9"


def carregar_prefs():
    if PREFS.exists():
        cp = ConfigParser()
        cp.read(PREFS, encoding="utf-8")
        if cp.has_section("u"):
            return cp["u"].get("login", ""), cp["u"].get("turma", "7")
    return "", "7"


def salvar_prefs(login, turma):
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        cp = ConfigParser()
        cp["u"] = {"login": login, "turma": turma}
        with open(PREFS, "w", encoding="utf-8") as f:
            cp.write(f)
    except Exception:
        pass


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Atualizar Banco — SimuladoPH")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.q = queue.Queue()
        self.rodando = False

        login0, turma0 = carregar_prefs()

        wrap = tk.Frame(self, bg=BG, padx=22, pady=18)
        wrap.pack(fill="both", expand=True)

        tk.Label(wrap, text="Atualizar Banco de Questoes", bg=BG, fg=INDIGO,
                 font=("Segoe UI", 15, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")
        tk.Label(wrap, text="Puxa questoes novas do Plurall e publica no site.",
                 bg=BG, fg="#64748b", font=("Segoe UI", 9)).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 14))

        def campo(r, texto):
            tk.Label(wrap, text=texto, bg=BG, font=("Segoe UI", 9, "bold")).grid(row=r, column=0, sticky="e", padx=(0, 8), pady=4)

        campo(2, "Login Plurall")
        self.e_login = ttk.Entry(wrap, width=34)
        self.e_login.grid(row=2, column=1, sticky="w", pady=4)
        self.e_login.insert(0, login0)

        campo(3, "Senha Plurall")
        self.e_senha = ttk.Entry(wrap, width=34, show="•")
        self.e_senha.grid(row=3, column=1, sticky="w", pady=4)

        campo(4, "Turma")
        fr_turma = tk.Frame(wrap, bg=BG)
        fr_turma.grid(row=4, column=1, sticky="w", pady=4)
        self.turma = tk.StringVar(value=turma0)
        ttk.Radiobutton(fr_turma, text="7º ano", value="7", variable=self.turma).pack(side="left")
        ttk.Radiobutton(fr_turma, text="8º ano", value="8", variable=self.turma).pack(side="left", padx=(12, 0))

        campo(5, "Listas")
        self.e_listas = ttk.Entry(wrap, width=34)
        self.e_listas.grid(row=5, column=1, sticky="w", pady=4)
        tk.Label(wrap, text="ex: PH14   ou   PH14 PH15", bg=BG, fg="#94a3b8",
                 font=("Segoe UI", 8)).grid(row=6, column=1, sticky="w")

        self.btn = tk.Button(wrap, text="Atualizar banco", command=self.iniciar,
                             bg=INDIGO, fg="white", font=("Segoe UI", 10, "bold"),
                             relief="flat", padx=16, pady=8, cursor="hand2",
                             activebackground="#3730a3", activeforeground="white")
        self.btn.grid(row=7, column=0, columnspan=2, pady=(14, 10))

        self.log = tk.Text(wrap, width=64, height=13, bg="#0f172a", fg="#a7f3d0",
                           font=("Consolas", 8), relief="flat", padx=10, pady=8, state="disabled")
        self.log.grid(row=8, column=0, columnspan=2)

        self.status = tk.Label(wrap, text="pronto", bg=BG, fg="#64748b", font=("Segoe UI", 9))
        self.status.grid(row=9, column=0, columnspan=2, sticky="w", pady=(8, 0))

        self.e_listas.insert(0, "")
        (self.e_senha if login0 else self.e_login).focus_set()
        self.after(120, self._drenar)

    # -- log --------------------------------------------------------------
    def _escrever(self, linha):
        self.log.configure(state="normal")
        self.log.insert("end", linha + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _drenar(self):
        try:
            while True:
                tipo, val = self.q.get_nowait()
                if tipo == "log":
                    self._escrever(val)
                elif tipo == "fim":
                    self._fim(*val)
        except queue.Empty:
            pass
        self.after(120, self._drenar)

    # -- acao ------------------------------------------------------------
    def iniciar(self):
        if self.rodando:
            return
        login = self.e_login.get().strip()
        senha = self.e_senha.get()
        turma = "7ano" if self.turma.get() == "7" else "8ano"
        listas = self.e_listas.get().replace(",", " ").split()

        if not login or not senha:
            messagebox.showwarning("Falta dado", "Preencha login e senha do Plurall.")
            return
        if not listas:
            messagebox.showwarning("Falta dado", "Informe as listas (ex: PH14).")
            return

        salvar_prefs(login, self.turma.get())
        self.rodando = True
        self.btn.configure(state="disabled", text="Atualizando...")
        self.status.configure(text="rodando — pode demorar alguns minutos", fg=INDIGO)
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

        threading.Thread(target=self._worker, args=(login, senha, turma, listas), daemon=True).start()

    def _worker(self, login, senha, turma, listas):
        try:
            ok, msg = ab.executar(login, senha, turma, listas, emit=lambda s: self.q.put(("log", s)))
            self.q.put(("fim", (ok, msg)))
        except ab._Erro as e:
            self.q.put(("fim", (False, str(e))))
        except Exception as e:
            self.q.put(("fim", (False, f"Erro inesperado: {e}")))

    def _fim(self, ok, msg):
        self.rodando = False
        self.btn.configure(state="normal", text="Atualizar banco")
        if ok:
            self.status.configure(text="concluido", fg="#16a34a")
            messagebox.showinfo("Pronto!", msg)
        else:
            self.status.configure(text="falhou", fg="#dc2626")
            messagebox.showerror("Deu erro", msg)


if __name__ == "__main__":
    App().mainloop()
