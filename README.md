# Projeto Final — Computação em Nuvem

Plataforma de comércio conversacional na AWS: o cliente conversa com um vendedor de IA
generativa que consulta dados reais e registra pedidos. O que se avalia é a arquitetura.

- **Etapa 1:** construção manual em Ohio (`us-east-2`), 100% no console, sem código.
- **Etapa 2:** reconstrução integral em Terraform em São Paulo (`sa-east-1`).

**Tema:** atendente conversacional de condomínio. O morador (com login liberado por um admin)
pede pelo chat; a IA, como portaria digital, reserva área comum com taxa, abre ordem de
serviço, autoriza visitante e consulta encomendas e cota.

**Estado (30/10): a infraestrutura da etapa 1 está toda de pé em Ohio.** Rede, security
groups, RDS Multi-AZ, SQS com DLQ, ECR, 4 roles IAM, grupos de log, target group, ALB,
Launch Template, ASG (2 × `t3.small`, uma por AZ, já registradas no cluster), cluster ECS e
Capacity Provider como estratégia padrão. Lista com IDs em
[docs/recursos-ohio.md](docs/recursos-ohio.md). O ALB responde
`http://cloud-projeto-final-alb-1611305876.us-east-2.elb.amazonaws.com` com **503**, o
esperado enquanto não há task. O código ainda é o esqueleto genérico ("pedidos").

**Onde paramos / próximo passo (a aplicação):**

1. Adaptar o código ao condomínio (`chat-service` → `atendimento`, `order-worker` →
   `operacoes`), escolher o modelo do Bedrock e acrescentar a permissão dele na role
   `cloud-projeto-final-role-app-atendimento`.
2. `docker build` + `docker push` pelo **CloudShell** para os dois repositórios do ECR.
3. Task definitions (modo `bridge`, porta do host 0, log nos grupos `/ecs/cloud-projeto-final/…`,
   senha do banco pelo ARN do segredo, roles de execução e de aplicação).
4. Serviços ECS: `atendimento` ligado ao target group `cloud-projeto-final-tg-atend`;
   `operacoes` sem load balancer.
5. Escala das tasks, alarmes do CloudWatch e as demos de falha.

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
docs/               arquitetura, recursos criados em Ohio, passos no console
infra/terraform/    etapa 2 (São Paulo)
```

## Regras do repositório

- **Nenhum segredo commitado.** `.env`, credenciais AWS e estado do Terraform estão no
  `.gitignore`. Na AWS, segredo vem do Secrets Manager.
- **Nenhum valor de região no código da aplicação.** Região, fila e banco vêm de variável de
  ambiente, para o mesmo container rodar em Ohio e em São Paulo.
- **Todo recurso AWS leva a tag `projeto=cloud-projeto-final`.**
