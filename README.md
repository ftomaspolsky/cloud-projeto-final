# Zelo — Plataforma de comércio conversacional na AWS

A Zelo é um zelador digital de condomínio baseado em IA generativa, desenvolvido para o Projeto Final de Computação em Nuvem (Insper). Pelo chat, o morador consulta a disponibilidade das áreas comuns (Salão de festas, Churrasqueira e Quadra), faz reservas com checagem de conflito e taxa, acompanha a geração da cobrança via PIX e cancela reservas com estorno. Ordem de serviço, visitantes, encomendas, cota condominial e login de morador ficam fora do MVP.

A infraestrutura foi construída em duas regiões independentes:

- **Etapa 1, Ohio (`us-east-2`):** criada manualmente pelo Console AWS e pela AWS CLI no CloudShell, sem IaC. No ar em `http://cloud-projeto-final-alb-1611305876.us-east-2.elb.amazonaws.com`, rodando `atendimento:v6` (revisão 7) e `operacoes:v4` (revisão 2), com inventário em [docs/recursos-ohio.md](docs/recursos-ohio.md).
- **Etapa 2, São Paulo (`sa-east-1`):** reconstruída integralmente em Terraform em [infra/terraform/](infra/terraform/), sem reaproveitar recursos manuais de Ohio.

## Arquitetura

```
Internet → ALB (sub-redes públicas, 2 AZs)
             │
             ▼
   atendimento    (ECS/EC2, síncrono) ──► Guardrail ──► Claude Haiku 5.5
     │        │
     │        └── reserva + taxa + evento_saida (transação única) ──► RDS MySQL 8.4
     │ evento depois do commit                                        Multi-AZ
     ▼                                                                (privadas)
   SQS eventos ──(3 recebimentos)──► SQS eventos-dlq                     ▲
     │                                                                   │
     ▼                                                                   │
   operacoes      (ECS/EC2, assíncrono, idempotente: PIX e estorno) ─────┘
```

O diagrama da arquitetura está em [docs/arquitetura-ohio.png](docs/arquitetura-ohio.png) (editável em [docs/arquitetura-ohio.drawio](docs/arquitetura-ohio.drawio)) e as decisões técnicas estão registradas em [docs/arquitetura.md](docs/arquitetura.md).

A aplicação usa dois serviços ECS sobre instâncias EC2 (`t3.small`) com perfis de carga distintos. O `atendimento` responde ao tráfego síncrono atrás do ALB, limitado pela latência do modelo, e escala de 2 a 16 tasks com alvo de 100 requisições por task por minuto (`ALBRequestCountPerTarget`). O `operacoes` não expõe porta externa, consome eventos do SQS e escala de 1 a 4 tasks com alvo de 100 mensagens visíveis por task. Quando faltam recursos nas instâncias para novas tasks, o Capacity Provider (alvo de 100%, drenagem e proteção contra encerramento gerenciadas) escala o Auto Scaling Group de 2 para até 4 instâncias. As tasks usam posicionamento `spread` por zona de disponibilidade e `binpack` por memória.

Toda reserva ou cancelamento grava na mesma transação no RDS MySQL 8.4 Multi-AZ o registro da reserva, o lançamento financeiro e o evento na caixa de saída (`evento_saida`). O banco impede reservas duplicadas pelo índice único `uma_reserva_ativa_por_horario` (com coluna gerada `vaga`, que sai da restrição quando a reserva é cancelada) e trava o limite de 3 reservas futuras por unidade com `SELECT ... FOR UPDATE`. Depois do commit, o `atendimento` publica o evento na fila SQS padrão `cloud-projeto-final-eventos` (visibilidade de 60 s, long polling de 20 s, redrive para `cloud-projeto-final-eventos-dlq` após 3 recebimentos); se a fila estiver fora do ar, o publicador tenta de novo a cada 10 s. Do outro lado, o `operacoes` registra o `evento_id` em `evento_processado` na mesma transação em que gera a referência PIX (`ReservaSolicitada`) ou cancela e solicita estorno (`ReservaCancelada`). Eventos repetidos são descartados, e um cancelamento que chegue antes da solicitação impede a cobrança.

