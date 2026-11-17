# Projeto Final — Computação em Nuvem

Plataforma de comércio conversacional na AWS: o cliente conversa com um vendedor de IA
generativa que consulta dados reais e registra pedidos. O que se avalia é a arquitetura.

- **Etapa 1:** construção manual em Ohio (`us-east-2`), no console e no CloudShell.
- **Etapa 2:** reconstrução integral em Terraform em São Paulo (`sa-east-1`).

**Tema:** atendente conversacional de condomínio. O morador pede pelo chat, e a IA, como portaria
digital, consulta a disponibilidade e reserva a área comum com taxa. Ordem de serviço, visitante,
encomendas, cota e o login liberado por um admin ficam para depois.

**Estado (05/11), ainda valendo:**

- **A aplicação está no ar em Ohio:**
  `http://cloud-projeto-final-alb-1611305876.us-east-2.elb.amazonaws.com`, com 2 tasks do
  `atendimento` e 1 do `operacoes`. Lista com IDs em [docs/recursos-ohio.md](docs/recursos-ohio.md).
- **Jornada real provada:** da conversa com o Haiku 5.5 à reserva gravada no RDS e à cobrança pelo
  `operacoes`, com o mesmo `correlation_id` nos dois logs.
- **Troca de versão:** da `v1` para a `v2`, 90 chamadas a `/health` em 3 minutos, todas com 200.
- **Testes locais:** 28 passando, com MySQL e fila em containers e o modelo simulado.

**Estado (06/11), horários em UTC, o relógio do CloudShell (Brasília = UTC − 3):**

- **Consumo medido em repouso, por task** (Container Insights; o valor por serviço é a média por
  task): `atendimento` 59 MiB de 256 reservados e 15 de 256 unidades de CPU; `operacoes` 40 de 128
  MiB e 4 de 128 unidades. As reservas ficaram como estavam: a folga é de 3 a 4 vezes.
- **Cada `t3.small` oferece ao ECS 2048 unidades de CPU e 1913 MiB.** A memória limita: cabem 7
  tasks do `atendimento` por instância. Com o `operacoes`, as 2 instâncias seguram 13.
- **Escala em dois níveis provada** com `scripts/carga.py` (40 req/s no `/health`, 12 min): às 14:49:55
  as tasks foram de 2 para 16, 13 rodaram e 3 ficaram sem lugar; às 14:51:29 o `ASG` foi a 3; às
  14:53:03, 16 rodando em 3 instâncias. **28.820 requisições, todas 200.** Prints em
  [docs/evidencias/](docs/evidencias/).
- **Escala do `operacoes` pela fila provada** com `scripts/encher-fila.py` (28.860 cópias de um evento
  já processado, 60/s por 8 min): 1 task processa ~30 mensagens/s, a fila chegou a 9205, às 15:14:22
  subiram 4 tasks (~100/s juntas), a fila zerou às 15:17:33. **DLQ em 0 o tempo todo:** toda cópia
  foi descartada como duplicada.
- **Alarmes:** 12, todos em OK, avisando o tópico SNS `cloud-projeto-final-alertas` (e-mail do autor
  confirmado). Criados por `scripts/alarmes.sh`.
- **Armadilha vista:** com 3 instâncias em 2 AZs, o ECS tentou rebalancear as tasks por AZ e deixou
  1 task pendente na AZ cheia (evento "AZ Rebalancing in progress", 15:08:01). Não derrubou nada, e o
  `Capacity Provider` não contou essa task como falta de instância.

**Estado (10/11), UTC.** Saídas em [docs/evidencias/](docs/evidencias/):

- **Descida de 06/11 conferida:** voltou a 2 tasks do `atendimento`, 1 do `operacoes` e 2 instâncias.
- **Task parada com `stop-task`, sob ~2 req/s:** o serviço não cai, e a contagem volta a 2 em ~1 min.
- **`v3` no ar:** `--timeout-keep-alive 65` no `uvicorn`, acima dos 60 s de ociosidade do ALB. Os `502`
  esporádicos foram de 4 em 743 (`v2`) para 0 em 939 (`v3`).
