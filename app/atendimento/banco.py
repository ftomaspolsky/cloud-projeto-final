"""Conexão com o MySQL e criação das tabelas do condomínio.

As tabelas nascem quando o serviço sobe porque o RDS não tem acesso público: não há de onde
rodar um script de fora da VPC. Tudo aqui é idempotente, então duas tasks subindo juntas não
se atrapalham.
"""

import logging
import os
import time

import pymysql
from pymysql.cursors import DictCursor

from observabilidade import registrar

# O morador é fixo até o login existir. Vem daqui, nunca do que o modelo ou o cliente mandam.
MORADOR_DEMO_ID = 1

AREAS = [
    (1, "Salão de festas", "150.00"),
    (2, "Churrasqueira", "80.00"),
    (3, "Quadra", "30.00"),
]
NOMES_DAS_AREAS = [nome for _, nome, _ in AREAS]
PERIODOS = ["manha", "tarde", "noite"]

TABELAS = [
    """CREATE TABLE IF NOT EXISTS condominio (
           id INT PRIMARY KEY,
           nome VARCHAR(120) NOT NULL
       )""",
    """CREATE TABLE IF NOT EXISTS unidade (
           id INT PRIMARY KEY,
           condominio_id INT NOT NULL,
           numero VARCHAR(10) NOT NULL,
           FOREIGN KEY (condominio_id) REFERENCES condominio (id)
       )""",
    """CREATE TABLE IF NOT EXISTS morador (
           id INT PRIMARY KEY,
           unidade_id INT NOT NULL,
           nome VARCHAR(120) NOT NULL,
           FOREIGN KEY (unidade_id) REFERENCES unidade (id)
       )""",
    """CREATE TABLE IF NOT EXISTS area_comum (
           id INT PRIMARY KEY,
           condominio_id INT NOT NULL,
           nome VARCHAR(60) NOT NULL UNIQUE,
           taxa DECIMAL(10, 2) NOT NULL,
           FOREIGN KEY (condominio_id) REFERENCES condominio (id)
       )""",
    # A UNIQUE é quem garante que não existe reserva dupla, mesmo com duas tasks ao mesmo tempo.
    """CREATE TABLE IF NOT EXISTS reserva (
           id BIGINT AUTO_INCREMENT PRIMARY KEY,
           area_comum_id INT NOT NULL,
           unidade_id INT NOT NULL,
           morador_id INT NOT NULL,
           data DATE NOT NULL,
           periodo ENUM('manha', 'tarde', 'noite') NOT NULL,
           criada_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
           UNIQUE KEY uma_reserva_por_horario (area_comum_id, data, periodo),
           FOREIGN KEY (area_comum_id) REFERENCES area_comum (id),
           FOREIGN KEY (unidade_id) REFERENCES unidade (id),
           FOREIGN KEY (morador_id) REFERENCES morador (id)
       )""",
    """CREATE TABLE IF NOT EXISTS lancamento_financeiro (
           id BIGINT AUTO_INCREMENT PRIMARY KEY,
           reserva_id BIGINT NOT NULL UNIQUE,
           unidade_id INT NOT NULL,
           descricao VARCHAR(160) NOT NULL,
           valor DECIMAL(10, 2) NOT NULL,
           status ENUM('pendente', 'cobranca_gerada') NOT NULL DEFAULT 'pendente',
           referencia_pagamento VARCHAR(64),
           criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
           FOREIGN KEY (reserva_id) REFERENCES reserva (id)
       )""",
    """CREATE TABLE IF NOT EXISTS mensagem (
           id BIGINT AUTO_INCREMENT PRIMARY KEY,
           conversa_id VARCHAR(36) NOT NULL,
           morador_id INT NOT NULL,
           papel ENUM('user', 'assistant') NOT NULL,
           texto TEXT NOT NULL,
           criada_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
           KEY por_conversa (conversa_id, id)
       )""",
    # Caixa de saída: o evento é gravado na transação da reserva e publicado depois. Assim,
    # a fila fora do ar atrasa o evento, mas não o perde.
    """CREATE TABLE IF NOT EXISTS evento_saida (
           evento_id VARCHAR(36) PRIMARY KEY,
           corpo JSON NOT NULL,
           correlation_id VARCHAR(64) NOT NULL,
           criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
           publicado_em TIMESTAMP NULL,
           KEY pendentes (publicado_em, criado_em)
       )""",
]

DADOS_INICIAIS = [
    ("INSERT IGNORE INTO condominio (id, nome) VALUES (1, 'Residencial Exemplo')", ()),
    ("INSERT IGNORE INTO unidade (id, condominio_id, numero) VALUES (1, 1, '101')", ()),
    ("INSERT IGNORE INTO morador (id, unidade_id, nome) VALUES (%s, 1, 'Morador Demo')", (MORADOR_DEMO_ID,)),
] + [
    ("INSERT IGNORE INTO area_comum (id, condominio_id, nome, taxa) VALUES (%s, 1, %s, %s)", area)
    for area in AREAS
]


def conectar():
    opcoes = {}
    # Na AWS, o caminho do certificado do RDS vem por variável de ambiente. Local não há TLS.
    if os.environ.get("DB_SSL_CA"):
        opcoes = {
            "ssl_ca": os.environ["DB_SSL_CA"],
            "ssl_verify_cert": True,
            "ssl_verify_identity": True,
        }
    return pymysql.connect(
        host=os.environ["DB_HOST"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_NAME"],
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
        connect_timeout=5,
        **opcoes,
    )


def preparar_banco():
    with conectar() as conexao, conexao.cursor() as cursor:
        for tabela in TABELAS:
            cursor.execute(tabela)
        for comando, parametros in DADOS_INICIAIS:
            cursor.execute(comando, parametros)
        conexao.commit()


def preparar_banco_ate_conseguir():
    # Roda em segundo plano: o /health não depende do banco, para o ALB não derrubar a task
    # só porque o banco ainda está subindo.
    while True:
        try:
            preparar_banco()
            registrar(logging.INFO, "banco pronto")
            return
        except pymysql.Error as erro:
            registrar(logging.WARNING, "banco ainda indisponivel", erro=str(erro))
            time.sleep(3)