A VPC própria (`10.0.0.0/16`) se divide em duas zonas de disponibilidade, cada uma com sub-rede pública (ALB e NAT Gateway) e sub-rede privada (instâncias EC2 e RDS, sem IP público). Os security groups são encadeados por origem: o `sg-alb` recebe HTTP na porta 80, o `sg-ecs` aceita apenas portas dinâmicas `32768-65535` vindas do `sg-alb` (sem SSH; acesso só por SSM Session Manager), e o `sg-rds` aceita apenas MySQL na `3306` vindo do `sg-ecs`, sem regras de saída. As instâncias exigem IMDSv2 com hop limit 1 (containers em modo `bridge` não alcançam a credencial do host), os containers rodam com o usuário sem privilégio `app`, e a conexão ao RDS valida certificado e identidade com `global-bundle.pem`.

As permissões ficam separadas em 4 IAM roles: instância EC2, execução das tasks, aplicação `atendimento` (com a condição `bedrock:InferenceProfileArn` na invocação do modelo) e aplicação `operacoes` (somente leitura e exclusão na fila). A senha do banco nasce e rotaciona automaticamente no Secrets Manager; quando ocorre rotação com tasks no ar, os dois serviços releem a credencial atual via `DB_SECRET_ARN` ao receber `Access denied` (erro 1045).

A proteção contra prompt injection atua em duas camadas. Antes de chamar o Claude Haiku 5.5 pela API Converse, o `atendimento` envia o histórico de mensagens do morador para uma Bedrock Guardrail com o filtro `PROMPT_ATTACK` em força `HIGH`, no tier Standard (o único que entende português). Quando a guardrail intervém, o modelo nem é chamado, a conversa orienta o morador a abrir uma nova, e o log registra apenas tipo e confiança do filtro, sem gravar o texto digitado. Se a guardrail ou o modelo falharem, a mensagem fica gravada no banco e o chat abre o formulário guiado sem IA, que aplica as mesmas regras. A camada principal está no código: a identidade do morador vem do servidor, nunca do texto ou dos parâmetros das ferramentas, e unidade, limite e taxa são validados no banco.

## Subir com Terraform (São Paulo)

Pré-requisitos na máquina que executa o código: Terraform >= 1.10, AWS CLI v2 autenticado com permissão administrativa, Docker aberto (o `apply` compila e envia as imagens) e Python 3 (`python` no Windows; `python3` no Linux e macOS). Em uma conta AWS nova, a primeira chamada a modelos da Anthropic no Bedrock pede o preenchimento único do formulário de caso de uso no console.

```bash
export AWS_PROFILE=cloud            # PowerShell: $env:AWS_PROFILE = "cloud"

cd infra/terraform/bootstrap
terraform init
terraform apply                     # cria o bucket S3 do estado (uma vez por conta)

cd ../ambiente
terraform init -backend-config="bucket=$(terraform "-chdir=../bootstrap" output -raw bucket_do_estado)"
terraform apply
```

As aspas em `"-chdir=../bootstrap"` evitam que o PowerShell 5.1 quebre o argumento no ponto. O `apply` completo leva entre 16 e 20 minutos (quase todo o tempo esperando o RDS Multi-AZ) e imprime `endereco_do_chat` (acesso por `http://`). Para inscrever um e-mail nos alarmes do SNS, passe `-var email_alertas=voce@exemplo.com`. Para destruir o ambiente inteiro sem deixar recursos órfãos, rode `terraform destroy` dentro de `infra/terraform/ambiente`; o bucket do `bootstrap` permanece protegido por `prevent_destroy`.

O código de São Paulo não tem IDs de conta, zonas ou AMIs fixas: as zonas vêm de `data "aws_availability_zones"`, a AMI ECS-optimized vem do parâmetro público do SSM da região, o perfil `global.anthropic.claude-haiku-5-5` vem de `data "aws_bedrock_inference_profile"`, e as imagens são compiladas para `linux/amd64` (tag pelo hash do código) e enviadas ao ECR de `sa-east-1` via [scripts/publicar-imagem.py](scripts/publicar-imagem.py). Como `sa-east-1` só tem o tier Classic da Bedrock Guardrail (inglês, francês e espanhol) e não é origem de perfis cross-region de guardrail, o Terraform cria uma guardrail própria para São Paulo (`cloud-projeto-final-sa-east-1-prompt`) em `us-east-2` (`GUARDRAIL_REGION`), separada da guardrail manual de Ohio. Mais detalhes em [infra/terraform/README.md](infra/terraform/README.md).

