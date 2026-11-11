"""Enche a fila de eventos com cópias de um evento já processado, para a demo do `operacoes`.

Uso, no CloudShell:
    python3 encher-fila.py <evento_id> --rps 60 --minutos 8

Cada cópia é um `ReservaSolicitada` com um `evento_id` que já está em `evento_processado`. O
`operacoes` reconhece a duplicata, apaga a mensagem e não cobra de novo. A mesma demo mostra
a escala por fila (o backlog sobe, as tasks sobem) e a idempotência (nenhuma cobrança nova,
nada na DLQ). Um `evento_id` que NÃO foi processado faria o contrário: cada cópia viraria uma
cobrança tentada, falharia e acabaria na DLQ. Por isso o id vem do log do `operacoes`.

Manda em lotes de 10, o máximo do SendMessageBatch. A cada 15 s imprime quantas foram aceitas
e quantas a fila recusou. Ctrl+C para antes do fim.
"""

import argparse
import json
import threading
import time

import boto3

FILA = "cloud-projeto-final-eventos"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("evento_id")
    parser.add_argument("--rps", type=float, default=60, help="mensagens por segundo, no total")
    parser.add_argument("--minutos", type=float, default=8)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--regiao", default="us-east-2")
    parser.add_argument("--endpoint-url", default=None, help="só para teste local")
    args = parser.parse_args()

    sqs = boto3.client("sqs", region_name=args.regiao, endpoint_url=args.endpoint_url)
    url = sqs.get_queue_url(QueueName=FILA)["QueueUrl"]
    corpo = json.dumps({"tipo": "ReservaSolicitada", "evento_id": args.evento_id})
    lote = [
        {
            "Id": str(i),
            "MessageBody": corpo,
            "MessageAttributes": {
                "correlation_id": {"DataType": "String", "StringValue": "demo-fila"}
            },
        }
        for i in range(10)
    ]

    fim = time.monotonic() + args.minutos * 60
    intervalo = args.workers * 10 / args.rps  # cada worker manda um lote de 10 a cada `intervalo`
    total = {"aceitas": 0, "recusadas": 0, "erros": 0}
    trava = threading.Lock()

    def worker(indice):
        proxima = time.monotonic() + indice * intervalo / args.workers
        while True:
            agora = time.monotonic()
            if agora >= fim:
                return
            if proxima > agora:
                time.sleep(proxima - agora)
            proxima += intervalo
            try:
                resposta = sqs.send_message_batch(QueueUrl=url, Entries=lote)
                with trava:
                    total["aceitas"] += len(resposta.get("Successful", []))
                    total["recusadas"] += len(resposta.get("Failed", []))
            except Exception as erro:
                with trava:
                    total["erros"] += 1
                print(f"erro: {erro}", flush=True)

    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(args.workers)]
    for thread in threads:
        thread.start()

    inicio = time.monotonic()
    while any(thread.is_alive() for thread in threads):
        time.sleep(15)
        with trava:
            retrato = dict(total)
        decorrido = int(time.monotonic() - inicio)
        print(f"{time.strftime('%H:%M:%S')} +{decorrido}s {retrato}", flush=True)


if __name__ == "__main__":
    main()
