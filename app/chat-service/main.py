"""chat-service — o serviço síncrono, atrás do ALB.

Recebe a conversa do cliente. Quando o tema for decidido, é aqui que o LLM entra, com as
ferramentas (consultar catálogo, criar pedido). Por enquanto, o vendedor só ecoa, e existe
uma rota de teste que publica um pedido na fila para exercitar o caminho assíncrono.

Toda configuração vem de variável de ambiente: nada de região, URL ou credencial no código.
"""

import contextvars
import json
import logging
import os
import sys
import time
import uuid

import boto3
from fastapi import FastAPI, Request
from pydantic import BaseModel

SERVICO = "chat-service"
correlation_id = contextvars.ContextVar("correlation_id", default="-")


class JsonFormatter(logging.Formatter):
    """Uma linha JSON por evento, com o correlation_id: é o que torna os logs correlacionáveis."""

    def format(self, record):
        evento = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "nivel": record.levelname,
            "servico": SERVICO,
            "correlation_id": correlation_id.get(),
            "msg": record.getMessage(),
        }
        evento.update(getattr(record, "extra_campos", {}))
        return json.dumps(evento, ensure_ascii=False)


handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JsonFormatter())
log = logging.getLogger(SERVICO)
log.addHandler(handler)
log.setLevel(logging.INFO)

sqs = boto3.client(
    "sqs",
    region_name=os.environ["AWS_REGION"],
    endpoint_url=os.environ.get("SQS_ENDPOINT_URL"),  # só existe no ambiente local
)
_queue_url = None


def queue_url():
    # A URL da fila é resolvida pelo nome, na região em que o serviço roda.
    global _queue_url
    if _queue_url is None:
        _queue_url = sqs.get_queue_url(QueueName=os.environ["QUEUE_NAME"])["QueueUrl"]
    return _queue_url


app = FastAPI(title="chat-service")


@app.middleware("http")
async def correlacionar(request: Request, call_next):
    cid = request.headers.get("X-Correlation-Id") or str(uuid.uuid4())
    correlation_id.set(cid)
    inicio = time.perf_counter()
    resposta = await call_next(request)
    resposta.headers["X-Correlation-Id"] = cid
    if request.url.path != "/health":
        log.info(
            "requisicao",
            extra={"extra_campos": {
                "metodo": request.method,
                "rota": request.url.path,
                "status": resposta.status_code,
                "ms": round((time.perf_counter() - inicio) * 1000, 1),
            }},
        )
    return resposta


@app.get("/health")
def health():
    # Liveness: responde se o processo está de pé. Não depende de banco nem de fila,
    # para o ALB não derrubar a task por causa de uma dependência fora do ar.
    return {"status": "ok", "servico": SERVICO}


class Mensagem(BaseModel):
    mensagem: str
    conversa_id: str | None = None


@app.post("/chat")
def chat(entrada: Mensagem):
    conversa_id = entrada.conversa_id or str(uuid.uuid4())
    return {
        "conversa_id": conversa_id,
        "resposta": f"(vendedor ainda sem tema) você disse: {entrada.mensagem}",
    }


class PedidoTeste(BaseModel):
    pedido_id: str | None = None   # repetir o mesmo id simula entrega duplicada
    falhar: bool = False           # true simula mensagem não processável (vai para a DLQ)


@app.post("/pedidos/teste", status_code=202)
def pedido_teste(entrada: PedidoTeste):
    pedido_id = entrada.pedido_id or str(uuid.uuid4())
    corpo = {"pedido_id": pedido_id, "falhar": entrada.falhar}
    sqs.send_message(
        QueueUrl=queue_url(),
        MessageBody=json.dumps(corpo),
        MessageAttributes={
            "correlation_id": {"DataType": "String", "StringValue": correlation_id.get()},
        },
    )
    log.info("pedido enfileirado", extra={"extra_campos": {"pedido_id": pedido_id}})
    return {"pedido_id": pedido_id, "estado": "enfileirado"}
