# Persistência e mensageria: linhas 11 a 14 de docs/recursos-ohio.md.

resource "aws_db_subnet_group" "principal" {
  name       = "${var.projeto}-db-subnets"
  subnet_ids = aws_subnet.privada[*].id # só as privadas, uma por zona
}

# O RDS cria este grupo sozinho ao exportar o log de erros, e com retenção "Nunca expira".
# Criado aqui antes, ele nasce com 14 dias e some no destroy, sem deixar resto.
resource "aws_cloudwatch_log_group" "rds_erros" {
  name              = "/aws/rds/instance/${var.projeto}-db/error"
  retention_in_days = 14
}

resource "aws_db_instance" "principal" {
  identifier     = "${var.projeto}-db"
  engine         = "mysql"
  engine_version = "8.4" # a linha 8.4; a AWS escolhe a versão menor mais recente da região
  instance_class = "db.t4g.micro"

  allocated_storage = 20
  storage_type      = "gp3"
  storage_encrypted = true

  multi_az               = true # uma cópia em espera síncrona na outra zona; failover automático
  db_subnet_group_name   = aws_db_subnet_group.principal.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false

  db_name                     = "condominio" # sem isto o RDS sobe o servidor sem banco nenhum
  username                    = "admin"
  manage_master_user_password = true # a senha nasce e roda no Secrets Manager; não passa pelo código

  backup_retention_period         = 7
  enabled_cloudwatch_logs_exports = ["error"]
  apply_immediately               = true

  # O destroy tem que funcionar sem passo manual: sem snapshot final e sem trava de exclusão.
  skip_final_snapshot = true
  deletion_protection = false

  depends_on = [aws_cloudwatch_log_group.rds_erros]
}

resource "aws_sqs_queue" "dlq" {
  name                      = "${var.projeto}-eventos-dlq"
  message_retention_seconds = 1209600 # 14 dias para diagnosticar
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "eventos" {
  name                       = "${var.projeto}-eventos"
  visibility_timeout_seconds = 60 # mensagem pega e não apagada volta depois de 60 s
  receive_wait_time_seconds  = 20 # long polling: menos chamadas vazias
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = 3 # na 3ª entrega sem sucesso, vai para a DLQ
  })
}
