# Rede: a mesma forma de Ohio (linhas 1 a 10 de docs/recursos-ohio.md).
# 2 zonas, uma sub-rede pública e uma privada em cada, 1 NAT, 3 security groups encadeados.

resource "aws_vpc" "principal" {
  cidr_block           = var.cidr_vpc
  enable_dns_support   = true
  enable_dns_hostnames = true # o RDS e os endpoints da AWS são acessados por nome
  tags                 = { Name = "${var.projeto}-vpc" }
}

# Porta da VPC para a internet. Só as sub-redes públicas apontam para ela.
resource "aws_internet_gateway" "principal" {
  vpc_id = aws_vpc.principal.id
  tags   = { Name = "${var.projeto}-igw" }
}

# cidrsubnet(10.0.0.0/16, 4, n) recorta o /20 número n:
# 0 -> 10.0.0.0/20, 1 -> 10.0.16.0/20, 8 -> 10.0.128.0/20, 9 -> 10.0.144.0/20 (iguais a Ohio).
resource "aws_subnet" "publica" {
  count                   = 2
  vpc_id                  = aws_vpc.principal.id
  availability_zone       = local.zonas[count.index]
  cidr_block              = cidrsubnet(var.cidr_vpc, 4, count.index)
  map_public_ip_on_launch = false # nada aqui recebe IP público sozinho; o ALB e o NAT têm o deles
  tags                    = { Name = "${var.projeto}-subnet-publica-${local.zonas[count.index]}" }
}

resource "aws_subnet" "privada" {
  count             = 2
  vpc_id            = aws_vpc.principal.id
  availability_zone = local.zonas[count.index]
  cidr_block        = cidrsubnet(var.cidr_vpc, 4, count.index + 8)
  tags              = { Name = "${var.projeto}-subnet-privada-${local.zonas[count.index]}" }
}

# NAT: as instâncias privadas saem por ele para ECR, Bedrock, SQS, Secrets Manager e
# CloudWatch, sem que ninguém de fora consiga entrar. Um só, na 1ª zona, como em Ohio
# (economia; se a zona dele cair, as privadas perdem a saída até ele voltar).
resource "aws_eip" "nat" {
  domain = "vpc"
  tags   = { Name = "${var.projeto}-eip-nat" }
}

resource "aws_nat_gateway" "principal" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.publica[0].id
  tags          = { Name = "${var.projeto}-nat" }

  depends_on = [aws_internet_gateway.principal] # o NAT precisa da saída da VPC já pronta
}

# Rotas: pública sai pelo internet gateway; privada sai pelo NAT.
resource "aws_route_table" "publica" {
  vpc_id = aws_vpc.principal.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.principal.id
  }
  tags = { Name = "${var.projeto}-rt-publica" }
}

resource "aws_route_table" "privada" {
  vpc_id = aws_vpc.principal.id
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.principal.id
  }
  tags = { Name = "${var.projeto}-rt-privada" }
}

resource "aws_route_table_association" "publica" {
  count          = 2
  subnet_id      = aws_subnet.publica[count.index].id
  route_table_id = aws_route_table.publica.id
}

resource "aws_route_table_association" "privada" {
  count          = 2
  subnet_id      = aws_subnet.privada[count.index].id
  route_table_id = aws_route_table.privada.id
}

# ------------------------------------------------------------ security groups
# Encadeados: internet -> sg-alb -> sg-ecs -> sg-rds. Cada um só aceita o anterior.
# O Terraform apaga a regra de saída "tudo liberado" que a AWS cria por padrão, então
# a saída só existe onde está escrita abaixo. O sg-rds fica sem nenhuma, como em Ohio.

resource "aws_security_group" "alb" {
  name        = "${var.projeto}-sg-alb"
  description = "ALB: HTTP 80 da internet" # sem acento: a AWS recusa
  vpc_id      = aws_vpc.principal.id
  tags        = { Name = "${var.projeto}-sg-alb" }
}

resource "aws_vpc_security_group_ingress_rule" "alb_http" {
  security_group_id = aws_security_group.alb.id
  description       = "HTTP da internet"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_egress_rule" "alb_tudo" {
  security_group_id = aws_security_group.alb.id
  description       = "Saida para as instancias"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_security_group" "ecs" {
  name        = "${var.projeto}-sg-ecs"
  description = "Instancias ECS: portas dinamicas so do ALB"
  vpc_id      = aws_vpc.principal.id
  tags        = { Name = "${var.projeto}-sg-ecs" }
}

# Modo bridge: cada task ganha uma porta alta aleatória na instância, por isso a faixa toda.
resource "aws_vpc_security_group_ingress_rule" "ecs_do_alb" {
  security_group_id            = aws_security_group.ecs.id
  description                  = "Portas dinamicas, so do ALB"
  ip_protocol                  = "tcp"
  from_port                    = 32768
  to_port                      = 65535
  referenced_security_group_id = aws_security_group.alb.id
}

resource "aws_vpc_security_group_egress_rule" "ecs_tudo" {
  security_group_id = aws_security_group.ecs.id
  description       = "Saida para ECR, Bedrock, SQS, RDS e logs"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_security_group" "rds" {
  name        = "${var.projeto}-sg-rds"
  description = "RDS: MySQL so das instancias ECS"
  vpc_id      = aws_vpc.principal.id
  tags        = { Name = "${var.projeto}-sg-rds" }
}

resource "aws_vpc_security_group_ingress_rule" "rds_do_ecs" {
  security_group_id            = aws_security_group.rds.id
  description                  = "MySQL so do sg-ecs"
  ip_protocol                  = "tcp"
  from_port                    = 3306
  to_port                      = 3306
  referenced_security_group_id = aws_security_group.ecs.id
}
