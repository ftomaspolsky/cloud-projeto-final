# Terraform — etapa 2 (São Paulo, sa-east-1)

A mesma solução da etapa 1 (Ohio), criada do zero pelo código. Nada é reaproveitado de Ohio:
rede, banco, fila, imagens, roles e alarmes nascem aqui.

## Pré-requisitos na máquina que roda

- Terraform ≥ 1.10, AWS CLI v2, Docker **aberto** (as imagens são geradas e enviadas durante o
  `apply`) e Python 3 (roda `scripts/publicar-imagem.py`; o código chama `python` no Windows e
  `python3` no Linux e no macOS).
- Uma credencial da conta AWS com permissão de administrador. Nós usamos o IAM Identity Center
  num perfil chamado `cloud`: `aws configure sso --profile cloud` uma vez, depois
  `aws sso login --profile cloud` quando expirar. Qualquer outra credencial serve.
- **Numa conta nova, acesso aos modelos da Anthropic no Bedrock.** O Terraform sobe tudo sem
  isso, mas o chat responde com o menu em vez do modelo até o acesso ser liberado. Na primeira
  vez que a conta usa um modelo da Anthropic, a AWS pede um formulário de caso de uso no console
  do Bedrock; é uma vez por conta.

## Estrutura

| Diretório | O que é | Estado |
|---|---|---|
| `bootstrap/` | o bucket S3 do estado (versionado, criptografado, sem acesso público) | local, roda uma vez e fica |
| `ambiente/` | todo o resto, um arquivo por área | no bucket, `ambiente/terraform.tfstate`, travado com `use_lockfile` |

Arquivos de `ambiente/`: `principal.tf` (backend, provider, zonas), `variaveis.tf`, `rede.tf`,
`dados.tf` (RDS e SQS), `imagens.tf` (ECR e imagens), `iam.tf` (as 4 roles), `computacao.tf`
(logs, cluster, Launch Template, ASG, Capacity Provider, ALB, tasks e serviços), `escala.tf`,
`alarmes.tf` e `saidas.tf`.

## Criar do zero

São dois diretórios, nesta ordem. O `init` do ambiente lê o nome do bucket da saída do
bootstrap, porque o nome leva o número da conta e não pode estar escrito no código. A mesma
linha funciona no bash e no PowerShell.

```bash
export AWS_PROFILE=cloud            # PowerShell: $env:AWS_PROFILE = "cloud"

cd infra/terraform/bootstrap
terraform init
terraform apply                     # só na primeira vez: cria o bucket do estado

cd ../ambiente
terraform init -backend-config="bucket=$(terraform "-chdir=../bootstrap" output -raw bucket_do_estado)"
terraform apply
```

As aspas em `"-chdir=../bootstrap"` são de propósito: sem elas, o PowerShell 5.1 parte o
argumento no ponto, e o bucket chega vazio ("Backend configuration changed").

Se o estado local do bootstrap se perdeu (outra máquina, por exemplo), o nome do bucket é
`cloud-projeto-final-tfstate-<número da conta>-sa-east-1` e pode ir direto no `-backend-config`.

O `apply` do ambiente leva uns 20 min, quase tudo esperando o RDS Multi-AZ. No fim, a saída
`endereco_do_chat` é o endereço do ALB (abrir com `http://`).

Opcional: `terraform apply -var email_alertas=voce@exemplo.com` inscreve um e-mail no tópico
de alertas. A AWS manda um link de confirmação, e só depois dele os avisos chegam.

## Destruir

```powershell
cd infra/terraform/ambiente; terraform destroy
```

Apaga tudo o que o `ambiente/` criou, inclusive o banco (sem snapshot final) e as imagens.
O bucket do `bootstrap/` fica, de propósito (`prevent_destroy`): é ele que guarda o estado.

## Por que não há nada de Ohio escondido

- **Zonas:** `data "aws_availability_zones"`, as 2 primeiras disponíveis na região.
- **AMI:** o parâmetro público do SSM
  `/aws/service/ecs/optimized-ami/amazon-linux-2023/recommended/image_id` da própria região.
- **Modelo:** o perfil de inferência é lido por `data "aws_bedrock_inference_profile"`, que já
  traz os ARNs dos modelos para a política do IAM. Em São Paulo só existe o perfil `global.`.
- **Imagens:** geradas a partir de `app/` e enviadas ao ECR de São Paulo. A tag é o hash do código.
- **Nomes do IAM:** IAM é global e os nomes de Ohio já existem, então aqui as roles levam a região
  (`cloud-projeto-final-sa-east-1-*`).
- **Conta:** nenhum número de conta no código. O bootstrap lê a conta da credencial em uso, e o
  ambiente recebe o nome do bucket no `init`.
- **Região:** variável `regiao`. Trocá-la exige um bucket de estado na região nova
  (`terraform apply -var regiao=...` no bootstrap) e passar a região também no `init`:
  `-backend-config="region=..."`.
