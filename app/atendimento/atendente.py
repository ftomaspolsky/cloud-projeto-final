"""A conversa com o modelo no Bedrock, pela API Converse, com as ferramentas da aplicação.

O modelo só pede: quem executa cada ferramenta é este código, e o morador sai do servidor, nunca
da entrada do modelo. A IA é tratada como dependência que falha: qualquer erro dela cai no menu
guiado, e a mensagem do morador já está gravada.
"""

import logging
import os
import time
from dataclasses import dataclass

import boto3
import pymysql
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

import reservas
from banco import NOMES_DAS_AREAS, PERIODOS
from observabilidade import registrar

# O raciocínio do Haiku conta nesse limite: um valor baixo corta a resposta antes do texto.
MAX_TOKENS = 4096
MAX_RODADAS = 4
# O ALB desiste da requisição em 60 s. Melhor cair no menu antes disso.
PRAZO_SEGUNDOS = 45

bedrock = boto3.client(
    "bedrock-runtime",
    region_name=os.environ["AWS_REGION"],
    endpoint_url=os.environ.get("BEDROCK_ENDPOINT_URL"),  # só existe no ambiente local
    config=Config(
        connect_timeout=3,
        read_timeout=25,
        retries={"total_max_attempts": 2, "mode": "standard"},
    ),
)

_ENTRADA_COMUM = {
    "area": {"type": "string", "enum": NOMES_DAS_AREAS},
    "data": {"type": "string", "description": "Data no formato AAAA-MM-DD."},
}

FERRAMENTAS = {
    "tools": [
        {
            "toolSpec": {
                "name": "consultar_disponibilidade",
                "description": "Lista os períodos livres de uma área comum numa data, e a taxa.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": _ENTRADA_COMUM,
                        "required": ["area", "data"],
                        "additionalProperties": False,
                    }
                },
            }
        },
        {
            "toolSpec": {
                "name": "criar_reserva",
                "description": (
                    "Reserva uma área comum para o morador e gera a taxa. Use só depois de o "
                    "morador pedir a reserva, com área, data e período definidos."
                ),
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            **_ENTRADA_COMUM,
                            "periodo": {"type": "string", "enum": PERIODOS},
                        },
                        "required": ["area", "data", "periodo"],
                        "additionalProperties": False,
                    }
                },
            }
        },
    ]
}

MENU = "menu"
IA = "ia"
TEXTO_DO_MENU = (
    "Não consegui processar sua mensagem agora, mas ela ficou registrada. "
    "Você pode fazer a reserva pelo menu abaixo."
)


@dataclass
class Resposta:
    texto: str
    modo: str


def _sistema():
    return [{"text": (
        "Você é o atendente virtual de um condomínio e fala com um morador pelo chat. Responda "
        "sempre em português do Brasil, em mensagens curtas. "
        f"Hoje é {reservas.hoje().isoformat()}. "
        "Use as ferramentas para consultar a disponibilidade e criar reservas. Nunca afirme que "
        "um horário está livre ou que uma reserva foi feita sem o resultado da ferramenta. Se "
        "faltar a área, a data ou o período, pergunte. O período é manha, tarde ou noite. Se "
        "uma ferramenta recusar o pedido, explique o motivo e ofereça uma alternativa."
    )}]


def _executar(nome, entrada, morador_id):
    """Devolve (resultado, deu_certo). Recusa da regra é resposta para o modelo, não falha nossa."""
    try:
        if nome == "consultar_disponibilidade":
            return reservas.consultar_disponibilidade(entrada["area"], entrada["data"]), True
        if nome == "criar_reserva":
            resultado = reservas.criar_reserva(
                entrada["area"], entrada["data"], entrada["periodo"], morador_id
            )
            return resultado, True
        return {"erro": "ferramenta_inexistente"}, False
    except KeyError as erro:
        return {"erro": f"campo_faltando: {erro}"}, False
    except reservas.ReservaRecusada as recusa:
        return {"recusada": recusa.motivo}, False
    except pymysql.Error as erro:
        registrar(logging.ERROR, "falha do banco na ferramenta", ferramenta=nome, erro=str(erro))
        return {"erro": "sistema_indisponivel"}, False