## Rodar e testar localmente

Requer Docker. O ambiente local replica a mesma topologia com MySQL 8.4, ElasticMQ (SQS compatível com DLQ após 3 falhas) e `local/bedrock-fake/` (simula as APIs Converse com ferramentas e `ApplyGuardrail`).

```bash
cp .env.example .env
docker compose up --build                            # http://localhost:8000
docker compose --profile teste run --rm --build testes
```

A suíte em [tests/test_fluxo.py](tests/test_fluxo.py) roda 46 testes: jornada completa, concorrência de reservas, limite por unidade, rollback transacional, caixa de saída com fila fora do ar, idempotência, DLQ, cancelamento com estorno, entrega fora de ordem, migração de esquema, fallback sem IA e bloqueio pela guardrail.

| Rota | Função |
|---|---|
| `GET /` | página de chat e painel "Minhas reservas" |
| `GET /health` | health check de liveness (independe de banco, fila e modelo) |
| `POST /chat` | conversa com o modelo (`{"mensagem": "...", "conversa_id": "..."}`) |
| `GET /chat/{conversa_id}` | histórico persistido da conversa |
| `GET /menu/areas` | áreas comuns, taxas e períodos |
| `GET /menu/disponibilidade` | disponibilidade por área e data (sem IA) |
| `POST /menu/reservas` | reserva pelo fluxo sem IA |
| `GET /menu/minhas-reservas` | reservas ativas da unidade com status da cobrança e referência PIX |
| `DELETE /menu/reservas/{reserva_id}` | cancelamento de reserva e disparo do estorno |

Enviar `X-Correlation-Id: <id>` no cabeçalho (ou copiar o ID exibido no rodapé da interface) permite rastrear a mesma operação nos logs JSON do `atendimento` e do `operacoes` no CloudWatch Logs Insights.

## Configuração das tasks ECS

Os dois serviços rodam em modo `bridge` com logs JSON enviados para `/ecs/cloud-projeto-final/{atendimento,operacoes}` (retenção de 14 dias):

- `atendimento`: `256` unidades de CPU, `256` MiB reservados (`512` MiB de limite), porta do container `8000` mapeada na porta `0` (dinâmica) do host, health check do ALB em `GET /health` a cada 10 s e `uvicorn` com `--timeout-keep-alive 65` (acima dos 60 s de ociosidade do ALB).
- `operacoes`: `128` unidades de CPU, `128` MiB reservados (`256` MiB de limite), sem porta exposta, health check do container em `GET :8081/health` a cada 30 s e encerramento limpo ao receber `SIGTERM`.

| Variável | `atendimento` | `operacoes` | Valor em Ohio (`us-east-2`) | Valor em São Paulo (`sa-east-1`) |
|---|---|---|---|---|
| `AWS_REGION` | sim | sim | `us-east-2` | `sa-east-1` |
| `QUEUE_NAME` | sim | sim | `cloud-projeto-final-eventos` | `cloud-projeto-final-eventos` |
| `DB_HOST` | sim | sim | endpoint do RDS de Ohio | endpoint do RDS de São Paulo |
| `DB_NAME` | sim | sim | `condominio` | `condominio` |
| `DB_SSL_CA` | sim | sim | `/app/rds-ca.pem` | `/app/rds-ca.pem` |
| `DB_SECRET_ARN` | sim | sim | ARN do segredo do RDS de Ohio | ARN do segredo do RDS de São Paulo |
| `DB_USER`, `DB_PASSWORD` | sim | sim | injetados do Secrets Manager (`username` / `password`) | injetados do Secrets Manager (`username` / `password`) |
| `BEDROCK_MODEL_ID` | sim | não | `us.anthropic.claude-haiku-5-5` | `global.anthropic.claude-haiku-5-5` |
| `GUARDRAIL_ID`, `GUARDRAIL_VERSION` | sim | não | ID de `cloud-projeto-final-prompt` e `1` | ID de `cloud-projeto-final-sa-east-1-prompt` e `1` |
| `GUARDRAIL_REGION` | opcional | não | não definida (usa `AWS_REGION`) | `us-east-2` |

