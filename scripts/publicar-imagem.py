"""Gera a imagem de um serviço e envia ao ECR. Chamado pelo Terraform (etapa 2).

    python scripts/publicar-imagem.py <regiao> <url-do-repositorio> <tag> <pasta-do-servico>

Precisa de Docker e AWS CLI na máquina que roda o `terraform apply`. A imagem é x86_64,
a arquitetura da t3.small. Se a tag já existe no repositório, não faz nada: a tag é o hash
do código, então tag igual é imagem igual.

O login no ECR vai para uma configuração do Docker temporária, apagada no fim: no Windows, o
cofre de senhas do Docker Desktop recusa o token do ECR ("The stub received bad data").
"""

import json
import os
import subprocess
import sys
import tempfile


def rodar(cmd, env, entrada=None):
    print("+", " ".join(cmd), flush=True)
    r = subprocess.run(cmd, input=entrada, text=True, env=env,
                       capture_output=entrada is not None)
    if r.returncode != 0:
        if entrada is not None:
            print(r.stdout, r.stderr, file=sys.stderr)
        sys.exit(f"falhou: {' '.join(cmd)}")


def main():
    regiao, repo, tag, pasta = sys.argv[1:5]
    registro = repo.split("/")[0]
    nome_repo = repo.split("/", 1)[1]
    imagem = f"{repo}:{tag}"

    existe = subprocess.run(
        ["aws", "ecr", "describe-images", "--region", regiao, "--repository-name", nome_repo,
         "--image-ids", f"imageTag={tag}"],
        capture_output=True, text=True,
    )
    if existe.returncode == 0:
        print(f"{imagem} já está no ECR, nada a fazer")
        return

    senha = subprocess.run(
        ["aws", "ecr", "get-login-password", "--region", regiao],
        capture_output=True, text=True, check=True,
    ).stdout
    with tempfile.TemporaryDirectory() as config:
        # Com alguma entrada em "auths", o Docker não procura o cofre de senhas do sistema e
        # grava o token neste arquivo.
        with open(os.path.join(config, "config.json"), "w") as f:
            json.dump({"auths": {registro: {}}}, f)
        env = {**os.environ, "DOCKER_CONFIG": config}
        rodar(["docker", "login", "--username", "AWS", "--password-stdin", registro], env, entrada=senha)
        rodar(["docker", "build", "--platform", "linux/amd64", "-t", imagem, pasta], env)
        rodar(["docker", "push", imagem], env)
    print(f"publicada: {imagem}")


if __name__ == "__main__":
    main()
