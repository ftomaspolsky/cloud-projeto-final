"""Carga constante no ALB, para a demo de escala.

Uso, no CloudShell:
    python3 carga.py http://<dns-do-alb>/health --rps 40 --minutos 12

Bate no /health, que não toca no banco, na fila nem no Bedrock: a carga não custa chamada de
modelo. A cada 15 s imprime o total por código de resposta. Qualquer coisa além de "200" é uma
requisição que o usuário teria visto falhar. Ctrl+C para antes do fim.
"""

import argparse
import collections
import threading
import time
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--rps", type=float, default=40, help="requisições por segundo, no total")
    parser.add_argument("--minutos", type=float, default=12)
    parser.add_argument("--workers", type=int, default=20)
    args = parser.parse_args()

    fim = time.monotonic() + args.minutos * 60
    intervalo = args.workers / args.rps  # cada worker dispara uma requisição a cada `intervalo`
    contagem = collections.Counter()
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
                with urllib.request.urlopen(args.url, timeout=5) as resposta:
                    resposta.read()
                    codigo = str(resposta.status)
            except urllib.error.HTTPError as erro:
                codigo = str(erro.code)
            except Exception as erro:  # timeout, conexão recusada: também é falha vista pelo usuário
                codigo = type(erro).__name__
            with trava:
                contagem[codigo] += 1

    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(args.workers)]
    for thread in threads:
        thread.start()

    inicio = time.monotonic()
    while any(thread.is_alive() for thread in threads):
        time.sleep(15)
        with trava:
            retrato = dict(contagem)
        decorrido = int(time.monotonic() - inicio)
        print(f"{time.strftime('%H:%M:%S')} +{decorrido}s {retrato}", flush=True)


if __name__ == "__main__":
    main()
