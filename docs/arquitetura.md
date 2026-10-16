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

## Decisões pendentes

| Decisão | Depende de |
|---|---|
| Domínio comercial | o grupo |
| Modelo de dados (catálogo, estoque, pedido) | domínio |
| LLM (Bedrock ou API externa) e as ferramentas | domínio + disponibilidade de modelos nas duas regiões |
| RDS Single-AZ ou Multi-AZ | custo × disponibilidade na troca de instância |
| 1 NAT Gateway ou 1 por AZ (ou VPC endpoints) | custo × disponibilidade |
| Tipo de instância e reservas de CPU/memória das tasks | medição de consumo dos containers |
