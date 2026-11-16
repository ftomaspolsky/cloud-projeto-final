"""A conversa com o modelo no Bedrock, pela API Converse, com as ferramentas da aplicação.

O modelo só pede: quem executa cada ferramenta é este código, e o morador sai do servidor, nunca
da entrada do modelo. A IA é tratada como dependência que falha: qualquer erro dela cai no menu
guiado, e a mensagem do morador já está gravada.
"""

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import timedelta

import boto3
import pymysql
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

import reservas
from banco import AREAS, HORARIOS_DOS_PERIODOS, NOMES_DAS_AREAS, PERIODOS
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
                "description": (
                    "Lista os períodos livres e a taxa, por área e por dia. Sem área, traz todas "
                    "as áreas. Com data_fim, traz cada dia de data até data_fim (inclusive, no "
                    "máximo 14 dias)."
                ),
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            **_ENTRADA_COMUM,
                            "data_fim": {
                                "type": "string",
                                "description": "Último dia da consulta, AAAA-MM-DD. Opcional.",
                            },
                        },
                        "required": ["data"],
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
        {
            "toolSpec": {
                "name": "listar_minhas_reservas",
                "description": (
                    "Lista as reservas ativas do morador, de hoje em diante, com o número de cada "
                    "uma, e o limite de reservas futuras da unidade."
                ),
                "inputSchema": {
                    "json": {"type": "object", "properties": {}, "additionalProperties": False}
                },
            }
        },
        {
            "toolSpec": {
                "name": "cancelar_reserva",
                "description": (
                    "Cancela uma reserva do morador pelo número e cancela a taxa. Use só depois "
                    "de o morador confirmar qual reserva quer cancelar."
                ),
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "reserva_id": {"type": "integer", "description": "Número da reserva."},
                        },
                        "required": ["reserva_id"],
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
    # O que de fato foi reservado ou cancelado nesta mensagem, para a tela não depender do texto.
    acoes: list = field(default_factory=list)
    # Os dias e áreas consultados, para a tela mostrar os períodos livres como botões.
    disponibilidade: list = field(default_factory=list)


def _calendario():
    # O modelo erra ao calcular "sábado que vem" de cabeça. Com o calendário escrito, ele só lê.
    hoje = reservas.hoje()
    dias = [hoje + timedelta(days=n) for n in range(reservas.MAXIMO_DIAS_POR_CONSULTA)]
    return "; ".join(f"{d.isoformat()} {reservas.DIAS_DA_SEMANA[d.weekday()]}" for d in dias)


def _sistema(morador):
    hoje = reservas.hoje()
    areas = ", ".join(f"{nome} (taxa de R$ {taxa.replace('.', ',')})" for _, nome, taxa in AREAS)
    periodos = ", ".join(f"{p} ({h})" for p, h in HORARIOS_DOS_PERIODOS.items())
    return [{"text": (
        "Você é o atendente virtual de um condomínio e fala com um morador pelo chat. Responda "
        "sempre em português do Brasil, em mensagens curtas. "
        f"O morador é {morador['nome']}, da unidade {morador['unidade']}. "
        f"Hoje é {hoje.isoformat()}, {reservas.DIAS_DA_SEMANA[hoje.weekday()]}. "
        f"Próximos dias: {_calendario()}. "
        f"As áreas são: {areas}. Os períodos são: {periodos}. Cada unidade pode ter até "
        f"{reservas.LIMITE_RESERVAS_FUTURAS_POR_UNIDADE} reservas futuras, com até "
        f"{reservas.MAXIMO_DIAS_ANTECEDENCIA} dias de antecedência. "
        "Use as ferramentas para consultar a disponibilidade, criar reservas, listar as reservas "
        "do morador e cancelar. A consulta aceita várias áreas e vários dias numa chamada só: "
        "sem área, traz todas; com data_fim, traz o intervalo. Nunca "
        "afirme que um horário está livre, que uma reserva foi feita ou cancelada sem o "
        "resultado da ferramenta. Se faltar a área, a data ou o período, pergunte. Antes de "
        "cancelar, confirme com o morador qual reserva, pelo número, área e data. Para remarcar, "
        "crie a reserva nova e só depois cancele a antiga; se o limite da unidade impedir, "
        "explique e pergunte se o morador quer cancelar a antiga primeiro. Se uma ferramenta "
        "recusar o pedido, explique o motivo em palavras simples e ofereça uma alternativa. "
        "Escreva datas como DD/MM/AAAA para o morador. "
        "Faça no máximo uma pergunta por mensagem, sempre oferecendo as opções. Nunca pergunte o "
        "que dá para descobrir consultando: se o morador disser a área e o dia, consulte e mostre "
        "os períodos livres em vez de perguntar o período; se disser só o dia, consulte todas as "
        "áreas. O morador pode responder com uma palavra só, como \"Quadra\", \"sábado\" ou "
        "\"noite\": isso completa o pedido anterior. Horário em horas, como \"às 17h\", "
        "converta para o período correspondente, pelos horários acima. "
        "Você ainda não abre ordem de serviço, não cuida de visitantes nem de encomendas e não "
        "trata de boletos ou da cota do condomínio. Se o morador pedir isso, diga que ainda não "
        "faz e oriente a procurar a administração, sem inventar resposta. "
        # O histórico guarda só o texto. Sem este aviso, o modelo lê a resposta anterior, não vê
        # a consulta que a sustentou e pede desculpas ao morador por um erro que não aconteceu.
        "As mensagens anteriores aparecem só como texto, sem as chamadas de ferramenta que as "
        "sustentaram, e essas chamadas foram feitas. Não comente isso com o morador. Quando "
        "precisar de um dado atualizado, use a ferramenta de novo."
    )}]


def _executar(nome, entrada, morador_id):
    """Devolve (resultado, deu_certo). Recusa da regra é resposta para o modelo, não falha nossa."""
    try:
        if nome == "consultar_disponibilidade":
            resultado = reservas.consultar_agenda(
                entrada["data"], entrada.get("data_fim"), entrada.get("area")
            )
            return resultado, True
        if nome == "criar_reserva":
            resultado = reservas.criar_reserva(
                entrada["area"], entrada["data"], entrada["periodo"], morador_id
            )
            return resultado, True
        if nome == "listar_minhas_reservas":
            return reservas.listar_minhas_reservas(morador_id), True
        if nome == "cancelar_reserva":
            return reservas.cancelar_reserva(entrada["reserva_id"], morador_id), True
        return {"erro": "ferramenta_inexistente"}, False
    except KeyError as erro:
        return {"erro": f"campo_faltando: {erro}"}, False
    except reservas.ReservaRecusada as recusa:
        return {"recusada": recusa.motivo}, False
    except pymysql.Error as erro:
        registrar(logging.ERROR, "falha do banco na ferramenta", ferramenta=nome, erro=str(erro))
        return {"erro": "sistema_indisponivel"}, False


def _confirmacao(acao):
    if acao.get("cancelada"):
        return (
            f"Sua reserva {acao['reserva_id']} foi cancelada: {acao['area']}, {acao['data']}, "
            f"período {acao['periodo']}."
        )
    return (
        f"Sua reserva foi registrada: {acao['area']}, {acao['data']}, período "
        f"{acao['periodo']}, taxa de R$ {acao['taxa']}."
    )


def _sem_modelo(acoes_feitas):
    # Se a reserva já foi gravada (ou cancelada), mandar para o menu faria o morador repetir o
    # pedido e ouvir "horário ocupado" pela própria reserva. Melhor confirmar o que aconteceu.
    if acoes_feitas:
        return Resposta(" ".join(_confirmacao(a) for a in acoes_feitas), IA, acoes_feitas)
    return Resposta(TEXTO_DO_MENU, MENU)


def _texto_de(mensagem):
    # Por tipo, nunca por posição: a resposta pode começar com um bloco de raciocínio.
    return "".join(bloco["text"] for bloco in mensagem["content"] if "text" in bloco).strip()


def responder(historico, morador_id):
    # Lido fora dos try abaixo: banco fora do ar não é falha do modelo, e a rota responde 503.
    sistema = _sistema(reservas.dados_do_morador(morador_id))
    mensagens = list(historico)
    reservas_feitas = []
    disponibilidade = []
    inicio = time.monotonic()

    for rodada in range(MAX_RODADAS):
        if time.monotonic() - inicio > PRAZO_SEGUNDOS:
            registrar(logging.ERROR, "modelo_falhou", erro_codigo="prazo_esgotado", rodada=rodada)
            return _sem_modelo(reservas_feitas)
        try:
            saida = bedrock.converse(
                modelId=os.environ["BEDROCK_MODEL_ID"],
                system=sistema,
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
            return Resposta(texto, IA, reservas_feitas, disponibilidade)

        # A mensagem volta inteira, com os blocos de raciocínio: o modelo exige isso.
        mensagens.append(mensagem)
        resultados = []
        for bloco in mensagem["content"]:
            if "toolUse" not in bloco:
                continue
            pedido = bloco["toolUse"]
            resultado, deu_certo = _executar(pedido["name"], pedido["input"], morador_id)
            if deu_certo and pedido["name"] in ("criar_reserva", "cancelar_reserva"):
                reservas_feitas.append(resultado)
            if deu_certo and pedido["name"] == "consultar_disponibilidade":
                disponibilidade.extend(resultado["disponibilidade"])
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
