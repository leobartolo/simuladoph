import os
import json
import re
import random
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

import markupsafe
from flask import Flask, render_template, redirect, url_for, request, flash, session, send_from_directory
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

from sqlalchemy import inspect as sa_inspect, text
from models import db, Usuario, Questao, Alternativa, Simulado, SimuladoQuestao, Resposta
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer
import requests
# ---------------------------------------------------------------------------
# App & configuração
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "troque-esta-chave-em-producao")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:///simuladoph.db"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Render usa "postgres://" mas SQLAlchemy exige "postgresql://"
uri = app.config["SQLALCHEMY_DATABASE_URI"]
if uri.startswith("postgres://"):
    app.config["SQLALCHEMY_DATABASE_URI"] = uri.replace("postgres://", "postgresql://", 1)



db.init_app(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Faça login para continuar."
login_manager.login_message_category = "warning"

LETRAS = ["A", "B", "C", "D", "E"]


_IMG_DIR = Path(__file__).parent / "static" / "imagens"


@app.template_filter("enunciado_html")
def enunciado_html_filter(text):
    """Renderiza [img:filename] dentro do enunciado como tags <img>.
    Imagens > 6 KB são exibidas como figuras centralizadas;
    imagens menores são notações inline (α, β, x̂ etc.)."""
    if not text:
        return markupsafe.Markup("")
    parts = re.split(r"(\[img:[^\]]+\])", text)
    result = []
    for part in parts:
        m = re.match(r"\[img:([^\]]+)\]", part)
        if m:
            filename = m.group(1)
            img_path = _IMG_DIR / filename
            size = img_path.stat().st_size if img_path.exists() else 0
            img_url = url_for("static", filename=f"imagens/{filename}")
            if size > 6000:
                result.append(
                    f'<img src="{img_url}" '
                    f'class="block max-w-full max-h-72 mx-auto my-4 '
                    f'rounded-lg border border-slate-100">'
                )
            else:
                result.append(
                    f'<img src="{img_url}" '
                    f'class="max-h-7 inline-block align-middle mx-0.5">'
                )
        else:
            result.append(str(markupsafe.escape(part)))
    return markupsafe.Markup("".join(result))


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(Usuario, int(user_id))


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# PWA — instalável no PC/celular, sempre puxando as questões da AWS
# ---------------------------------------------------------------------------

@app.route("/sw.js")
def service_worker():
    resp = send_from_directory(app.static_folder, "sw.js")
    resp.headers["Content-Type"] = "application/javascript"
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.route("/manifest.webmanifest")
def web_manifest():
    resp = send_from_directory(app.static_folder, "manifest.webmanifest")
    resp.headers["Content-Type"] = "application/manifest+json"
    return resp


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        senha = request.form["senha"]
        usuario = Usuario.query.filter_by(email=email).first()
        if usuario and check_password_hash(usuario.senha_hash, senha):
            login_user(usuario, remember=True)
            return redirect(url_for("dashboard"))
        flash("E-mail ou senha incorretos.", "danger")
    return render_template("login.html")


@app.route("/registro", methods=["GET", "POST"])
def registro():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        nome = request.form["nome"].strip()
        email = request.form["email"].strip().lower()
        senha = request.form["senha"]
        if Usuario.query.filter_by(email=email).first():
            flash("E-mail já cadastrado.", "danger")
        else:
            turma = request.form.get("turma", "7ano")
            if turma not in ("7ano", "8ano"):
                turma = "7ano"
            u = Usuario(nome=nome, email=email,
                        senha_hash=generate_password_hash(senha), turma=turma)
            db.session.add(u)
            db.session.commit()
            login_user(u)
            flash(f"Bem-vindo, {nome}!", "success")
            return redirect(url_for("dashboard"))
    return render_template("registro.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.route("/dashboard")
@login_required
def dashboard():
    simulados = (
        Simulado.query
        .filter_by(usuario_id=current_user.id)
        .order_by(Simulado.criado_em.desc())
        .all()
    )
    resumos = []
    for s in simulados:
        total = len(s.itens)
        eliminadas = sum(1 for i in s.itens if i.eliminada)
        tem_fila = bool(s.fila_json and json.loads(s.fila_json))
        resumos.append({
            "simulado": s,
            "total": total,
            "eliminadas": eliminadas,
            "restantes": total - eliminadas,
            "concluido": s.encerrado_em is not None,
            "tem_fila": tem_fila,
        })
    return render_template("dashboard.html", resumos=resumos)


# ---------------------------------------------------------------------------
# Novo simulado
# ---------------------------------------------------------------------------

@app.route("/novo", methods=["GET", "POST"])
@login_required
def novo_simulado():
    listas_disponiveis = sorted({q.lista_ph for q in Questao.query.filter_by(turma=current_user.turma).all()})
    disciplinas_disponiveis = sorted({q.disciplina for q in Questao.query.filter_by(turma=current_user.turma).all()})

    if request.method == "POST":
        listas = request.form.getlist("listas")
        disciplinas = request.form.getlist("disciplinas")
        quantidade = int(request.form.get("quantidade", 10))

        if not listas or not disciplinas:
            flash("Selecione pelo menos uma lista e uma matéria.", "warning")
            return redirect(url_for("novo_simulado"))

        questoes = (
            Questao.query
            .filter(Questao.lista_ph.in_(listas))
            .filter(Questao.disciplina.in_(disciplinas))
            .filter(Questao.turma == current_user.turma)
            .all()
        )
        if not questoes:
            flash("Nenhuma questão encontrada para os filtros selecionados.", "warning")
            return redirect(url_for("novo_simulado"))

        quantidade = min(quantidade, len(questoes))
        sorteadas = random.sample(questoes, quantidade)

        dificuldade = int(request.form.get("dificuldade", 3))
        dificuldade = max(1, min(4, dificuldade))  # garante 1-4
        embaralhar = request.form.get("embaralhar_alternativas") != "0"

        simulado = Simulado(
            usuario_id=current_user.id,
            listas=",".join(listas),
            disciplinas=",".join(disciplinas),
            acertos_para_eliminar=dificuldade,
            embaralhar_alternativas=embaralhar,
        )
        db.session.add(simulado)
        db.session.flush()   # pega o id antes do commit

        for q in sorteadas:
            letras_q = [l for l in LETRAS if q.alt_dict().get(l)] or ["A","B","C","D"]
            if embaralhar:
                random.shuffle(letras_q)
            sq = SimuladoQuestao(simulado_id=simulado.id, questao_id=q.id)
            sq.set_ordem(letras_q)
            db.session.add(sq)

        db.session.commit()
        return redirect(url_for("rodada", simulado_id=simulado.id))

    return render_template(
        "novo_simulado.html",
        listas=listas_disponiveis,
        disciplinas=disciplinas_disponiveis,
    )


# ---------------------------------------------------------------------------
# Rodada
# ---------------------------------------------------------------------------

def _itens_ativos(simulado_id):
    """Questões não eliminadas, em ordem aleatória."""
    itens = (
        SimuladoQuestao.query
        .filter_by(simulado_id=simulado_id, eliminada=False)
        .all()
    )
    random.shuffle(itens)
    return itens


@app.route("/simulado/<int:simulado_id>/rodada")
@login_required
def rodada(simulado_id):
    s = db.session.get(Simulado, simulado_id)
    if not s or s.usuario_id != current_user.id:
        flash("Simulado não encontrado.", "danger")
        return redirect(url_for("dashboard"))

    if s.encerrado_em:
        return redirect(url_for("resultado_final", simulado_id=simulado_id))

    itens = _itens_ativos(simulado_id)
    if not itens:
        # Todas eliminadas → encerra
        s.encerrado_em = datetime.now()
        db.session.commit()
        return redirect(url_for("resultado_final", simulado_id=simulado_id))

    # Reembaralha as alternativas a cada nova rodada (se configurado)
    for item in itens:
        letras_q = [l for l in LETRAS if item.questao.alt_dict().get(l)] or ["A","B","C","D"]
        if s.embaralhar_alternativas:
            random.shuffle(letras_q)
        item.set_ordem(letras_q)
    db.session.commit()

    ids = [i.id for i in itens]
    session[f"fila_{simulado_id}"] = ids
    session[f"rodada_acertos_{simulado_id}"] = 0
    session[f"rodada_total_{simulado_id}"] = len(ids)

    # Persiste a fila no banco para retomada caso a sessão expire
    s.fila_json = json.dumps(ids)
    db.session.commit()

    return redirect(url_for("questao", simulado_id=simulado_id))


@app.route("/simulado/<int:simulado_id>/questao", methods=["GET"])
@login_required
def questao(simulado_id):
    s = db.session.get(Simulado, simulado_id)
    if not s or s.usuario_id != current_user.id:
        return redirect(url_for("dashboard"))

    fila = session.get(f"fila_{simulado_id}", [])

    # Sessão expirou mas há fila salva no banco → retoma de onde parou
    if not fila and s.fila_json:
        fila = json.loads(s.fila_json)
        if fila:
            session[f"fila_{simulado_id}"] = fila
            session[f"rodada_total_{simulado_id}"] = len(fila)

    if not fila:
        return redirect(url_for("resultado_rodada", simulado_id=simulado_id))

    item_id = fila[0]
    item = db.session.get(SimuladoQuestao, item_id)
    q = item.questao

    # Monta as alternativas na ordem embaralhada
    alt_dict = q.alt_dict()
    ordem = item.get_ordem()   # ["C","A","D","B"] ou ["C","A","D","B","E"] — letras ORIGINAIS
    alternativas_exibidas = [
        {"letra_exibida": LETRAS[i], "texto": alt_dict[ordem[i]]}
        for i in range(len(ordem))
    ]

    total = session.get(f"rodada_total_{simulado_id}", len(fila))
    respondidas = total - len(fila)

    return render_template(
        "questao.html",
        simulado=s,
        item=item,
        questao=q,
        alternativas=alternativas_exibidas,
        numero=respondidas + 1,
        total=total,
        rodada=s.rodada_atual,
    )


@app.route("/simulado/<int:simulado_id>/responder", methods=["POST"])
@login_required
def responder(simulado_id):
    s = db.session.get(Simulado, simulado_id)
    if not s or s.usuario_id != current_user.id:
        return redirect(url_for("dashboard"))

    item_id = int(request.form["item_id"])
    letra_escolhida = request.form["letra"].upper()

    item = db.session.get(SimuladoQuestao, item_id)
    q = item.questao

    letra_correta_exibida = item.letra_correta_embaralhada()
    correta = letra_escolhida == letra_correta_exibida

    # Atualiza acertos seguidos
    if correta:
        item.acertos_seguidos += 1
        session[f"rodada_acertos_{simulado_id}"] = (
            session.get(f"rodada_acertos_{simulado_id}", 0) + 1
        )
        if item.acertos_seguidos >= s.acertos_para_eliminar:
            item.eliminada = True
    else:
        item.acertos_seguidos = 0

    # Grava a resposta
    resp = Resposta(
        simulado_id=simulado_id,
        questao_id=q.id,
        rodada=s.rodada_atual,
        letra_escolhida=letra_escolhida,
        correta=correta,
    )
    db.session.add(resp)

    # Remove da fila — recupera do banco se a sessão foi perdida (cookie grande)
    fila = session.get(f"fila_{simulado_id}", [])
    if not fila and s.fila_json:
        fila = json.loads(s.fila_json)
    if item_id in fila:
        fila.remove(item_id)
    session[f"fila_{simulado_id}"] = fila
    s.fila_json = json.dumps(fila)

    db.session.commit()

    # Monta texto da alternativa escolhida e da correta para o feedback
    alt_dict = q.alt_dict()
    ordem = item.get_ordem()

    def texto_de(letra_exibida):
        letras_exibidas = LETRAS[:len(ordem)]
        idx = letras_exibidas.index(letra_exibida)
        return alt_dict[ordem[idx]]

    return render_template(
        "feedback.html",
        simulado=s,
        questao=q,
        correta=correta,
        letra_escolhida=letra_escolhida,
        letra_correta=letra_correta_exibida,
        texto_escolhido=texto_de(letra_escolhida),
        texto_correto=texto_de(letra_correta_exibida),
        eliminada=item.eliminada,
        acertos_seguidos=item.acertos_seguidos,
        fila_vazia=len(fila) == 0,
        rodada=s.rodada_atual,
    )


@app.route("/simulado/<int:simulado_id>/deletar", methods=["POST"])
@login_required
def deletar_simulado(simulado_id):
    s = db.session.get(Simulado, simulado_id)
    if not s or s.usuario_id != current_user.id:
        flash("Simulado não encontrado.", "danger")
        return redirect(url_for("dashboard"))
    Resposta.query.filter_by(simulado_id=simulado_id).delete()
    SimuladoQuestao.query.filter_by(simulado_id=simulado_id).delete()
    db.session.delete(s)
    db.session.commit()
    session.pop(f"fila_{simulado_id}", None)
    session.pop(f"rodada_acertos_{simulado_id}", None)
    session.pop(f"rodada_total_{simulado_id}", None)
    flash("Simulado apagado.", "success")
    return redirect(url_for("dashboard"))


@app.route("/simulado/<int:simulado_id>/resultado-rodada")
@login_required
def resultado_rodada(simulado_id):
    s = db.session.get(Simulado, simulado_id)
    if not s or s.usuario_id != current_user.id:
        return redirect(url_for("dashboard"))

    acertos = session.get(f"rodada_acertos_{simulado_id}", 0)
    total = session.get(f"rodada_total_{simulado_id}", 0)

    itens_ativos = SimuladoQuestao.query.filter_by(
        simulado_id=simulado_id, eliminada=False
    ).count()
    itens_eliminados = SimuladoQuestao.query.filter_by(
        simulado_id=simulado_id, eliminada=True
    ).count()

    eliminadas_nessa_rodada = [
        i for i in s.itens
        if i.eliminada and i.acertos_seguidos == 0  # recem-eliminadas ficam com 0
    ]

    # Avança o contador de rodada e limpa a fila persistida
    s.rodada_atual += 1
    s.fila_json = None
    db.session.commit()

    concluido = itens_ativos == 0
    if concluido:
        s.encerrado_em = datetime.now()
        db.session.commit()

    return render_template(
        "resultado_rodada.html",
        simulado=s,
        acertos=acertos,
        total=total,
        itens_ativos=itens_ativos,
        itens_eliminados=itens_eliminados,
        concluido=concluido,
        rodada=s.rodada_atual - 1,
    )


@app.route("/simulado/<int:simulado_id>/resultado-final")
@login_required
def resultado_final(simulado_id):
    s = db.session.get(Simulado, simulado_id)
    if not s or s.usuario_id != current_user.id:
        return redirect(url_for("dashboard"))

    total_questoes = len(s.itens)
    total_respostas = Resposta.query.filter_by(simulado_id=simulado_id).count()
    total_acertos = Resposta.query.filter_by(simulado_id=simulado_id, correta=True).count()
    total_rodadas = s.rodada_atual - 1

    return render_template(
        "resultado_final.html",
        simulado=s,
        total_questoes=total_questoes,
        total_respostas=total_respostas,
        total_acertos=total_acertos,
        total_rodadas=total_rodadas,
        pct=round(total_acertos / total_respostas * 100) if total_respostas else 0,
    )




# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    if session.get("admin_ok"):
        return redirect(url_for("admin_dashboard"))
    if request.method == "POST":
        if request.form.get("senha") == ADMIN_PASSWORD:
            session["admin_ok"] = True
            return redirect(url_for("admin_dashboard"))
        flash("Senha incorreta.", "danger")
    return render_template("admin_login.html")

@app.route("/admin/usuario/<int:uid>/senha", methods=["POST"])
def admin_mudar_senha(uid):
    if not session.get("admin_ok"):
        return redirect(url_for("admin_login"))
    u = db.session.get(Usuario, uid)
    if not u:
        flash("Usuário não encontrado.", "warning")
        return redirect(url_for("admin_dashboard"))
    nova = request.form.get("nova_senha", "").strip()
    if len(nova) < 4:
        flash("Senha deve ter ao menos 4 caracteres.", "warning")
        return redirect(url_for("admin_dashboard"))
    u.senha_hash = generate_password_hash(nova)
    db.session.commit()
    flash(f"Senha de {u.nome} alterada.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/usuario/<int:uid>/turma", methods=["POST"])
def admin_mudar_turma(uid):
    if not session.get("admin_ok"):
        return redirect(url_for("admin_login"))
    u = db.session.get(Usuario, uid)
    if u:
        nova_turma = request.form.get("turma", "7ano")
        if nova_turma in ("7ano", "8ano"):
            u.turma = nova_turma
            db.session.commit()
            flash(f"Turma de {u.nome} alterada para {nova_turma}.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/usuario/<int:uid>/deletar", methods=["POST"])
def admin_deletar_usuario(uid):
    if not session.get("admin_ok"):
        return redirect(url_for("admin_login"))
    u = db.session.get(Usuario, uid)
    if not u:
        flash("Usuário não encontrado.", "warning")
        return redirect(url_for("admin_dashboard"))
    sims = Simulado.query.filter_by(usuario_id=uid).all()
    for s in sims:
        Resposta.query.filter_by(simulado_id=s.id).delete()
        SimuladoQuestao.query.filter_by(simulado_id=s.id).delete()
        db.session.delete(s)
    db.session.delete(u)
    db.session.commit()
    flash(f"Usuário {u.nome} excluído.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_ok", None)
    return redirect(url_for("admin_login"))

@app.route("/admin/dashboard")
def admin_dashboard():
    if not session.get("admin_ok"):
        return redirect(url_for("admin_login"))

    usuarios = Usuario.query.order_by(Usuario.criado_em.desc()).all()
    resumo = []
    for u in usuarios:
        sims = Simulado.query.filter_by(usuario_id=u.id).all()
        total_sims = len(sims)
        concluidos = sum(1 for s in sims if s.encerrado_em)
        total_respostas = Resposta.query.filter(
            Resposta.simulado_id.in_([s.id for s in sims])
        ).count() if sims else 0
        resumo.append({
            "usuario": u,
            "total_sims": total_sims,
            "concluidos": concluidos,
            "total_respostas": total_respostas,
        })

    simulados = Simulado.query.order_by(Simulado.criado_em.desc()).limit(50).all()
    total_questoes = Questao.query.count()

    return render_template(
        "admin_dashboard.html",
        resumo=resumo,
        simulados=simulados,
        total_questoes=total_questoes,
        total_usuarios=len(usuarios),
    )

# ---------------------------------------------------------------------------
# Admin — Banco de questões
# ---------------------------------------------------------------------------

@app.route("/admin/banco")
def admin_banco():
    if not session.get("admin_ok"):
        return redirect(url_for("admin_login"))

    lista_sel      = request.args.get("lista_ph", "")
    disciplina_sel = request.args.get("disciplina", "")
    turma_sel      = request.args.get("turma", "")

    q = Questao.query
    if turma_sel:
        q = q.filter_by(turma=turma_sel)
    if lista_sel:
        q = q.filter_by(lista_ph=lista_sel)
    if disciplina_sel:
        q = q.filter_by(disciplina=disciplina_sel)
    questoes = q.order_by(Questao.lista_ph, Questao.disciplina, Questao.id).all()

    base_q = Questao.query
    if turma_sel:
        base_q = base_q.filter_by(turma=turma_sel)
    listas     = [r[0] for r in base_q.with_entities(Questao.lista_ph).distinct().order_by(Questao.lista_ph).all()]
    disciplinas = [r[0] for r in base_q.with_entities(Questao.disciplina).distinct().order_by(Questao.disciplina).all()]

    return render_template("admin_banco.html",
        questoes=questoes,
        listas=listas,
        disciplinas=disciplinas,
        lista_sel=lista_sel,
        disciplina_sel=disciplina_sel,
        turma_sel=turma_sel,
        turmas=["7ano", "8ano"],
    )


# ---------------------------------------------------------------------------
# Admin — Scraper / Importar Excel
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent
SCRAPER_LOG = BASE_DIR / "scraper.log"
IMPORT_LOG  = BASE_DIR / "import.log"
SCRAPER_PID = BASE_DIR / "scraper.pid"
IMPORT_PID  = BASE_DIR / "import.pid"
_scraper_proc: dict = {"proc": None}
_import_proc:  dict = {"proc": None}

# O scraper (Chromium/Playwright) só roda na máquina de casa. A presença do
# deploy.local marca "esta é a máquina local" — na AWS o arquivo não existe.
SCRAPER_LOCAL = (BASE_DIR / "deploy.local").exists()


def _pid_vivo(pid: int) -> bool:
    """Checa se um PID ainda está vivo. Necessário porque o Gunicorn roda
    múltiplos workers (processos separados) e o objeto Popen só existe na
    memória do worker que deu Popen — outro worker precisa checar via PID."""
    if os.name != "posix":
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _processo_rodando(proc_dict: dict, pidfile: Path) -> bool:
    proc = proc_dict.get("proc")
    if proc is not None and proc.poll() is None:
        return True
    try:
        pid = int(pidfile.read_text().strip())
    except (FileNotFoundError, ValueError):
        return False
    return _pid_vivo(pid)


@app.route("/admin/importar-excel", methods=["POST"])
def admin_importar_excel():
    if not session.get("admin_ok"):
        return redirect(url_for("admin_login"))

    if _processo_rodando(_import_proc, IMPORT_PID):
        flash("Importação já em andamento.", "warning")
        return redirect(url_for("admin_scraper"))

    log_file = open(IMPORT_LOG, "w", encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen(
        [sys.executable, "-u", str(BASE_DIR / "importar_questoes.py")],
        stdout=log_file, stderr=subprocess.STDOUT,
        cwd=str(BASE_DIR), env=env,
    )
    _import_proc["proc"] = proc
    _import_proc["log_file"] = log_file
    IMPORT_PID.write_text(str(proc.pid))
    flash("Importando Excel → banco...", "success")
    return redirect(url_for("admin_scraper"))


@app.route("/admin/scraper/status")
def admin_scraper_status():
    if not session.get("admin_ok"):
        return {"ok": False}, 403
    rodando = _processo_rodando(_scraper_proc, SCRAPER_PID)
    importando = _processo_rodando(_import_proc, IMPORT_PID)
    from flask import jsonify
    return jsonify({
        "rodando": rodando,
        "importando": importando,
        "log": SCRAPER_LOG.read_text(encoding="utf-8", errors="replace") if SCRAPER_LOG.exists() else "",
        "import_log": IMPORT_LOG.read_text(encoding="utf-8", errors="replace") if IMPORT_LOG.exists() else "",
    })


@app.route("/admin/scraper", methods=["GET", "POST"])
def admin_scraper():
    if not session.get("admin_ok"):
        return redirect(url_for("admin_login"))

    if request.method == "POST":
        if not SCRAPER_LOCAL:
            flash("O scraper só roda na máquina de casa. Aqui, use apenas "
                  '"Carregar Excel → Banco" ou o botão de deploy.', "warning")
            return redirect(url_for("admin_scraper"))

        listas = request.form.getlist("listas")
        forcar = request.form.get("forcar") == "1"
        turma_scraper = request.form.get("turma", "7ano")
        if turma_scraper not in ("7ano", "8ano"):
            turma_scraper = "7ano"
        session["scraper_turma"] = turma_scraper

        if not listas:
            flash("Selecione pelo menos uma lista.", "warning")
            return redirect(url_for("admin_scraper"))

        # Encerra processo anterior se ainda estiver rodando
        proc = _scraper_proc.get("proc")
        if proc and proc.poll() is None:
            proc.terminate()

        cmd = [sys.executable, "-u", str(BASE_DIR / "run_importacao.py"), "--lista"] + listas
        if forcar:
            cmd.append("--forcar")

        log_file = open(SCRAPER_LOG, "w", encoding="utf-8")
        usuario = request.form.get("plurall_usuario", "").strip()
        senha   = request.form.get("plurall_senha", "").strip()
        if not usuario or not senha:
            flash("Informe o usuário e senha do Plurall.", "warning")
            return redirect(url_for("admin_scraper"))

        # Guarda na sessão para pré-preencher da próxima vez
        session["plurall_usuario"] = usuario
        session["plurall_senha"]   = senha

        env = os.environ.copy()
        env["PYTHONIOENCODING"]  = "utf-8"
        env["PLURALL_USUARIO"]   = usuario
        env["PLURALL_SENHA"]     = senha
        env["SCRAPER_TURMA"]     = turma_scraper

        proc = subprocess.Popen(
            cmd, stdout=log_file, stderr=subprocess.STDOUT,
            cwd=str(BASE_DIR), env=env
        )
        _scraper_proc["proc"] = proc
        _scraper_proc["log_file"] = log_file
        SCRAPER_PID.write_text(str(proc.pid))

        flash(f"Importação iniciada para: {', '.join(listas)}.", "success")
        return redirect(url_for("admin_scraper"))

    log = SCRAPER_LOG.read_text(encoding="utf-8", errors="replace") if SCRAPER_LOG.exists() else ""
    import_log = IMPORT_LOG.read_text(encoding="utf-8", errors="replace") if IMPORT_LOG.exists() else ""
    rodando = _processo_rodando(_scraper_proc, SCRAPER_PID)
    importando = _processo_rodando(_import_proc, IMPORT_PID)
    listas_db = {r[0] for r in db.session.query(Questao.lista_ph).distinct().all()}
    listas_possiveis = sorted(listas_db | {f"PH{i:02d}" for i in range(1, 25)})

    return render_template(
        "admin_scraper.html",
        log=log,
        import_log=import_log,
        rodando=rodando,
        importando=importando,
        listas=listas_possiveis,
        plurall_usuario=session.get("plurall_usuario", ""),
        plurall_senha=session.get("plurall_senha", ""),
        turma=session.get("scraper_turma", "7ano"),
        scraper_local=SCRAPER_LOCAL,
    )


# ---------------------------------------------------------------------------
# API de sincronizacao — o AtualizarBanco.exe (PC do Miguel) usa isto:
#   GET  /admin/xlsx  -> baixa o questoes.xlsx atual (pra raspar a partir dele)
#   POST /admin/xlsx  -> envia o xlsx novo (+ zip de imagens) e reimporta
# Autenticacao: header X-Upload-Token == env UPLOAD_TOKEN, ou sessao admin.
# ---------------------------------------------------------------------------

UPLOAD_TOKEN = os.environ.get("UPLOAD_TOKEN", "")
XLSX_PATH = BASE_DIR / "questoes.xlsx"
IMAGENS_DIR = BASE_DIR / "static" / "imagens"
BACKUPS_DIR = BASE_DIR / "backups"


def _sync_autorizado():
    if session.get("admin_ok"):
        return True
    tok = request.headers.get("X-Upload-Token") or request.form.get("token") or request.args.get("token")
    return bool(UPLOAD_TOKEN) and tok == UPLOAD_TOKEN


@app.route("/admin/xlsx", methods=["GET"])
def admin_xlsx_download():
    if not _sync_autorizado():
        return "nao autorizado", 403
    if not XLSX_PATH.exists():
        return "questoes.xlsx nao encontrado", 404
    return send_from_directory(BASE_DIR, "questoes.xlsx", as_attachment=True)


@app.route("/admin/xlsx", methods=["POST"])
def admin_xlsx_upload():
    if not _sync_autorizado():
        return "nao autorizado", 403

    arquivo = request.files.get("xlsx")
    if not arquivo or not arquivo.filename:
        return "faltou o arquivo 'xlsx'", 400

    BACKUPS_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if XLSX_PATH.exists():
        shutil.copy(XLSX_PATH, BACKUPS_DIR / f"questoes.xlsx.{ts}")
    db_file = BASE_DIR / "instance" / "simuladoph.db"
    if db_file.exists():
        shutil.copy(db_file, BACKUPS_DIR / f"simuladoph.db.{ts}")

    arquivo.save(str(XLSX_PATH))

    novas_imgs = 0
    zip_imgs = request.files.get("imagens")
    if zip_imgs and zip_imgs.filename:
        IMAGENS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(zip_imgs) as z:
                for nome in z.namelist():
                    base = os.path.basename(nome)
                    if not base or nome.endswith("/") or ".." in nome:
                        continue
                    (IMAGENS_DIR / base).write_bytes(z.read(nome))
                    novas_imgs += 1
        except zipfile.BadZipFile:
            return "zip de imagens invalido", 400

    proc = subprocess.run(
        [sys.executable, "-u", str(BASE_DIR / "importar_questoes.py")],
        capture_output=True, text=True, cwd=str(BASE_DIR),
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    saida = (proc.stdout + proc.stderr)[-4000:]
    if proc.returncode != 0:
        return {"ok": False, "imagens": novas_imgs, "log": saida}, 500
    return {"ok": True, "imagens": novas_imgs, "log": saida}


# ---------------------------------------------------------------------------
# Recuperação de senha
# ---------------------------------------------------------------------------

def gerar_token(email):
    s = URLSafeTimedSerializer(app.secret_key)
    return s.dumps(email, salt="recuperar-senha")

def verificar_token(token, expiracao=3600):
    s = URLSafeTimedSerializer(app.secret_key)
    try:
        email = s.loads(token, salt="recuperar-senha", max_age=expiracao)
    except Exception:
        return None
    return email


@app.route("/esqueci-senha", methods=["GET", "POST"])
def esqueci_senha():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        usuario = Usuario.query.filter_by(email=email).first()
        # Mesmo se não encontrar, mostra a mesma mensagem (segurança)
        if usuario:
            token = gerar_token(email)
            link = url_for("resetar_senha", token=token, _external=True)
            requests.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {os.environ.get('RESEND_API_KEY')}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": "SimuladoPH <onboarding@resend.dev>",
                    "to": [email],
                    "subject": "SimuladoPH — Recuperação de senha",
                    "html": f"""
                    <div style="font-family:Arial,sans-serif;max-width:480px;margin:auto;">
                    <h2 style="color:#4338ca;">SimuladoPH 📚</h2>
                    <p>Olá, <strong>{usuario.nome}</strong>!</p>
                    <p>Clique no botão abaixo para criar uma nova senha. Válido por 1 hora.</p>
                    <a href="{link}" style="display:inline-block;background:#4338ca;color:#fff;
                        padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:bold;margin:16px 0;">
                        Redefinir senha
                    </a>
                    </div>
                    """,
                },
                timeout=10
            )

        flash("Se esse e-mail estiver cadastrado, você receberá as instruções em breve.", "success")
        return redirect(url_for("login"))
    return render_template("esqueci_senha.html")


@app.route("/resetar-senha/<token>", methods=["GET", "POST"])
def resetar_senha(token):
    email = verificar_token(token)
    if not email:
        flash("Link inválido ou expirado. Solicite um novo.", "danger")
        return redirect(url_for("esqueci_senha"))

    if request.method == "POST":
        nova_senha = request.form["senha"]
        usuario = Usuario.query.filter_by(email=email).first()
        if usuario:
            usuario.senha_hash = generate_password_hash(nova_senha)
            db.session.commit()
            flash("Senha alterada com sucesso! Faça login.", "success")
            return redirect(url_for("login"))

    return render_template("resetar_senha.html", token=token)

# ---------------------------------------------------------------------------
# Migração automática — adiciona colunas novas sem apagar dados existentes
# ---------------------------------------------------------------------------

def _migrar_banco():
    with app.app_context():
        inspector = sa_inspect(db.engine)
        if "simulados" not in inspector.get_table_names():
            return
        colunas = {c["name"] for c in inspector.get_columns("simulados")}
        with db.engine.connect() as conn:
            if "fila_json" not in colunas:
                conn.execute(text("ALTER TABLE simulados ADD COLUMN fila_json TEXT"))
                conn.commit()
                print("Migração: coluna fila_json adicionada.")
            if "embaralhar_alternativas" not in colunas:
                conn.execute(text("ALTER TABLE simulados ADD COLUMN embaralhar_alternativas BOOLEAN NOT NULL DEFAULT TRUE"))
                conn.commit()
                print("Migração: coluna embaralhar_alternativas adicionada.")

        # Para tabela usuarios
        cols_usuarios = {c["name"] for c in inspector.get_columns("usuarios")}
        with db.engine.connect() as conn:
            if "turma" not in cols_usuarios:
                conn.execute(text("ALTER TABLE usuarios ADD COLUMN turma VARCHAR(10) NOT NULL DEFAULT '7ano'"))
                conn.commit()
                print("Migração: coluna turma adicionada em usuarios.")

        cols_questoes = {c["name"] for c in inspector.get_columns("questoes")}
        with db.engine.connect() as conn:
            if "turma" not in cols_questoes:
                conn.execute(text("ALTER TABLE questoes ADD COLUMN turma VARCHAR(10) NOT NULL DEFAULT '7ano'"))
                conn.commit()
                print("Migração: coluna turma adicionada em questoes.")

_migrar_banco()

# ---------------------------------------------------------------------------
# Inicialização
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
