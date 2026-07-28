from __future__ import annotations

import collections
import json
import logging
import os
import secrets
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv
from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    stream_with_context,
    url_for,
)
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import and_, func, or_, text
from sqlalchemy.orm.attributes import flag_modified
from werkzeug.security import check_password_hash, generate_password_hash

from security_utils import encrypt_secret, has_secret

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
IS_PRODUCTION = APP_ENV == "production"

app = Flask(__name__)

secret_key = os.getenv("FLASK_SECRET_KEY", "").strip()
if IS_PRODUCTION and len(secret_key) < 32:
    raise RuntimeError("FLASK_SECRET_KEY must contain at least 32 characters in production")
app.secret_key = secret_key or secrets.token_urlsafe(32)

app.config.update(
    MAX_CONTENT_LENGTH=int(os.getenv("MAX_CONTENT_LENGTH_MB", "10")) * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=_env_bool("SESSION_COOKIE_SECURE", IS_PRODUCTION),
    SESSION_COOKIE_SAMESITE=os.getenv("SESSION_COOKIE_SAMESITE", "Lax"),
    PERMANENT_SESSION_LIFETIME=timedelta(hours=int(os.getenv("SESSION_HOURS", "8"))),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
)

instance_dir = BASE_DIR / "instance"
instance_dir.mkdir(exist_ok=True)
default_database = f"sqlite:///{(instance_dir / 'helpdesk.db').as_posix()}"
database_url = os.getenv("DATABASE_URL", default_database).strip()
app.config["SQLALCHEMY_DATABASE_URI"] = database_url
if not database_url.startswith("sqlite"):
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_size": int(os.getenv("DB_POOL_SIZE", "5")),
        "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "10")),
        "pool_timeout": int(os.getenv("DB_POOL_TIMEOUT", "30")),
        "pool_recycle": int(os.getenv("DB_POOL_RECYCLE", "1800")),
        "pool_pre_ping": True,
    }

db = SQLAlchemy(app)
allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "SOCKETIO_ALLOWED_ORIGINS",
        "http://localhost:5000,http://127.0.0.1:5000",
    ).split(",")
    if origin.strip()
]
socketio = SocketIO(
    app,
    cors_allowed_origins=allowed_origins,
    async_mode=os.getenv("SOCKETIO_ASYNC_MODE", "threading"),
    manage_session=True,
)

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("helpdesk")


@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), geolocation=(), payment=()")
    response.headers.setdefault(
        "Content-Security-Policy",
        os.getenv(
            "CONTENT_SECURITY_POLICY",
            "default-src 'self'; img-src 'self' data: https:; media-src 'self' blob: data:; "
            "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline' https://cdn.socket.io; "
            "connect-src 'self' ws: wss:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'",
        ),
    )
    return response


@app.before_request
def validate_same_origin_for_writes():
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None
    origin = (request.headers.get("Origin") or "").rstrip("/")
    if not origin:
        return None
    trusted = {request.host_url.rstrip("/"), *allowed_origins}
    if origin not in trusted:
        return jsonify({"error": "Origem não autorizada"}), 403
    return None


@app.before_request
def enforce_privileged_domains():
    """Protect inventory and local-AI endpoints with an explicit admin boundary."""
    protected_prefixes = ("/api/it/", "/api/ia/")
    if not request.path.startswith(protected_prefixes):
        return None
    if "usuario" not in session:
        return jsonify({"error": "Autenticação necessária"}), 401
    if not _current_chat_is_admin():
        return jsonify({"error": "Acesso negado"}), 403
    return None


@app.get("/health")
def healthcheck():
    return jsonify({"status": "ok", "service": "helpdesk-it-operations"}), 200


# -------------------------------
# Configurações Globais e Fuso Horário
# -------------------------------
def get_now():
    """Return a naive datetime normalized to America/Sao_Paulo for legacy columns."""
    return datetime.now(ZoneInfo("America/Sao_Paulo")).replace(tzinfo=None)

# ── Rate limiter simples (sem dependência extra) ─────────────────────────────
# Armazena timestamps de tentativas por IP: {ip: deque([t1, t2, ...])}
_login_attempts: dict = collections.defaultdict(collections.deque)
_LOGIN_MAX_ATTEMPTS = 10       # máximo de tentativas
_LOGIN_WINDOW_SECONDS = 60    # janela de tempo (segundos)

def _is_rate_limited(ip: str) -> bool:
    """Retorna True se o IP excedeu o limite de tentativas de login."""
    now = time.monotonic()
    dq = _login_attempts[ip]
    # Remove entradas antigas fora da janela
    while dq and now - dq[0] > _LOGIN_WINDOW_SECONDS:
        dq.popleft()
    if len(dq) >= _LOGIN_MAX_ATTEMPTS:
        return True
    dq.append(now)
    return False

# Rate limiter para mensagens do chat (10 mensagens a cada 5 segundos por usuário)
_chat_rate_limit: dict = collections.defaultdict(collections.deque)
_CHAT_MAX_MSG = 10
_CHAT_WINDOW = 5

def _is_chat_rate_limited(username: str) -> bool:
    now = time.monotonic()
    dq = _chat_rate_limit[username]
    while dq and now - dq[0] > _CHAT_WINDOW:
        dq.popleft()
    if len(dq) >= _CHAT_MAX_MSG:
        return True
    dq.append(now)
    return False

