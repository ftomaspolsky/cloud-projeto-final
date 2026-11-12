# Bootstrap: o bucket S3 que guarda o estado do Terraform da etapa 2.
#
# Roda UMA vez, antes de tudo, e fica de pé mesmo quando o ambiente é destruído.
# O estado DESTE diretório é local (não há onde guardá-lo antes de o bucket existir).
# Se ele se perder, o bucket continua lá e pode ser reimportado com `terraform import`.

terraform {
  required_version = ">= 1.10" # 1.10+ trava o estado com um arquivo no próprio S3 (use_lockfile)

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

variable "regiao" {
  description = "Região onde o bucket do estado é criado."
  type        = string
  default     = "sa-east-1"
}

provider "aws" {
  region = var.regiao

  # Toda peça criada por este código leva a mesma tag, como em Ohio.
  default_tags {
    tags = {
      projeto = "cloud-projeto-final"
      etapa   = "2"
    }
  }
}

# Número da conta, lido da credencial em uso. Entra no nome do bucket porque nome de
# bucket é único no mundo inteiro, e assim ninguém mais tem esse nome.
data "aws_caller_identity" "atual" {}

resource "aws_s3_bucket" "estado" {
  bucket = "cloud-projeto-final-tfstate-${data.aws_caller_identity.atual.account_id}-${var.regiao}"

  # Um `terraform destroy` aqui por engano apagaria o estado do ambiente inteiro.
  lifecycle {
    prevent_destroy = true
  }
}

# Cada `apply` grava uma versão nova do estado; as antigas ficam para recuperar um erro.
resource "aws_s3_bucket_versioning" "estado" {
  bucket = aws_s3_bucket.estado.id
  versioning_configuration {
    status = "Enabled"
  }
}

# O estado guarda segredos em texto puro (a senha do banco, por exemplo): criptografar em repouso.
resource "aws_s3_bucket_server_side_encryption_configuration" "estado" {
  bucket = aws_s3_bucket.estado.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Nenhum caminho para o bucket ficar público, nem por engano.
resource "aws_s3_bucket_public_access_block" "estado" {
  bucket                  = aws_s3_bucket.estado.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

output "bucket_do_estado" {
  description = "Nome do bucket, usado no bloco backend \"s3\" da configuração principal."
  value       = aws_s3_bucket.estado.bucket
}