- **Drenagem e substituição de instância:** 1516 requisições, todas 200.

**Estado (11/11), UTC.** As demos de falha da etapa 1 estão feitas:

- **Queda abrupta de instância** (encerrada sem drenagem, sob ~2 req/s): tudo de volta em ~1,5 min, o
  ASG subiu a substituta em 22 s. **23 falhas em ~170 pedidos** (8 `502`, 15 sem resposta em 5 s),
  na janela de ~20 s em que o ALB ainda mandava tráfego para a task morta. Na drenagem planejada, 0.
- **Modelo fora do ar** (política `invocar-haiku` retirada): 10 de 10 mensagens caíram no menu, o
  alarme `erros-atendimento` acendeu em ~1,5 min, o log mostrou `AccessDeniedException`, e tudo voltou
  com a política recolocada.
- **Fila fora do ar** (política `publicar-eventos` retirada): a reserva foi confirmada na hora (201), o
  evento ficou na caixa de saída, e saiu sozinho 23 s depois da volta da permissão. A cobrança do
  `operacoes` tem o mesmo `correlation_id` (`demo5-fila-144335`). O SQS respondeu `NonExistentQueue`,
  não "acesso negado": a fila existe.
- **Banco fora do ar** (failover forçado do RDS Multi-AZ): 5 leituras com `503` em ~13 s, 211 com 200,
  a aplicação voltou sozinha, e o primário passou para `us-east-2b`.
- **Rebalanceamento por zona do ECS está ligado:** depois de uma substituição, o serviço volta a ter
  uma task por zona sozinho, uns 12 min depois de a instância nova entrar no cluster.

**Onde paramos (17/11):** as duas etapas estão de pé, as duas na v5.

- **Etapa 1, Ohio:** na v5 desde 17/11. Diagrama em `docs/arquitetura-ohio.drawio` (editável) e
  `docs/arquitetura-ohio.png`.
- **Etapa 2, São Paulo:** criada pelo Terraform em `infra/terraform/` (como rodar: o README de lá).
  Provado em 12/11: `destroy` completo e `apply` do zero numa passada só, com 77 recursos em 15 min 52 s,
  as imagens geradas e enviadas pelo próprio `apply`; depois, a conversa com o Haiku (perfil `global.`)
  reservou, e o `operacoes` processou o evento com o mesmo `correlation_id`. Os 12 alarmes em OK.
  Evidências em `docs/evidencias/2026-11-12-sp-*`.
- **17/11, o Terraform roda em qualquer conta e sistema:** o nome do bucket do estado, que leva o
  número da conta, saiu do código e entra no `terraform init`; o Python é chamado como `python3` fora
  do Windows. Conferido com `fmt`, `validate`, `init` no PowerShell e no bash, e `plan`.
- **17/11, v5 publicada em São Paulo** por `terraform apply` (40 s, só a imagem nova do `atendimento`;
  a troca das tasks levou mais 140 s). As 2 tasks `healthy`, os 12 alarmes em OK, e o Haiku real
  respondeu "o que está livre no fim de semana?" com a consulta por intervalo, numa rodada só.
- **17/11, v5 publicada em Ohio** pelo PC: imagem `atendimento:v5` e task definition revisão 6 (a 5
  saiu por engano igual à 4, com a imagem v4, e não está em uso). Rollout em 130 s, 2 tasks `healthy`,
  12 alarmes em OK, e a mesma pergunta respondida pelo Haiku real em 4,1 s. O `operacoes` não mudou.

**Próximo passo:**

1. Antes de apresentar, em Ohio: **cancelar as 3 reservas de teste** (12/12, 13/12 e 20/12), que lotam
   a unidade de demo. Desde a v4, dá para fazer pela própria página: "Minhas reservas" → "Cancelar".
