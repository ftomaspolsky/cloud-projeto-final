"""Bedrock simulado: responde na mesma rota e no mesmo formato da API Converse.

Serve só para testar o fluxo sem AWS, como o ElasticMQ faz com o SQS. O código do `atendimento`
é o mesmo, muda só o BEDROCK_ENDPOINT_URL. NÃO prova que o modelo real escolhe bem a ferramenta,
nem que a política IAM está certa: isso só se prova na AWS.

As rotas /_modo e /_requisicoes não existem na AWS: são o controle dos testes.
"""

import json
import re
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI()
modo = {"valor": "normal"}
requisicoes = []

AREAS = {"sal[aã]o": "Salão de festas", "churrasqueira": "Churrasqueira", "quadra": "Quadra"}
PERIODOS = {"manh[aã]": "manha", "tarde": "tarde", "noite": "noite"}
RACIOCINIO = {"reasoningContent": {"reasoningText": {"text": "", "signature": "assinatura-simulada"}}}


def erro(status, tipo):
    return JSONResponse(
        status_code=status,
        content={"message": f"simulado: {tipo}"},
        headers={"x-amzn-errortype": tipo},
    )


def resposta(conteudo, parada):
    return {
        "output": {"message": {"role": "assistant", "content": conteudo}},
        "stopReason": parada,
        "usage": {"inputTokens": 10, "outputTokens": 20, "totalTokens": 30},
        "metrics": {"latencyMs": 1},
    }


def procurar(tabela, texto):
    for padrao, valor in tabela.items():
        if re.search(padrao, texto, re.IGNORECASE):
            return valor
    return None


def usar_ferramenta(nome, entrada):
    bloco = {"toolUse": {"toolUseId": str(uuid.uuid4()), "name": nome, "input": entrada}}
    return resposta([RACIOCINIO, {"text": "Vou verificar."}, bloco], "tool_use")


@app.post("/_modo/{valor}")
def definir_modo(valor: str):
    modo["valor"] = valor
    return modo


@app.get("/_requisicoes")
def listar_requisicoes():
    return requisicoes


@app.delete("/_requisicoes")
def limpar_requisicoes():
    requisicoes.clear()
    return {"ok": True}


@app.post("/model/{model_id:path}/converse")
async def converse(model_id: str, request: Request):
    corpo = await request.json()
    requisicoes.append({"modelo": model_id, **corpo})

    if modo["valor"] == "fora":
        return erro(503, "ServiceUnavailableException")
    if modo["valor"] == "sem_permissao":
        return erro(403, "AccessDeniedException")
    if modo["valor"] == "cortado":
        return resposta([RACIOCINIO], "max_tokens")

    ultimo = corpo["messages"][-1]["content"]
    resultados = [b["toolResult"] for b in ultimo if "toolResult" in b]
    if resultados:
        if modo["valor"] == "falha_depois_da_ferramenta":
            return erro(503, "ServiceUnavailableException")
        return resposta([{"text": "Resultado: " + json.dumps(resultados[0]["content"][0]["json"], ensure_ascii=False)}], "end_turn")

    texto = " ".join(b["text"] for b in ultimo if "text" in b)
    area = procurar(AREAS, texto)
    periodo = procurar(PERIODOS, texto)
    datas = re.findall(r"\d{4}-\d{2}-\d{2}", texto)
    cancelar = re.search(r"cancel\w* a reserva (\d+)", texto, re.IGNORECASE)

    if cancelar:
        return usar_ferramenta("cancelar_reserva", {"reserva_id": int(cancelar.group(1))})
    if re.search("reserv", texto, re.IGNORECASE) and area and periodo and datas:
        return usar_ferramenta("criar_reserva", {"area": area, "data": datas[0], "periodo": periodo})
    if re.search("livre|dispon", texto, re.IGNORECASE) and datas:
        # Sem área, consulta todas; com duas datas, consulta o intervalo.
        entrada = {"data": datas[0]}
        if area:
            entrada["area"] = area
        if len(datas) > 1:
            entrada["data_fim"] = datas[1]
        return usar_ferramenta("consultar_disponibilidade", entrada)
    return resposta([RACIOCINIO, {"text": "Qual área, data e período você quer?"}], "end_turn")
