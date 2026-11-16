"""Bedrock simulado: responde na mesma rota e no mesmo formato da API Converse.

Serve só para testar o fluxo sem AWS, como o ElasticMQ faz com o SQS. O código do `atendimento`
é o mesmo, muda só o BEDROCK_ENDPOINT_URL. NÃO prova que o modelo real escolhe bem a ferramenta,
nem que a política IAM está certa: isso só se prova na AWS.

Entende o bastante para sustentar uma conversa local: junta área, data e período de todas as
mensagens do morador, para "Churrasqueira" → "sábado" → "noite" funcionar como no modelo real.

As rotas /_modo e /_requisicoes não existem na AWS: são o controle dos testes.
"""

import re
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI()
modo = {"valor": "normal"}
requisicoes = []

FUSO = timezone(timedelta(hours=-3))  # o mesmo do atendimento
AREAS = {"sal[aã]o": "Salão de festas", "churrasqueira": "Churrasqueira", "quadra": "Quadra"}
# \b antes de "manhã": senão "amanhã" vira período.
PERIODOS = {r"\bmanh[aã]": "manha", "tarde": "tarde", "noite": "noite"}
NOMES_DOS_PERIODOS = {"manha": "manhã", "tarde": "tarde", "noite": "noite"}
DIAS_DA_SEMANA = ["segunda", "ter[cç]a", "quarta", "quinta", "sexta", "s[aá]bado", "domingo"]
DATA = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})|\b(\d{1,2})/(\d{1,2})(?:/(\d{4}))?|\b(hoje|amanh[aã]|"
    + "|".join(DIAS_DA_SEMANA) + r")\b",
    re.IGNORECASE,
)
HORA = re.compile(r"\b(\d{1,2})\s*(?:horas|hrs|hr|h)(?![a-zà-ú])", re.IGNORECASE)
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


def falar(texto):
    return resposta([RACIOCINIO, {"text": texto}], "end_turn")


def procurar(tabela, texto):
    for padrao, valor in tabela.items():
        if re.search(padrao, texto, re.IGNORECASE):
            return valor
    return None


def datas_em(texto, hoje):
    datas = []
    for m in DATA.finditer(texto):
        try:
            if m.group(1):
                datas.append(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
            elif m.group(4):
                dia = date(int(m.group(6) or hoje.year), int(m.group(5)), int(m.group(4)))
                # DD/MM sem ano que já passou é do ano que vem.
                if not m.group(6) and dia < hoje:
                    dia = dia.replace(year=dia.year + 1)
                datas.append(dia)
            else:
                palavra = m.group(7).lower()
                if palavra == "hoje":
                    datas.append(hoje)
                elif palavra.startswith("amanh"):
                    datas.append(hoje + timedelta(days=1))
                else:
                    semana = next(i for i, p in enumerate(DIAS_DA_SEMANA) if re.fullmatch(p, palavra))
                    # A próxima ocorrência: hoje não conta.
                    datas.append(hoje + timedelta(days=(semana - hoje.weekday() - 1) % 7 + 1))
        except ValueError:
            continue  # 31/02 e afins
    return datas


def periodo_em(texto):
    periodo = procurar(PERIODOS, texto)
    if periodo:
        return periodo
    hora = HORA.search(texto)
    if not hora:
        return None
    h = int(hora.group(1))
    return "manha" if h < 12 else "tarde" if h < 18 else "noite"


def usar_ferramenta(nome, entrada):
    bloco = {"toolUse": {"toolUseId": str(uuid.uuid4()), "name": nome, "input": entrada}}
    return resposta([RACIOCINIO, {"text": "Vou verificar."}, bloco], "tool_use")


def data_br(iso):
    a, m, d = iso.split("-")
    return f"{d}/{m}/{a}"


def reais(valor):
    return "R$ " + valor.replace(".", ",")


def contar_resultado(resultado):
    """Uma frase curta a partir do resultado da ferramenta, como o modelo real faria."""
    if "recusada" in resultado or "erro" in resultado:
        return f"Não foi possível: {resultado.get('recusada') or resultado.get('erro')}."
    if "disponibilidade" in resultado:
        return "Veja os horários livres:"
    if "reservas" in resultado:
        if not resultado["reservas"]:
            return "Você não tem reservas futuras."
        return "\n".join(
            f"- Reserva {r['reserva_id']}: {r['area']}, {data_br(r['data'])}, "
            f"{NOMES_DOS_PERIODOS[r['periodo']]}"
            for r in resultado["reservas"]
        )
    if resultado.get("cancelada"):
        return f"Reserva {resultado['reserva_id']} cancelada."
    return (
        f"Reserva confirmada: {resultado['area']}, {data_br(resultado['data'])}, "
        f"{NOMES_DOS_PERIODOS[resultado['periodo']]}. Taxa de {reais(resultado['taxa'])}."
    )


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
        return falar(contar_resultado(resultados[0]["content"][0]["json"]))

    # A memória da conversa: cada campo vem da mensagem mais recente que o trouxe.
    hoje = datetime.now(FUSO).date()
    textos = [
        " ".join(b["text"] for b in m["content"] if "text" in b)
        for m in corpo["messages"] if m["role"] == "user"
    ]
    area = periodo = None
    datas = []
    for texto in textos:
        area = procurar(AREAS, texto) or area
        periodo = periodo_em(texto) or periodo
        datas = datas_em(texto, hoje) or datas
    texto = textos[-1]

    cancelar = re.search(r"cancel\w* a reserva (\d+)", texto, re.IGNORECASE)
    if cancelar:
        return usar_ferramenta("cancelar_reserva", {"reserva_id": int(cancelar.group(1))})
    if re.search(r"(minhas|quais) reservas", texto, re.IGNORECASE):
        return usar_ferramenta("listar_minhas_reservas", {})
    if re.search("reserv", texto, re.IGNORECASE) and area and periodo and datas:
        return usar_ferramenta("criar_reserva", {"area": area, "data": datas[0].isoformat(), "periodo": periodo})
    if datas:
        # Sem área, consulta todas; com duas datas, consulta o intervalo.
        entrada = {"data": datas[0].isoformat()}
        if area:
            entrada["area"] = area
        if len(datas) > 1:
            entrada["data_fim"] = datas[1].isoformat()
        return usar_ferramenta("consultar_disponibilidade", entrada)
    if area:
        return falar("Para qual dia?")
    return falar("Qual área: Salão de festas, Churrasqueira ou Quadra?")
