# Computação: linhas 21 a 32 de docs/recursos-ohio.md.
# Logs, cluster, Launch Template, ASG, Capacity Provider, ALB e os dois serviços.

resource "aws_cloudwatch_log_group" "servico" {
  for_each          = toset(local.servicos)
  name              = "/ecs/${var.projeto}/${each.key}"
  retention_in_days = 14
}

# O Container Insights cria este grupo sozinho, sem prazo de validade, e ele sobrava depois do
# destroy (visto em 12/11). Criado aqui antes do cluster, nasce com 14 dias e sai junto.
resource "aws_cloudwatch_log_group" "container_insights" {
  name              = "/aws/ecs/containerinsights/${var.projeto}-cluster/performance"
  retention_in_days = 14
}

resource "aws_ecs_cluster" "principal" {
  name = "${var.projeto}-cluster"
  setting {
    name  = "containerInsights"
    value = "enabled" # dá a contagem de tasks usada no alarme e na escala do operacoes
  }
  depends_on = [aws_cloudwatch_log_group.container_insights]
}

# ------------------------------------------------------------ instâncias
# A AMI otimizada para ECS vem do parâmetro público da própria região. Um "ami-..." escrito
# aqui só valeria numa região.
data "aws_ssm_parameter" "ami_ecs" {
  name = "/aws/service/ecs/optimized-ami/amazon-linux-2023/recommended/image_id"
}

resource "aws_launch_template" "ecs" {
  name                   = "${var.projeto}-lt"
  image_id               = nonsensitive(data.aws_ssm_parameter.ami_ecs.value)
  instance_type          = "t3.small"
  vpc_security_group_ids = [aws_security_group.ecs.id]

  iam_instance_profile {
    arn = aws_iam_instance_profile.ec2.arn
  }

  # Só IMDSv2, hop limit 1: um container em modo bridge não alcança a credencial da instância.
  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  # Diz ao agente do ECS em qual cluster se registrar.
  user_data = base64encode("#!/bin/bash\necho ECS_CLUSTER=${aws_ecs_cluster.principal.name} >> /etc/ecs/ecs.config\n")

  tag_specifications {
    resource_type = "instance"
    tags          = { Name = "${var.projeto}-ecs-node", projeto = var.projeto, etapa = "2" }
  }
  tag_specifications {
    resource_type = "volume"
    tags          = { projeto = var.projeto, etapa = "2" }
  }
}

resource "aws_autoscaling_group" "ecs" {
  name                = "${var.projeto}-asg"
  vpc_zone_identifier = aws_subnet.privada[*].id
  min_size            = 2 # uma por zona
  max_size            = 4
  desired_capacity    = 2

  launch_template {
    id      = aws_launch_template.ecs.id
    version = aws_launch_template.ecs.latest_version
  }

  health_check_type         = "EC2"
  health_check_grace_period = 300
  protect_from_scale_in     = true # quem decide qual instância sai é o ECS, depois de esvaziá-la
  force_delete              = true # o destroy encerra as instâncias mesmo protegidas
  enabled_metrics           = ["GroupInServiceInstances", "GroupDesiredCapacity", "GroupMinSize", "GroupMaxSize"]

  instance_maintenance_policy {
    min_healthy_percentage = 100 # sobe a substituta antes de tirar a antiga
    max_healthy_percentage = 150
  }

  # O Capacity Provider exige esta tag e mexe na capacidade desejada: o Terraform não briga com ele.
  tag {
    key                 = "AmazonECSManaged"
    value               = "true"
    propagate_at_launch = true
  }
  tag {
    key                 = "projeto"
    value               = var.projeto
    propagate_at_launch = true
  }

  lifecycle {
    ignore_changes = [desired_capacity]
  }

  # As instâncias só podem existir com as permissões da role. Sem isto, o destroy tirava as
  # políticas antes de encerrar as instâncias: o agente do ECS perdia a conexão, as tasks
  # ficavam em STOPPING e os serviços presos em DRAINING até o tempo limite (visto em 12/11).
  # Pelo mesmo motivo, a saída pelo NAT tem que durar mais que elas: em 12/11 o NAT saiu no 1º
  # minuto do destroy, e o agente ficou sem alcançar o endpoint do ECS.
  depends_on = [
    aws_iam_role_policy_attachment.ec2_ecs, aws_iam_role_policy_attachment.ec2_ssm,
    aws_route_table_association.privada,
  ]
}