`SQS_ENDPOINT_URL` e `BEDROCK_ENDPOINT_URL` existem apenas no ambiente local. Em São Paulo, versões novas do código sobem com `terraform apply`. Em Ohio (Etapa 1, manual), o deploy usa `scripts/publicar-imagem.py`, atualização de [docs/task-definitions/](docs/task-definitions/), `aws ecs register-task-definition` e `aws ecs update-service`, publicando `operacoes` antes de `atendimento`.

## Evidências medidas na AWS

Todos os testes de carga, escala, falha e reconstrução foram executados na AWS e gravados em [docs/evidencias/](docs/evidencias/), com 12 alarmes do CloudWatch (saúde das tasks, CPU do cluster, capacidade do ASG e do Capacity Provider, 5xx e targets não saudáveis do ALB, idade de mensagem na fila, mensagens na DLQ e filtros de métrica `{ $.nivel = "ERROR" }` nos dois grupos de log) conectados ao tópico SNS `cloud-projeto-final-alertas`.

| Cenário testado | Resultado medido | Evidência |
|---|---|---|
| Consumo em repouso (Container Insights) | `atendimento` usa 59 de 256 MiB e 15 de 256 CPU; `operacoes` usa 40 de 128 MiB e 4 de 128 CPU. Em `t3.small` (2048 CPU, 1913 MiB), memória limita a 7 tasks de `atendimento` por nó (13 + 1 `operacoes` em 2 nós). | medição em 06/11 |
| Escala em dois níveis (`scripts/carga.py`, 40 req/s no `/health`, 12 min) | Tasks do `atendimento` foram de 2 a 16; Capacity Provider subiu o ASG de 2 para 3 instâncias. 28.820 requisições, todas HTTP 200; scale-in posterior de volta a 2 tasks e 2 instâncias. | [prints 06/11](docs/evidencias/), [descida](docs/evidencias/2026-11-10-descida-conferida.txt) |
| Escala pela fila e idempotência (`scripts/encher-fila.py`, 28.860 cópias, 60/s por 8 min) | Fila chegou a 9.205 mensagens; `operacoes` subiu de 1 para 4 tasks (~30 para ~100 msg/s) e zerou o backlog. DLQ em 0 o tempo todo, sem cobranças duplicadas. | [fila-1](docs/evidencias/2026-11-06-fila-1-envio.png), [fila-2](docs/evidencias/2026-11-06-fila-2-operacoes-sobe.png) |
| Keep-alive ALB/uvicorn (`v2` para `v3`) | Ajuste de `--timeout-keep-alive 65` reduziu erros `502` esporádicos de 4 em 743 (`v2`) para 0 em 939 (`v3`). | [troca v2→v3](docs/evidencias/2026-11-10-troca-v2-para-v3.txt), [demo1 v3](docs/evidencias/2026-11-10-demo1-task-morta-v3.txt) |
| Parada de task (`stop-task`, ~2 req/s) | Serviço manteve disponibilidade (480 de 480 respostas `200` na `v3`) e repôs a segunda task em ~1 min. | [demo1 v3](docs/evidencias/2026-11-10-demo1-task-morta-v3.txt) |
| Drenagem planejada e substituição de instância | 1.516 requisições, todas `200`; ASG subiu instância substituta automaticamente. | [demo2](docs/evidencias/2026-11-10-demo2-drenagem-e-substituicao.txt) |
| Queda abrupta de instância (sem drenagem, ~2 req/s) | 23 falhas em ~170 pedidos (8 `502`, 15 timeouts de 5 s) na janela de ~20 s do health check do ALB; ASG lançou substituta em 22 s e o ambiente normalizou em ~1,5 min. | [demo3](docs/evidencias/2026-11-11-demo3-queda-abrupta.txt) |
| Modelo indisponível (política `invocar-haiku` removida) | 10 de 10 mensagens caíram no menu guiado sem erro HTTP; alarme `erros-atendimento` abriu em ~1,5 min com `AccessDeniedException` no log; voltou ao recolocar a política. | [demo4](docs/evidencias/2026-11-11-demo4-modelo-fora-do-ar.txt) |
| Fila indisponível (política `publicar-eventos` removida) | Reserva confirmada (`201`), evento mantido em `evento_saida` e entregue 23 s após restaurar a permissão, com o mesmo `correlation_id` (`demo5-fila-144335`). | [demo5](docs/evidencias/2026-11-11-demo5-fila-fora-do-ar.txt) |
| Failover forçado do RDS Multi-AZ | 5 leituras `503` em ~13 s (211 com `200`), recuperação automática sem reiniciar tasks, primário migrado para `us-east-2b`. | [demo6](docs/evidencias/2026-11-11-demo6-banco-failover.txt) |
| Rotação de senha do RDS (`v4`) | Rotação forçada em São Paulo deixou o banco indisponível por ~1 min durante a troca; a aplicação releu o segredo e voltou sozinha. | [ohio](docs/evidencias/2026-11-12-ohio-senha-rotacionada.txt), [sp](docs/evidencias/2026-11-12-sp-3-rotacao-da-senha.txt) |
| Guardrail contra prompt injection | 3 de 6 ataques em português barrados na guardrail e 0 de 10 frases normais bloqueadas; os outros 3 ataques foram recusados pelo modelo e pelas regras do código, sem criar reserva. | teste em 19/11 |
| Reconstrução completa em São Paulo (`destroy` + `apply`) | 77 recursos criados do zero em 15 min 52 s, imagens geradas pelo `apply`, jornada completa validada pelo `correlation_id` e 12 alarmes em `OK` (atualizado em 19/11 com a guardrail). | [sp-1](docs/evidencias/2026-11-12-sp-1-jornada.txt), [sp-2](docs/evidencias/2026-11-12-sp-2-destroy-e-apply-do-zero.txt) |

