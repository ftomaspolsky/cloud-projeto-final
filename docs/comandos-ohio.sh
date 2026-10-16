#!/usr/bin/env bash
# Comandos da AWS CLI usados na etapa 1 (Ohio), na ordem em que foram executados.
# O enunciado permite CLI na etapa manual. Isto NÃO é IaC: é o registro do que foi feito,
# para reproduzir no Terraform. Ações feitas no console entram aqui como comentário.
set -euo pipefail
export AWS_REGION=us-east-2
TAGS='Key=projeto,Value=cloud-projeto-final'