resource "aws_ecs_capacity_provider" "ecs" {
  name = "${var.projeto}-cp"
  auto_scaling_group_provider {
    auto_scaling_group_arn         = aws_autoscaling_group.ecs.arn
    managed_termination_protection = "ENABLED" # não encerra instância com task rodando
    managed_draining               = "ENABLED" # esvazia a instância antes de ela sair

    managed_scaling {
      status          = "ENABLED"
      target_capacity = 100 # sobe instância só quando falta lugar para task, sem sobra ociosa
    }
  }
}

resource "aws_ecs_cluster_capacity_providers" "principal" {
  cluster_name       = aws_ecs_cluster.principal.name
  capacity_providers = [aws_ecs_capacity_provider.ecs.name]
  default_capacity_provider_strategy {
    capacity_provider = aws_ecs_capacity_provider.ecs.name
    weight            = 1
  }
}

# ------------------------------------------------------------ balanceador
resource "aws_lb" "principal" {
  name               = "${var.projeto}-alb"
  load_balancer_type = "application"
  internal           = false
  subnets            = aws_subnet.publica[*].id
  security_groups    = [aws_security_group.alb.id]

  # ALB voltado para a internet precisa do internet gateway; e no destroy, os IPs públicos do
  # ALB impedem desligar o gateway, então o ALB sai antes.
  depends_on = [aws_internet_gateway.principal, aws_route_table_association.publica]
}

# Tipo instância: no modo bridge, o ECS registra instância + porta dinâmica de cada task.
resource "aws_lb_target_group" "atendimento" {
  name                 = "${var.projeto}-tg-atend"
  port                 = 80
  protocol             = "HTTP"
  target_type          = "instance"
  vpc_id               = aws_vpc.principal.id
  deregistration_delay = 30 # task saindo termina as requisições em 30 s (o padrão é 300)

  health_check {
    path                = "/health"
    healthy_threshold   = 2
    unhealthy_threshold = 2
    timeout             = 5
    interval            = 10 # task doente sai em ~20 s
    matcher             = "200"
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.principal.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.atendimento.arn
  }
}

# ------------------------------------------------------------ tasks
locals {
  segredo_db = aws_db_instance.principal.master_user_secret[0].secret_arn

  ambiente_comum = [
    { name = "AWS_REGION", value = var.regiao },
    { name = "QUEUE_NAME", value = aws_sqs_queue.eventos.name },
    { name = "DB_HOST", value = aws_db_instance.principal.address },
    { name = "DB_NAME", value = aws_db_instance.principal.db_name },
    { name = "DB_SSL_CA", value = "/app/rds-ca.pem" },
    { name = "DB_SECRET_ARN", value = local.segredo_db }, # para reler a senha depois da rotação
  ]

  segredos_db = [
    { name = "DB_USER", valueFrom = "${local.segredo_db}:username::" },
    { name = "DB_PASSWORD", valueFrom = "${local.segredo_db}:password::" },
  ]

  logs = {
    for s in local.servicos : s => {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.servico[s].name
        "awslogs-region"        = var.regiao
        "awslogs-stream-prefix" = s
      }
    }
  }
}

resource "aws_ecs_task_definition" "atendimento" {
  family                   = "${var.projeto}-atendimento"
  requires_compatibilities = ["EC2"]
  network_mode             = "bridge"
  execution_role_arn       = aws_iam_role.execucao.arn
  task_role_arn            = aws_iam_role.app_atendimento.arn

  container_definitions = jsonencode([{
    name              = "atendimento"
    image             = local.imagem["atendimento"]
    essential         = true
    cpu               = 256
    memoryReservation = 256 # medido em Ohio: 59 MiB em repouso
    memory            = 512
    portMappings      = [{ containerPort = 8000, hostPort = 0, protocol = "tcp" }] # 0 = porta dinâmica
    environment = concat(local.ambiente_comum, [
      { name = "BEDROCK_MODEL_ID", value = var.perfil_do_modelo },
      { name = "GUARDRAIL_ID", value = aws_bedrock_guardrail.prompt.guardrail_id },
      { name = "GUARDRAIL_VERSION", value = aws_bedrock_guardrail_version.prompt.version },
      { name = "GUARDRAIL_REGION", value = var.regiao_da_guardrail },
    ])
    secrets          = local.segredos_db
    logConfiguration = local.logs["atendimento"]
  }])

  depends_on = [terraform_data.imagem]
}