Com 3 instâncias em 2 zonas durante a carga, o rebalanceamento por zona do ECS tentou equilibrar as 16 tasks entre as zonas e deixou 1 task pendente na zona cheia sem impactar o serviço; o Capacity Provider não contabilizou essa pendência como falta de instância.

## Limites conhecidos e evoluções para produção

A arquitetura mantém alta disponibilidade automática dentro da região (2 AZs, RDS Multi-AZ, reposição de tasks e instâncias, outbox com DLQ, fallback sem IA e 12 alarmes), com compromissos assumidos para o escopo do projeto:

- Um único NAT Gateway na primeira zona reduz custo, mas cria ponto único de saída: se essa zona cair, as instâncias da segunda zona perdem acesso a Bedrock, SQS, ECR, Secrets Manager e CloudWatch. A primeira correção para produção seria manter um NAT por zona ou usar VPC Endpoints.
- Em uma indisponibilidade completa de `sa-east-1`, o Terraform recria a infraestrutura em outra região em cerca de 16 minutos, mas os backups automáticos do RDS (retenção de 7 dias) ficam na própria região. Uma estratégia completa de recuperação de desastres exigiria cópia cross-region de snapshots, `deletion_protection` e snapshot final.
- O ALB escuta em HTTP (`:80`) porque o projeto não usa domínio próprio para emissão de certificado ACM, e a interface opera com um morador fixo (`unidade 101`). Num ambiente comercial, entram domínio com HTTPS/ACM, WAF e login de moradores liberado pela administração.

## Estrutura do repositório

```
app/atendimento/    serviço síncrono (FastAPI, Bedrock, Guardrail, regras de reserva, outbox, interface web)
app/operacoes/      consumidor assíncrono do SQS (cobrança PIX, cancelamento/estorno, idempotência)
infra/terraform/    Etapa 2 em São Paulo (bootstrap/ para o bucket S3 de estado e ambiente/ para a infra)
docs/               arquitetura, inventário de Ohio, task definitions, política de escala e evidências
scripts/            build/push no ECR, alarmes de Ohio, carga no ALB e na fila, diagrama e pacote .zip
local/              simulados locais (ElasticMQ e bedrock-fake com guardrail simulada)
tests/              46 testes de integração em containers (test_fluxo.py)
```

## Regras do repositório

- Nenhum segredo ou credencial entra no Git (`.env`, chaves e estado do Terraform estão no `.gitignore`; na AWS, credenciais vêm do Secrets Manager).
- Nenhuma região ou número de conta aparece fixo no código da aplicação: região, fila, banco, modelo e guardrail chegam por variável de ambiente para o mesmo container rodar em Ohio e em São Paulo.
- Todo recurso AWS recebe a tag `projeto=cloud-projeto-final`.
