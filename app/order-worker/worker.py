"""order-worker — o serviço assíncrono, consumidor da fila de pedidos.

Três garantias que o enunciado pede, já no esqueleto:
- repetição: se o processamento falha, a mensagem NÃO é apagada e volta para a fila depois
  do visibility timeout;
- duplicidade: cada pedido_id é gravado numa tabela com chave primária, então a mesma
  mensagem entregue duas vezes é processada uma vez só;
- mensagem não processável: depois de N recebimentos sem sucesso, a própria fila a manda
  para a DLQ (configurado na fila, não aqui).

Ao receber SIGTERM (o ECS manda isso ao parar uma task, inclusive na drenagem de uma
instância), o worker termina a mensagem atual e sai, sem pegar mensagem nova.
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

SERVICO = "order-worker"
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


def conectar():
    return pymysql.connect(
        host=os.environ["DB_HOST"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_NAME"],
        autocommit=False,
    )


def preparar_banco():
    # Tabela de idempotência. Não depende do tema: guarda só o id de cada pedido processado.
    for tentativa in range(30):
        try:
            with conectar() as conexao, conexao.cursor() as cursor:
                cursor.execute(
                    """CREATE TABLE IF NOT EXISTS pedidos_processados (
                           pedido_id VARCHAR(64) PRIMARY KEY,
                           processado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                       )"""
                )
            return
        except pymysql.err.OperationalError:
            log.info("banco ainda indisponivel", extra={"extra_campos": {"tentativa": tentativa}})
            time.sleep(2)
    raise RuntimeError("banco indisponivel")


def processar(corpo, correlation_id):
    campos = {"pedido_id": corpo["pedido_id"], "correlation_id": correlation_id}
    if corpo.get("falhar"):
        raise ValueError("mensagem marcada como nao processavel")
    with conectar() as conexao, conexao.cursor() as cursor:
        try:
            # O registro de idempotência e o efeito do pedido entram na MESMA transação.
            # Quando o tema existir, a baixa de estoque e o INSERT do pedido vão aqui dentro.
            cursor.execute(
                "INSERT INTO pedidos_processados (pedido_id) VALUES (%s)", (corpo["pedido_id"],)
            )
            conexao.commit()
            log.info("pedido processado", extra={"extra_campos": campos})
        except pymysql.err.IntegrityError:
            conexao.rollback()
            log.info("pedido duplicado ignorado", extra={"extra_campos": campos})


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
