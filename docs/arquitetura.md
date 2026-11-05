# Arquitetura

## Serviços

| Serviço | Tipo | Responsabilidade | Escala por | Health check |
|---|---|---|---|---|
| `atendimento` | síncrono, atrás do ALB | conversa com o morador; chama o modelo e as ferramentas; grava a reserva na hora; serve a página de chat e o menu guiado | requisições por target / CPU | `GET :8000/health` |
| `operacoes` | assíncrono, sem tráfego de entrada | consome `ReservaSolicitada`; gera a cobrança e o aviso ao morador, idempotente | profundidade da fila (mensagens por task) | `GET :8081/health` |

**Por que dois serviços** (o enunciado pede a justificativa):

- **Carga:** o `atendimento` é limitado pela latência do modelo e escala com o número de
  conversas. O `operacoes` é limitado pelo banco e escala com o volume de eventos. São métricas
  diferentes.
- **Isolamento de falha:** se o `operacoes` cair, a reserva continua sendo feita e os eventos
  esperam na fila. Se o modelo cair, o morador continua reservando pelo menu, e a cobrança segue.
- **Evolução independente:** trocar o modelo ou o prompt não exige redeploy do `operacoes`.

## O caminho de uma reserva

```
Morador → ALB → atendimento → Bedrock (o modelo pede a ferramenta)
                    │
                    ▼
    MySQL, numa transação só: conflito + reserva + taxa + evento_saida
                    │  commit: a resposta ao morador já é verdade
                    ▼
    publicador → SQS eventos ──(3 recebimentos)──► SQS eventos-dlq
                    │
                    ▼
    operacoes, numa transação só: evento_processado + cobrança + notificação
```

- **O conflito é garantido pelo banco:** `UNIQUE (area_comum_id, data, periodo)` na tabela
  `reserva`. Duas tasks ao mesmo tempo não conseguem reservar o mesmo horário.
- **Não existe reserva sem taxa:** reserva, lançamento e evento entram na mesma transação. Se o
  processo cair no meio, nada fica gravado.
- **Quem é o morador é decisão do servidor, nunca do modelo.** As ferramentas não têm esse
  campo. Uma injeção de prompt não consegue reservar em nome de outra unidade.

## Mensageria

- Fila `eventos`, com redrive para `eventos-dlq` após **3** recebimentos.
- **Caixa de saída (`evento_saida`):** o evento nasce na transação da reserva e é publicado
  depois, logo após o commit e, se falhar, a cada 10 s. A fila fora do ar atrasa o evento, mas
  não o perde. O custo é publicar pelo menos uma vez, o que torna a duplicidade normal.
- **Repetição:** o `operacoes` só apaga a mensagem depois de processar. Em falha, ela volta
  depois do visibility timeout.
- **Duplicidade:** a tabela `evento_processado` tem `evento_id` como chave primária. A entrega
  repetida bate no `IntegrityError` e é ignorada. O registro de idempotência e o efeito do evento
  entram na **mesma transação**.
- **Não processável:** vai para a DLQ, onde fica para diagnóstico (alarme na profundidade da
  DLQ > 0).
- **Banco fora do ar não é culpa da mensagem:** o `operacoes` espera 60 s antes de tentar de novo,
  para não gastar as 3 entregas durante um failover do RDS. **Risco conhecido:** uma queda muito
  longa ainda manda eventos válidos para a DLQ. A saída é reenviá-los pelo console (redrive).

## O modelo como dependência que falha

Modelo: **Claude Haiku 5.5** no Bedrock, pela API Converse, com o ID de perfil em
`BEDROCK_MODEL_ID` (`us.anthropic.claude-haiku-5-5` em Ohio e `global.anthropic.claude-haiku-5-5`
em São Paulo, onde é o único perfil que existe).

| O que acontece | O que o morador vê |
|---|---|
| Bedrock fora, sem permissão, resposta cortada ou prazo de 45 s estourado | a mensagem fica gravada, e o menu guiado aparece, com as mesmas regras e a mesma cobrança |
| O modelo cai **depois** de a reserva ser gravada | a confirmação da reserva, montada pelo código. O menu faria o morador tentar de novo e ouvir "horário ocupado" pela própria reserva |
| Banco fora | HTTP 503 com aviso. O `/health` continua 200, para o ALB não derrubar a task |

Toda falha do modelo gera a linha de log `modelo_falhou`, com `erro_codigo`. É nela que entra o
filtro de métrica do alarme de falha da aplicação.

## Encerramento limpo

O `operacoes` trata `SIGTERM`: termina o lote atual e sai. É o que o ECS manda ao parar uma task,
inclusive quando uma instância entra em `DRAINING`. Verificado localmente com
`docker compose stop`: saída com código 0.

## Observabilidade

