# Observabilidade: os 12 alarmes e os 2 filtros de scripts/alarmes.sh (linhas 35 a 37 de
# docs/recursos-ohio.md), agora em código. Cada alarme avisa o tópico ao entrar em ALARM
# e ao voltar a OK.

resource "aws_sns_topic" "alertas" {
  name = "${var.projeto}-alertas"
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.email_alertas == "" ? 0 : 1
  topic_arn = aws_sns_topic.alertas.arn
  protocol  = "email"
  endpoint  = var.email_alertas
}

locals {
  cluster = aws_ecs_cluster.principal.name
  alb     = aws_lb.principal.arn_suffix
  tg      = aws_lb_target_group.atendimento.arn_suffix

  alarmes = {
    atendimento-abaixo-do-minimo = {
      desc = "Menos de 2 tasks do atendimento rodando por 2 min", ns = "ECS/ContainerInsights",
      met  = "RunningTaskCount", est = "Minimum", per = 60, aval = 2, op = "LessThanThreshold", lim = 2,
      falt = "breaching", dim = { ClusterName = local.cluster, ServiceName = "atendimento" }
    }
    operacoes-sem-task = {
      desc = "Nenhuma task do operacoes rodando por 2 min", ns = "ECS/ContainerInsights",
      met  = "RunningTaskCount", est = "Minimum", per = 60, aval = 2, op = "LessThanThreshold", lim = 1,
      falt = "breaching", dim = { ClusterName = local.cluster, ServiceName = "operacoes" }
    }
    cluster-cpu-alta = {
      desc = "CPU media do cluster acima de 80% por 10 min", ns = "AWS/ECS",
      met  = "CPUUtilization", est = "Average", per = 300, aval = 2, op = "GreaterThanThreshold", lim = 80,
      falt = "notBreaching", dim = { ClusterName = local.cluster }
    }
    tasks-sem-instancia = {
      desc = "Tasks esperando instancia por 10 min (ASG no maximo ou sem subir)", ns = "AWS/ECS/ManagedScaling",
      met  = "CapacityProviderReservation", est = "Maximum", per = 300, aval = 2, op = "GreaterThanThreshold", lim = 100,
      falt = "notBreaching", dim = { CapacityProviderName = aws_ecs_capacity_provider.ecs.name, ClusterName = local.cluster }
    }
    asg-abaixo-do-minimo = {
      desc = "Menos de 2 instancias em servico no ASG por 3 min", ns = "AWS/AutoScaling",
      met  = "GroupInServiceInstances", est = "Minimum", per = 60, aval = 3, op = "LessThanThreshold", lim = 2,
      falt = "breaching", dim = { AutoScalingGroupName = aws_autoscaling_group.ecs.name }
    }
    alb-5xx = {
      desc = "ALB respondendo 5xx (sem task saudavel) mais de 5 vezes por minuto", ns = "AWS/ApplicationELB",
      met  = "HTTPCode_ELB_5XX_Count", est = "Sum", per = 60, aval = 2, op = "GreaterThanThreshold", lim = 5,
      falt = "notBreaching", dim = { LoadBalancer = local.alb }
    }
    app-5xx = {
      desc = "Aplicacao respondendo 5xx mais de 5 vezes por minuto", ns = "AWS/ApplicationELB",
      met  = "HTTPCode_Target_5XX_Count", est = "Sum", per = 60, aval = 2, op = "GreaterThanThreshold", lim = 5,
      falt = "notBreaching", dim = { LoadBalancer = local.alb, TargetGroup = local.tg }
    }
    alb-task-nao-saudavel = {
      desc = "Alguma task do atendimento reprovada no health check por 2 min", ns = "AWS/ApplicationELB",
      met  = "UnHealthyHostCount", est = "Maximum", per = 60, aval = 2, op = "GreaterThanThreshold", lim = 0,
      falt = "notBreaching", dim = { LoadBalancer = local.alb, TargetGroup = local.tg }
    }
    fila-mensagem-velha = {
      desc = "Mensagem esperando na fila ha mais de 5 min", ns = "AWS/SQS",
      met  = "ApproximateAgeOfOldestMessage", est = "Maximum", per = 300, aval = 1, op = "GreaterThanThreshold", lim = 300,
      falt = "notBreaching", dim = { QueueName = aws_sqs_queue.eventos.name }
    }
    dlq-com-mensagem = {
      desc = "Mensagem nao processavel na DLQ", ns = "AWS/SQS",
      met  = "ApproximateNumberOfMessagesVisible", est = "Maximum", per = 300, aval = 1, op = "GreaterThanThreshold", lim = 0,
      falt = "notBreaching", dim = { QueueName = aws_sqs_queue.dlq.name }
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "infra" {
  for_each            = local.alarmes
  alarm_name          = "${var.projeto}-${each.key}"
  alarm_description   = each.value.desc
  namespace           = each.value.ns
  metric_name         = each.value.met
  statistic           = each.value.est
  period              = each.value.per
  evaluation_periods  = each.value.aval
  comparison_operator = each.value.op
  threshold           = each.value.lim
  treat_missing_data  = each.value.falt
  dimensions          = each.value.dim
  alarm_actions       = [aws_sns_topic.alertas.arn]
  ok_actions          = [aws_sns_topic.alertas.arn]
}

# Falhas da aplicação: os dois serviços logam JSON com "nivel". O filtro conta as linhas ERROR.
# Métrica sem dimensão, porque o CloudWatch não aceita valor padrão junto com dimensão, e sem
# o 0 padrão a métrica some nos minutos sem erro.
resource "aws_cloudwatch_log_metric_filter" "erros" {
  for_each       = toset(local.servicos)
  name           = "erros-${each.key}"
  log_group_name = aws_cloudwatch_log_group.servico[each.key].name
  pattern        = "{ $.nivel = \"ERROR\" }"

  metric_transformation {
    name          = "Erros-${each.key}"
    namespace     = var.projeto
    value         = "1"
    default_value = "0"
  }
}

resource "aws_cloudwatch_metric_alarm" "erros" {
  for_each            = toset(local.servicos)
  alarm_name          = "${var.projeto}-erros-${each.key}"
  alarm_description   = "Mais de 5 linhas ERROR no log do ${each.key} em 5 min"
  namespace           = var.projeto
  metric_name         = "Erros-${each.key}"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 5
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alertas.arn]
  ok_actions          = [aws_sns_topic.alertas.arn]

  depends_on = [aws_cloudwatch_log_metric_filter.erros]
}