2. Atualizar o resumo público (artefato) com a etapa 2 e a v5.
3. Testar na AWS reserva e cancelamento com o prompt da v5 (até aqui, só consulta).
4. Opcional: fechar a janela de ~1 min sem banco durante a rotação da senha, tentando também a versão
   `AWSPENDING` do segredo.

**Colar no CloudShell:** ele às vezes come o primeiro caractere de um bloco colado. Blocos longos
começam por uma linha de comentário.

**Para publicar uma versão nova do código:**

- **São Paulo:** `terraform apply` em `infra/terraform/ambiente`. A tag da imagem é o hash do código,
  então código novo gera imagem, revisão da task definition e implantação sozinho.
- **Ohio** (etapa 1, sem IaC), do PC, com o perfil SSO `cloud`:
  1. `python scripts/publicar-imagem.py us-east-2 <conta>.dkr.ecr.us-east-2.amazonaws.com/cloud-projeto-final/<serviço> <tag> app/<serviço>`.
  2. Trocar a tag em `docs/task-definitions/<serviço>.json`, `aws ecs register-task-definition --cli-input-json file://…`
     e `aws ecs update-service --task-definition <família>:<revisão>`. **O `operacoes` primeiro**, para ele já
     entender os eventos novos quando o `atendimento` novo subir.

Hoje rodam, em Ohio, `atendimento:v5` (revisão 6) e `operacoes:v4` (revisão 2), que não mudou na v5. Em São Paulo, o
`atendimento` da v5 (task definition revisão 4, imagem `4c2d0fdb81ac`) e o `operacoes` sem mudança
desde a v4 (revisão 3).

**v4 (12/11):** "minhas reservas" e cancelamento (pelo chat e pela página), front-end com sugestões e
painéis, e a senha do banco relida no Secrets Manager quando o RDS a rotaciona. Em 12/11, a rotação
automática de 05:08 tinha derrubado o chat de Ohio até as tasks serem reiniciadas (evidência em
`docs/evidencias/2026-11-12-ohio-senha-rotacionada.txt`). Com a v4, uma rotação forçada em São Paulo
deixou o banco indisponível por ~1 min, só durante a própria rotação, e o app voltou sozinho
(`docs/evidencias/2026-11-12-sp-3-rotacao-da-senha.txt`).

**v5 (16/11), publicada em São Paulo e em Ohio em 17/11:**

- **Agente com mais contexto:** o prompt leva o dia da semana, o calendário dos próximos 14 dias, as
  áreas com taxas, os horários dos períodos, as regras (limite e antecedência), o nome e a unidade do
  morador (lidos pelo servidor) e o que está fora do escopo.
- **Consulta por intervalo:** `consultar_disponibilidade` aceita área opcional e `data_fim` (até 14
  dias), numa consulta SQL só. "O que está livre no fim de semana?" cabe numa rodada.
- **API:** `POST /chat` devolve `acoes` (o que foi reservado ou cancelado), `GET /chat/{conversa_id}`
  devolve o histórico, e "minhas reservas" traz a referência do PIX gerada pelo `operacoes`.
- **Front-end:** painel "Minhas reservas" ao lado do chat, que mostra a cobrança passando de
  "gerando" a "gerada"; cartão de confirmação; conversa que sobrevive ao recarregar; e o
  `correlation_id` da última mensagem no rodapé, para buscar no CloudWatch.
- **Testes locais:** 42 passando em 17/11. **Na AWS (São Paulo, 17/11):** o Haiku real usou a
  consulta por intervalo para sábado e domingo numa rodada só, em 4 s. Reserva e cancelamento com o
  prompt novo ainda não foram testados na AWS.

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
| `GET  /chat/{conversa_id}` | o histórico da conversa, para a página reabrir |
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
