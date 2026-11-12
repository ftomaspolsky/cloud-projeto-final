# Ambiente da etapa 2: a mesma solução de Ohio, criada do zero em São Paulo.
#
# Um diretório só, um arquivo por área (rede.tf, dados.tf, ...). Um `terraform apply`
# cria tudo, e um `terraform destroy` apaga tudo, sem passo manual.

terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # Estado remoto no bucket criado por ../bootstrap. O bloco backend não aceita
  # variáveis, por isso o nome vai escrito aqui.
  backend "s3" {
    bucket       = "cloud-projeto-final-tfstate-116979769772-sa-east-1"
    key          = "ambiente/terraform.tfstate"
    region       = "sa-east-1"
    encrypt      = true
    use_lockfile = true # trava o estado durante um apply, com um arquivo .tflock no bucket
  }
}

provider "aws" {
  region = var.regiao

  default_tags {
    tags = {
      projeto = var.projeto
      etapa   = "2"
    }
  }
}

# As zonas vêm da própria região, nunca escritas à mão: "us-east-2a" no código seria
# exatamente a dependência oculta de Ohio que a rubrica pede para não ter.
data "aws_availability_zones" "disponiveis" {
  state = "available"
}

locals {
  zonas = slice(data.aws_availability_zones.disponiveis.names, 0, 2)
}
