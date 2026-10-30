# Arquitetura

## Serviços

| Serviço | Tipo | Responsabilidade | Escala por | Health check |
|---|---|---|---|---|
| `chat-service` | síncrono, atrás do ALB | conversa com o cliente; chama o LLM e as ferramentas (catálogo, criar pedido) | requisições por target / CPU | `GET :8000/health` |
| `order-worker` | assíncrono, sem tráfego de entrada | consome `pedidos`; grava o pedido em transação, idempotente | profundidade da fila (mensagens por task) | `GET :8081/health` |

**Por que dois serviços** (o enunciado pede a justificativa):

- **Carga:** o chat é limitado pela latência do LLM e escala com o número de conversas. O
  worker é limitado pelo banco e escala com o volume de pedidos. São métricas diferentes.
- **Isolamento de falha:** se o LLM cair, os pedidos já enfileirados continuam sendo
  gravados. Se o banco engasgar, o chat continua respondendo e os pedidos esperam na fila.
- **Evolução independente:** trocar o modelo ou o prompt não exige redeploy do worker.

## Mensageria

- Fila `pedidos`, com redrive para `pedidos-dlq` após **3** recebimentos.
- **Repetição:** o worker só apaga a mensagem depois de processar. Em falha, ela volta depois
  do visibility timeout.
- **Duplicidade:** a tabela `pedidos_processados` tem `pedido_id` como chave primária. A
  entrega repetida bate no `IntegrityError` e é ignorada. O registro de idempotência e o
  efeito do pedido entram na **mesma transação**.
- **Não processável:** vai para a DLQ, onde fica para diagnóstico (alarme na profundidade da
  DLQ > 0).

## Encerramento limpo

O worker trata `SIGTERM`: termina a mensagem atual e sai. É o que o ECS manda ao parar uma
task, inclusive quando uma instância entra em `DRAINING`. Verificado localmente com
`docker compose stop`.

## Observabilidade

Logs em JSON, uma linha por evento, com `servico` e `correlation_id`. O `chat-service`
aceita `X-Correlation-Id` (ou gera um), devolve no cabeçalho da resposta e propaga como
atributo da mensagem SQS. O worker loga com o mesmo id. No CloudWatch Logs Insights, filtrar
por `correlation_id` mostra a jornada inteira de um pedido.

## Decisões tomadas

| Decisão | Valor | Por quê |
|---|---|---|
| Domínio | atendente de condomínio: reserva, OS, visitante, encomenda, cota | proposta do grupo (22/10) |
| LLM | Amazon Bedrock | o grupo (22/10); fica dentro da AWS e a permissão é uma IAM role, sem chave externa |
| Login | só morador, liberado por um admin que verifica. Visitante não tem login | o grupo (22/10) |
| Aprovação | a IA aprova, como portaria digital, seguindo regras do sistema (conflito, limite por unidade) | o grupo (22/10) |
| Reserva | **síncrona**: checar conflito e gravar reserva + lançamento numa transação no RDS. Só o que vem depois vai para a fila | o morador precisa da resposta na hora; e não existe reserva sem cobrança |
| Rede das tasks | modo `bridge`, porta dinâmica no host, ALB com target tipo `instance` | menos peças que `awsvpc` (sem limite de ENI por instância); custo: um SG só para todas as tasks da instância |
| NAT | 1 NAT Gateway, em `us-east-2a` | custo. Risco conhecido: se `us-east-2a` cair, a sub-rede privada de `us-east-2b` perde a saída |
| Publicar imagem na etapa 1 | **build e push pelo CloudShell**, o terminal dentro do console | o enunciado permite "console e AWS CLI" na etapa 1; o CloudShell fica dentro do console, já autenticado na conta, sem chave no PC. Decisão do grupo, sem consulta ao professor (30/10) |
| Instância do ECS | **t3 (x86)**, tamanho `t3.small` (2 vCPU, 2 GiB) | o CloudShell gera imagem x86, e t4g (ARM) não roda essa imagem. 2 GiB cabem os dois serviços + o agente do ECS e ainda deixam a escala de tasks visível antes de precisar de outra instância |
| Roles da aplicação | **uma por serviço** (`app-atendimento`, `app-operacoes`) | menor privilégio: quem publica não consome, e só o `atendimento` vai chamar o Bedrock |

## Decisões pendentes

| Decisão | Depende de |
|---|---|
| Modelo do Bedrock | disponibilidade em `us-east-2` e `sa-east-1` |
| RDS Single-AZ ou Multi-AZ | custo × disponibilidade na troca de instância |
| Reservas de CPU/memória das tasks | medição de consumo dos containers (a instância já é `t3.small`) |
