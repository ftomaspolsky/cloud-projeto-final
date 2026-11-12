# Escala das tasks: linhas 33 e 34 de docs/recursos-ohio.md.
# A escala das instâncias é o Capacity Provider (computacao.tf).

# atendimento: 2 a 16 tasks, alvo de 100 requisições por task por minuto, vindas do ALB.
resource "aws_appautoscaling_target" "atendimento" {
  service_namespace  = "ecs"
  scalable_dimension = "ecs:service:DesiredCount"
  resource_id        = "service/${aws_ecs_cluster.principal.name}/${aws_ecs_service.atendimento.name}"
  min_capacity       = 2
  max_capacity       = 16
}

resource "aws_appautoscaling_policy" "atendimento" {
  name               = "atendimento-requisicoes-por-task"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = aws_appautoscaling_target.atendimento.service_namespace
  scalable_dimension = aws_appautoscaling_target.atendimento.scalable_dimension
  resource_id        = aws_appautoscaling_target.atendimento.resource_id

  target_tracking_scaling_policy_configuration {
    target_value       = 100
    scale_out_cooldown = 60  # sobe rápido
    scale_in_cooldown  = 300 # desce devagar
    predefined_metric_specification {
      predefined_metric_type = "ALBRequestCountPerTarget"
      resource_label         = "${aws_lb.principal.arn_suffix}/${aws_lb_target_group.atendimento.arn_suffix}"
    }
  }
}

# operacoes: 1 a 4 tasks, alvo de 100 mensagens visíveis na fila por task rodando.
resource "aws_appautoscaling_target" "operacoes" {
  service_namespace  = "ecs"
  scalable_dimension = "ecs:service:DesiredCount"
  resource_id        = "service/${aws_ecs_cluster.principal.name}/${aws_ecs_service.operacoes.name}"
  min_capacity       = 1
  max_capacity       = 4
}

resource "aws_appautoscaling_policy" "operacoes" {
  name               = "operacoes-fila-por-task"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = aws_appautoscaling_target.operacoes.service_namespace
  scalable_dimension = aws_appautoscaling_target.operacoes.scalable_dimension
  resource_id        = aws_appautoscaling_target.operacoes.resource_id

  target_tracking_scaling_policy_configuration {
    target_value       = 100
    scale_out_cooldown = 60
    scale_in_cooldown  = 300

    # Uma conta de métricas: mensagens visíveis ÷ tasks rodando.
    customized_metric_specification {
      metrics {
        id          = "fila"
        return_data = false
        metric_stat {
          stat = "Sum"
          metric {
            namespace   = "AWS/SQS"
            metric_name = "ApproximateNumberOfMessagesVisible"
            dimensions {
              name  = "QueueName"
              value = aws_sqs_queue.eventos.name
            }
          }
        }
      }
      metrics {
        id          = "tasks"
        return_data = false
        metric_stat {
          stat = "Average"
          metric {
            namespace   = "ECS/ContainerInsights"
            metric_name = "RunningTaskCount"
            dimensions {
              name  = "ClusterName"
              value = aws_ecs_cluster.principal.name
            }
            dimensions {
              name  = "ServiceName"
              value = aws_ecs_service.operacoes.name
            }
          }
        }
      }
      metrics {
        id          = "porTask"
        expression  = "fila / tasks"
        label       = "mensagens na fila por task"
        return_data = true
      }
    }
  }
}
