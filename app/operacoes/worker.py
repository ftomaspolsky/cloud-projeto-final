"""operacoes — o serviço assíncrono, consumidor da fila de eventos.

Recebe `ReservaSolicitada` e faz o que vem depois da reserva: gera a cobrança e registra o aviso
ao morador. Recebe `ReservaCancelada` e cancela a cobrança (com estorno, se já tinha sido gerada).
A fila padrão do SQS não garante ordem: se o cancelamento chegar antes da solicitação, a
solicitação encontra a cobrança já cancelada e não cobra. As três garantias que o enunciado pede:
- repetição: se o processamento falha, a mensagem NÃO é apagada e volta para a fila depois
  do visibility timeout;
- duplicidade: cada evento_id é gravado numa tabela com chave primária, na mesma transação do
  efeito, então o mesmo evento entregue duas vezes é processado uma vez só;
- mensagem não processável: depois de 3 recebimentos sem sucesso, a própria fila a manda para
  a DLQ (configurado na fila, não aqui).

Ao receber SIGTERM (o ECS manda isso ao parar uma task, inclusive na drenagem de uma
instância), o worker termina o lote atual e sai, sem pegar mensagem nova.
"""

import json
import logging
import os
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import boto3
import pymysql

SERVICO = "operacoes"
ACESSO_NEGADO = 1045
# Banco fora do ar não é culpa da mensagem. Esperar evita gastar as 3 entregas à toa e mandar
# um evento válido para a DLQ durante um failover do RDS.
ESPERA_BANCO_FORA_SEGUNDOS = 60
parar = threading.Event()


class JsonFormatter(logging.Formatter):
    def format(self, record):
        evento = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "nivel": record.levelname,
            "servico": SERVICO,
            "msg": record.getMessage(),
        }
        evento.update(getattr(record, "extra_campos", {}))
        return json.dumps(evento, ensure_ascii=False)


handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JsonFormatter())
log = logging.getLogger(SERVICO)
log.addHandler(handler)
log.setLevel(logging.INFO)


_credenciais = {}
_trava_credenciais = threading.Lock()


def _credenciais_atuais(reler=False):
    """A senha do RDS é rotacionada a cada 7 dias, e o ECS só a injeta quando a task sobe. Ao
    receber "Access denied", relê a senha atual no Secrets Manager (visto em Ohio, em 12/11)."""
    with _trava_credenciais:
        if reler and os.environ.get("DB_SECRET_ARN"):
            segredos = boto3.client("secretsmanager", region_name=os.environ["AWS_REGION"])
            valor = json.loads(segredos.get_secret_value(SecretId=os.environ["DB_SECRET_ARN"])["SecretString"])
            _credenciais.update(user=valor["username"], password=valor["password"])
            log.warning("senha do banco relida no Secrets Manager")
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
        autocommit=False,
        connect_timeout=5,
        **opcoes,
    )


def preparar_banco():
    # Só as tabelas deste serviço. Sem chave estrangeira para as do `atendimento`, porque não
    # há garantia de qual dos dois sobe primeiro.
    for tentativa in range(30):
        try:
            with conectar() as conexao, conexao.cursor() as cursor:
                cursor.execute(
                    """CREATE TABLE IF NOT EXISTS evento_processado (
                           evento_id VARCHAR(36) PRIMARY KEY,
                           processado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                       )"""
                )
                cursor.execute(
                    """CREATE TABLE IF NOT EXISTS notificacao (
                           id BIGINT AUTO_INCREMENT PRIMARY KEY,
                           reserva_id BIGINT NOT NULL,
                           texto VARCHAR(255) NOT NULL,
                           criada_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                       )"""
                )
                conexao.commit()
            return
        except pymysql.err.OperationalError:
            log.info("banco ainda indisponivel", extra={"extra_campos": {"tentativa": tentativa}})
            time.sleep(2)
    raise RuntimeError("banco indisponivel")


def _status_do_lancamento(cursor, corpo):
    cursor.execute(
        "SELECT status FROM lancamento_financeiro WHERE id = %s AND reserva_id = %s FOR UPDATE",
        (corpo["lancamento_id"], corpo["reserva_id"]),
    )
    linha = cursor.fetchone()
    if linha is None:
        raise ValueError("lancamento inexistente")
    return linha[0]


def _avisar(cursor, corpo, texto):
    cursor.execute("INSERT INTO notificacao (reserva_id, texto) VALUES (%s, %s)", (corpo["reserva_id"], texto))


