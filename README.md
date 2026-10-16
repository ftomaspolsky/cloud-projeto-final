# Projeto Final — Computação em Nuvem

Plataforma de comércio conversacional na AWS: o cliente conversa com um vendedor de IA
generativa que consulta dados reais e registra pedidos. O que se avalia é a arquitetura.

- **Etapa 1:** construção manual em Ohio (`us-east-2`), só console e AWS CLI.
- **Etapa 2:** reconstrução integral em Terraform em São Paulo (`sa-east-1`).

**Estado:** esqueleto independente do tema. O domínio comercial ainda não foi escolhido.

## Arquitetura

```
Internet → ALB (sub-redes públicas, 2 AZs)
             │
             ▼
   chat-service   (ECS, síncrono)  conversa + LLM com ferramentas
             │ publica pedido
             ▼
   SQS pedidos ──(3 recebimentos)──► SQS pedidos-dlq
             │
             ▼
   order-worker   (ECS, assíncrono) idempotente, grava em transação
             │
             ▼
   RDS MySQL (sub-redes privadas)
```

Detalhes e decisões em [docs/arquitetura.md](docs/arquitetura.md).

## Rodar local

Precisa de Docker.

```bash
cp .env.example .env
docker compose up --build
```

| Rota | O que faz |
|---|---|
| `GET  localhost:8000/health` | health check do chat-service |
| `POST localhost:8000/chat` `{"mensagem": "oi"}` | vendedor (ainda só ecoa) |
| `POST localhost:8000/pedidos/teste` `{"pedido_id": "p-1"}` | publica um pedido na fila |
| idem com o mesmo `pedido_id` | prova a idempotência: o worker ignora o duplicado |
| idem com `{"falhar": true}` | prova a DLQ: 3 tentativas e a mensagem vai para `pedidos-dlq` |

Mande `X-Correlation-Id: <algo>` no cabeçalho e o mesmo id aparece no log do worker.

## Estrutura

```
app/chat-service/   serviço síncrono (FastAPI)
app/order-worker/   consumidor da fila
local/              configuração do SQS local (ElasticMQ)
docs/               arquitetura, recursos criados em Ohio, comandos usados
infra/terraform/    etapa 2 (São Paulo)
```

## Regras do repositório

- **Nenhum segredo commitado.** `.env`, credenciais AWS e estado do Terraform estão no
  `.gitignore`. Na AWS, segredo vem do Secrets Manager.
- **Nenhum valor de região no código da aplicação.** Região, fila e banco vêm de variável de
  ambiente, para o mesmo container rodar em Ohio e em São Paulo.
- **Todo recurso AWS leva a tag `projeto=cloud-projeto-final`.**
