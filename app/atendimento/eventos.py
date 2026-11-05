"""Publica na fila os eventos que a reserva deixou na tabela evento_saida.

A entrega é "pelo menos uma vez": se o serviço cair entre publicar e marcar como publicado, o
evento sai de novo. Quem consome (operacoes) ignora o repetido pelo evento_id.
"""

import logging
import os
import time

import boto3
import pymysql
from botocore.exceptions import BotoCoreError, ClientError

from banco import conectar
from observabilidade import registrar

INTERVALO_SEGUNDOS = 10

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


def publicar_pendentes():
    """Nunca levanta exceção: a reserva já está gravada, e o evento fica para a próxima rodada."""
    try:
        with conectar() as conexao, conexao.cursor() as cursor:
            cursor.execute(
                """SELECT evento_id, corpo, correlation_id FROM evento_saida
                   WHERE publicado_em IS NULL ORDER BY criado_em LIMIT 20"""
            )
            for evento in cursor.fetchall():
                sqs.send_message(
                    QueueUrl=queue_url(),
                    MessageBody=evento["corpo"],
                    MessageAttributes={
                        "correlation_id": {
                            "DataType": "String",
                            "StringValue": evento["correlation_id"],
                        },
                    },
                )
                cursor.execute(
                    "UPDATE evento_saida SET publicado_em = CURRENT_TIMESTAMP WHERE evento_id = %s",
                    (evento["evento_id"],),
                )
                conexao.commit()
                registrar(logging.INFO, "evento publicado", evento_id=evento["evento_id"])
    except (pymysql.Error, BotoCoreError, ClientError) as erro:
        registrar(logging.ERROR, "falha ao publicar eventos", erro=str(erro))


def publicar_para_sempre():
    while True:
        time.sleep(INTERVALO_SEGUNDOS)
        publicar_pendentes()