Logs em JSON, uma linha por evento, com `servico` e `correlation_id`. O `atendimento` aceita
`X-Correlation-Id` (ou gera um), devolve no cabeçalho da resposta, grava junto do evento e propaga
como atributo da mensagem SQS. O `operacoes` loga com o mesmo id. No CloudWatch Logs Insights,
filtrar por `correlation_id` mostra a jornada inteira de uma reserva. O texto das mensagens não vai
para o log, porque é dado do morador. Cada chamada ao modelo registra tokens e latência.

## Decisões tomadas

| Decisão | Valor | Por quê |
|---|---|---|
| Domínio | atendente de condomínio: reserva, OS, visitante, encomenda, cota | proposta do grupo (22/10) |
| LLM | Amazon Bedrock | o grupo (22/10); fica dentro da AWS e a permissão é uma IAM role, sem chave externa |
| Modelo | **Claude Haiku 5.5** | a Amazon não tem modelo de conversa em São Paulo, e o Haiku 5.5 existe nas duas regiões, com `tool use`. Testado no Playground das duas em 05/11 |
| Primeira versão | só `consultar_disponibilidade` e `criar_reserva`, com morador fixo. **Login fica para depois** (decisão do autor, 05/11) | é o mínimo que a rubrica pede (uma consulta real + uma operação registrada), para pôr a infraestrutura à prova antes |
| Login | só morador, liberado por um admin que verifica. Visitante não tem login | o grupo (22/10) |
| Aprovação | a IA aprova, como portaria digital, seguindo regras do sistema (conflito, limite de 3 reservas futuras por unidade) | o grupo (22/10) |
| Reserva | **síncrona**, gravada pelo `atendimento`: o `operacoes` não tem load balancer, e o morador precisa da resposta na hora. Só o que vem depois vai para a fila | custo: sem banco não há reserva, mas a conversa segue de pé |
| Histórico da conversa | no **RDS**, não no DynamoDB da proposta original | o enunciado aceita os dois; evita mais um recurso e mais uma permissão perto do prazo |
| Tabelas | criadas pelo próprio serviço ao subir, de forma idempotente | o RDS não tem acesso público, então não há de onde rodar um script de fora da VPC |
| Rede das tasks | modo `bridge`, porta dinâmica no host, ALB com target tipo `instance` | menos peças que `awsvpc` (sem limite de ENI por instância); custo: um SG só para todas as tasks da instância |
| NAT | 1 NAT Gateway, em `us-east-2a` | custo. Risco conhecido: se `us-east-2a` cair, a sub-rede privada de `us-east-2b` perde a saída, e com ela o Bedrock e a fila |
| Publicar imagem na etapa 1 | **build e push pelo CloudShell**, o terminal dentro do console | o enunciado permite "console e AWS CLI" na etapa 1; o CloudShell fica dentro do console, já autenticado na conta, sem chave no PC. Decisão do grupo, sem consulta ao professor (30/10) |
| Instância do ECS | **t3 (x86)**, tamanho `t3.small` (2 vCPU, 2 GiB) | o CloudShell gera imagem x86, e t4g (ARM) não roda essa imagem. 2 GiB cabem os dois serviços + o agente do ECS e ainda deixam a escala de tasks visível antes de precisar de outra instância |
| Roles da aplicação | **uma por serviço** (`app-atendimento`, `app-operacoes`) | menor privilégio: quem publica não consome, e só o `atendimento` chama o Bedrock |

## Riscos conhecidos

| Risco | Efeito | O que fazer |
|---|---|---|
| **O RDS rotaciona a senha** do segredo, e o ECS só a injeta quando a task sobe | depois da rotação, as tasks antigas perdem o acesso ao banco até serem recriadas | o agendamento e o comportamento real não foram conferidos. Se acontecer: forçar uma nova implantação do serviço |
| **A política `invocar-haiku` e a chamada ao Bedrock real** nunca rodaram de dentro de uma task | pode dar `AccessDenied`. O sintoma é o menu guiado, com `modelo_falhou` no log | é a primeira coisa a conferir no primeiro deploy |
| **TLS até o RDS** não é testável localmente | a conexão pode falhar na AWS. O certificado foi conferido, e a conexão real não | conferir no primeiro deploy, pelo log `banco pronto` |

## Decisões pendentes

| Decisão | Depende de |
|---|---|
| RDS Single-AZ ou Multi-AZ | custo × disponibilidade na troca de instância |
| Reservas de CPU/memória das tasks | medição de consumo dos containers (a instância já é `t3.small`) |
| `output_config.effort` do modelo | medir a latência real. O padrão do Haiku 5.5 é `medium`, e `low` pode bastar para o chat |
| Política de IAM do perfil `global.` em São Paulo | etapa 2, no Terraform |
