# Terraform — etapa 2 (São Paulo, sa-east-1)

Ainda não iniciado. Começa depois que a etapa 1 estiver de pé em Ohio.

Exigências do enunciado que moldam o código:

- **estado em backend remoto** (S3), criado por uma configuração `bootstrap/` separada;
- **parametrizado**: a região é variável;
- **nenhuma dependência de Ohio**: zonas por `data "aws_availability_zones"`, AMI otimizada
  para ECS lida do parâmetro público do SSM da região, imagens no ECR de São Paulo;
- **criar e destruir reproduzíveis**, sem passo manual.
