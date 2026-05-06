"""
database.py — SQLite setup e modelos de dados
Clínica DTM & Sono — Dr. Victor Vaz
"""
import sqlite3
import os
from datetime import datetime

DB_PATH = os.environ.get("DB_PATH", "clinica.db")

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    nome        TEXT NOT NULL,
    email       TEXT UNIQUE NOT NULL,
    senha_hash  TEXT NOT NULL,
    papel       TEXT NOT NULL DEFAULT 'secretaria',
    clinica_id  INTEGER,
    ativo       INTEGER NOT NULL DEFAULT 1,
    criado_em   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS clinicas (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    nome      TEXT NOT NULL,
    cidade    TEXT NOT NULL,
    cnpj      TEXT,
    ativo     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS transacoes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    clinica_id  INTEGER NOT NULL REFERENCES clinicas(id),
    tipo        TEXT NOT NULL,
    categoria   TEXT NOT NULL,
    subtipo     TEXT,
    descricao   TEXT,
    valor       REAL NOT NULL,
    data        TEXT NOT NULL,
    mes         INTEGER NOT NULL,
    ano         INTEGER NOT NULL,
    comprovante TEXT,
    criado_por  INTEGER REFERENCES users(id),
    criado_em   TEXT NOT NULL DEFAULT (datetime('now')),
    origem_msg  TEXT
);

CREATE TABLE IF NOT EXISTS leads (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    clinica_id      INTEGER NOT NULL REFERENCES clinicas(id),
    nome            TEXT NOT NULL,
    telefone        TEXT,
    origem          TEXT,
    mes             INTEGER,
    ano             INTEGER,
    contato_feito   INTEGER DEFAULT 0,
    agendou         INTEGER DEFAULT 0,
    data_consulta   TEXT,
    compareceu      INTEGER DEFAULT 0,
    virou_paciente  INTEGER DEFAULT 0,
    observacoes     TEXT,
    criado_por      INTEGER REFERENCES users(id),
    criado_em       TEXT NOT NULL DEFAULT (datetime('now')),
    atualizado_em   TEXT
);

CREATE TABLE IF NOT EXISTS notas_fiscais (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    clinica_id      INTEGER NOT NULL REFERENCES clinicas(id),
    tomador_nome    TEXT NOT NULL,
    tomador_doc     TEXT,
    servico         TEXT NOT NULL,
    valor           REAL NOT NULL,
    data_emissao    TEXT,
    numero_nfse     TEXT,
    status          TEXT DEFAULT 'pendente',
    pdf_url         TEXT,
    xml_url         TEXT,
    erro_msg        TEXT,
    criado_por      INTEGER REFERENCES users(id),
    criado_em       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS comprovantes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    clinica_id  INTEGER NOT NULL REFERENCES clinicas(id),
    nome_arquivo TEXT NOT NULL,
    caminho     TEXT NOT NULL,
    tipo        TEXT,
    categoria   TEXT,
    mes         INTEGER,
    ano         INTEGER,
    tamanho     INTEGER,
    transacao_id INTEGER REFERENCES transacoes(id),
    criado_por  INTEGER REFERENCES users(id),
    criado_em   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS anuncios (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    clinica_id  INTEGER NOT NULL REFERENCES clinicas(id),
    plataforma  TEXT NOT NULL,
    mes         INTEGER NOT NULL,
    ano         INTEGER NOT NULL,
    investimento REAL DEFAULT 0,
    impressoes  INTEGER DEFAULT 0,
    cliques     INTEGER DEFAULT 0,
    leads       INTEGER DEFAULT 0,
    agendamentos INTEGER DEFAULT 0,
    novos_pacientes INTEGER DEFAULT 0,
    criado_por  INTEGER REFERENCES users(id),
    criado_em   TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(clinica_id, plataforma, mes, ano)
);

CREATE TABLE IF NOT EXISTS chat_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER REFERENCES users(id),
    clinica_id  INTEGER REFERENCES clinicas(id),
    mensagem    TEXT NOT NULL,
    resposta    TEXT,
    acao        TEXT,
    criado_em   TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

SEED = """
INSERT OR IGNORE INTO clinicas (id, nome, cidade, cnpj) VALUES
  (1, 'Clínica DTM & Sono — Balneário Camboriú', 'Balneário Camboriú/SC', NULL),
  (2, 'Clínica DTM & Sono — São José dos Campos', 'São José dos Campos/SP', NULL);

INSERT OR IGNORE INTO users (id, nome, email, senha_hash, papel, clinica_id) VALUES
  (1, 'Dr. Victor Vaz', 'admin@clinicadtm.com.br',
   '$2b$12$PLACEHOLDER_HASH_ADMIN', 'admin', NULL);
"""


def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.executescript(SEED)
    conn.commit()
    conn.close()
    print(f"[DB] Banco inicializado em {DB_PATH}")


def row_to_dict(row):
    if row is None:
        return None
    return dict(row)
