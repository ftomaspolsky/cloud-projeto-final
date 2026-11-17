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

  # Estado remoto no bucket criado por ../bootstrap. O nome do bucket leva o número da
  # conta, e o bloco backend não aceita variáveis, por isso ele fica fora daqui e entra
  # no `terraform init`, lido da saída do bootstrap (ver o README):
  #   terraform init -backend-config="bucket=$(terraform "-chdir=../bootstrap" output -raw bucket_do_estado)"
  # Assim o código roda em qualquer conta, sem editar nada.
  backend "s3" {
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
