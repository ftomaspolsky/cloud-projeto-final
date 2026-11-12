"""Conexão com o MySQL e criação das tabelas do condomínio.

As tabelas nascem quando o serviço sobe porque o RDS não tem acesso público: não há de onde
rodar um script de fora da VPC. Tudo aqui é idempotente, então duas tasks subindo juntas não
se atrapalham.

A senha do banco é rotacionada pelo RDS a cada 7 dias. O ECS injeta a senha só quando a task
sobe, então uma task antiga passa a ouvir "Access denied" (visto em Ohio, em 12/11). Por isso,
ao receber esse erro, a conexão relê a senha atual no Secrets Manager e tenta de novo.
"""

import json
import logging
import os
import threading
import time

import boto3
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
    # Reserva cancelada não é apagada (o histórico e a cobrança apontam para ela): ela sai da
    # UNIQUE porque `vaga` vira NULL, e o MySQL aceita vários NULL numa chave única.
    """CREATE TABLE IF NOT EXISTS reserva (
           id BIGINT AUTO_INCREMENT PRIMARY KEY,
           area_comum_id INT NOT NULL,
           unidade_id INT NOT NULL,
           morador_id INT NOT NULL,
           data DATE NOT NULL,
           periodo ENUM('manha', 'tarde', 'noite') NOT NULL,
           status ENUM('ativa', 'cancelada') NOT NULL DEFAULT 'ativa',
           criada_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
           cancelada_em TIMESTAMP NULL,
           vaga TINYINT AS (IF(status = 'ativa', 1, NULL)) STORED,
           UNIQUE KEY uma_reserva_ativa_por_horario (area_comum_id, data, periodo, vaga),
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
           status ENUM('pendente', 'cobranca_gerada', 'cancelado') NOT NULL DEFAULT 'pendente',
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


_credenciais = {}
_trava_credenciais = threading.Lock()
ACESSO_NEGADO = 1045


def _credenciais_atuais(reler=False):
    """Usuário e senha. Começa pelo que o ECS injetou; relê no Secrets Manager quando pedido."""
    with _trava_credenciais:
        if reler and os.environ.get("DB_SECRET_ARN"):
            segredos = boto3.client("secretsmanager", region_name=os.environ["AWS_REGION"])
            valor = json.loads(segredos.get_secret_value(SecretId=os.environ["DB_SECRET_ARN"])["SecretString"])
            _credenciais.update(user=valor["username"], password=valor["password"])
            registrar(logging.WARNING, "senha do banco relida no Secrets Manager")
        if not _credenciais:
            _credenciais.update(user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"])
        return dict(_credenciais)


def conectar():
    try:
        return _abrir(_credenciais_atuais())
    except pymysql.err.OperationalError as erro:
        if erro.args[0] != ACESSO_NEGADO or not os.environ.get("DB_SECRET_ARN"):
            raise
        return _abrir(_credenciais_atuais(reler=True))


def _abrir(credenciais):
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
        user=credenciais["user"],
        password=credenciais["password"],
        database=os.environ["DB_NAME"],
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
        connect_timeout=5,
        **opcoes,
    )


# Erros que querem dizer "outra task já fez esta migração": coluna, chave ou índice já mexidos.
JA_MIGRADO = {1060, 1061, 1091}


def _tem_coluna(cursor, tabela, coluna):
    cursor.execute(
        """SELECT COLUMN_TYPE FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s""",
        (tabela, coluna),
    )
    linha = cursor.fetchone()
    return linha["COLUMN_TYPE"] if linha else None


def _tem_indice(cursor, tabela, indice):
    cursor.execute(
        """SELECT 1 FROM information_schema.STATISTICS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND INDEX_NAME = %s LIMIT 1""",
        (tabela, indice),
    )
    return cursor.fetchone() is not None


def _alterar(cursor, comando):
    try:
        cursor.execute(comando)
    except pymysql.err.OperationalError as erro:
        if erro.args[0] not in JA_MIGRADO:
            raise


def migrar(cursor):
    """Leva um banco da v3 (sem cancelamento) ao esquema atual. Idempotente."""
    if not _tem_coluna(cursor, "reserva", "status"):
        _alterar(cursor, """ALTER TABLE reserva
            ADD COLUMN status ENUM('ativa', 'cancelada') NOT NULL DEFAULT 'ativa' AFTER periodo,
            ADD COLUMN cancelada_em TIMESTAMP NULL,
            ADD COLUMN vaga TINYINT AS (IF(status = 'ativa', 1, NULL)) STORED""")
    # A chave nova entra antes de a antiga sair: a chave estrangeira de area_comum_id precisa
    # de um índice que comece por ela o tempo todo.
    if not _tem_indice(cursor, "reserva", "uma_reserva_ativa_por_horario"):
        _alterar(cursor, """ALTER TABLE reserva ADD UNIQUE KEY uma_reserva_ativa_por_horario
                            (area_comum_id, data, periodo, vaga)""")
    if _tem_indice(cursor, "reserva", "uma_reserva_por_horario"):
        _alterar(cursor, "ALTER TABLE reserva DROP INDEX uma_reserva_por_horario")
    if "cancelado" not in (_tem_coluna(cursor, "lancamento_financeiro", "status") or ""):
        _alterar(cursor, """ALTER TABLE lancamento_financeiro MODIFY status
                            ENUM('pendente', 'cobranca_gerada', 'cancelado') NOT NULL DEFAULT 'pendente'""")


def preparar_banco():
    with conectar() as conexao, conexao.cursor() as cursor:
        for tabela in TABELAS:
            cursor.execute(tabela)
        migrar(cursor)
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