# ── Decorator de autenticação ────────────────────────────────────────────────
def login_required(f):
    """Rejeita requisições não autenticadas com 401."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "usuario" not in session:
            # Retorna JSON para rotas de API, redirect para rotas de página
            if request.path.startswith("/api/"):
                return jsonify({"error": "Autenticação necessária"}), 401
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return decorated


# ================================
# Ticket Model (existing)
# ================================
class Ticket(db.Model):
    __tablename__ = "tickets"

    id = db.Column(db.String(8), primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    titulo = db.Column(db.String(200), nullable=False, default="Sem título")
    descricao = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=get_now)
    status = db.Column(db.String(20), default="Aberto")
    prioridade = db.Column(db.String(20), default="media")
    responsavel = db.Column(db.String(100))
    categoria = db.Column(db.String(100), default="Geral")
    tempoEstimado = db.Column(db.String(20), default="2h")
    tempoGasto = db.Column(db.String(20), default="0h")
    dataVencimento = db.Column(db.String(20))
    historico = db.Column(db.JSON, default=list)
    comentarios = db.Column(db.JSON, default=list)
    anexos = db.Column(db.JSON, default=list)
    cliente = db.Column(db.JSON, default=dict)
    dataFechamento = db.Column(db.DateTime, nullable=True)
    checklist = db.Column(db.Text)

    def to_dict(self):
        return {
            "id": self.id, "nome": self.nome, "titulo": self.titulo,
            "descricao": self.descricao,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "status": self.status, "prioridade": self.prioridade,
            "responsavel": self.responsavel, "categoria": self.categoria,
            "tempoEstimado": self.tempoEstimado, "tempoGasto": self.tempoGasto,
            "dataVencimento": self.dataVencimento, "historico": self.historico,
            "comentarios": self.comentarios, "anexos": self.anexos,
            "cliente": self.cliente,
            "dataFechamento": self.dataFechamento.isoformat() if self.dataFechamento else None,
            "checklist": self.checklist,
        }


# ================================
# IT Control Models
# ================================

class ITUser(db.Model):
    __tablename__ = "it_users"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nome = db.Column(db.String(150), nullable=False)
    cargo = db.Column(db.String(100))
    setor = db.Column(db.String(100))
    email_corporativo = db.Column(db.String(200))
    ramal = db.Column(db.String(20))
    cabo_rede = db.Column(db.String(50))
    ip = db.Column(db.String(50))
    status = db.Column(db.String(20), default="Ativo")
    data_entrada = db.Column(db.Date, nullable=True)
    data_saida = db.Column(db.Date, nullable=True)
    responsavel_ti = db.Column(db.String(100))
    obs = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=get_now)
    updated_at = db.Column(db.DateTime, default=get_now, onupdate=datetime.now)

    pc = db.relationship("ITPC", backref="user", uselist=False, cascade="all, delete-orphan")
    contas = db.relationship("ITConta", backref="user", cascade="all, delete-orphan")
    emails = db.relationship("ITEmail", backref="user", cascade="all, delete-orphan")
    certificados = db.relationship("ITCertificado", backref="user", cascade="all, delete-orphan")
    programas = db.relationship("ITPrograma", backref="user", cascade="all, delete-orphan")
    sticky_notes = db.relationship("ITStickyNote", backref="user",
                                   cascade="all, delete-orphan",
                                   foreign_keys="ITStickyNote.it_user_id")

    def to_dict(self, full=False):
        d = {
            "id": self.id, "nome": self.nome, "cargo": self.cargo,
            "setor": self.setor, "email_corporativo": self.email_corporativo,
            "ramal": self.ramal, "cabo_rede": self.cabo_rede, "ip": self.ip,
            "status": self.status,
            "data_entrada": self.data_entrada.isoformat() if self.data_entrada else None,
            "data_saida": self.data_saida.isoformat() if self.data_saida else None,
            "responsavel_ti": self.responsavel_ti, "obs": self.obs,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if full:
            d["pc"] = self.pc.to_dict() if self.pc else None
            d["contas"] = [c.to_dict() for c in self.contas]
            d["emails"] = [e.to_dict() for e in self.emails]
            d["certificados"] = [c.to_dict() for c in self.certificados]
            d["programas"] = [p.to_dict() for p in self.programas]
        return d


class ITPC(db.Model):
    __tablename__ = "it_pcs"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    it_user_id = db.Column(db.Integer, db.ForeignKey("it_users.id"), nullable=True)
    hostname = db.Column(db.String(100))
    num_serie = db.Column(db.String(100))
    num_patrimonio = db.Column(db.String(100))
    fabricante = db.Column(db.String(100))
    modelo = db.Column(db.String(100))
    data_compra = db.Column(db.Date, nullable=True)
    data_garantia_fim = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(30), default="Em Uso")
    monitor = db.Column(db.String(200))
    mouse_pad = db.Column(db.String(200))
    mouse = db.Column(db.String(200))
    teclado = db.Column(db.String(200))
    gabinete = db.Column(db.String(200))
    processador = db.Column(db.String(200))
    ram = db.Column(db.String(200))
    placa_mae = db.Column(db.String(200))
    placa_video = db.Column(db.String(200))
    placa_rede = db.Column(db.String(200))
    fonte = db.Column(db.String(200))
    hdds = db.Column(db.Text)
    obs = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=get_now)
    updated_at = db.Column(db.DateTime, default=get_now, onupdate=datetime.now)

    manutencoes = db.relationship("ITManutencao", backref="pc", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id, "it_user_id": self.it_user_id, "hostname": self.hostname,
            "num_serie": self.num_serie, "num_patrimonio": self.num_patrimonio,
            "fabricante": self.fabricante, "modelo": self.modelo,
            "data_compra": self.data_compra.isoformat() if self.data_compra else None,
            "data_garantia_fim": self.data_garantia_fim.isoformat() if self.data_garantia_fim else None,
            "status": self.status, "monitor": self.monitor, "mouse_pad": self.mouse_pad,
            "mouse": self.mouse, "teclado": self.teclado, "gabinete": self.gabinete,
            "processador": self.processador, "ram": self.ram, "placa_mae": self.placa_mae,
            "placa_video": self.placa_video, "placa_rede": self.placa_rede,
            "fonte": self.fonte, "hdds": self.hdds, "obs": self.obs,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "manutencoes": [m.to_dict() for m in self.manutencoes],
        }


class ITConta(db.Model):
    __tablename__ = "it_contas"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    it_user_id = db.Column(db.Integer, db.ForeignKey("it_users.id"), nullable=False)
    sistema = db.Column(db.String(100), nullable=False)
    nome_custom = db.Column(db.String(100))
    login = db.Column(db.String(200))
    senha = db.Column(db.Text)
    acessos = db.Column(db.Text)
    data_criacao = db.Column(db.Date, nullable=True)
    data_ultima_revisao = db.Column(db.Date, nullable=True)
    obs = db.Column(db.Text)

    def to_dict(self):
        return {
            "id": self.id, "it_user_id": self.it_user_id, "sistema": self.sistema,
            "nome_custom": self.nome_custom, "login": self.login, "senha": None, "has_secret": has_secret(self.senha),
            "acessos": self.acessos,
            "data_criacao": self.data_criacao.isoformat() if self.data_criacao else None,
            "data_ultima_revisao": self.data_ultima_revisao.isoformat() if self.data_ultima_revisao else None,
            "obs": self.obs,
        }


class ITEmail(db.Model):
    __tablename__ = "it_emails"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    it_user_id = db.Column(db.Integer, db.ForeignKey("it_users.id"), nullable=False)
    endereco = db.Column(db.String(200), nullable=False)
    servidor = db.Column(db.String(100))
    login = db.Column(db.String(200))
    senha = db.Column(db.Text)
    obs = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=get_now)

    def to_dict(self):
        return {
            "id": self.id, "it_user_id": self.it_user_id, "endereco": self.endereco,
            "servidor": self.servidor, "login": self.login, "senha": None, "has_secret": has_secret(self.senha),
            "obs": self.obs,
        }


class ITCertificado(db.Model):
    __tablename__ = "it_certificados"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    it_user_id = db.Column(db.Integer, db.ForeignKey("it_users.id"), nullable=False)
    tipo = db.Column(db.String(100), nullable=False)
    nome_outro = db.Column(db.String(200))
    versao = db.Column(db.String(100))
    chave = db.Column(db.Text)
    validade = db.Column(db.Date, nullable=True)
    fornecedor = db.Column(db.String(200))
    obs = db.Column(db.Text)

    def to_dict(self):
        return {
            "id": self.id, "it_user_id": self.it_user_id, "tipo": self.tipo,
            "nome_outro": self.nome_outro, "versao": self.versao, "chave": None, "has_secret": has_secret(self.chave),
            "validade": self.validade.isoformat() if self.validade else None,
            "fornecedor": self.fornecedor, "obs": self.obs,
        }


class ITPrograma(db.Model):
    __tablename__ = "it_programas"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    it_user_id = db.Column(db.Integer, db.ForeignKey("it_users.id"), nullable=False)
    nome = db.Column(db.String(200), nullable=False)
    versao = db.Column(db.String(100))
    chave = db.Column(db.Text)
    categoria = db.Column(db.String(100))
    obs = db.Column(db.Text)

    def to_dict(self):
        return {
            "id": self.id, "it_user_id": self.it_user_id, "nome": self.nome,
            "versao": self.versao, "chave": None, "has_secret": has_secret(self.chave),
            "categoria": self.categoria, "obs": self.obs,
        }


class ITStickyNote(db.Model):
    __tablename__ = "it_sticky_notes"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    it_user_id = db.Column(db.Integer, db.ForeignKey("it_users.id"), nullable=True)
    titulo = db.Column(db.String(200))
    conteudo = db.Column(db.Text)
    tags = db.Column(db.JSON, default=list)
    color = db.Column(db.String(20), default="yellow")
    created_at = db.Column(db.DateTime, default=get_now)
    updated_at = db.Column(db.DateTime, default=get_now, onupdate=datetime.now)

    def to_dict(self):
        return {
            "id": self.id, "it_user_id": self.it_user_id, "titulo": self.titulo,
            "conteudo": self.conteudo, "tags": self.tags or [], "color": self.color,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ITManutencao(db.Model):
    __tablename__ = "it_manutencoes"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    it_pc_id = db.Column(db.Integer, db.ForeignKey("it_pcs.id"), nullable=False)
    tipo = db.Column(db.String(50))
    descricao = db.Column(db.Text)
    data = db.Column(db.Date, nullable=True)
    tecnico = db.Column(db.String(100))
    status = db.Column(db.String(50), default="Concluída")
    custo = db.Column(db.String(50))
    obs = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=get_now)

    def to_dict(self):
        return {
            "id": self.id, "it_pc_id": self.it_pc_id, "tipo": self.tipo,
            "descricao": self.descricao,
            "data": self.data.isoformat() if self.data else None,
            "tecnico": self.tecnico, "status": self.status,
            "custo": self.custo, "obs": self.obs,
        }


class ITAuditLog(db.Model):
    __tablename__ = "it_audit_log"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    tabela = db.Column(db.String(100))
    registro_id = db.Column(db.String(50))
    acao = db.Column(db.String(20))
    campo = db.Column(db.String(100))
    valor_anterior = db.Column(db.Text)
    valor_novo = db.Column(db.Text)
    usuario_sistema = db.Column(db.String(100))
    timestamp = db.Column(db.DateTime, default=get_now)

    def to_dict(self):
        return {
            "id": self.id, "tabela": self.tabela, "registro_id": self.registro_id,
            "acao": self.acao, "campo": self.campo,
            "valor_anterior": self.valor_anterior, "valor_novo": self.valor_novo,
            "usuario_sistema": self.usuario_sistema,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


def registrar_audit(tabela, registro_id, acao, campo="", valor_ant="", valor_novo=""):
    try:
        log = ITAuditLog(
            tabela=tabela, registro_id=str(registro_id), acao=acao,
            campo=campo, valor_anterior=str(valor_ant), valor_novo=str(valor_novo),
            usuario_sistema=session.get("usuario", "Sistema")
        )
        db.session.add(log)
    except Exception as e:
        logger.exception("Falha ao registrar auditoria")



# ================================
# Shared Resources Models
# ================================

class ITEmailGlobal(db.Model):
    """Global email registry — one email can be linked to many users/PCs."""
    __tablename__ = "it_emails_global"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    endereco = db.Column(db.String(200), nullable=False, unique=True)
    servidor = db.Column(db.String(100))       # Ex: Outlook, Thunderbird, Gmail
    login = db.Column(db.String(200))
    senha = db.Column(db.Text)
    tipo = db.Column(db.String(50), default="Corporativo")  # Corporativo/Pessoal/Suporte
    obs = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=get_now)
    updated_at = db.Column(db.DateTime, default=get_now, onupdate=datetime.now)

    vinculos = db.relationship("ITEmailVinculo", backref="email", cascade="all, delete-orphan")

    def to_dict(self, with_vinculos=False):
        d = {
            "id": self.id, "endereco": self.endereco, "servidor": self.servidor,
            "login": self.login, "senha": None, "has_secret": has_secret(self.senha), "tipo": self.tipo,
            "obs": self.obs,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if with_vinculos:
            d["vinculos"] = [v.to_dict() for v in self.vinculos]
        return d


class ITEmailVinculo(db.Model):
    """Association: email ↔ user (with optional PC context)."""
    __tablename__ = "it_email_vinculos"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    email_id = db.Column(db.Integer, db.ForeignKey("it_emails_global.id"), nullable=False)
    it_user_id = db.Column(db.Integer, db.ForeignKey("it_users.id"), nullable=False)
    hostname_pc = db.Column(db.String(100))   # PC onde o e-mail está configurado
    cliente_email = db.Column(db.String(100)) # Ex: Thunderbird, Outlook, Webmail
    obs = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=get_now)

    user = db.relationship("ITUser", backref="email_vinculos")

    def to_dict(self):
        return {
            "id": self.id, "email_id": self.email_id, "it_user_id": self.it_user_id,
            "hostname_pc": self.hostname_pc, "cliente_email": self.cliente_email,
            "obs": self.obs,
            "user_nome": self.user.nome if self.user else None,
            "endereco": self.email.endereco if self.email else None,
        }


class ITNASPasta(db.Model):
    """NAS folder registry — shared folders mapped by drive letters."""
    __tablename__ = "it_nas_pastas"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nome = db.Column(db.String(200), nullable=False)         # Ex: "Projetos", "RH"
    caminho_rede = db.Column(db.String(500))                 # Ex: \\\\SERVIDOR\\Projetos
    descricao = db.Column(db.Text)
    obs = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=get_now)
    updated_at = db.Column(db.DateTime, default=get_now, onupdate=datetime.now)

    acessos = db.relationship("ITNASAcesso", backref="pasta", cascade="all, delete-orphan")

    def to_dict(self, with_acessos=False):
        d = {
            "id": self.id, "nome": self.nome, "caminho_rede": self.caminho_rede,
            "descricao": self.descricao, "obs": self.obs,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if with_acessos:
            d["acessos"] = [a.to_dict() for a in self.acessos]
        return d


class ITNASAcesso(db.Model):
    """Association: NAS folder ↔ user (with drive letter and permission)."""
    __tablename__ = "it_nas_acessos"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    pasta_id = db.Column(db.Integer, db.ForeignKey("it_nas_pastas.id"), nullable=False)
    it_user_id = db.Column(db.Integer, db.ForeignKey("it_users.id"), nullable=False)
    letra_mapeada = db.Column(db.String(5))      # Ex: G:, H:, Z:
    permissao = db.Column(db.String(30), default="Leitura")  # Leitura/Escrita/Admin
    obs = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=get_now)

    user = db.relationship("ITUser", backref="nas_acessos")

    def to_dict(self):
        return {
            "id": self.id, "pasta_id": self.pasta_id, "it_user_id": self.it_user_id,
            "letra_mapeada": self.letra_mapeada, "permissao": self.permissao,
            "obs": self.obs,
            "user_nome": self.user.nome if self.user else None,
            "pasta_nome": self.pasta.nome if self.pasta else None,
            "caminho_rede": self.pasta.caminho_rede if self.pasta else None,
        }


class UserShortcut(db.Model):
    """Atalhos personalizados por usuário."""
    __tablename__ = "user_shortcuts"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    usuario = db.Column(db.String(100), nullable=False, index=True)
    nome = db.Column(db.String(200), nullable=False)
    caminho = db.Column(db.String(500), nullable=False)
    icone = db.Column(db.String(50), default="📁")
    created_at = db.Column(db.DateTime, default=get_now)

    def to_dict(self):
        return {
            "id": self.id,
            "usuario": self.usuario,
            "nome": self.nome,
            "caminho": self.caminho,
            "icone": self.icone,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

class ITShortcut(db.Model):
    """Atalhos globais gerenciados pelo T.I."""
    __tablename__ = "it_shortcuts"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nome = db.Column(db.String(200), nullable=False)
    caminho = db.Column(db.String(500), nullable=False)
    icone = db.Column(db.String(50), default="📁")
    tags = db.Column(db.JSON, default=list)
    created_at = db.Column(db.DateTime, default=get_now)

    def to_dict(self):
        return {
            "id": self.id,
            "nome": self.nome,
            "caminho": self.caminho,
            "icone": self.icone,
            "tags": self.tags,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

# Local demo accounts are opt-in and configured only through environment variables.
# Production deployments should provision users through a dedicated identity process.
ENABLE_DEMO_AUTH = _env_bool("ENABLE_DEMO_AUTH", not IS_PRODUCTION)
CHAT_USERS: dict[str, dict] = {}
if ENABLE_DEMO_AUTH:
    demo_admin_username = os.getenv("DEMO_ADMIN_USERNAME", "demo_admin").strip().lower()
    demo_admin_password = os.getenv("DEMO_ADMIN_PASSWORD", "change-me-local")
    demo_user_username = os.getenv("DEMO_USER_USERNAME", "demo_user").strip().lower()
    demo_user_password = os.getenv("DEMO_USER_PASSWORD", "change-me-local")
    CHAT_USERS = {
        demo_admin_username: {
            "name": "Administrador de demonstração",
            "role": "TI / Administração",
            "avatar": "🛡️",
            "password": generate_password_hash(demo_admin_password),
            "profile": "master",
        },
        demo_user_username: {
            "name": "Usuário de demonstração",
            "role": "Colaborador",
            "avatar": "👤",
            "password": generate_password_hash(demo_user_password),
            "profile": "user",
        },
    }

# Kept as an empty compatibility map for older local databases.
usuarios: dict[str, str] = {}

# Usuários adicionados em runtime via painel admin (persistidos no DB)
class ChatUser(db.Model):
    __tablename__ = "chat_users_extra"
    id       = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    name     = db.Column(db.String(200), nullable=False)
    role     = db.Column(db.String(100))
    avatar   = db.Column(db.String(10), default="😊")
    password = db.Column(db.String(255), nullable=False)  # Werkzeug password hash
    profile  = db.Column(db.String(20), default="user")
    active   = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=get_now)

    def to_dict(self):
        return {"username": self.username, "name": self.name, "role": self.role,
                "avatar": self.avatar, "profile": self.profile}

class ChatMessage(db.Model):
    __tablename__ = "chat_messages"
    id        = db.Column(db.Integer, primary_key=True, autoincrement=True)
    room      = db.Column(db.String(150), nullable=False, index=True)
    from_user = db.Column(db.String(100), nullable=False)
    msg_type  = db.Column(db.String(20), default="text")   # text | image | file | audio
    content   = db.Column(db.Text)
    file_name = db.Column(db.String(300))
    file_size = db.Column(db.Integer)
    timestamp = db.Column(db.DateTime, default=get_now)
    deleted_at = db.Column(db.DateTime, nullable=True)
    deleted_by = db.Column(db.String(100), nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    visibility_mode = db.Column(db.String(20), default="normal")  # normal | once
    viewed_by = db.Column(db.JSON, default=list)
    reply_to_id = db.Column(db.Integer, nullable=True)
    edited_at = db.Column(db.DateTime, nullable=True)
    pinned = db.Column(db.Boolean, default=False)
    read_by = db.Column(db.JSON, default=list)

    def to_dict(self, viewer=None, force_visible=False, audit=False):
        viewer = (viewer or "").strip().lower()
        is_deleted = self.deleted_at is not None
        is_expired = self.expires_at is not None and self.expires_at <= get_now()
        mode = self.visibility_mode or "normal"
        viewed_by = self.viewed_by or []
        if isinstance(viewed_by, str):
            try:
                viewed_by = json.loads(viewed_by)
            except Exception:
                viewed_by = []
        opened_by_me = bool(viewer and viewer in viewed_by)
        read_by = self.read_by or []
        if isinstance(read_by, str):
            try:
                read_by = json.loads(read_by)
            except Exception:
                read_by = []
        is_once_hidden = mode == "once" and viewer != self.from_user and not force_visible
        hidden = not audit and (is_deleted or is_expired or is_once_hidden)
        reply_payload = None
        if self.reply_to_id:
            reply = db.session.get(ChatMessage, self.reply_to_id)
            if reply:
                reply_payload = {
                    "id": reply.id,
                    "from": reply.from_user,
                    "type": reply.msg_type,
                    "text": (reply.content or "")[:120] if reply.msg_type == "text" else (reply.file_name or reply.msg_type),
                }
        return {
            "id": self.id, "room": self.room, "from": self.from_user,
            "type": self.msg_type,
            "text": "" if hidden else (self.content if self.msg_type == "text" else ""),
            "data": None if hidden else (self.content if self.msg_type in ("image", "file", "audio") else None),
            "fileName": self.file_name, "fileSize": self.file_size,
            "ts": int(self.timestamp.timestamp() * 1000),
            "deleted": is_deleted,
            "deletedBy": self.deleted_by,
            "expiresAt": int(self.expires_at.timestamp() * 1000) if self.expires_at else None,
            "temporary": self.expires_at is not None,
            "visibilityMode": mode,
            "viewOnce": mode == "once",
            "openedByMe": opened_by_me,
            "contentAvailable": audit or (not is_deleted and not is_expired and (not opened_by_me or viewer == self.from_user)),
            "expired": is_expired,
            "auditVisible": bool(audit),
            "replyTo": reply_payload,
            "editedAt": int(self.edited_at.timestamp() * 1000) if self.edited_at else None,
            "pinned": bool(self.pinned),
            "readBy": read_by,
        }


class ChatAuditLog(db.Model):
    __tablename__ = "chat_audit_logs"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    action = db.Column(db.String(50), nullable=False)
    actor = db.Column(db.String(100), nullable=False)
    room = db.Column(db.String(150), index=True)
    message_id = db.Column(db.Integer, nullable=True)
    details = db.Column(db.JSON, default=dict)
    timestamp = db.Column(db.DateTime, default=get_now)

    def to_dict(self):
        return {
            "id": self.id,
            "action": self.action,
            "actor": self.actor,
            "room": self.room,
            "messageId": self.message_id,
            "details": self.details or {},
            "ts": int(self.timestamp.timestamp() * 1000),
        }

class ChatGroup(db.Model):
    __tablename__ = "chat_groups"
    id         = db.Column(db.String(50), primary_key=True)
    name       = db.Column(db.String(200), nullable=False)
    icon       = db.Column(db.String(10), default="📁")
    members    = db.Column(db.JSON, default=list)
    created_by = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=get_now)

    def to_dict(self):
        return {"id": self.id, "name": self.name, "icon": self.icon,
                "members": self.members or [], "createdBy": self.created_by}

# Rastreia usuários online: {username: sid}
_online_users: dict = {}


# -------------------------------
# Funções auxiliares
# -------------------------------
def gerar_id_ticket():
    return str(uuid.uuid4())[:8].upper()

def obter_timestamp():
    return get_now().strftime('%d/%m/%Y %H:%M')

def parse_date(val):
    if not val:
        return None
    try:
        return date.fromisoformat(val)
    except Exception:
        return None


# -------------------------------
# Rotas de autenticação
# -------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    # Se já estiver logado, vai para a raiz (que decide o destino)
    if "usuario" in session and request.method == "GET":
        next_page = request.args.get("next")
        return redirect(url_for("index_root", next=next_page) if next_page else url_for("index_root"))

    if request.method == "POST":
        ip = request.remote_addr or "unknown"
        if _is_rate_limited(ip):
            return jsonify({"message": "Muitas tentativas. Aguarde 1 minuto."}), 429
        data = request.get_json(force=True, silent=True) or {}
        username = data.get("username", "").strip().lower()
        password = data.get("password", "")
        auth_user = _authenticate_unified_user(username, password)
        if auth_user:
            _login_attempts.pop(ip, None)  # limpa contador após sucesso
            session["usuario"] = auth_user["username"]
            # Redireciona para o destino original ou para a raiz
            next_page = request.args.get("next") or "/"
            if not next_page.startswith("/") or next_page.startswith("//"):
                next_page = "/"
            return jsonify({"message": "Login realizado!", "redirect": next_page}), 200
        return jsonify({"message": "Usuário ou senha incorretos"}), 401
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("usuario", None)
    return redirect(url_for("login"))


@app.route("/usuario")
@login_required
def get_usuario_info():
    """Retorna o nome do usuário logado para o dashboard."""
    return jsonify({"usuario": session.get("usuario", "Visitante")})


# -------------------------------
# Rotas Principais e Versão do App
# -------------------------------
@app.route("/api/app-version")
def app_version():
    """Retorna a versão mais recente do Electron detectando automaticamente o .exe em static/dist."""
    import re as _re
    dist_dir = os.path.join(app.root_path, "static", "dist")
    version = "1.0.0"
    url = ""
    try:
        exes = [f for f in os.listdir(dist_dir) if f.lower().endswith(".exe")]
        if exes:
            # Ordena decrescente para pegar o mais recente pelo nome
            exes.sort(reverse=True)
            latest = exes[0]
            m = _re.search(r'(\d+\.\d+\.\d+)', latest)
            if m:
                version = m.group(1)
            url = request.url_root.rstrip("/") + url_for("static", filename=f"dist/{latest}")
    except Exception:
        pass
    return jsonify({
        "version": version,
        "url": url,
        "notes": "Atualiza\u00e7\u00e3o autom\u00e1tica — coloque o novo .exe em static/dist/ e reinicie o servidor."
    }), 200

@app.route("/")
def index_root():
    if "usuario" not in session:
        return render_template("login.html")
    
    user = session.get("usuario")
    next_page = request.args.get("next")
    
    # Se houver um redirecionamento pendente, segue para ele
    if next_page and next_page.startswith("/") and not next_page.startswith("//") and next_page != url_for("index_root"):
        return redirect(next_page)
        
    # Se for admin, mostra o portal de escolha. Se não, vai direto para o chat.
    if _current_chat_is_admin():
        return redirect(url_for("portal"))
    return redirect(url_for("chat"))

@app.route("/portal")
@login_required
def portal():
    if not _current_chat_is_admin():
        return redirect(url_for("chat"))
    return render_template("portal.html", usuario=session.get("usuario", "Visitante"))

@app.route("/admin-login")
def admin_login():
    return redirect(url_for("login"), code=302)

# -------------------------------
# Rotas e Setores
# -------------------------------
@app.route("/ti")
@login_required
def index():
    if not _current_chat_is_admin():
        return redirect(url_for("chat"))
    return render_template("index.html", usuario=session.get("usuario", "Visitante"))

@app.route("/comercial")
@login_required
def comercial():
    return "<h1>Setor Comercial</h1><p>Em constru\u00e7\u00e3o...</p><a href='/'>Voltar</a>"


@app.route("/financeiro")
@login_required
def financeiro():
    return "<h1>Setor Financeiro</h1><p>Em constru\u00e7\u00e3o...</p><a href='/'>Voltar</a>"


@app.route("/dashboard")
@login_required
def dashboard_route():
    if not _current_chat_is_admin():
        return redirect(url_for("portal"))
    return render_template("dashboard.html", usuario=session.get("usuario", "Visitante"))


@app.route("/estoque")
@login_required
def estoque():
    if not _current_chat_is_admin():
        return redirect(url_for("chat"))
    return render_template("estoque.html", usuario=session.get("usuario", "Visitante"))


@app.route("/kanban")
@login_required
def kanban():
    return redirect(url_for("dashboard_route"), code=302)


# -------------------------------
# Rota do Chat Interno
# -------------------------------
@app.route("/chat")
@login_required
def chat():
    return render_template("chat.html")


# -------------------------------
# API Tickets (existing)
# -------------------------------
@app.route("/api/tickets", methods=["GET"])
@login_required
def get_tickets():
    try:
        tickets = Ticket.query.filter(Ticket.status != "Fechado").all()
        return jsonify([t.to_dict() for t in tickets]), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/tickets/fechados", methods=["GET"])
@login_required
def get_tickets_fechados():
    try:
        tickets = Ticket.query.filter(Ticket.status == "Fechado").all()
        return jsonify([t.to_dict() for t in tickets]), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/tickets/todos", methods=["GET"])
@login_required
def get_all_tickets():
    try:
        tickets = Ticket.query.all()
        return jsonify([t.to_dict() for t in tickets]), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/tickets", methods=["POST"])
@login_required
def create_ticket():
    """Pública: qualquer usuário pode abrir um chamado sem estar logado."""
    try:
        data = request.get_json(force=True, silent=True) or {}
        if not data.get("nome") or not data.get("descricao"):
            return jsonify({"error": "Nome e descrição são obrigatórios"}), 400
        nome = str(data["nome"])[:100].strip()
        descricao = str(data["descricao"])[:2000].strip()
        if not nome or not descricao:
            return jsonify({"error": "Nome e descrição não podem estar em branco"}), 400
        ticket_id = gerar_id_ticket()
        novo_ticket = Ticket(
            id=ticket_id, nome=nome,
            titulo=data.get("titulo", "Sem título"),
            descricao=descricao, timestamp=get_now(),
            status="Aberto", prioridade=data.get("prioridade", "media"),
            responsavel=data.get("responsavel", nome),
            categoria=data.get("categoria", "Geral"),
            tempoEstimado=data.get("tempoEstimado", "2h"),
            dataVencimento=data.get("dataVencimento", ""),
            historico=[{
                "acao": "Criado", "usuario": "Fórum Público",
                "timestamp": get_now().strftime("%d/%m/%Y %H:%M:%S"),
                "detalhes": "Ticket criado via formulário público",
            }],
            cliente={
                "nome": nome, "email": data.get("email", ""),
                "telefone": data.get("telefone", ""),
                "departamento": data.get("departamento", ""),
            },
        )
        db.session.add(novo_ticket)
        db.session.commit()
        return jsonify({"success": True, "ticket_id": ticket_id}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@app.route("/api/tickets/<ticket_id>", methods=["GET"])
@login_required
def get_ticket(ticket_id):
    ticket = Ticket.query.get(ticket_id)
    if ticket:
        return jsonify(ticket.to_dict()), 200
    return jsonify({"error": "Ticket não encontrado"}), 404


@app.route("/api/tickets/<ticket_id>", methods=["PUT"])
@login_required
def update_ticket(ticket_id):
    try:
        data = request.get_json()
        ticket = Ticket.query.filter_by(id=ticket_id).first()
        if not ticket:
            return jsonify({"error": "Ticket não encontrado"}), 404
        valores_antigos = {}
        campos_monitorados = ["status", "prioridade", "responsavel", "titulo", "descricao", "checklist"]
        for campo in campos_monitorados:
            if campo in data and getattr(ticket, campo) != data[campo]:
                valores_antigos[campo] = getattr(ticket, campo)
        for campo, valor in data.items():
            if hasattr(ticket, campo):
                setattr(ticket, campo, valor)
        if data.get("status", "").lower() == "fechado" and not ticket.dataFechamento:
            ticket.dataFechamento = get_now()
        if valores_antigos:
            for campo, valor_antigo in valores_antigos.items():
                ticket.historico.append({
                    "acao": f"Atualizado {campo}",
                    "usuario": session.get("usuario", "Sistema"),
                    "timestamp": get_now().strftime("%d/%m/%Y %H:%M:%S"),
                    "detalhes": f'{campo.capitalize()} alterado de "{valor_antigo}" para "{data[campo]}"',
                })
            flag_modified(ticket, "historico")
        db.session.commit()
        return jsonify({"success": True, "message": "Ticket atualizado com sucesso"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/tickets/<ticket_id>", methods=["DELETE"])
@login_required
def delete_ticket(ticket_id):
    ticket = Ticket.query.filter_by(id=ticket_id).first()
    if not ticket:
        return jsonify({"error": "Ticket não encontrado"}), 404
    db.session.delete(ticket)
    db.session.commit()
    return jsonify({"success": True, "message": "Ticket deletado com sucesso"}), 200


@app.route("/api/tickets/<ticket_id>/comentarios", methods=["POST"])
@login_required
def add_comment(ticket_id):
    try:
        data = request.get_json()
        ticket = Ticket.query.filter_by(id=ticket_id).first()
        if not ticket:
            return jsonify({"error": "Ticket não encontrado"}), 404
        comentario = {
            "id": str(uuid.uuid4())[:8],
            "usuario": session.get("usuario", "Anônimo"),
            "comentario": data["comentario"],
            "timestamp": get_now().strftime("%d/%m/%Y %H:%M:%S"),
            "tipo": data.get("tipo", "comentario"),
        }
        if ticket.comentarios is None:
            ticket.comentarios = []
        ticket.comentarios.append(comentario)
        flag_modified(ticket, "comentarios")
        if ticket.historico is None:
            ticket.historico = []
        ticket.historico.append({
            "id": str(uuid.uuid4())[:8],
            "acao": "Comentário adicionado",
            "usuario": session.get("usuario", "Sistema"),
            "timestamp": get_now().strftime("%d/%m/%Y %H:%M:%S"),
            "detalhes": f'Comentário: "{data["comentario"][:50]}..."',
        })
        flag_modified(ticket, "historico")
        db.session.commit()
        return jsonify({"success": True, "comentario": comentario}), 201
    except Exception as e:
        logger.exception("Falha ao adicionar comentário")
        return jsonify({"error": str(e)}), 500


# -------------------------------
# Estatísticas
# -------------------------------
@app.route("/api/estatisticas", methods=["GET"])
@login_required
def get_statistics():
    """Estatísticas via SQL GROUP BY — evita carregar todos os tickets em memória."""
    try:
        total = db.session.query(func.count(Ticket.id)).scalar() or 0

        por_status_rows = db.session.query(
            Ticket.status, func.count(Ticket.id)
        ).group_by(Ticket.status).all()
        por_status = {r[0] or "Aberto": r[1] for r in por_status_rows}

        por_prio_rows = db.session.query(
            Ticket.prioridade, func.count(Ticket.id)
        ).group_by(Ticket.prioridade).all()
        por_prioridade = {r[0] or "media": r[1] for r in por_prio_rows}

        por_resp_rows = db.session.query(
            Ticket.responsavel, func.count(Ticket.id)
        ).group_by(Ticket.responsavel).all()
        por_responsavel = {(r[0] or "Não atribuído"): r[1] for r in por_resp_rows}

        por_cat_rows = db.session.query(
            Ticket.categoria, func.count(Ticket.id)
        ).group_by(Ticket.categoria).all()
        por_categoria = {r[0] or "Geral": r[1] for r in por_cat_rows}

        fechados = por_status.get("Fechado", 0)
        stats = {
            "total": total,
            "por_status": por_status,
            "por_prioridade": por_prioridade,
            "por_responsavel": por_responsavel,
            "por_categoria": por_categoria,
            "ativos": total - fechados,
            "fechados": fechados,
        }
        return jsonify(stats), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ================================
# API IT Control — Usuários TI
# ================================
@app.route("/api/it/users", methods=["GET"])
@login_required
def it_get_users():
    try:
        q = request.args.get("q", "")
        status = request.args.get("status", "")
        query = ITUser.query
        if q:
            query = query.filter(
                (ITUser.nome.ilike(f"%{q}%")) |
                (ITUser.setor.ilike(f"%{q}%")) |
                (ITUser.cargo.ilike(f"%{q}%"))
            )
        if status:
            query = query.filter(ITUser.status == status)
        users = query.order_by(ITUser.nome).all()
        return jsonify([u.to_dict(full=False) for u in users]), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/it/users/<int:user_id>", methods=["GET"])
@login_required
def it_get_user(user_id):
    u = ITUser.query.get_or_404(user_id)
    return jsonify(u.to_dict(full=True)), 200


@app.route("/api/it/users", methods=["POST"])
@login_required
def it_create_user():
    try:
        data = request.get_json()
        u = ITUser(
            nome=data["nome"], cargo=data.get("cargo"), setor=data.get("setor"),
            email_corporativo=data.get("email_corporativo"), ramal=data.get("ramal"),
            cabo_rede=data.get("cabo_rede"), ip=data.get("ip"),
            status=data.get("status", "Ativo"),
            data_entrada=parse_date(data.get("data_entrada")),
            responsavel_ti=data.get("responsavel_ti"), obs=data.get("obs"),
        )
        db.session.add(u)
        db.session.flush()
        registrar_audit("it_users", u.id, "CREATE", "nome", "", u.nome)
        db.session.commit()
        return jsonify(u.to_dict()), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@app.route("/api/it/users/<int:user_id>", methods=["PUT"])
@login_required
def it_update_user(user_id):
    try:
        u = ITUser.query.get_or_404(user_id)
        data = request.get_json()
        fields = ["nome", "cargo", "setor", "email_corporativo", "ramal", "cabo_rede",
                  "ip", "status", "responsavel_ti", "obs"]
        for f in fields:
            if f in data:
                old = getattr(u, f)
                setattr(u, f, data[f])
                if old != data[f]:
                    registrar_audit("it_users", u.id, "UPDATE", f, old, data[f])
        if "data_entrada" in data:
            u.data_entrada = parse_date(data["data_entrada"])
        if "data_saida" in data:
            u.data_saida = parse_date(data["data_saida"])
        u.updated_at = get_now()
        db.session.commit()
        return jsonify(u.to_dict()), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@app.route("/api/it/users/<int:user_id>", methods=["DELETE"])
@login_required
def it_delete_user(user_id):
    try:
        u = ITUser.query.get_or_404(user_id)
        registrar_audit("it_users", u.id, "DELETE", "nome", u.nome, "")
        db.session.delete(u)
        db.session.commit()
        return jsonify({"success": True}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# ================================
# API IT — PCs
# ================================
@app.route("/api/it/users/<int:user_id>/pc", methods=["GET", "POST", "PUT"])
@login_required
def it_user_pc(user_id):
    u = ITUser.query.get_or_404(user_id)
    if request.method == "GET":
        return jsonify(u.pc.to_dict() if u.pc else None), 200
    data = request.get_json()
    if u.pc:
        pc = u.pc
    else:
        pc = ITPC(it_user_id=user_id)
        db.session.add(pc)
    fields = ["hostname", "num_serie", "num_patrimonio", "fabricante", "modelo", "status",
              "monitor", "mouse_pad", "mouse", "teclado", "gabinete", "processador",
              "ram", "placa_mae", "placa_video", "placa_rede", "fonte", "hdds", "obs"]
    for f in fields:
        if f in data:
            old = getattr(pc, f)
            setattr(pc, f, data[f])
            if old != data[f]:
                registrar_audit("it_pcs", pc.id or "new", "UPDATE", f, old, data[f])
    if "data_compra" in data:
        pc.data_compra = parse_date(data["data_compra"])
    if "data_garantia_fim" in data:
        pc.data_garantia_fim = parse_date(data["data_garantia_fim"])
    pc.updated_at = get_now()
    db.session.commit()
    return jsonify(pc.to_dict()), 200


@app.route("/api/it/pcs", methods=["GET"])
@login_required
def it_get_all_pcs():
    try:
        pcs = ITPC.query.all()
        result = []
        for pc in pcs:
            d = pc.to_dict()
            d["usuario_nome"] = pc.user.nome if pc.user else "Sem usuário"
            result.append(d)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ================================
# API IT — Contas
# ================================
@app.route("/api/it/users/<int:user_id>/contas", methods=["GET", "POST"])
@login_required
def it_user_contas(user_id):
    ITUser.query.get_or_404(user_id)
    if request.method == "GET":
        contas = ITConta.query.filter_by(it_user_id=user_id).all()
        return jsonify([c.to_dict() for c in contas]), 200
    data = request.get_json()
    c = ITConta(
        it_user_id=user_id, sistema=data["sistema"],
        nome_custom=data.get("nome_custom"), login=data.get("login"),
        senha=encrypt_secret(data.get("senha")), acessos=data.get("acessos"),
        data_criacao=parse_date(data.get("data_criacao")),
        data_ultima_revisao=parse_date(data.get("data_ultima_revisao")),
        obs=data.get("obs"),
    )
    db.session.add(c)
    db.session.flush()
    registrar_audit("it_contas", c.id, "CREATE", "sistema", "", c.sistema)
    db.session.commit()
    return jsonify(c.to_dict()), 201


@app.route("/api/it/contas/<int:conta_id>", methods=["PUT", "DELETE"])
@login_required
def it_conta(conta_id):
    c = ITConta.query.get_or_404(conta_id)
    if request.method == "DELETE":
        registrar_audit("it_contas", c.id, "DELETE", "sistema", c.sistema, "")
        db.session.delete(c)
        db.session.commit()
        return jsonify({"success": True}), 200
    data = request.get_json()
    for f in ["sistema", "nome_custom", "login", "senha", "acessos", "obs"]:
        if f not in data:
            continue
        if f == "senha":
            if data[f]:
                c.senha = encrypt_secret(data[f])
                registrar_audit("it_contas", c.id, "UPDATE", "senha", "[redacted]", "[updated]")
            continue
        old = getattr(c, f)
        setattr(c, f, data[f])
        if old != data[f]:
            registrar_audit("it_contas", c.id, "UPDATE", f, old, data[f])
    if "data_ultima_revisao" in data:
        c.data_ultima_revisao = parse_date(data["data_ultima_revisao"])
    db.session.commit()
    return jsonify(c.to_dict()), 200


# ================================
# API IT — Emails
# ================================
@app.route("/api/it/users/<int:user_id>/emails", methods=["GET", "POST"])
@login_required
def it_user_emails(user_id):
    ITUser.query.get_or_404(user_id)
    if request.method == "GET":
        emails = ITEmail.query.filter_by(it_user_id=user_id).all()
        return jsonify([e.to_dict() for e in emails]), 200
    data = request.get_json()
    e = ITEmail(
        it_user_id=user_id, endereco=data["endereco"],
        servidor=data.get("servidor"), login=data.get("login"),
        senha=encrypt_secret(data.get("senha")), obs=data.get("obs"),
    )
    db.session.add(e)
    db.session.flush()
    registrar_audit("it_emails", e.id, "CREATE", "endereco", "", e.endereco)
    db.session.commit()
    return jsonify(e.to_dict()), 201


@app.route("/api/it/emails/<int:email_id>", methods=["PUT", "DELETE"])
@login_required
def it_email(email_id):
    e = ITEmail.query.get_or_404(email_id)
    if request.method == "DELETE":
        registrar_audit("it_emails", e.id, "DELETE", "endereco", e.endereco, "")
        db.session.delete(e)
        db.session.commit()
        return jsonify({"success": True}), 200
    data = request.get_json()
    for f in ["endereco", "servidor", "login", "senha", "obs"]:
        if f in data:
            if f == "senha":
                if data[f]:
                    e.senha = encrypt_secret(data[f])
            else:
                setattr(e, f, data[f])
    db.session.commit()
    return jsonify(e.to_dict()), 200


# ================================
# API IT — Certificados
# ================================
@app.route("/api/it/users/<int:user_id>/certificados", methods=["GET", "POST"])
@login_required
def it_user_certificados(user_id):
    ITUser.query.get_or_404(user_id)
    if request.method == "GET":
        certs = ITCertificado.query.filter_by(it_user_id=user_id).all()
        return jsonify([c.to_dict() for c in certs]), 200
    data = request.get_json()
    c = ITCertificado(
        it_user_id=user_id, tipo=data["tipo"],
        nome_outro=data.get("nome_outro"), versao=data.get("versao"),
        chave=encrypt_secret(data.get("chave")), validade=parse_date(data.get("validade")),
        fornecedor=data.get("fornecedor"), obs=data.get("obs"),
    )
    db.session.add(c)
    db.session.flush()
    registrar_audit("it_certificados", c.id, "CREATE", "tipo", "", c.tipo)
    db.session.commit()
    return jsonify(c.to_dict()), 201


@app.route("/api/it/certificados/<int:cert_id>", methods=["PUT", "DELETE"])
@login_required
def it_certificado(cert_id):
    c = ITCertificado.query.get_or_404(cert_id)
    if request.method == "DELETE":
        registrar_audit("it_certificados", c.id, "DELETE", "tipo", c.tipo, "")
        db.session.delete(c)
        db.session.commit()
        return jsonify({"success": True}), 200
    data = request.get_json()
    for f in ["tipo", "nome_outro", "versao", "chave", "fornecedor", "obs"]:
        if f not in data:
            continue
        if f == "chave":
            if data[f]:
                c.chave = encrypt_secret(data[f])
            continue
        setattr(c, f, data[f])
    if "validade" in data:
        c.validade = parse_date(data["validade"])
    db.session.commit()
    return jsonify(c.to_dict()), 200


# ================================
# API IT — Programas
# ================================
@app.route("/api/it/users/<int:user_id>/programas", methods=["GET", "POST"])
@login_required
def it_user_programas(user_id):
    ITUser.query.get_or_404(user_id)
    if request.method == "GET":
        progs = ITPrograma.query.filter_by(it_user_id=user_id).all()
        return jsonify([p.to_dict() for p in progs]), 200
    data = request.get_json()
    p = ITPrograma(
        it_user_id=user_id, nome=data["nome"],
        versao=data.get("versao"), chave=encrypt_secret(data.get("chave")),
        categoria=data.get("categoria"), obs=data.get("obs"),
    )
    db.session.add(p)
    db.session.flush()
    registrar_audit("it_programas", p.id, "CREATE", "nome", "", p.nome)
    db.session.commit()
    return jsonify(p.to_dict()), 201


@app.route("/api/it/programas/<int:prog_id>", methods=["PUT", "DELETE"])
@login_required
def it_programa(prog_id):
    p = ITPrograma.query.get_or_404(prog_id)
    if request.method == "DELETE":
        registrar_audit("it_programas", p.id, "DELETE", "nome", p.nome, "")
        db.session.delete(p)
        db.session.commit()
        return jsonify({"success": True}), 200
    data = request.get_json()
    for f in ["nome", "versao", "chave", "categoria", "obs"]:
        if f in data:
            if f == "chave":
                if data[f]:
                    p.chave = encrypt_secret(data[f])
            else:
                setattr(p, f, data[f])
    db.session.commit()
    return jsonify(p.to_dict()), 200


# ================================
# API IT — Manutenções
# ================================
@app.route("/api/it/pcs/<int:pc_id>/manutencoes", methods=["GET", "POST"])
@login_required
def it_pc_manutencoes(pc_id):
    ITPC.query.get_or_404(pc_id)
    if request.method == "GET":
        mans = ITManutencao.query.filter_by(it_pc_id=pc_id).order_by(ITManutencao.data.desc()).all()
        return jsonify([m.to_dict() for m in mans]), 200
    data = request.get_json()
    m = ITManutencao(
        it_pc_id=pc_id, tipo=data.get("tipo"), descricao=data.get("descricao"),
        data=parse_date(data.get("data")), tecnico=data.get("tecnico"),
        status=data.get("status", "Concluída"), custo=data.get("custo"),
        obs=data.get("obs"),
    )
    db.session.add(m)
    db.session.flush()
    registrar_audit("it_manutencoes", m.id, "CREATE", "tipo", "", m.tipo)
    db.session.commit()
    return jsonify(m.to_dict()), 201


@app.route("/api/it/manutencoes/<int:man_id>", methods=["DELETE"])
@login_required
def it_manutencao(man_id):
    m = ITManutencao.query.get_or_404(man_id)
    db.session.delete(m)
    db.session.commit()
    return jsonify({"success": True}), 200


# ================================
# API IT — Sticky Notes
# ================================
@app.route("/api/it/sticky", methods=["GET", "POST"])
@login_required
def it_sticky():
    if request.method == "GET":
        tag = request.args.get("tag")
        notes = ITStickyNote.query
        if tag:
            notes = notes.filter(ITStickyNote.tags.contains([tag]))
        notes = notes.order_by(ITStickyNote.updated_at.desc()).all()
        return jsonify([n.to_dict() for n in notes]), 200
    data = request.get_json()
    n = ITStickyNote(
        it_user_id=data.get("it_user_id"), titulo=data.get("titulo"),
        conteudo=data.get("conteudo"), tags=data.get("tags", []),
        color=data.get("color", "yellow"),
    )
    db.session.add(n)
    db.session.commit()
    return jsonify(n.to_dict()), 201


@app.route("/api/it/sticky/<int:note_id>", methods=["PUT", "DELETE"])
@login_required
def it_sticky_note(note_id):
    n = ITStickyNote.query.get_or_404(note_id)
    if request.method == "DELETE":
        db.session.delete(n)
        db.session.commit()
        return jsonify({"success": True}), 200
    data = request.get_json()
    for f in ["titulo", "conteudo", "color", "it_user_id"]:
        if f in data:
            setattr(n, f, data[f])
    if "tags" in data:
        n.tags = data["tags"]
        flag_modified(n, "tags")
    n.updated_at = get_now()
    db.session.commit()
    return jsonify(n.to_dict()), 200


# ================================
# API IT — Audit Log
# ================================
@app.route("/api/it/audit", methods=["GET"])
@login_required
def it_audit():
    try:
        tabela = request.args.get("tabela")
        limit = int(request.args.get("limit", 200))
        q = ITAuditLog.query
        if tabela:
            q = q.filter(ITAuditLog.tabela == tabela)
        logs = q.order_by(ITAuditLog.timestamp.desc()).limit(limit).all()
        return jsonify([l.to_dict() for l in logs]), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ================================
# API IT — Dashboard Stats
# ================================
@app.route("/api/it/stats", methods=["GET"])
@login_required
def it_stats():
    try:
        hoje = date.today()
        em_30_dias = hoje + timedelta(days=30)

        total_users = ITUser.query.filter_by(status="Ativo").count()
        total_pcs = ITPC.query.filter_by(status="Em Uso").count()
        pcs_manutencao = ITPC.query.filter_by(status="Manutenção").count()

        certs_expirando_30 = ITCertificado.query.filter(
            ITCertificado.validade <= em_30_dias,
            ITCertificado.validade >= hoje
        ).count()
        certs_expirados = ITCertificado.query.filter(
            ITCertificado.validade < hoje
        ).count()

        revisao_limite = hoje - timedelta(days=90)
        contas_sem_revisao = ITConta.query.filter(
            (ITConta.data_ultima_revisao == None) |
            (ITConta.data_ultima_revisao < revisao_limite)
        ).count()

        return jsonify({
            "usuarios_ativos": total_users,
            "pcs_em_uso": total_pcs,
            "pcs_manutencao": pcs_manutencao,
            "certs_expirando_30": certs_expirando_30,
            "certs_expirados": certs_expirados,
            "contas_sem_revisao": contas_sem_revisao,
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ================================
# API — E-mails Globais (Shared)
# ================================

@app.route("/api/it/emails-global", methods=["GET"])
@login_required
def it_emails_global_list():
    try:
        q = request.args.get("q", "")
        query = ITEmailGlobal.query
        if q:
            query = query.filter(
                ITEmailGlobal.endereco.ilike(f"%{q}%") |
                ITEmailGlobal.servidor.ilike(f"%{q}%") |
                ITEmailGlobal.tipo.ilike(f"%{q}%")
            )
        emails = query.order_by(ITEmailGlobal.endereco).all()
        return jsonify([e.to_dict(with_vinculos=True) for e in emails]), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/it/emails-global", methods=["POST"])
@login_required
def it_email_global_create():
    try:
        data = request.get_json()
        em = ITEmailGlobal(
            endereco=data["endereco"],
            servidor=data.get("servidor"),
            login=data.get("login"),
            senha=encrypt_secret(data.get("senha")),
            tipo=data.get("tipo", "Corporativo"),
            obs=data.get("obs"),
        )
        db.session.add(em)
        db.session.flush()
        registrar_audit("it_emails_global", em.id, "CREATE", "endereco", "", em.endereco)
        db.session.commit()
        return jsonify(em.to_dict(with_vinculos=True)), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@app.route("/api/it/emails-global/<int:email_id>", methods=["GET"])
@login_required
def it_email_global_get(email_id):
    em = ITEmailGlobal.query.get_or_404(email_id)
    return jsonify(em.to_dict(with_vinculos=True)), 200


@app.route("/api/it/emails-global/<int:email_id>", methods=["PUT"])
@login_required
def it_email_global_update(email_id):
    try:
        em = ITEmailGlobal.query.get_or_404(email_id)
        data = request.get_json()
        for f in ["endereco", "servidor", "login", "senha", "tipo", "obs"]:
            if f in data:
                old = getattr(em, f)
                setattr(em, f, data[f])
                if old != data[f]:
                    registrar_audit("it_emails_global", em.id, "UPDATE", f, old, data[f])
        em.updated_at = get_now()
        db.session.commit()
        return jsonify(em.to_dict(with_vinculos=True)), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@app.route("/api/it/emails-global/<int:email_id>", methods=["DELETE"])
@login_required
def it_email_global_delete(email_id):
    try:
        em = ITEmailGlobal.query.get_or_404(email_id)
        registrar_audit("it_emails_global", em.id, "DELETE", "endereco", em.endereco, "")
        db.session.delete(em)
        db.session.commit()
        return jsonify({"success": True}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# Vinculos de email ↔ usuário
@app.route("/api/it/emails-global/<int:email_id>/vinculos", methods=["GET", "POST"])
@login_required
def it_email_vinculos(email_id):
    ITEmailGlobal.query.get_or_404(email_id)
    if request.method == "GET":
        vinculos = ITEmailVinculo.query.filter_by(email_id=email_id).all()
        return jsonify([v.to_dict() for v in vinculos]), 200
    data = request.get_json()
    # Check for duplicate
    existing = ITEmailVinculo.query.filter_by(
        email_id=email_id, it_user_id=data["it_user_id"]
    ).first()
    if existing:
        return jsonify({"error": "Este e-mail já está vinculado a este usuário"}), 409
    v = ITEmailVinculo(
        email_id=email_id,
        it_user_id=data["it_user_id"],
        hostname_pc=data.get("hostname_pc"),
        cliente_email=data.get("cliente_email"),
        obs=data.get("obs"),
    )
    db.session.add(v)
    db.session.flush()
    registrar_audit("it_email_vinculos", v.id, "CREATE", "email_id", "", str(email_id))
    db.session.commit()
    return jsonify(v.to_dict()), 201


@app.route("/api/it/email-vinculos/<int:vinculo_id>", methods=["PUT", "DELETE"])
@login_required
def it_email_vinculo(vinculo_id):
    v = ITEmailVinculo.query.get_or_404(vinculo_id)
    if request.method == "DELETE":
        registrar_audit("it_email_vinculos", v.id, "DELETE", "email_id", str(v.email_id), "")
        db.session.delete(v)
        db.session.commit()
        return jsonify({"success": True}), 200
    data = request.get_json()
    for f in ["hostname_pc", "cliente_email", "obs"]:
        if f in data:
            setattr(v, f, data[f])
    db.session.commit()
    return jsonify(v.to_dict()), 200


# E-mails vinculados a um usuário específico
@app.route("/api/it/users/<int:user_id>/email-vinculos", methods=["GET"])
@login_required
def it_user_email_vinculos(user_id):
    ITUser.query.get_or_404(user_id)
    vinculos = ITEmailVinculo.query.filter_by(it_user_id=user_id).all()
    return jsonify([v.to_dict() for v in vinculos]), 200


# ================================
# API — NAS Pastas (Shared)
# ================================

@app.route("/api/it/nas-pastas", methods=["GET"])
@login_required
def it_nas_pastas_list():
    try:
        q = request.args.get("q", "")
        query = ITNASPasta.query
        if q:
            query = query.filter(
                ITNASPasta.nome.ilike(f"%{q}%") |
                ITNASPasta.caminho_rede.ilike(f"%{q}%")
            )
        pastas = query.order_by(ITNASPasta.nome).all()
        return jsonify([p.to_dict(with_acessos=True) for p in pastas]), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/it/nas-pastas", methods=["POST"])
@login_required
def it_nas_pasta_create():
    try:
        data = request.get_json()
        p = ITNASPasta(
            nome=data["nome"],
            caminho_rede=data.get("caminho_rede"),
            descricao=data.get("descricao"),
            obs=data.get("obs"),
        )
        db.session.add(p)
        db.session.flush()
        registrar_audit("it_nas_pastas", p.id, "CREATE", "nome", "", p.nome)
        db.session.commit()
        return jsonify(p.to_dict(with_acessos=True)), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@app.route("/api/it/nas-pastas/<int:pasta_id>", methods=["GET"])
@login_required
def it_nas_pasta_get(pasta_id):
    p = ITNASPasta.query.get_or_404(pasta_id)
    return jsonify(p.to_dict(with_acessos=True)), 200


@app.route("/api/it/nas-pastas/<int:pasta_id>", methods=["PUT"])
@login_required
def it_nas_pasta_update(pasta_id):
    try:
        p = ITNASPasta.query.get_or_404(pasta_id)
        data = request.get_json()
        for f in ["nome", "caminho_rede", "descricao", "obs"]:
            if f in data:
                old = getattr(p, f)
                setattr(p, f, data[f])
                if old != data[f]:
                    registrar_audit("it_nas_pastas", p.id, "UPDATE", f, old, data[f])
        p.updated_at = get_now()
        db.session.commit()
        return jsonify(p.to_dict(with_acessos=True)), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@app.route("/api/it/nas-pastas/<int:pasta_id>", methods=["DELETE"])
@login_required
def it_nas_pasta_delete(pasta_id):
    try:
        p = ITNASPasta.query.get_or_404(pasta_id)
        registrar_audit("it_nas_pastas", p.id, "DELETE", "nome", p.nome, "")
        db.session.delete(p)
        db.session.commit()
        return jsonify({"success": True}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# Acessos de NAS ↔ usuário
@app.route("/api/it/nas-pastas/<int:pasta_id>/acessos", methods=["GET", "POST"])
@login_required
def it_nas_acessos(pasta_id):
    ITNASPasta.query.get_or_404(pasta_id)
    if request.method == "GET":
        acessos = ITNASAcesso.query.filter_by(pasta_id=pasta_id).all()
        return jsonify([a.to_dict() for a in acessos]), 200
    data = request.get_json()
    existing = ITNASAcesso.query.filter_by(
        pasta_id=pasta_id, it_user_id=data["it_user_id"]
    ).first()
    if existing:
        return jsonify({"error": "Acesso já cadastrado para este usuário nesta pasta"}), 409
    a = ITNASAcesso(
        pasta_id=pasta_id,
        it_user_id=data["it_user_id"],
        letra_mapeada=data.get("letra_mapeada"),
        permissao=data.get("permissao", "Leitura"),
        obs=data.get("obs"),
    )
    db.session.add(a)
    db.session.flush()
    registrar_audit("it_nas_acessos", a.id, "CREATE", "pasta_id", "", str(pasta_id))
    db.session.commit()
    return jsonify(a.to_dict()), 201


@app.route("/api/it/nas-acessos/<int:acesso_id>", methods=["PUT", "DELETE"])
@login_required
def it_nas_acesso(acesso_id):
    a = ITNASAcesso.query.get_or_404(acesso_id)
    if request.method == "DELETE":
        registrar_audit("it_nas_acessos", a.id, "DELETE", "pasta_id", str(a.pasta_id), "")
        db.session.delete(a)
        db.session.commit()
        return jsonify({"success": True}), 200
    data = request.get_json()
    for f in ["letra_mapeada", "permissao", "obs"]:
        if f in data:
            old = getattr(a, f)
            setattr(a, f, data[f])
            if old != data[f]:
                registrar_audit("it_nas_acessos", a.id, "UPDATE", f, old, data[f])
    db.session.commit()
    return jsonify(a.to_dict()), 200


# NAS acessos de um usuário específico
@app.route("/api/it/users/<int:user_id>/nas-acessos", methods=["GET"])
@login_required
def it_user_nas_acessos(user_id):
    ITUser.query.get_or_404(user_id)
    acessos = ITNASAcesso.query.filter_by(it_user_id=user_id).all()
    return jsonify([a.to_dict() for a in acessos]), 200


# Updated stats with NAS count
@app.route("/api/it/nas-stats", methods=["GET"])
@login_required
def it_nas_stats():
    try:
        total_pastas = ITNASPasta.query.count()
        total_acessos = ITNASAcesso.query.count()
        total_emails = ITEmailGlobal.query.count()
        return jsonify({
            "total_pastas_nas": total_pastas,
            "total_acessos_nas": total_acessos,
            "total_emails_global": total_emails,
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ================================
# IA Assistant — Ollama + Qwen3
# ================================

def obter_contexto_ti_full():
    """Coleta dados resumidos do sistema para enviar à IA. Usa .limit() para evitar OOM."""
    try:
        _LIMIT = 100   # máximo de registros por tabela — evita enviar tudo para a IA
        users        = ITUser.query.limit(_LIMIT).all()
        pcs          = ITPC.query.limit(_LIMIT).all()
        emails       = ITEmailGlobal.query.limit(_LIMIT).all()
        pastas       = ITNASPasta.query.limit(_LIMIT).all()
        certificados = ITCertificado.query.limit(_LIMIT).all()
        contas       = ITConta.query.limit(_LIMIT).all()
        manutencoes  = ITManutencao.query.order_by(ITManutencao.created_at.desc()).limit(10).all()

        hoje = date.today()
        contexto = {
            "resumo": {
                "total_usuarios":    ITUser.query.count(),
                "total_pcs":         ITPC.query.count(),
                "total_emails":      ITEmailGlobal.query.count(),
                "total_pastas_nas":  ITNASPasta.query.count(),
                "total_certificados": ITCertificado.query.count(),
            },
            "status_geral": {
                "usuarios_ativos":  ITUser.query.filter_by(status='Ativo').count(),
                "pcs_em_uso":       ITPC.query.filter_by(status='Em Uso').count(),
                "pcs_manutencao":   ITPC.query.filter_by(status='Manutenção').count(),
            },
            "alertas": {
                "certificados_expirados": ITCertificado.query.filter(
                    ITCertificado.validade < hoje
                ).count(),
                "contas_sem_revisao": ITConta.query.filter(
                    ITConta.data_ultima_revisao == None
                ).count(),
            },
            "recentes_manutencoes": [m.to_dict() for m in manutencoes],
        }
        return contexto
    except Exception as e:
        return {"error": str(e)}

@app.route("/api/ia/chat", methods=["POST"])
@login_required
def api_ia_chat():
    """Rota de chat local com streaming, disponível apenas para administradores."""
    if not _current_chat_is_admin():
        return jsonify({"error": "Acesso negado"}), 403
    if not _env_bool("OLLAMA_ENABLED", False):
        return jsonify({"error": "Integração local de IA desabilitada"}), 503
    try:
        data = request.get_json(force=True, silent=True) or {}
        pergunta = str(data.get("pergunta") or "")[:2000]   # trunca perguntas gigantes
        if not pergunta.strip():
            return jsonify({"error": "Pergunta vazia"}), 400

        # Limita histórico a 20 mensagens para evitar OOM
        historico_raw = data.get("historico", [])
        if not isinstance(historico_raw, list):
            historico_raw = []
        historico = historico_raw[-20:]
        
        contexto_db = obter_contexto_ti_full()
        contexto_json = json.dumps(contexto_db, default=str)
        logger.info("Contexto local de IA preparado com %s caracteres", len(contexto_json))
        
        # System Prompt conciso
        system_prompt = (
            "Você é um especialista em operações de TI. Analise o contexto e responda de forma técnica, objetiva e verificável.\n"
            f"\nCONTEXTO:\n{contexto_json}"
        )
        
        url_ollama = os.getenv("OLLAMA_CHAT_URL", "http://127.0.0.1:11434/api/chat")
        payload = {
            "model": os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b"),
            "messages": [
                {"role": "system", "content": system_prompt},
                *historico,
                {"role": "user", "content": pergunta}
            ],
            "stream": True,
            "options": {
                "num_ctx": 2048,      # Reduzido para maior estabilidade
                "temperature": 0.7,
                "num_thread": int(os.getenv("OLLAMA_NUM_THREADS", "4"))
            }
        }
        
        def generate():
            try:
                logger.info("Conectando ao Ollama local")
                with requests.post(url_ollama, json=payload, timeout=60, stream=True) as resp:
                    logger.info("Ollama respondeu com status %s", resp.status_code)
                    if resp.status_code != 200:
                        logger.warning("Ollama retornou falha HTTP %s", resp.status_code)
                        yield f"data: {json.dumps({'error': 'Serviço local de IA indisponível'})}\n\n"
                        return

                    for line in resp.iter_lines():
                        if line:
                            try:
                                chunk = json.loads(line)
                                content = chunk.get("message", {}).get("content", "")
                                done = chunk.get("done", False)
                                if content or done:
                                    yield f"data: {json.dumps({'text': content, 'done': done})}\n\n"
                            except Exception as e_json:
                                logger.warning("Resposta inválida do Ollama: %s", e_json)
                logger.info("Stream local de IA concluído")
            except Exception:
                logger.exception("Falha no stream local de IA")
                yield f"data: {json.dumps({'error': 'Serviço local de IA indisponível'})}\n\n"

        return Response(
            stream_with_context(generate()), 
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no'
            }
        )
        
    except Exception:
        logger.exception("Falha ao preparar solicitação para IA local")
        return jsonify({"error": "Serviço local de IA indisponível"}), 500

@app.route("/api/ia/analise", methods=["GET"])
@login_required
def api_ia_analise():
    """Gera análise demonstrativa do inventário, somente para administradores."""
    if not _current_chat_is_admin():
        return jsonify({"error": "Acesso negado"}), 403
    if not _env_bool("OLLAMA_ENABLED", False):
        return jsonify({"error": "Integração local de IA desabilitada"}), 503
    try:
        contexto_db = obter_contexto_ti_full()

        system_prompt = (
            "/no_think\n"
            "Você é um consultor sênior de TI especializado em governança, inventário e auditoria interna.\n"
            "Sua tarefa é gerar um relatório técnico do parque tecnológico.\n"
            "Identifique pontos críticos, riscos de segurança e falhas de processo.\n"
            f"\nCONTEXTO COMPLETO DO BANCO DE DADOS:\n{json.dumps(contexto_db, default=str)}"
        )

        url_ollama = os.getenv("OLLAMA_CHAT_URL", "http://127.0.0.1:11434/api/chat")
        payload = {
            "model": os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b"),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Gere um parecer técnico completo baseado no contexto fornecido."}
            ],
            "stream": True,
            "options": {
                "num_ctx": 2048,
                "num_thread": int(os.getenv("OLLAMA_NUM_THREADS", "4")),
                "num_predict": 512,
                "num_batch": 512,
                "temperature": 0.5
            }
        }

        def generate():
            try:
                with requests.post(url_ollama, json=payload, timeout=240, stream=True) as resp:
                    for line in resp.iter_lines():
                        if line:
                            chunk = json.loads(line)
                            content = chunk.get("message", {}).get("content", "")
                            done = chunk.get("done", False)
                            yield f"data: {json.dumps({'text': content, 'done': done})}\n\n"
            except Exception:
                logger.exception("Falha no stream de análise local")
                yield f"data: {json.dumps({'error': 'Serviço local de IA indisponível'})}\n\n"

        return Response(
            stream_with_context(generate()),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no'
            }
        )
    except Exception:
        logger.exception("Falha ao preparar análise local")
        return jsonify({"error": "Serviço local de IA indisponível"}), 500

# -------------------------------
# API Gerenciador de Atalhos
# -------------------------------
@app.route("/atalho")
@login_required
def atalho_page():
    return render_template("atalho.html", usuario=session.get("usuario", "Visitante"))

# -------------------------------
# API Gerenciador de Atalhos Personalizados
# -------------------------------
@app.route("/api/user/shortcuts", methods=["GET"])
@login_required
def get_user_shortcuts():
    try:
        user = session.get("usuario")
        shortcuts = UserShortcut.query.filter_by(usuario=user).order_by(UserShortcut.nome).all()
        return jsonify([s.to_dict() for s in shortcuts]), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/user/shortcuts", methods=["POST"])
@login_required
def create_user_shortcut():
    try:
        data = request.get_json()
        if not data.get("nome") or not data.get("caminho"):
            return jsonify({"error": "Nome e caminho são obrigatórios"}), 400
        
        shortcut = UserShortcut(
            usuario=session.get("usuario"),
            nome=data.get("nome"),
            caminho=data.get("caminho"),
            icone=data.get("icone", "📁")
        )
        db.session.add(shortcut)
        db.session.commit()
        return jsonify(shortcut.to_dict()), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@app.route("/api/user/shortcuts/<int:id>", methods=["DELETE"])
@login_required
def delete_user_shortcut(id):
    try:
        shortcut = UserShortcut.query.get(id)
        if not shortcut or shortcut.usuario != session.get("usuario"):
            return jsonify({"error": "Não encontrado ou permissão negada"}), 404
        
        db.session.delete(shortcut)
        db.session.commit()
        return jsonify({"success": True}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@app.route("/api/it/shortcuts", methods=["GET"])
@login_required
def get_shortcuts():
    try:
        shortcuts = ITShortcut.query.order_by(ITShortcut.nome).all()
        return jsonify([s.to_dict() for s in shortcuts]), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/it/shortcuts", methods=["POST"])
@login_required
def create_shortcut():
    try:
        data = request.get_json()
        if not data.get("nome") or not data.get("caminho"):
            return jsonify({"error": "Nome e caminho são obrigatórios"}), 400
        
        tags = data.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]

        novo = ITShortcut(
            nome=data["nome"],
            caminho=data["caminho"],
            tags=tags,
            icone=data.get("icone", "📁")
        )
        db.session.add(novo)
        db.session.commit()
        return jsonify(novo.to_dict()), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@app.route("/api/it/shortcuts/<int:short_id>", methods=["DELETE"])
@login_required
def delete_shortcut(short_id):
    try:
        s = ITShortcut.query.get(short_id)
        if not s:
            return jsonify({"error": "Atalho não encontrado"}), 404
        db.session.delete(s)
        db.session.commit()
        return jsonify({"success": True}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# ================================
# Chat — REST helpers
# ================================
def _all_chat_users():
    """Retorna dict unificado: CHAT_USERS + ChatUser do DB + usuarios legados."""
    users = {u: {**CHAT_USERS[u], "username": u} for u in CHAT_USERS}
    try:
        extras = ChatUser.query.filter_by(active=True).all()
        for e in extras:
            if e.username not in users:
                users[e.username] = e.to_dict()
                users[e.username]["password"] = e.password  # base64
    except Exception:
        pass
    return users


def _verify_password(stored_hash: str, candidate: str) -> bool:
    if not stored_hash or not candidate:
        return False
    try:
        return check_password_hash(stored_hash, candidate)
    except (ValueError, TypeError):
        return False


def _chat_user_payload(username, user_data):
    return {
        "username": username,
        "name": user_data.get("name", username),
        "role": user_data.get("role", ""),
        "avatar": user_data.get("avatar", "😊"),
        "profile": user_data.get("profile", "user"),
    }


def _authenticate_unified_user(username, password):
    if not username or not password:
        return None
    users = _all_chat_users()
    user_data = users.get(username)
    if not user_data:
        return None
    stored_hash = user_data.get("password", "")
    if _verify_password(stored_hash, password):
        return _chat_user_payload(username, user_data)
    return None


def _current_chat_user():
    username = (session.get("usuario") or "").strip().lower()
    if not username:
        return None
    return _all_chat_users().get(username)


def _current_chat_is_admin():
    user_data = _current_chat_user()
    return bool(user_data and user_data.get("profile") in ("admin", "master"))


def _current_chat_is_master():
    user_data = _current_chat_user()
    return bool(user_data and user_data.get("profile") == "master")


def _current_chat_username():
    return (session.get("usuario") or "").strip().lower()


def _unique_valid_members(members):
    users = _all_chat_users()
    clean = []
    for member in members or []:
        username = str(member or "").strip().lower()
        if username and username in users and username not in clean:
            clean.append(username)
    return clean


def _room_members(room):
    if not room:
        return []
    if room.startswith("dm_"):
        return [u for u in room[3:].split("__") if u]
    if room.startswith("grp_"):
        g = db.session.get(ChatGroup, room[4:])
        return g.members if g else []
    return []


def _can_access_room(username, room):
    if not username or not room:
        return False
    if _current_chat_is_admin():
        return True
    return username in _room_members(room)


def _can_manage_group(username, group):
    if not username or not group:
        return False
    return _current_chat_is_admin() or group.created_by == username


def _chat_active_filter():
    now = get_now()
    return and_(
        ChatMessage.deleted_at.is_(None),
        or_(ChatMessage.expires_at.is_(None), ChatMessage.expires_at > now),
    )


def _parse_expires_at(data):
    try:
        minutes = int(data.get("expireMinutes") or 0)
    except (TypeError, ValueError):
        minutes = 0
    if minutes <= 0:
        return None
    minutes = min(minutes, 7 * 24 * 60)
    return get_now() + timedelta(minutes=minutes)


def _parse_visibility_mode(data):
    mode = (data.get("visibilityMode") or data.get("mode") or "normal").strip().lower()
    return "once" if mode in ("once", "view_once", "single", "unica", "única") else "normal"


def _chat_master_usernames():
    return [username for username, data in _all_chat_users().items() if data.get("profile") == "master"]


def _chat_audit(action, actor, room=None, message_id=None, details=None):
    if actor in _chat_master_usernames() and action in ("open_once", "read"):
        return
    try:
        db.session.add(ChatAuditLog(
            action=action,
            actor=actor or "",
            room=room,
            message_id=message_id,
            details=details or {},
        ))
    except Exception:
        pass


def _mark_messages_read(room, username, msgs):
    if not username or _current_chat_is_master():
        return
    changed = []
    for msg in msgs:
        if msg.from_user == username:
            continue
        read_by = msg.read_by or []
        if isinstance(read_by, str):
            try:
                read_by = json.loads(read_by)
            except Exception:
                read_by = []
        if username not in read_by:
            read_by.append(username)
            msg.read_by = read_by
            flag_modified(msg, "read_by")
            changed.append(msg.id)
    if changed:
        _chat_audit("read", username, room=room, details={"ids": changed})


def _emit_to_chat_room(room, event, payload):
    if room.startswith("dm_"):
        for username in set(_room_members(room) + _chat_master_usernames()):
            socketio.emit(event, payload, to=f"user_{username}")
        return
    if room.startswith("grp_"):
        for username in set(_room_members(room) + _chat_master_usernames()):
            socketio.emit(event, payload, to=f"user_{username}")
        return
    socketio.emit(event, payload, to=room)


def _emit_chat_message(msg):
    for username in set(_room_members(msg.room) + _chat_master_usernames()):
        user_data = _all_chat_users().get(username, {})
        audit = user_data.get("profile") == "master"
        socketio.emit("new_message", msg.to_dict(viewer=username, force_visible=audit, audit=audit), to=f"user_{username}")


def _ensure_chat_schema():
    """Garante colunas novas do chat em bancos existentes sem Flask-Migrate."""
    dialect = db.engine.dialect.name
    if dialect == "postgresql":
        statements = [
            "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP",
            "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS deleted_by VARCHAR(100)",
            "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP",
            "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS visibility_mode VARCHAR(20) DEFAULT 'normal'",
            "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS viewed_by JSON DEFAULT '[]'::json",
            "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS reply_to_id INTEGER",
            "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS edited_at TIMESTAMP",
            "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS pinned BOOLEAN DEFAULT FALSE",
            "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS read_by JSON DEFAULT '[]'::json",
        ]
        for statement in statements:
            db.session.execute(text(statement))
        db.session.commit()
        return

    if dialect == "sqlite":
        rows = db.session.execute(text("PRAGMA table_info(chat_messages)")).fetchall()
        columns = {row[1] for row in rows}
        if "deleted_at" not in columns:
            db.session.execute(text("ALTER TABLE chat_messages ADD COLUMN deleted_at DATETIME"))
        if "deleted_by" not in columns:
            db.session.execute(text("ALTER TABLE chat_messages ADD COLUMN deleted_by VARCHAR(100)"))
        if "expires_at" not in columns:
            db.session.execute(text("ALTER TABLE chat_messages ADD COLUMN expires_at DATETIME"))
        if "visibility_mode" not in columns:
            db.session.execute(text("ALTER TABLE chat_messages ADD COLUMN visibility_mode VARCHAR(20) DEFAULT 'normal'"))
        if "viewed_by" not in columns:
            db.session.execute(text("ALTER TABLE chat_messages ADD COLUMN viewed_by JSON DEFAULT '[]'"))
        if "reply_to_id" not in columns:
            db.session.execute(text("ALTER TABLE chat_messages ADD COLUMN reply_to_id INTEGER"))
        if "edited_at" not in columns:
            db.session.execute(text("ALTER TABLE chat_messages ADD COLUMN edited_at DATETIME"))
        if "pinned" not in columns:
            db.session.execute(text("ALTER TABLE chat_messages ADD COLUMN pinned BOOLEAN DEFAULT 0"))
        if "read_by" not in columns:
            db.session.execute(text("ALTER TABLE chat_messages ADD COLUMN read_by JSON DEFAULT '[]'"))
        db.session.commit()


_chat_schema_ready = False


@app.before_request
def _ensure_chat_schema_once():
    global _chat_schema_ready
    if _chat_schema_ready:
        return
    try:
        db.create_all()
        _ensure_chat_schema()
        _chat_schema_ready = True
    except Exception:
        db.session.rollback()


@app.route("/api/chat/login", methods=["POST"])
def chat_login():
    data = request.get_json(force=True, silent=True) or {}
    username = (data.get("username") or "").strip().lower()
    password = (data.get("password") or "").strip()
    if not username or not password:
        return jsonify({"error": "Preencha usuário e senha."}), 400
    auth_user = _authenticate_unified_user(username, password)
    if not auth_user:
        users = _all_chat_users()
        if username not in users:
            return jsonify({"error": "Usuário não encontrado."}), 401
        return jsonify({"error": "Senha incorreta."}), 401
    session["usuario"] = auth_user["username"] # IMPORTANTE: Define a sessão para o chat
    return jsonify(auth_user), 200


@app.route("/api/chat/me", methods=["GET"])
def chat_me():
    username = session.get("usuario")
    if not username:
        return jsonify({"error": "Sessão não encontrada."}), 401
    
    username = str(username).strip().lower()
    users = _all_chat_users()
    u = users.get(username)
    if not u:
        return jsonify({"error": "Acesso ao chat não autorizado."}), 403
    
    response = jsonify(_chat_user_payload(username, u))
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    return response, 200


@app.route("/api/chat/users", methods=["GET"])
@login_required
def chat_get_users():
    users = _all_chat_users()
    me = _current_chat_username()
    is_master = _current_chat_is_master()
    result = []
    for k, v in users.items():
        if k == me: continue
        if v.get("profile") == "master" and not is_master: continue
        result.append({"username": k, "name": v["name"], "role": v.get("role", ""),
                       "avatar": v.get("avatar", "😊"), "profile": v.get("profile", "user")})
    return jsonify(result), 200


@app.route("/api/chat/users", methods=["POST"])
@login_required
def chat_add_user():
    """Admin adiciona usuário extra."""
    if not _current_chat_is_admin():
        return jsonify({"error": "Acesso negado."}), 403
    data = request.get_json(force=True, silent=True) or {}
    username = (data.get("username") or "").strip().lower()
    name     = (data.get("name") or "").strip()
    password = (data.get("password") or "").strip()
    if not username or not name or not password:
        return jsonify({"error": "username, name e password são obrigatórios."}), 400
    if len(password) < 10:
        return jsonify({"error": "A senha deve ter no mínimo 10 caracteres."}), 400
    users = _all_chat_users()
    if username in users:
        return jsonify({"error": "Usuário já existe."}), 409
    profile = data.get("profile", "user")
    if profile not in ("user", "admin", "master"):
        profile = "user"
    if profile == "master" and not _current_chat_is_master():
        return jsonify({"error": "Apenas usuÃ¡rio master pode criar outro master."}), 403
    password_hash = generate_password_hash(password)
    cu = ChatUser(username=username, name=name, role=data.get("role", ""),
                  avatar=data.get("avatar", "😊"), password=password_hash,
                  profile=profile)
    db.session.add(cu)
    db.session.commit()
    return jsonify(cu.to_dict()), 201


@app.route("/api/chat/users/<username>", methods=["DELETE"])
@login_required
def chat_delete_user(username):
    """Admin remove usuário extra."""
    if not _current_chat_is_admin():
        return jsonify({"error": "Acesso negado."}), 403
    if username in CHAT_USERS:
        return jsonify({"error": "Não é possível remover usuário padrão."}), 403
    cu = ChatUser.query.filter_by(username=username).first()
    if not cu:
        return jsonify({"error": "Não encontrado."}), 404
    db.session.delete(cu)
    db.session.commit()
    return jsonify({"success": True}), 200


@app.route("/api/chat/groups", methods=["GET"])
@login_required
def chat_get_groups():
    username = _current_chat_username()
    # Admin vê todos os grupos, usuários normais vêem apenas onde são membros
    if username and not _current_chat_is_admin():
        # No PostgreSQL, para buscar em JSON, convertemos para texto para usar LIKE
        groups = ChatGroup.query.filter(
            ChatGroup.members.cast(db.Text).like(f'%"{username}"%')
        ).all()
    else:
        groups = ChatGroup.query.all()
    return jsonify([g.to_dict() for g in groups]), 200


@app.route("/api/chat/groups", methods=["POST"])
@login_required
def chat_create_group():
    data = request.get_json(force=True, silent=True) or {}
    name    = (data.get("name") or "").strip()
    icon    = data.get("icon", "📁")
    created_by = _current_chat_username()
    members = _unique_valid_members(data.get("members", []))
    if not name:
        return jsonify({"error": "Nome obrigatório."}), 400
    if created_by not in members:
        members.insert(0, created_by)
    gid = str(uuid.uuid4())[:12]
    g = ChatGroup(id=gid, name=name, icon=icon, members=members, created_by=created_by)
    db.session.add(g)
    db.session.commit()
    # Notifica membros via Socket.IO
    socketio.emit("group_created", g.to_dict(), to="lobby")
    return jsonify(g.to_dict()), 201


@app.route("/api/chat/groups/<gid>", methods=["DELETE"])
@login_required
def chat_delete_group(gid):
    """Admin ou criador remove um grupo permanentemente."""
    g = db.session.get(ChatGroup, gid)
    if not g: return jsonify({"error": "Grupo não encontrado."}), 404
    if not _can_manage_group(_current_chat_username(), g):
        return jsonify({"error": "Acesso negado."}), 403
    
    # Apaga mensagens do grupo também
    ChatMessage.query.filter_by(room='grp_'+gid).delete()
    db.session.delete(g)
    db.session.commit()
    socketio.emit("group_deleted", {"id": gid}, to="lobby")
    return jsonify({"success": True}), 200


@app.route("/api/chat/groups/<gid>", methods=["PUT"])
@login_required
def chat_update_group(gid):
    data = request.get_json(force=True, silent=True) or {}
    g = db.session.get(ChatGroup, gid)
    if not g:
        return jsonify({"error": "Grupo não encontrado."}), 404
    if not _can_manage_group(_current_chat_username(), g):
        return jsonify({"error": "Acesso negado."}), 403
    if "name" in data: g.name = data["name"].strip()
    if "icon" in data: g.icon = data["icon"]
    if "members" in data:
        members = _unique_valid_members(data["members"])
        if g.created_by and g.created_by not in members:
            members.insert(0, g.created_by)
        g.members = members
    db.session.commit()
    socketio.emit("group_updated", g.to_dict(), to="lobby")
    return jsonify(g.to_dict()), 200


@app.route("/api/chat/messages/<room>", methods=["GET"])
@login_required
def chat_get_messages(room):
    if not _can_access_room(_current_chat_username(), room):
        return jsonify({"error": "Acesso negado."}), 403
    limit = int(request.args.get("limit", 80))
    query = ChatMessage.query.filter(ChatMessage.room == room)
    if not _current_chat_is_master():
        query = query.filter(_chat_active_filter())
    msgs = query.order_by(ChatMessage.timestamp.desc()).limit(limit).all()
    viewer = _current_chat_username()
    audit = _current_chat_is_master()
    ordered = list(reversed(msgs))
    _mark_messages_read(room, viewer, ordered)
    db.session.commit()
    return jsonify([m.to_dict(viewer=viewer, force_visible=audit, audit=audit) for m in ordered]), 200


@app.route("/api/chat/messages/<int:msg_id>/open-once", methods=["POST"])
@login_required
def chat_open_once_message(msg_id):
    username = _current_chat_username()
    msg = db.session.get(ChatMessage, msg_id)
    is_master = _current_chat_is_master()
    if not msg or (msg.deleted_at is not None and not is_master):
        return jsonify({"error": "Mensagem nÃ£o encontrada."}), 404
    if not _can_access_room(username, msg.room):
        return jsonify({"error": "Acesso negado."}), 403
    if msg.expires_at is not None and msg.expires_at <= get_now() and not is_master:
        return jsonify({"error": "Mensagem expirada."}), 410
    if (msg.visibility_mode or "normal") != "once":
        return jsonify(msg.to_dict(viewer=username, force_visible=is_master, audit=is_master)), 200

    viewed_by = msg.viewed_by or []
    if isinstance(viewed_by, str):
        try:
            viewed_by = json.loads(viewed_by)
        except Exception:
            viewed_by = []
    if username != msg.from_user and username in viewed_by and not is_master:
        return jsonify({"error": "Essa mensagem jÃ¡ foi visualizada.", "message": msg.to_dict(viewer=username)}), 410

    payload = msg.to_dict(viewer=username, force_visible=True, audit=is_master)
    if username != msg.from_user and not is_master:
        viewed_by.append(username)
        msg.viewed_by = viewed_by
        flag_modified(msg, "viewed_by")
        _chat_audit("open_once", username, room=msg.room, message_id=msg.id)
        db.session.commit()
        socketio.emit("once_message_opened", {"room": msg.room, "id": msg.id, "viewer": username}, to=f"user_{username}")
    return jsonify(payload), 200


@app.route("/api/chat/messages/delete-selected", methods=["POST"])
@login_required
def chat_delete_selected_messages():
    data = request.get_json(force=True, silent=True) or {}
    room = data.get("room", "")
    ids = data.get("ids", [])
    username = _current_chat_username()
    if not _can_access_room(username, room):
        return jsonify({"error": "Acesso negado."}), 403
    try:
        ids = [int(i) for i in ids]
    except (TypeError, ValueError):
        return jsonify({"error": "IDs inválidos."}), 400
    if not ids:
        return jsonify({"error": "Selecione ao menos uma mensagem."}), 400

    query = ChatMessage.query.filter(ChatMessage.room == room, ChatMessage.id.in_(ids), ChatMessage.deleted_at.is_(None))
    if not _current_chat_is_admin():
        query = query.filter(ChatMessage.from_user == username)
    msgs = query.all()
    if not msgs:
        return jsonify({"error": "Nenhuma mensagem permitida para apagar."}), 403

    now = get_now()
    deleted_ids = []
    for msg in msgs:
        msg.deleted_at = now
        msg.deleted_by = username
        deleted_ids.append(msg.id)
        _chat_audit("delete", username, room=room, message_id=msg.id)
    db.session.commit()

    payload = {"room": room, "ids": deleted_ids, "deletedBy": username}
    _emit_to_chat_room(room, "messages_deleted", payload)
    return jsonify({"success": True, "ids": deleted_ids}), 200


@app.route("/api/chat/messages/<int:msg_id>", methods=["PUT"])
@login_required
def chat_edit_message(msg_id):
    username = _current_chat_username()
    data = request.get_json(force=True, silent=True) or {}
    text = (data.get("text") or "").strip()
    msg = db.session.get(ChatMessage, msg_id)
    if not msg or msg.deleted_at is not None:
        return jsonify({"error": "Mensagem nÃ£o encontrada."}), 404
    if msg.from_user != username and not _current_chat_is_master():
        return jsonify({"error": "Acesso negado."}), 403
    if msg.msg_type != "text":
        return jsonify({"error": "Apenas texto pode ser editado."}), 400
    if not text:
        return jsonify({"error": "Mensagem vazia."}), 400
    msg.content = text[:4000]
    msg.edited_at = get_now()
    _chat_audit("edit", username, room=msg.room, message_id=msg.id)
    db.session.commit()
    payload = msg.to_dict(viewer=username, force_visible=_current_chat_is_master(), audit=_current_chat_is_master())
    _emit_to_chat_room(msg.room, "message_updated", payload)
    return jsonify(payload), 200


@app.route("/api/chat/messages/<int:msg_id>/pin", methods=["POST"])
@login_required
def chat_pin_message(msg_id):
    username = _current_chat_username()
    msg = db.session.get(ChatMessage, msg_id)
    if not msg or msg.deleted_at is not None:
        return jsonify({"error": "Mensagem nÃ£o encontrada."}), 404
    if not _can_access_room(username, msg.room) or not _current_chat_is_admin():
        return jsonify({"error": "Acesso negado."}), 403
    msg.pinned = not bool(msg.pinned)
    _chat_audit("pin" if msg.pinned else "unpin", username, room=msg.room, message_id=msg.id)
    db.session.commit()
    payload = msg.to_dict(viewer=username, force_visible=_current_chat_is_master(), audit=_current_chat_is_master())
    _emit_to_chat_room(msg.room, "message_updated", payload)
    return jsonify(payload), 200


@app.route("/api/chat/messages/<int:msg_id>/forward", methods=["POST"])
@login_required
def chat_forward_message(msg_id):
    username = _current_chat_username()
    data = request.get_json(force=True, silent=True) or {}
    target_room = data.get("room", "")
    src = db.session.get(ChatMessage, msg_id)
    if not src or src.deleted_at is not None:
        return jsonify({"error": "Mensagem nÃ£o encontrada."}), 404
    if not _can_access_room(username, src.room) or not _can_access_room(username, target_room):
        return jsonify({"error": "Acesso negado."}), 403
    msg = ChatMessage(
        room=target_room,
        from_user=username,
        msg_type=src.msg_type,
        content=src.content,
        file_name=src.file_name,
        file_size=src.file_size,
        reply_to_id=src.id,
    )
    db.session.add(msg)
    _chat_audit("forward", username, room=target_room, message_id=src.id, details={"fromRoom": src.room})
    db.session.commit()
    _emit_chat_message(msg)
    return jsonify(msg.to_dict(viewer=username)), 201


@app.route("/api/chat/messages/<room>/files", methods=["GET"])
@login_required
def chat_room_files(room):
    username = _current_chat_username()
    if not _can_access_room(username, room):
        return jsonify({"error": "Acesso negado."}), 403
    query = ChatMessage.query.filter(ChatMessage.room == room, ChatMessage.msg_type.in_(("image", "file", "audio")))
    if not _current_chat_is_master():
        query = query.filter(_chat_active_filter())
    files = query.order_by(ChatMessage.timestamp.desc()).limit(200).all()
    audit = _current_chat_is_master()
    return jsonify([m.to_dict(viewer=username, force_visible=audit, audit=audit) for m in files]), 200


@app.route("/api/chat/messages/<room>/export", methods=["GET"])
@login_required
def chat_export_room(room):
    username = _current_chat_username()
    if not _current_chat_is_admin() or not _can_access_room(username, room):
        return jsonify({"error": "Acesso negado."}), 403
    query = ChatMessage.query.filter(ChatMessage.room == room)
    if not _current_chat_is_master():
        query = query.filter(_chat_active_filter())
    msgs = query.order_by(ChatMessage.timestamp.asc()).all()
    lines = [f"Exportacao Help Desk - sala {room} - {get_now().strftime('%d/%m/%Y %H:%M')}"]
    for msg in msgs:
        stamp = msg.timestamp.strftime("%d/%m/%Y %H:%M")
        status = []
        if msg.deleted_at: status.append(f"apagada por {msg.deleted_by}")
        if msg.expires_at and msg.expires_at <= get_now(): status.append("expirada")
        if msg.visibility_mode == "once": status.append("visualizacao unica")
        body = msg.content if msg.msg_type == "text" else f"[{msg.msg_type}] {msg.file_name or ''}"
        lines.append(f"[{stamp}] {msg.from_user}: {body} {' '.join(status)}")
    _chat_audit("export", username, room=room)
    return Response("\n".join(lines), mimetype="text/plain; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename=chat_{room}.txt"})


@app.route("/api/chat/messages/<room>", methods=["DELETE"])
@login_required
def chat_delete_messages(room):
    """Admin apaga histórico de uma sala."""
    if not _current_chat_is_admin():
        return jsonify({"error": "Acesso negado."}), 403
    if not _can_access_room(_current_chat_username(), room):
        return jsonify({"error": "Acesso negado."}), 403

    try:
        now = get_now()
        ChatMessage.query.filter(ChatMessage.room == room, ChatMessage.deleted_at.is_(None)).update(
            {"deleted_at": now, "deleted_by": _current_chat_username()},
            synchronize_session=False,
        )
        _chat_audit("clear_room", _current_chat_username(), room=room)
        db.session.commit()
        _emit_to_chat_room(room, "chat_cleared", {"room": room})
        return jsonify({"success": True}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@app.route("/api/chat/last_messages", methods=["GET"])
@login_required
def chat_last_messages():
    """Retorna o timestamp da última mensagem de cada sala (para ordenação)."""
    # Subquery para pegar o maior timestamp por sala
    subq = db.session.query(
        ChatMessage.room,
        func.max(ChatMessage.timestamp).label("max_ts")
    ).filter(_chat_active_filter()).group_by(ChatMessage.room).subquery()
    
    results = db.session.query(subq.c.room, subq.c.max_ts).all()
    
    # Formata: { room_id: timestamp_ms }
    summary = {r: int(ts.timestamp() * 1000) for r, ts in results if ts}
    return jsonify(summary), 200


@app.route("/api/chat/audit/rooms", methods=["GET"])
@login_required
def chat_audit_rooms():
    if not _current_chat_is_master():
        return jsonify({"error": "Acesso negado."}), 403
    users = _all_chat_users()
    rooms = {}
    for room, max_ts in db.session.query(ChatMessage.room, func.max(ChatMessage.timestamp)).group_by(ChatMessage.room).all():
        if room.startswith("dm_"):
            parts = room[3:].split("__")
            label = " ↔ ".join(users.get(p, {}).get("name", p) for p in parts)
            rooms[room] = {"id": room, "type": "dm", "label": label, "icon": "👁️", "ts": int(max_ts.timestamp()*1000) if max_ts else 0}
        elif room.startswith("grp_"):
            gid = room[4:]
            g = db.session.get(ChatGroup, gid)
            label = g.name if g else room
            rooms[room] = {"id": room, "type": "group", "target": gid, "label": label, "icon": g.icon if g else "📁", "ts": int(max_ts.timestamp()*1000) if max_ts else 0}
    for g in ChatGroup.query.all():
        rid = "grp_" + g.id
        rooms.setdefault(rid, {"id": rid, "type": "group", "target": g.id, "label": g.name, "icon": g.icon, "ts": 0})
    return jsonify(sorted(rooms.values(), key=lambda r: r.get("ts", 0), reverse=True)), 200


@app.route("/api/chat/audit/logs", methods=["GET"])
@login_required
def chat_audit_logs():
    if not _current_chat_is_master():
        return jsonify({"error": "Acesso negado."}), 403
    logs = ChatAuditLog.query.order_by(ChatAuditLog.timestamp.desc()).limit(200).all()
    return jsonify([l.to_dict() for l in logs]), 200


@app.route("/api/chat/upload", methods=["POST"])
@login_required
def chat_upload():
    """Upload de arquivo/imagem — retorna o conteúdo base64 para broadcast."""
    data = request.get_json(force=True, silent=True) or {}
    room      = data.get("room", "")
    from_user = _current_chat_username()
    file_name = data.get("fileName", "arquivo")
    file_size = data.get("fileSize", 0)
    file_data = data.get("data", "")  # base64
    msg_type  = data.get("type", "file")  # image | file | audio
    reply_to = data.get("replyTo")
    if msg_type not in ("image", "file", "audio"):
        msg_type = "file"
    if not room or not from_user or not file_data:
        return jsonify({"error": "Dados incompletos."}), 400
    if not _can_access_room(from_user, room):
        return jsonify({"error": "Acesso negado."}), 403
    msg = ChatMessage(room=room, from_user=from_user, msg_type=msg_type,
                      content=file_data, file_name=file_name, file_size=file_size,
                      expires_at=_parse_expires_at(data),
                      visibility_mode=_parse_visibility_mode(data),
                      reply_to_id=reply_to if isinstance(reply_to, int) else None,
                      read_by=[from_user])
    db.session.add(msg)
    db.session.commit()
    payload = msg.to_dict(viewer=from_user)
    _emit_chat_message(msg)
    return jsonify(payload), 201


# ================================
# GIF Search Proxy
# ================================
_FALLBACK_GIFS = [
    {"thumb": "https://media.giphy.com/media/3oEjI6SIIHBdRxXI40/200w.gif", "url": "https://media.giphy.com/media/3oEjI6SIIHBdRxXI40/giphy.gif"},
    {"thumb": "https://media.giphy.com/media/5GoVLqeAOo6PK/200w.gif", "url": "https://media.giphy.com/media/5GoVLqeAOo6PK/giphy.gif"},
]


@app.route("/api/gif/search", methods=["GET"])
@login_required
def gif_search():
    q = request.args.get("q", "").strip()[:100]
    try:
        limit = max(1, min(int(request.args.get("limit", 20)), 30))
    except (TypeError, ValueError):
        limit = 20

    api_key = os.getenv("GIPHY_API_KEY", "").strip()
    if not api_key:
        return jsonify({"gifs": _FALLBACK_GIFS[:limit], "source": "fallback"}), 200

    endpoint = "trending" if not q or q == "trending" else "search"
    params = {"api_key": api_key, "limit": limit, "rating": "g"}
    if endpoint == "search":
        params.update({"q": q, "lang": "pt"})
    try:
        response = requests.get(
            f"https://api.giphy.com/v1/gifs/{endpoint}",
            params=params,
            timeout=6,
        )
        response.raise_for_status()
        gifs = []
        for item in response.json().get("data", []):
            images = item.get("images", {})
            thumb = images.get("fixed_height_small", {}).get("url", "")
            full = images.get("fixed_height", {}).get("url", "")
            if thumb and full:
                gifs.append({"thumb": thumb, "url": full})
        if gifs:
            return jsonify({"gifs": gifs, "source": "giphy"}), 200
    except requests.RequestException:
        logger.info("Giphy unavailable; using curated fallback")
    return jsonify({"gifs": _FALLBACK_GIFS[:limit], "source": "fallback"}), 200


# ================================
# Socket.IO — Eventos
# ================================
@socketio.on("connect")
def sio_connect():
    username = _current_chat_username()
    if not username or username not in _all_chat_users():
        return False
    join_room("lobby")
    join_room(f"user_{username}")
    _online_users[username] = request.sid
    socketio.emit("online_list", list(_online_users.keys()), to="lobby")

@socketio.on("disconnect")
def sio_disconnect_evt():
    username = None
    for u, sid in list(_online_users.items()):
        if sid == request.sid:
            username = u
            break
    if username:
        del _online_users[username]
        socketio.emit("user_offline", {"username": username}, to="lobby")

@socketio.on("user_online")
def sio_user_online(data):
    username = _current_chat_username()
    if username:
        _online_users[username] = request.sid
        join_room("lobby")
        join_room(f"user_{username}")
        socketio.emit("online_list", list(_online_users.keys()), to="lobby")

@socketio.on("join")
def sio_join(data):
    username = _current_chat_username()
    room = str((data or {}).get("room", ""))[:150]
    if username and room and _can_access_room(username, room):
        join_room(room)

@socketio.on("leave")
def sio_leave(data):
    username = _current_chat_username()
    room = str((data or {}).get("room", ""))[:150]
    if username and room and _can_access_room(username, room):
        leave_room(room)

@socketio.on("send_message")
def sio_send_message(data):
    room      = data.get("room", "")
    from_user = _current_chat_username()
    text      = data.get("text", "")
    msg_type  = data.get("type", "text")
    msg_data  = data.get("data", "")
    reply_to  = data.get("replyTo")
    
    if not room or not from_user:
        return
    if msg_type not in ("text", "image"):
        msg_type = "text"
    if msg_type == "text" and not text.strip():
        return
    if not _can_access_room(from_user, room):
        socketio.emit("error_msg", {"message": "Acesso negado para esta conversa."}, to=request.sid)
        return
    
    # Segurança: Rate limit para evitar spam
    if _is_chat_rate_limited(from_user):
        socketio.emit("error_msg", {"message": "Calma! Você está enviando mensagens muito rápido."}, to=request.sid)
        return

    with app.app_context():
        # Limite de tamanho de mensagem (LGPD/Segurança)
        content = (msg_data if msg_type == "image" else text)[:4000] 
        msg = ChatMessage(room=room, from_user=from_user, msg_type=msg_type,
                          content=content, expires_at=_parse_expires_at(data),
                          visibility_mode=_parse_visibility_mode(data),
                          reply_to_id=reply_to if isinstance(reply_to, int) else None,
                          read_by=[from_user])
        db.session.add(msg)
        db.session.commit()
        payload = msg.to_dict(viewer=from_user)

    # Roteamento Inteligente: Envia para a sala individual de cada destinatário
    _emit_chat_message(msg)

@socketio.on("typing")
def sio_typing(data):
    username = _current_chat_username()
    room = str((data or {}).get("room", ""))[:150]
    if username and room and _can_access_room(username, room):
        emit("typing", {"room": room, "from": username}, to=room, include_self=False)

@socketio.on("confirm_call")
def sio_confirm_call(data):
    username = _current_chat_username()
    target = str((data or {}).get("to", ""))[:100]
    if username and target in _all_chat_users():
        socketio.emit("call_confirmed", {"userName": username}, to=f"user_{target}")

@socketio.on("stop_typing")
def sio_stop_typing(data):
    username = _current_chat_username()
    room = str((data or {}).get("room", ""))[:150]
    if username and room and _can_access_room(username, room):
        emit("stop_typing", {"room": room, "from": username}, to=room, include_self=False)

@socketio.on("call_user")
def sio_call_user(data):
    from_user = _current_chat_username()
    target = str((data or {}).get("target", ""))[:100]
    users = _all_chat_users()
    if not from_user or target not in users:
        return
    caller = users.get(from_user, {}).get("name", from_user)
    socketio.emit(
        "incoming_call",
        {"callerName": caller, "callerUser": from_user},
        to=f"user_{target}",
    )


# -------------------------------
# Inicialização
# -------------------------------
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        _ensure_chat_schema()

    _debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    socketio.run(
        app,
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "5000")),
        debug=_debug,
        allow_unsafe_werkzeug=not IS_PRODUCTION,
    )
