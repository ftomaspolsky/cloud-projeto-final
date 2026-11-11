# Alarmes da etapa 1 (Ohio), criados pela AWS CLI no CloudShell em 06/11.
# Pré-requisito: o tópico SNS cloud-projeto-final-alertas (create-topic é idempotente: devolve
# o mesmo ARN se ele já existe). Cada alarme avisa o tópico ao entrar em ALARM e ao voltar a OK.

R=us-east-2
C=cloud-projeto-final-cluster
ALB=app/cloud-projeto-final-alb/c2125044ee8b4027
TG=targetgroup/cloud-projeto-final-tg-atend/047a50b2315fd4bc
T=$(aws sns create-topic --region $R --name cloud-projeto-final-alertas --query TopicArn --output text)

# alarme NOME "DESCRICAO" NAMESPACE METRICA ESTATISTICA PERIODO AVALIACOES OPERADOR LIMITE DADO_FALTANDO DIMENSOES...
alarme() {
  local nome=$1 desc=$2 ns=$3 met=$4 est=$5 per=$6 aval=$7 op=$8 lim=$9 falt=${10}; shift 10
  aws cloudwatch put-metric-alarm --region $R --alarm-name "cloud-projeto-final-$nome" \
    --alarm-description "$desc" --namespace "$ns" --metric-name "$met" --statistic "$est" \
    --period "$per" --evaluation-periods "$aval" --comparison-operator "$op" --threshold "$lim" \
    --treat-missing-data "$falt" --dimensions "$@" --alarm-actions "$T" --ok-actions "$T" \
    --tags Key=projeto,Value=cloud-projeto-final \
  && echo "criado: $nome"
}

# Saúde das tasks
alarme atendimento-abaixo-do-minimo "Menos de 2 tasks do atendimento rodando por 2 min" \
  ECS/ContainerInsights RunningTaskCount Minimum 60 2 LessThanThreshold 2 breaching \
  Name=ClusterName,Value=$C Name=ServiceName,Value=atendimento
alarme operacoes-sem-task "Nenhuma task do operacoes rodando por 2 min" \
  ECS/ContainerInsights RunningTaskCount Minimum 60 2 LessThanThreshold 1 breaching \
  Name=ClusterName,Value=$C Name=ServiceName,Value=operacoes

# Uso do cluster
alarme cluster-cpu-alta "CPU media do cluster acima de 80% por 10 min" \
  AWS/ECS CPUUtilization Average 300 2 GreaterThanThreshold 80 notBreaching \
  Name=ClusterName,Value=$C

# Capacidade do ASG
alarme tasks-sem-instancia "Tasks esperando instancia por 10 min (ASG no maximo ou sem subir)" \
  AWS/ECS/ManagedScaling CapacityProviderReservation Maximum 300 2 GreaterThanThreshold 100 notBreaching \
  Name=CapacityProviderName,Value=cloud-projeto-final-cp Name=ClusterName,Value=$C
alarme asg-abaixo-do-minimo "Menos de 2 instancias em servico no ASG por 3 min" \
  AWS/AutoScaling GroupInServiceInstances Minimum 60 3 LessThanThreshold 2 breaching \
  Name=AutoScalingGroupName,Value=cloud-projeto-final-asg

# Respostas do ALB
alarme alb-5xx "ALB respondendo 5xx (sem task saudavel) mais de 5 vezes por minuto" \
  AWS/ApplicationELB HTTPCode_ELB_5XX_Count Sum 60 2 GreaterThanThreshold 5 notBreaching \
  Name=LoadBalancer,Value=$ALB
alarme app-5xx "Aplicacao respondendo 5xx mais de 5 vezes por minuto" \
  AWS/ApplicationELB HTTPCode_Target_5XX_Count Sum 60 2 GreaterThanThreshold 5 notBreaching \
  Name=LoadBalancer,Value=$ALB Name=TargetGroup,Value=$TG
alarme alb-task-nao-saudavel "Alguma task do atendimento reprovada no health check por 2 min" \
  AWS/ApplicationELB UnHealthyHostCount Maximum 60 2 GreaterThanThreshold 0 notBreaching \
  Name=LoadBalancer,Value=$ALB Name=TargetGroup,Value=$TG

# Profundidade da fila
alarme fila-mensagem-velha "Mensagem esperando na fila ha mais de 5 min" \
  AWS/SQS ApproximateAgeOfOldestMessage Maximum 300 1 GreaterThanThreshold 300 notBreaching \
  Name=QueueName,Value=cloud-projeto-final-eventos
alarme dlq-com-mensagem "Mensagem nao processavel na DLQ" \
  AWS/SQS ApproximateNumberOfMessagesVisible Maximum 300 1 GreaterThanThreshold 0 notBreaching \
  Name=QueueName,Value=cloud-projeto-final-eventos-dlq

# Falhas da aplicação: os dois serviços logam JSON com "nivel". O filtro conta as linhas ERROR.
# Uma métrica por serviço, sem dimensão: o CloudWatch não aceita defaultValue junto com dimensão,
# e sem o defaultValue=0 a métrica some nos minutos sem erro.
for s in atendimento operacoes; do
  aws logs put-metric-filter --region $R --log-group-name /ecs/cloud-projeto-final/$s \
    --filter-name erros-$s --filter-pattern '{ $.nivel = "ERROR" }' \
    --metric-transformations metricName=Erros-$s,metricNamespace=cloud-projeto-final,metricValue=1,defaultValue=0 \
  && echo "filtro: erros-$s"
  aws cloudwatch put-metric-alarm --region $R --alarm-name "cloud-projeto-final-erros-$s" \
    --alarm-description "Mais de 5 linhas ERROR no log do $s em 5 min" \
    --namespace cloud-projeto-final --metric-name Erros-$s --statistic Sum --period 300 \
    --evaluation-periods 1 --comparison-operator GreaterThanThreshold --threshold 5 \
    --treat-missing-data notBreaching --alarm-actions "$T" --ok-actions "$T" \
    --tags Key=projeto,Value=cloud-projeto-final \
  && echo "criado: erros-$s"
done
