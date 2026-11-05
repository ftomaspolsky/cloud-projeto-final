# Projeto Final — Computação em Nuvem

Plataforma de comércio conversacional na AWS: o cliente conversa com um vendedor de IA
generativa que consulta dados reais e registra pedidos. O que se avalia é a arquitetura.

- **Etapa 1:** construção manual em Ohio (`us-east-2`), no console e no CloudShell.
- **Etapa 2:** reconstrução integral em Terraform em São Paulo (`sa-east-1`).

**Tema:** atendente conversacional de condomínio. O morador pede pelo chat, e a IA, como portaria
digital, consulta a disponibilidade e reserva a área comum com taxa. Ordem de serviço, visitante,
encomendas, cota e o login liberado por um admin ficam para depois.

**Estado (05/11):**

- **A aplicação está no ar em Ohio:**
  `http://cloud-projeto-final-alb-1611305876.us-east-2.elb.amazonaws.com`, com 2 tasks do
  `atendimento` e 1 do `operacoes`. Lista com IDs em [docs/recursos-ohio.md](docs/recursos-ohio.md).
- **Jornada real provada:** da conversa com o Haiku 5.5 à reserva gravada no RDS e à cobrança pelo
  `operacoes`, com o mesmo `correlation_id` nos dois logs.
- **Troca de versão:** da `v1` para a `v2`, 90 chamadas a `/health` em 3 minutos, todas com 200.
- **Testes locais:** 28 passando, com MySQL e fila em containers e o modelo simulado.

**Onde paramos / próximo passo:**

1. Escala das tasks por métrica, e a escala das instâncias sob carga. Com as reservas atuais, cabem
   cerca de 7 tasks por instância, então a demo precisa de reservas maiores ou de mais tasks.
2. Medir o consumo real, para ajustar CPU e memória das task definitions.
3. Alarmes do CloudWatch.
4. As demos de falha: task, instância, modelo, fila e banco.
5. Diagrama.
6. Etapa 2, em São Paulo, com Terraform, escrito pelo agente e rodado pelo autor.

**Para publicar uma versão nova do código:**

1. No PC: `python scripts/gerar-zip.py`, que grava `../cloud-projeto-final.zip`, sem o `.env`.
2. No CloudShell: apagar o `.zip` antigo, enviar o novo por **Ações → Carregar arquivo** e extrair em
   `~/projeto`.
3. `docker login` no ECR, `docker build` e `docker push` com uma tag nova (`v3`, …).
4. Trocar a tag em `docs/task-definitions/<serviço>.json`, depois `aws ecs register-task-definition
   --cli-input-json file://…` e `aws ecs update-service --task-definition <família>:<revisão>`.

Hoje rodam `atendimento:v2` (revisão 2) e `operacoes:v1` (revisão 1).

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
docs/               arquitetura, recursos criados em Ohio, task definitions, passos no console
scripts/            o .zip que vai para o CloudShell
infra/terraform/    etapa 2 (São Paulo)
```

## Regras do repositório

- **Nenhum segredo commitado.** `.env`, credenciais AWS e estado do Terraform estão no
  `.gitignore`. Na AWS, segredo vem do Secrets Manager.
- **Nenhum valor de região no código da aplicação.** Região, fila, banco e modelo vêm de variável
  de ambiente, para o mesmo container rodar em Ohio e em São Paulo.
- **Todo recurso AWS leva a tag `projeto=cloud-projeto-final`.**
