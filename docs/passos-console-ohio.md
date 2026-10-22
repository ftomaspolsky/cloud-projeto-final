# Passos no console — etapa 1 (Ohio, us-east-2)

A etapa 1 é feita 100% no console da AWS, sem código (orientação do professor, 16/10).
Este arquivo registra **o que foi clicado e com que valores**, na ordem. É o roteiro que a
etapa 2 traduz para Terraform. Anote enquanto faz.

## 1. Rede (VPC)

Assistente **VPC → Criar VPC → "VPC e mais"**, prefixo `cloud-projeto-final`, CIDR
`10.0.0.0/16`, 2 AZs, 2 sub-redes públicas e 2 privadas (`/20`), **1 NAT Gateway** (em
`us-east-2a`). O assistente cria junto o Internet Gateway, as tabelas de rota (pública →
IGW, privada → NAT) e o Elastic IP do NAT.

## 2. Security groups

VPC → Grupos de segurança → Criar. Todos na `cloud-projeto-final-vpc`, tag
`projeto=cloud-projeto-final`. Descrição sem acento (o campo não aceita). Ordem obrigatória,
porque cada um é origem do seguinte:

| Nome | Entrada | Saída |
|---|---|---|
| `cloud-projeto-final-sg-alb` | HTTP 80, origem `0.0.0.0/0` | padrão (tudo) |
| `cloud-projeto-final-sg-ecs` | TCP 32768–65535, origem sg-alb | padrão (tudo) |
| `cloud-projeto-final-sg-rds` | MYSQL/Aurora 3306, origem sg-ecs | **regra padrão excluída** |

## 3. Banco (RDS)

**3a. Grupo de sub-redes:** Aurora and RDS → Grupos de sub-redes → Criar. Nome
`cloud-projeto-final-db-subnets`, VPC do projeto, AZs `us-east-2a` e `us-east-2b`, só as
sub-redes **privadas** (`10.0.128.0/20` e `10.0.144.0/20`).

**3b. Banco:** Bancos de dados → Criar → **Configuração completa**, MySQL 8.4.x, modelo
**Dev/Test** (o "Produção" vem com `db.m7g.large` e 200 GiB, ~US$ 250/mês),
**instância Multi-AZ (2 instâncias)**, `db.t4g.micro` (classes com capacidade de
intermitência), gp3 20 GiB sem autoescala, credencial **gerenciada no Secrets Manager**,
VPC do projeto, grupo `cloud-projeto-final-db-subnets`, acesso público **Não**, SG **só**
`sg-rds` (tirar o `default`), Enhanced Monitoring desligado, exportar **log de erros**,
banco inicial `condominio`, proteção contra exclusão desligada. Estimativa: US$ 27,96/mês.

## 4. Filas (SQS)

SQS → Criar fila, tipo **Padrão** (não FIFO: a duplicidade tem que ser tratada pela
aplicação, e a demo mostra isso). DLQ primeiro:

| Fila | Configuração |
|---|---|
| `cloud-projeto-final-eventos-dlq` | retenção 14 dias |
| `cloud-projeto-final-eventos` | visibilidade 60 s, espera de recebimento 20 s, DLQ habilitada → `…-dlq`, máximo de recebimentos 3 |