def _confirmacao(reserva):
    return (
        f"Sua reserva foi registrada: {reserva['area']}, {reserva['data']}, período "
        f"{reserva['periodo']}, taxa de R$ {reserva['taxa']}."
    )


def _sem_modelo(reservas_feitas):
    # Se a reserva já foi gravada, mandar para o menu faria o morador tentar de novo e ouvir
    # "horário ocupado" pela própria reserva. Melhor confirmar o que aconteceu.
    if reservas_feitas:
        return Resposta(" ".join(_confirmacao(r) for r in reservas_feitas), IA)
    return Resposta(TEXTO_DO_MENU, MENU)


def _texto_de(mensagem):
    # Por tipo, nunca por posição: a resposta pode começar com um bloco de raciocínio.
    return "".join(bloco["text"] for bloco in mensagem["content"] if "text" in bloco).strip()


def responder(historico, morador_id):
    mensagens = list(historico)
    reservas_feitas = []
    inicio = time.monotonic()

    for rodada in range(MAX_RODADAS):
        if time.monotonic() - inicio > PRAZO_SEGUNDOS:
            registrar(logging.ERROR, "modelo_falhou", erro_codigo="prazo_esgotado", rodada=rodada)
            return _sem_modelo(reservas_feitas)
        try:
            saida = bedrock.converse(
                modelId=os.environ["BEDROCK_MODEL_ID"],
                system=_sistema(),
                messages=mensagens,
                toolConfig=FERRAMENTAS,
                inferenceConfig={"maxTokens": MAX_TOKENS},
            )
        except ClientError as erro:
            codigo = erro.response.get("Error", {}).get("Code", "desconhecido")
            registrar(logging.ERROR, "modelo_falhou", erro_codigo=codigo, rodada=rodada)
            return _sem_modelo(reservas_feitas)
        except BotoCoreError as erro:
            registrar(logging.ERROR, "modelo_falhou", erro_codigo=type(erro).__name__, rodada=rodada)
            return _sem_modelo(reservas_feitas)

        uso = saida.get("usage", {})
        registrar(
            logging.INFO,
            "modelo_respondeu",
            rodada=rodada,
            parada=saida["stopReason"],
            tokens_entrada=uso.get("inputTokens"),
            tokens_saida=uso.get("outputTokens"),
            latencia_ms=saida.get("metrics", {}).get("latencyMs"),
        )
        mensagem = saida["output"]["message"]

        if saida["stopReason"] != "tool_use":
            texto = _texto_de(mensagem)
            if not texto:
                registrar(logging.ERROR, "modelo_falhou", erro_codigo=saida["stopReason"], rodada=rodada)
                return _sem_modelo(reservas_feitas)
            return Resposta(texto, IA)

        # A mensagem volta inteira, com os blocos de raciocínio: o modelo exige isso.
        mensagens.append(mensagem)
        resultados = []
        for bloco in mensagem["content"]:
            if "toolUse" not in bloco:
                continue
            pedido = bloco["toolUse"]
            resultado, deu_certo = _executar(pedido["name"], pedido["input"], morador_id)
            if deu_certo and pedido["name"] == "criar_reserva":
                reservas_feitas.append(resultado)
            registrar(logging.INFO, "ferramenta_executada", ferramenta=pedido["name"], ok=deu_certo)
            resultados.append({
                "toolResult": {
                    "toolUseId": pedido["toolUseId"],
                    "content": [{"json": resultado}],
                    "status": "success" if deu_certo else "error",
                }
            })
        mensagens.append({"role": "user", "content": resultados})

    registrar(logging.ERROR, "modelo_falhou", erro_codigo="rodadas_esgotadas", rodada=MAX_RODADAS)
    return _sem_modelo(reservas_feitas)
