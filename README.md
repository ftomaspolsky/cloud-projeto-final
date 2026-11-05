# Projeto Final — Computação em Nuvem

Plataforma de comércio conversacional na AWS: o cliente conversa com um vendedor de IA
generativa que consulta dados reais e registra pedidos. O que se avalia é a arquitetura.

- **Etapa 1:** construção manual em Ohio (`us-east-2`), no console e no CloudShell.
- **Etapa 2:** reconstrução integral em Terraform em São Paulo (`sa-east-1`).

**Tema:** atendente conversacional de condomínio. O morador pede pelo chat, e a IA, como portaria
digital, consulta a disponibilidade e reserva a área comum com taxa. Ordem de serviço, visitante,
encomendas, cota e o login liberado por um admin ficam para depois.

**Estado (05/11):**

- **Infraestrutura em Ohio:** toda de pé desde 30/10. Rede, security groups, RDS Multi-AZ, SQS com
  DLQ, ECR, 4 roles IAM, grupos de log, target group, ALB, Launch Template, ASG, cluster ECS e
  Capacity Provider. Lista com IDs em [docs/recursos-ohio.md](docs/recursos-ohio.md). A conta não
  foi consultada de novo depois disso, fora o Bedrock e a role abaixo.
- **Modelo:** Claude Haiku 5.5, testado no Playground de Ohio e de São Paulo. A role do
  `atendimento` já tem a política `invocar-haiku`.
- **Aplicação:** escrita e testada **só localmente**, com 28 testes passando, com MySQL e fila em
  containers e o modelo **simulado**. Nada foi publicado: o ALB continua respondendo 503.

**Onde paramos / próximo passo (publicar):**

1. Levar o código ao **CloudShell**, e lá fazer `docker build` + `docker push` para os dois
   repositórios do ECR.
2. Task definitions (ver abaixo).
3. Serviços ECS: `atendimento` ligado ao target group `cloud-projeto-final-tg-atend`;
   `operacoes` sem load balancer.
4. Conferir os três itens que só a AWS prova, em [Riscos conhecidos](docs/arquitetura.md#riscos-conhecidos).
5. Escala das tasks, alarmes do CloudWatch e as demos de falha.
6. Diagrama e etapa 2.

## Arquitetura

```
Internet → ALB (sub-redes públicas, 2 AZs)
             │
             ▼
   atendimento    (ECS, síncrono)  conversa + Bedrock + ferramentas ──► RDS MySQL
             │ evento depois do commit                                  (sub-redes
             ▼                                                           privadas)
   SQS eventos ──(3 recebimentos)──► SQS eventos-dlq                        ▲
             │                                                              │
             ▼                                                              │
   operacoes      (ECS, assíncrono) idempotente: cobrança + aviso ──────────┘
```

Detalhes e decisões em [docs/arquitetura.md](docs/arquitetura.md).

## Configuração das tasks

Modo `bridge`, porta do host 0, log nos grupos `/ecs/cloud-projeto-final/…`, roles de execução e
de aplicação do serviço.

| Variável | `atendimento` | `operacoes` | Valor em Ohio |
|---|---|---|---|
| `AWS_REGION` | sim | sim | `us-east-2` |
| `QUEUE_NAME` | sim | sim | `cloud-projeto-final-eventos` |
| `DB_HOST` | sim | sim | o endpoint do RDS, sem a porta |
| `DB_NAME` | sim | sim | `condominio` |
| `DB_SSL_CA` | sim | sim | `/app/rds-ca.pem` (já vem na imagem) |
| `DB_USER`, `DB_PASSWORD` | sim | sim | **segredo:** chaves `username` e `password` do ARN do Secrets Manager |
| `BEDROCK_MODEL_ID` | sim | não | `us.anthropic.claude-haiku-5-5` |

O `atendimento` expõe a porta 8000, e o ALB confere `GET /health`. O `operacoes` não expõe porta
nenhuma: o `/health` dele, na 8081, serve só ao health check do próprio container.

`SQS_ENDPOINT_URL` e `BEDROCK_ENDPOINT_URL` existem só no ambiente local. Na AWS, não defina.

## Rodar local

Precisa de Docker.

```bash
cp .env.example .env
docker compose up --build                            # http://localhost:8000
docker compose --profile teste run --rm --build testes
```

| Rota | O que faz |
|---|---|
| `GET  /` | a página de chat |
| `GET  /health` | health check |
| `POST /chat` `{"mensagem": "reserva o salão em 2026-12-12 à noite"}` | conversa com o modelo |
| `GET  /menu/areas`, `GET /menu/disponibilidade`, `POST /menu/reservas` | o menu guiado, sem IA |

Mande `X-Correlation-Id: <algo>` no cabeçalho e o mesmo id aparece no log do `operacoes`.

**O modelo local é simulado** (`local/bedrock-fake/`), como o ElasticMQ faz com o SQS. Ele entende
frases com área, data em `AAAA-MM-DD` e período, e devolve o resultado da ferramenta em formato
cru. Não prova que o Haiku real escolhe bem a ferramenta, nem que a política IAM está certa.

## Estrutura

```
app/atendimento/    serviço síncrono: rotas, Bedrock, regras da reserva, página de chat
app/operacoes/      consumidor da fila
local/              os simulados: SQS (ElasticMQ) e Bedrock
tests/              testes do fluxo inteiro, em containers
docs/               arquitetura, recursos criados em Ohio, passos no console
infra/terraform/    etapa 2 (São Paulo)
```

## Regras do repositório

- **Nenhum segredo commitado.** `.env`, credenciais AWS e estado do Terraform estão no
  `.gitignore`. Na AWS, segredo vem do Secrets Manager.
- **Nenhum valor de região no código da aplicação.** Região, fila, banco e modelo vêm de variável
  de ambiente, para o mesmo container rodar em Ohio e em São Paulo.
- **Todo recurso AWS leva a tag `projeto=cloud-projeto-final`.**
