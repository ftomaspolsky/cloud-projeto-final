# Filtro de prompt injection: uma guardrail do Bedrock com o filtro de ataque ao prompt.
#
# O app chama a guardrail (ApplyGuardrail) com as mensagens do morador ANTES do modelo. Se ela
# intervém, o modelo nem é chamado. As defesas estruturais continuam sendo as principais (o
# morador vem do servidor, as ferramentas validam tudo); a guardrail é a camada de cima.
#
# Por que fica em Ohio, e não em São Paulo: o morador escreve em português, e o filtro só entende
# português no tier Standard. São Paulo só tem o tier Classic (inglês, francês e espanhol) e não é
# origem de nenhum perfil de guardrail. O texto do morador já sai do Brasil para o modelo (perfil
# global.), então isso não muda para onde ele vai.

variable "regiao_da_guardrail" {
  description = "Região da guardrail. Precisa ter o tier Standard, que entende português."
  type        = string
  default     = "us-east-2"
}

variable "perfil_da_guardrail" {
  description = "Perfil de inferência entre regiões da guardrail, exigido pelo tier Standard."
  type        = string
  default     = "us.guardrail.v1:0"
}

data "aws_caller_identity" "atual" {}

locals {
  # Para onde o perfil us.guardrail.v1:0 pode mandar a avaliação, saindo de us-east-2.
  destinos_da_guardrail = ["us-east-1", "us-east-2", "us-west-2"]
  perfil_da_guardrail_arn = {
    for r in distinct(concat([var.regiao_da_guardrail], local.destinos_da_guardrail)) :
    r => "arn:aws:bedrock:${r}:${data.aws_caller_identity.atual.account_id}:guardrail-profile/${var.perfil_da_guardrail}"
  }
}

resource "aws_bedrock_guardrail" "prompt" {
  region      = var.regiao_da_guardrail
  name        = "${local.prefixo_iam}-prompt"
  description = "Bloqueia tentativas de prompt injection e jailbreak no chat do condominio."

  # O app não mostra estes textos (tem a própria resposta), mas a API exige os dois.
  blocked_input_messaging   = "Nao posso seguir com esse pedido."
  blocked_outputs_messaging = "Nao posso seguir com esse pedido."

  content_policy_config {
    tier_config {
      tier_name = "STANDARD"
    }
    filters_config {
      type            = "PROMPT_ATTACK"
      input_strength  = "HIGH"
      output_strength = "NONE" # o filtro de ataque ao prompt só vale para a entrada
    }
  }

  cross_region_config {
    # O provider exige o ARN do perfil na região da guardrail, não só o ID.
    guardrail_profile_identifier = local.perfil_da_guardrail_arn[var.regiao_da_guardrail]
  }
}

# O app chama uma versão fixa: mudar a guardrail no console não muda o que está em produção.
resource "aws_bedrock_guardrail_version" "prompt" {
  region        = var.regiao_da_guardrail
  guardrail_arn = aws_bedrock_guardrail.prompt.guardrail_arn
  description   = "Filtro de ataque ao prompt, forca HIGH, tier Standard."
}

resource "aws_iam_role_policy" "atendimento_guardrail" {
  name = "aplicar-guardrail"
  role = aws_iam_role.app_atendimento.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = "bedrock:ApplyGuardrail"
      Resource = concat(
        [aws_bedrock_guardrail.prompt.guardrail_arn],
        [for r in local.destinos_da_guardrail : local.perfil_da_guardrail_arn[r]],
      )
    }]
  })
}
