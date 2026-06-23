import os
import random
from datetime import datetime

from flask import Flask, render_template, redirect, url_for, request, flash, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

from models import db, Usuario, Questao, Alternativa, Simulado, SimuladoQuestao, Resposta

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

LETRAS = ["A", "B", "C", "D"]
# threshold de acertos definido por simulado (vem do campo acertos_para_eliminar)


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
            u = Usuario(nome=nome, email=email,
                        senha_hash=generate_password_hash(senha))
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
    # Resumo rápido por simulado
    resumos = []
    for s in simulados:
        total = len(s.itens)
        eliminadas = sum(1 for i in s.itens if i.eliminada)
        resumos.append({
            "simulado": s,
            "total": total,
            "eliminadas": eliminadas,
            "restantes": total - eliminadas,
            "concluido": s.encerrado_em is not None,
        })
    return render_template("dashboard.html", resumos=resumos)


# ---------------------------------------------------------------------------
# Novo simulado
# ---------------------------------------------------------------------------

@app.route("/novo", methods=["GET", "POST"])
@login_required
def novo_simulado():
    listas_disponiveis = sorted(
        db.session.query(Questao.lista_ph).distinct().all(), key=lambda x: x[0]
    )
    disciplinas_disponiveis = sorted(
        db.session.query(Questao.disciplina).distinct().all(), key=lambda x: x[0]
    )
    listas_disponiveis = [r[0] for r in listas_disponiveis]
    disciplinas_disponiveis = [r[0] for r in disciplinas_disponiveis]

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
            .all()
        )
        if not questoes:
            flash("Nenhuma questão encontrada para os filtros selecionados.", "warning")
            return redirect(url_for("novo_simulado"))

        quantidade = min(quantidade, len(questoes))
        sorteadas = random.sample(questoes, quantidade)

        dificuldade = int(request.form.get("dificuldade", 3))
        dificuldade = max(1, min(4, dificuldade))  # garante 1-4

        simulado = Simulado(
            usuario_id=current_user.id,
            listas=",".join(listas),
            disciplinas=",".join(disciplinas),
            acertos_para_eliminar=dificuldade,
        )
        db.session.add(simulado)
        db.session.flush()   # pega o id antes do commit

        for q in sorteadas:
            ordem = LETRAS[:]
            random.shuffle(ordem)
            sq = SimuladoQuestao(simulado_id=simulado.id, questao_id=q.id)
            sq.set_ordem(ordem)
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
        s.encerrado_em = datetime.utcnow()
        db.session.commit()
        return redirect(url_for("resultado_final", simulado_id=simulado_id))

    # Reembaralha as alternativas a cada nova rodada
    for item in itens:
        ordem = LETRAS[:]
        random.shuffle(ordem)
        item.set_ordem(ordem)
    db.session.commit()

    # Guarda a fila da rodada na sessão
    session[f"fila_{simulado_id}"] = [i.id for i in itens]
    session[f"rodada_acertos_{simulado_id}"] = 0
    session[f"rodada_total_{simulado_id}"] = len(itens)

    return redirect(url_for("questao", simulado_id=simulado_id))


@app.route("/simulado/<int:simulado_id>/questao", methods=["GET"])
@login_required
def questao(simulado_id):
    s = db.session.get(Simulado, simulado_id)
    if not s or s.usuario_id != current_user.id:
        return redirect(url_for("dashboard"))

    fila = session.get(f"fila_{simulado_id}", [])
    if not fila:
        return redirect(url_for("resultado_rodada", simulado_id=simulado_id))

    item_id = fila[0]
    item = db.session.get(SimuladoQuestao, item_id)
    q = item.questao

    # Monta as alternativas na ordem embaralhada
    alt_dict = q.alt_dict()
    ordem = item.get_ordem()   # ["C","A","D","B"] — letras ORIGINAIS embaralhadas
    alternativas_exibidas = [
        {"letra_exibida": LETRAS[i], "texto": alt_dict[ordem[i]]}
        for i in range(4)
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

    # Remove da fila
    fila = session.get(f"fila_{simulado_id}", [])
    if item_id in fila:
        fila.remove(item_id)
    session[f"fila_{simulado_id}"] = fila

    db.session.commit()

    # Monta texto da alternativa escolhida e da correta para o feedback
    alt_dict = q.alt_dict()
    ordem = item.get_ordem()

    def texto_de(letra_exibida):
        idx = LETRAS.index(letra_exibida)
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

    # Avança o contador de rodada
    s.rodada_atual += 1
    db.session.commit()

    concluido = itens_ativos == 0
    if concluido:
        s.encerrado_em = datetime.utcnow()
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

@app.route("/admin/reset-senha/<email>/<nova_senha>")
def reset_senha(email, nova_senha):
    u = Usuario.query.filter_by(email=email).first()
    if not u:
        return "Usuário não encontrado"
    u.senha_hash = generate_password_hash(nova_senha)
    db.session.commit()
    return f"Senha de {u.nome} alterada com sucesso!"

@app.route("/admin/listar-usuarios")
def listar_usuarios():
    usuarios = Usuario.query.all()
    return "<br>".join([f"{u.id} - {u.nome} - {u.email}" for u in usuarios])

# ---------------------------------------------------------------------------
# Inicialização
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
