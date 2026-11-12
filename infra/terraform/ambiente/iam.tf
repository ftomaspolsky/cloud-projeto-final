# As 4 roles de Ohio (linhas 17 a 20 de docs/recursos-ohio.md).
# IAM é GLOBAL: os nomes de Ohio já existem na conta, então aqui o nome leva a região.

locals {
  prefixo_iam = "${var.projeto}-${var.regiao}"
}

data "aws_iam_policy_document" "confia_ec2" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "confia_ecs_tasks" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# ------------------------------------------------ 1. instância: registrar no cluster e puxar imagem
resource "aws_iam_role" "ec2" {
  name               = "${local.prefixo_iam}-ec2"
  assume_role_policy = data.aws_iam_policy_document.confia_ec2.json
}

resource "aws_iam_role_policy_attachment" "ec2_ecs" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEC2ContainerServiceforEC2Role"
}

# Entrar na instância pelo Session Manager, já que não há SSH nem IP público.
resource "aws_iam_role_policy_attachment" "ec2_ssm" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "ec2" {
  name = "${local.prefixo_iam}-ec2"
  role = aws_iam_role.ec2.name
}

# ------------------------------------------------ 2. execução: o ECS, antes de o container subir
resource "aws_iam_role" "execucao" {
  name               = "${local.prefixo_iam}-execucao"
  assume_role_policy = data.aws_iam_policy_document.confia_ecs_tasks.json
}

resource "aws_iam_role_policy_attachment" "execucao_padrao" {
  role       = aws_iam_role.execucao.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Ler a senha do banco, e só ela.
resource "aws_iam_role_policy" "execucao_segredo" {
  name = "ler-segredo-rds"
  role = aws_iam_role.execucao.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "secretsmanager:GetSecretValue"
      Resource = aws_db_instance.principal.master_user_secret[0].secret_arn
    }]
  })
}

# ------------------------------------------------ 3. aplicação do atendimento
resource "aws_iam_role" "app_atendimento" {
  name               = "${local.prefixo_iam}-app-atendimento"
  assume_role_policy = data.aws_iam_policy_document.confia_ecs_tasks.json
}

resource "aws_iam_role_policy" "atendimento_fila" {
  name = "publicar-eventos"
  role = aws_iam_role.app_atendimento.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["sqs:GetQueueUrl", "sqs:SendMessage"]
      Resource = aws_sqs_queue.eventos.arn
    }]
  })
}

# O perfil de inferência é lido da própria região, com os modelos para onde ele manda o pedido.
data "aws_bedrock_inference_profile" "modelo" {
  inference_profile_id = var.perfil_do_modelo
}

resource "aws_iam_role_policy" "atendimento_modelo" {
  name = "invocar-haiku"
  role = aws_iam_role.app_atendimento.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "PeloPerfil"
        Effect   = "Allow"
        Action   = "bedrock:InvokeModel"
        Resource = data.aws_bedrock_inference_profile.modelo.inference_profile_arn
      },
      {
        # O modelo em si só pode ser chamado através desse perfil.
        Sid      = "ModeloSoPeloPerfil"
        Effect   = "Allow"
        Action   = "bedrock:InvokeModel"
        Resource = data.aws_bedrock_inference_profile.modelo.models[*].model_arn
        Condition = {
          StringEquals = { "bedrock:InferenceProfileArn" = data.aws_bedrock_inference_profile.modelo.inference_profile_arn }
        }
      },
    ]
  })
}

# ------------------------------------------------ 4. aplicação do operacoes: só consome
resource "aws_iam_role" "app_operacoes" {
  name               = "${local.prefixo_iam}-app-operacoes"
  assume_role_policy = data.aws_iam_policy_document.confia_ecs_tasks.json
}

resource "aws_iam_role_policy" "operacoes_fila" {
  name = "consumir-eventos"
  role = aws_iam_role.app_operacoes.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["sqs:GetQueueUrl", "sqs:ReceiveMessage", "sqs:DeleteMessage"]
      Resource = aws_sqs_queue.eventos.arn
    }]
  })
}

# ------------------------------------------------ 5. as duas aplicações releem a senha do banco
# O RDS rotaciona a senha a cada 7 dias, e o ECS só a injeta quando a task sobe. Em 12/11, em
# Ohio, as tasks antigas passaram a ouvir "Access denied". Desde a v4, o código relê a senha
# no Secrets Manager quando isso acontece, e para isso a role da aplicação precisa ler o segredo.
resource "aws_iam_role_policy" "app_le_segredo" {
  for_each = {
    atendimento = aws_iam_role.app_atendimento.id
    operacoes   = aws_iam_role.app_operacoes.id
  }
  name = "reler-segredo-rds"
  role = each.value
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "secretsmanager:GetSecretValue"
      Resource = aws_db_instance.principal.master_user_secret[0].secret_arn
    }]
  })
}
