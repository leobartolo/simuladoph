from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()


class Usuario(UserMixin, db.Model):
    __tablename__ = "usuarios"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    senha_hash = db.Column(db.String(256), nullable=False)
    criado_em = db.Column(db.DateTime, default=datetime.now)

    simulados = db.relationship("Simulado", backref="usuario", lazy=True)


class Questao(db.Model):
    __tablename__ = "questoes"
    id = db.Column(db.Integer, primary_key=True)
    enunciado = db.Column(db.Text, nullable=False)
    lista_ph = db.Column(db.String(10), nullable=False)
    disciplina = db.Column(db.String(60), nullable=False)
    gabarito = db.Column(db.String(1), nullable=False)  # A, B, C ou D (original)
    explicacao = db.Column(db.Text, default="")
    imagem = db.Column(db.String(120), nullable=True)

    alternativas = db.relationship(
        "Alternativa", backref="questao", lazy=True, order_by="Alternativa.letra"
    )

    def alt_dict(self):
        """Retorna {letra: texto} para as 4 alternativas."""
        return {a.letra: a.texto for a in self.alternativas}


class Alternativa(db.Model):
    __tablename__ = "alternativas"
    id = db.Column(db.Integer, primary_key=True)
    questao_id = db.Column(db.Integer, db.ForeignKey("questoes.id"), nullable=False)
    letra = db.Column(db.String(1), nullable=False)   # A, B, C, D (original)
    texto = db.Column(db.Text, nullable=False)


class Simulado(db.Model):
    __tablename__ = "simulados"
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    listas = db.Column(db.String(200), nullable=False)        # "PH1,PH2,..."
    disciplinas = db.Column(db.String(200), nullable=False)      # "Matemática,..."
    acertos_para_eliminar = db.Column(db.Integer, default=3)  # 1=Fácil 2=Médio 3=Difícil 4=Impossível
    rodada_atual = db.Column(db.Integer, default=1)
    criado_em = db.Column(db.DateTime, default=datetime.now)
    encerrado_em = db.Column(db.DateTime, nullable=True)

    fila_json = db.Column(db.Text, nullable=True)   # IDs da fila atual (JSON) para retomada
    itens = db.relationship("SimuladoQuestao", backref="simulado", lazy=True)


class SimuladoQuestao(db.Model):
    """Cada linha = uma questão dentro de um simulado, com seu progresso."""
    __tablename__ = "simulado_questoes"
    id = db.Column(db.Integer, primary_key=True)
    simulado_id = db.Column(db.Integer, db.ForeignKey("simulados.id"), nullable=False)
    questao_id = db.Column(db.Integer, db.ForeignKey("questoes.id"), nullable=False)
    acertos_seguidos = db.Column(db.Integer, default=0)
    eliminada = db.Column(db.Boolean, default=False)   # True = acertou 3x seguidas
    # Ordem embaralhada para a rodada atual (json list)
    ordem_alternativas = db.Column(db.Text, default="")   # "B,D,A,C" — mapeamento embaralhado

    questao = db.relationship("Questao")

    def set_ordem(self, lista_letras):
        self.ordem_alternativas = ",".join(lista_letras)

    def get_ordem(self):
        if self.ordem_alternativas:
            return self.ordem_alternativas.split(",")
        return ["A", "B", "C", "D"]

    def letra_correta_embaralhada(self):
        """Retorna a letra (A-D) que aparece na tela correspondente ao gabarito real."""
        letras_orig = ["A", "B", "C", "D"]
        ordem = self.get_ordem()           # ex: ["C","A","D","B"]
        gabarito_orig = self.questao.gabarito
        pos = ordem.index(gabarito_orig)   # posição na lista embaralhada
        return letras_orig[pos]            # letra exibida ao aluno


class Resposta(db.Model):
    __tablename__ = "respostas"
    id = db.Column(db.Integer, primary_key=True)
    simulado_id = db.Column(db.Integer, db.ForeignKey("simulados.id"), nullable=False)
    questao_id = db.Column(db.Integer, db.ForeignKey("questoes.id"), nullable=False)
    rodada = db.Column(db.Integer, nullable=False)
    letra_escolhida = db.Column(db.String(1), nullable=False)   # letra exibida
    correta = db.Column(db.Boolean, nullable=False)
    respondida_em = db.Column(db.DateTime, default=datetime.now)