def _cobrar(cursor, corpo, campos):
    status = _status_do_lancamento(cursor, corpo)
    if status == "cancelado":
        # O cancelamento chegou primeiro: não há o que cobrar.
        log.info("reserva ja cancelada, cobranca nao gerada", extra={"extra_campos": campos})
        return
    if status != "pendente":
        raise ValueError("lancamento ja cobrado")
    # Simula o pedido de cobrança à integração de pagamento, que é fora do escopo do MVP.
    cursor.execute(
        """UPDATE lancamento_financeiro SET status = 'cobranca_gerada', referencia_pagamento = %s
           WHERE id = %s""",
        (f"PIX-{corpo['evento_id']}", corpo["lancamento_id"]),
    )
    _avisar(cursor, corpo, "Sua reserva foi confirmada e a cobrança está disponível.")


def _cancelar_cobranca(cursor, corpo, campos):
    status = _status_do_lancamento(cursor, corpo)
    if status == "cancelado":
        return
    cursor.execute(
        "UPDATE lancamento_financeiro SET status = 'cancelado' WHERE id = %s", (corpo["lancamento_id"],)
    )
    if status == "cobranca_gerada":
        # Simula o pedido de estorno à integração de pagamento.
        _avisar(cursor, corpo, "Sua reserva foi cancelada e o estorno da taxa foi solicitado.")
    else:
        _avisar(cursor, corpo, "Sua reserva foi cancelada antes da cobrança: nada será cobrado.")
    campos["estorno"] = status == "cobranca_gerada"


EFEITOS = {"ReservaSolicitada": _cobrar, "ReservaCancelada": _cancelar_cobranca}


def processar(corpo, cid):
    efeito = EFEITOS.get(corpo.get("tipo"))
    if efeito is None:
        raise ValueError(f"tipo de evento desconhecido: {corpo.get('tipo')}")
    evento_id = corpo["evento_id"]
    campos = {"evento_id": evento_id, "tipo": corpo["tipo"], "correlation_id": cid}

    with conectar() as conexao, conexao.cursor() as cursor:
        try:
            # O registro de idempotência e o efeito do evento entram na MESMA transação.
            cursor.execute("INSERT INTO evento_processado (evento_id) VALUES (%s)", (evento_id,))
        except pymysql.err.IntegrityError:
            conexao.rollback()
            log.info("evento duplicado ignorado", extra={"extra_campos": campos})
            return

        efeito(cursor, corpo, campos)
        conexao.commit()
    log.info("evento processado", extra={"extra_campos": campos})


class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        ok = self.path == "/health"
        self.send_response(200 if ok else 404)
        self.end_headers()
        if ok:
            self.wfile.write(b'{"status": "ok"}')

    def log_message(self, *args):
        pass


def main():
    signal.signal(signal.SIGTERM, lambda *_: parar.set())
    threading.Thread(
        target=HTTPServer(("0.0.0.0", 8081), Health).serve_forever, daemon=True
    ).start()

    preparar_banco()
    sqs = boto3.client(
        "sqs",
        region_name=os.environ["AWS_REGION"],
        endpoint_url=os.environ.get("SQS_ENDPOINT_URL"),
    )
    url = sqs.get_queue_url(QueueName=os.environ["QUEUE_NAME"])["QueueUrl"]
    log.info("consumindo", extra={"extra_campos": {"fila": os.environ["QUEUE_NAME"]}})

    while not parar.is_set():
        resposta = sqs.receive_message(
            QueueUrl=url,
            MaxNumberOfMessages=5,
            WaitTimeSeconds=10,
            MessageAttributeNames=["All"],
            AttributeNames=["ApproximateReceiveCount"],
        )
        for mensagem in resposta.get("Messages", []):
            cid = mensagem.get("MessageAttributes", {}).get("correlation_id", {}).get("StringValue", "-")
            try:
                processar(json.loads(mensagem["Body"]), cid)
                sqs.delete_message(QueueUrl=url, ReceiptHandle=mensagem["ReceiptHandle"])
            except pymysql.err.OperationalError as erro:
                log.error("banco fora do ar", extra={"extra_campos": {
                    "correlation_id": cid,
                    "erro": str(erro),
                }})
                parar.wait(ESPERA_BANCO_FORA_SEGUNDOS)
                break
            except Exception as erro:
                # Não apaga: a fila reentrega, e depois de maxReceiveCount manda para a DLQ.
                log.error("falha ao processar", extra={"extra_campos": {
                    "correlation_id": cid,
                    "erro": str(erro),
                    "recebimentos": mensagem["Attributes"]["ApproximateReceiveCount"],
                }})
    log.info("SIGTERM recebido, encerrando")


if __name__ == "__main__":
    main()