resource "aws_ecs_task_definition" "operacoes" {
  family                   = "${var.projeto}-operacoes"
  requires_compatibilities = ["EC2"]
  network_mode             = "bridge"
  execution_role_arn       = aws_iam_role.execucao.arn
  task_role_arn            = aws_iam_role.app_operacoes.arn

  container_definitions = jsonencode([{
    name              = "operacoes"
    image             = local.imagem["operacoes"]
    essential         = true
    cpu               = 128
    memoryReservation = 128 # medido em Ohio: 40 MiB em repouso
    memory            = 256
    environment       = local.ambiente_comum
    secrets           = local.segredos_db
    healthCheck = {
      command     = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8081/health')\""]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 30
    }
    logConfiguration = local.logs["operacoes"]
  }])

  depends_on = [terraform_data.imagem]
}

# ------------------------------------------------------------ serviços
resource "aws_ecs_service" "atendimento" {
  name                              = "atendimento"
  cluster                           = aws_ecs_cluster.principal.id
  task_definition                   = aws_ecs_task_definition.atendimento.arn
  desired_count                     = 2
  health_check_grace_period_seconds = 60
  propagate_tags                    = "SERVICE"

  capacity_provider_strategy {
    capacity_provider = aws_ecs_capacity_provider.ecs.name
    weight            = 1
  }

  # Uma task por zona primeiro; dentro da zona, encher a instância antes de abrir outra.
  ordered_placement_strategy {
    type  = "spread"
    field = "attribute:ecs.availability-zone"
  }
  ordered_placement_strategy {
    type  = "binpack"
    field = "memory"
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.atendimento.arn
    container_name   = "atendimento"
    container_port   = 8000
  }

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  lifecycle {
    ignore_changes = [desired_count] # quem mexe é a escala automática
  }

  depends_on = [
    aws_lb_listener.http, aws_ecs_cluster_capacity_providers.principal,
    # Permissões das tasks: só saem depois que o serviço parou (ver o depends_on do ASG).
    aws_iam_role_policy_attachment.execucao_padrao, aws_iam_role_policy.execucao_segredo,
    aws_iam_role_policy.atendimento_fila, aws_iam_role_policy.atendimento_modelo, aws_iam_role_policy.operacoes_fila,
    aws_iam_role_policy.app_le_segredo,
  ]
}

resource "aws_ecs_service" "operacoes" {
  name            = "operacoes"
  cluster         = aws_ecs_cluster.principal.id
  task_definition = aws_ecs_task_definition.operacoes.arn
  desired_count   = 1
  propagate_tags  = "SERVICE"

  capacity_provider_strategy {
    capacity_provider = aws_ecs_capacity_provider.ecs.name
    weight            = 1
  }

  ordered_placement_strategy {
    type  = "spread"
    field = "attribute:ecs.availability-zone"
  }
  ordered_placement_strategy {
    type  = "binpack"
    field = "memory"
  }

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  lifecycle {
    ignore_changes = [desired_count]
  }

  depends_on = [
    aws_ecs_cluster_capacity_providers.principal,
    # Permissões das tasks: só saem depois que o serviço parou (ver o depends_on do ASG).
    aws_iam_role_policy_attachment.execucao_padrao, aws_iam_role_policy.execucao_segredo,
    aws_iam_role_policy.atendimento_fila, aws_iam_role_policy.atendimento_modelo, aws_iam_role_policy.operacoes_fila,
    aws_iam_role_policy.app_le_segredo,
  ]
}
