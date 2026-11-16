"""atendimento — o serviço síncrono, atrás do ALB.

Recebe a conversa do morador, chama o modelo e grava a reserva na hora, porque o morador precisa
saber se o salão está livre. O que vem depois (cobrança, avisos) vai pela fila para o `operacoes`.

Toda configuração vem de variável de ambiente: nada de região, URL ou credencial no código.
"""

import logging
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import pymysql
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

import atendente
import banco
import eventos
import reservas
from observabilidade import SERVICO, correlation_id, registrar

LIMITE_HISTORICO = 20  # o que vai para o modelo
LIMITE_DA_TELA = 50  # o que a tela mostra ao reabrir a conversa
PAGINA = Path(__file__).parent / "index.html"


@asynccontextmanager
async def ciclo_de_vida(_app):
    threading.Thread(target=banco.preparar_banco_ate_conseguir, daemon=True).start()
    threading.Thread(target=eventos.publicar_para_sempre, daemon=True).start()
    yield


app = FastAPI(title=SERVICO, lifespan=ciclo_de_vida)


@app.middleware("http")
async def correlacionar(request: Request, call_next):
    cid = request.headers.get("X-Correlation-Id") or str(uuid.uuid4())
    correlation_id.set(cid)
    inicio = time.perf_counter()
    resposta = await call_next(request)
    resposta.headers["X-Correlation-Id"] = cid
    if request.url.path != "/health":
        registrar(
            logging.INFO,
            "requisicao",
            metodo=request.method,
            rota=request.url.path,
            status=resposta.status_code,
            ms=round((time.perf_counter() - inicio) * 1000, 1),
        )
    return resposta


@app.exception_handler(pymysql.Error)
async def banco_fora(_request: Request, erro: pymysql.Error):
    registrar(logging.ERROR, "falha do banco", erro=str(erro))
    return JSONResponse(
        status_code=503,
        content={"erro": "sistema_indisponivel", "resposta": "O sistema está indisponível. Tente de novo em instantes."},
    )


@app.get("/health")
def health():
    # Liveness: responde se o processo está de pé. Não depende de banco, fila nem modelo,
    # para o ALB não derrubar a task por causa de uma dependência fora do ar.
    return {"status": "ok", "servico": SERVICO}


@app.get("/")
def pagina():
    return FileResponse(PAGINA, media_type="text/html; charset=utf-8")


def _gravar_mensagem(conversa_id, papel, texto):
    with banco.conectar() as conexao, conexao.cursor() as cursor:
        cursor.execute(
            "INSERT INTO mensagem (conversa_id, morador_id, papel, texto) VALUES (%s, %s, %s, %s)",
            (conversa_id, banco.MORADOR_DEMO_ID, papel, texto),
        )
        conexao.commit()


def _carregar_historico(conversa_id):
    """Só o texto das conversas passadas. O modelo exige começar pelo morador e alternar papéis."""
    with banco.conectar() as conexao, conexao.cursor() as cursor:
        cursor.execute(
            """SELECT papel, texto FROM mensagem WHERE conversa_id = %s AND morador_id = %s
               ORDER BY id DESC LIMIT %s""",
            (conversa_id, banco.MORADOR_DEMO_ID, LIMITE_HISTORICO),
        )
        linhas = list(reversed(cursor.fetchall()))

    while linhas and linhas[0]["papel"] != "user":
        linhas.pop(0)

    historico = []
    for linha in linhas:
        if historico and historico[-1]["role"] == linha["papel"]:
            historico[-1]["content"].append({"text": linha["texto"]})
        else:
            historico.append({"role": linha["papel"], "content": [{"text": linha["texto"]}]})
    return historico


class Mensagem(BaseModel):
    mensagem: str = Field(min_length=1, max_length=2000)
    conversa_id: uuid.UUID | None = None


@app.post("/chat")
def chat(entrada: Mensagem):
    conversa_id = str(entrada.conversa_id or uuid.uuid4())
    # Grava antes de chamar o modelo: se ele falhar, o pedido do morador não se perde.
    _gravar_mensagem(conversa_id, "user", entrada.mensagem)
    resposta = atendente.responder(_carregar_historico(conversa_id), banco.MORADOR_DEMO_ID)
    _gravar_mensagem(conversa_id, "assistant", resposta.texto)
    return {
        "conversa_id": conversa_id,
        "resposta": resposta.texto,
        "modo": resposta.modo,
        "acoes": resposta.acoes,
    }


@app.get("/chat/{conversa_id}")
def historico_da_conversa(conversa_id: uuid.UUID):
    """Para a tela reabrir a conversa. Conversa sem mensagens devolve lista vazia, não 404."""
    with banco.conectar() as conexao, conexao.cursor() as cursor:
        cursor.execute(
            """SELECT papel, texto FROM mensagem WHERE conversa_id = %s AND morador_id = %s
               ORDER BY id DESC LIMIT %s""",
            (str(conversa_id), banco.MORADOR_DEMO_ID, LIMITE_DA_TELA),
        )
        mensagens = list(reversed(cursor.fetchall()))
    return {"conversa_id": str(conversa_id), "mensagens": mensagens}


# O menu guiado: o caminho sem IA, para quando o modelo está fora do ar. Mesmas regras do chat.


@app.get("/menu/areas")
def menu_areas():
    return {"areas": reservas.listar_areas(), "periodos": banco.PERIODOS}


@app.get("/menu/disponibilidade")
def menu_disponibilidade(area: str, data: str):
    try:
        return reservas.consultar_disponibilidade(area, data)
    except reservas.ReservaRecusada as recusa:
        return JSONResponse(status_code=409, content={"recusada": recusa.motivo})


class PedidoDeReserva(BaseModel):
    area: str
    data: str
    periodo: str


@app.post("/menu/reservas", status_code=201)
def menu_reservar(pedido: PedidoDeReserva):
    try:
        return reservas.criar_reserva(pedido.area, pedido.data, pedido.periodo, banco.MORADOR_DEMO_ID)
    except reservas.ReservaRecusada as recusa:
        return JSONResponse(status_code=409, content={"recusada": recusa.motivo})


@app.get("/menu/minhas-reservas")
def menu_minhas_reservas():
    return reservas.listar_minhas_reservas(banco.MORADOR_DEMO_ID)


@app.delete("/menu/reservas/{reserva_id}")
def menu_cancelar(reserva_id: int):
    try:
        return reservas.cancelar_reserva(reserva_id, banco.MORADOR_DEMO_ID)
    except reservas.ReservaRecusada as recusa:
        return JSONResponse(status_code=409, content={"recusada": recusa.motivo})
