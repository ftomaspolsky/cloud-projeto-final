# Projeto Final — Computação em Nuvem

Plataforma de comércio conversacional na AWS: o cliente conversa com um vendedor de IA
generativa que consulta dados reais e registra pedidos. O que se avalia é a arquitetura.

- **Etapa 1:** construção manual em Ohio (`us-east-2`), 100% no console, sem código.
- **Etapa 2:** reconstrução integral em Terraform em São Paulo (`sa-east-1`).

**Tema:** atendente conversacional de condomínio. O morador (com login liberado por um admin)
pede pelo chat; a IA, como portaria digital, reserva área comum com taxa, abre ordem de
serviço, autoriza visitante e consulta encomendas e cota.

**Estado (22/10):** em Ohio estão prontos rede, security groups, RDS MySQL Multi-AZ e SQS
com DLQ (ver [docs/recursos-ohio.md](docs/recursos-ohio.md)). O código ainda é o esqueleto
genérico ("pedidos").

**Onde paramos / próximo passo:**

1. Anotar o **endpoint** do RDS (aba *Conectividade e segurança*) e o **ARN do segredo**
   (aba *Configuração*, "Credenciais do usuário principal").
2. Criar no ECR os repositórios `cloud-projeto-final/atendimento` e
   `cloud-projeto-final/operacoes` (tags mutáveis, AES-256).
3. Perguntar ao professor se o `docker push` pelo **CloudShell** cabe no "100% no console".
   Se couber, as instâncias ECS são **t3** (x86), porque o CloudShell faz build x86.
4. Adaptar o código ao condomínio.
5. Launch Template + ASG + cluster ECS com Capacity Provider → ALB → serviços → alarmes.

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
