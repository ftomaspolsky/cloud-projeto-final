# Recursos criados em Ohio (us-east-2)

Entregável da etapa 1 ("a relação dos recursos criados") e roteiro da etapa 2: cada linha
aqui vira um recurso no Terraform. Anote **enquanto cria**, não depois.

Todo recurso leva a tag `projeto=cloud-projeto-final`. Para conferir esta lista contra a
conta: Resource Groups → Tag Editor → região us-east-2 → tag `projeto`.

| # | Tipo | Nome / tag Name | ID | Depende de | Observação |
|---|---|---|---|---|---|
| 1 | VPC | `cloud-projeto-final-vpc` | `vpc-0a327d4e3c3062db9` | — | `10.0.0.0/16`, criada pelo assistente "VPC e mais" |
| 2 | Elastic IP | `cloud-projeto-final-eip-us-east-2a` | `eipalloc-003162896f09e360b` | — | `18.224.239.52`, usado pelo NAT |
| 3 | NAT Gateway | `cloud-projeto-final-nat-…` | `nat-0635a20e729ffe333` | 1, 2 | público, zonal, `us-east-2a`, IP privado `10.0.7.175`. **Cobra por hora mesmo parado** |
| 4 | Sub-rede pública | `cloud-projeto-final-subnet-public1-…` | `subnet-07440cb508a6106e3` | 1 | `10.0.0.0/20`, AZ 1 (`us-east-2a`, pelo nome). Abriga o NAT |
| 5 | Sub-rede pública | `cloud-projeto-final-subnet-public2-…` | `subnet-00444a0acd3aaf987` | 1 | `10.0.16.0/20`, AZ 2 |
| 6 | Sub-rede privada | `cloud-projeto-final-subnet-private1-…` | `subnet-0c3184701a6a96bc0` | 1 | `10.0.128.0/20`, AZ 1 |
| 7 | Sub-rede privada | `cloud-projeto-final-subnet-private2-…` | `subnet-0e9f6695edb9fdb93` | 1 | `10.0.144.0/20`, AZ 2 |
| 8 | Security group | `cloud-projeto-final-sg-alb` | `sg-05b9ae0a9518444cf` | 1 | entrada: HTTP 80 de `0.0.0.0/0`. Saída: tudo |
| 9 | Security group | `cloud-projeto-final-sg-ecs` | `sg-07da3f8f8d5f227f0` | 1, 8 | entrada: TCP 32768–65535 só do sg-alb (porta dinâmica do modo `bridge`). Saída: tudo (ECR, Bedrock, SQS via NAT). Sem SSH |
| 10 | Security group | `cloud-projeto-final-sg-rds` | `sg-01cd6f2c6e7520f26` | 1, 9 | entrada: MySQL 3306 só do sg-ecs. **Saída: nenhuma** |
| 11 | DB subnet group | `cloud-projeto-final-db-subnets` | (o nome é o ID) | 6, 7 | só as 2 privadas, `us-east-2a` e `us-east-2b` |
| 12 | RDS MySQL | `cloud-projeto-final-db` | (o nome é o ID) | 10, 11 | MySQL 8.4.11, `db.t4g.micro`, **Multi-AZ instância (2)**, gp3 20 GiB, sem acesso público, só sg-rds, senha gerenciada no Secrets Manager, banco inicial `condominio`, log de erros no CloudWatch, criptografia `aws/rds`, backup 7 dias, sem proteção contra exclusão. ~US$ 28/mês |
| 13 | SQS (padrão) | `cloud-projeto-final-eventos-dlq` | — | — | retenção 14 dias. DLQ da fila 14 |
| 14 | SQS (padrão) | `cloud-projeto-final-eventos` | — | 13 | visibilidade 60 s, long polling 20 s, redrive para a DLQ após **3** recebimentos, SSE-SQS |
