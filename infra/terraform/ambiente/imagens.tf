# Repositórios no ECR de São Paulo e as imagens dentro deles.
# As imagens de Ohio não servem: a etapa 2 não pode puxar nada de lá.

locals {
  servicos = ["atendimento", "operacoes"]
  raiz     = abspath("${path.root}/../../..")

  # A tag é o hash dos arquivos do serviço: mudou o código, muda a tag, e a task definition
  # ganha uma revisão nova. Código igual, tag igual, nada é reconstruído.
  tag = {
    for s in local.servicos : s => substr(sha1(join("", [
      for f in sort(fileset("${local.raiz}/app/${s}", "*")) : filesha1("${local.raiz}/app/${s}/${f}")
    ])), 0, 12)
  }

  # O comando do Python muda com o sistema: "python" no Windows, "python3" no Linux e no
  # macOS, onde "python" muitas vezes não existe. Caminho começando com letra de unidade
  # ("C:") é Windows.
  python = can(regex("^[A-Za-z]:", local.raiz)) ? "python" : "python3"
}

resource "aws_ecr_repository" "servico" {
  for_each             = toset(local.servicos)
  name                 = "${var.projeto}/${each.key}"
  image_tag_mutability = "MUTABLE"
  force_delete         = true # o destroy apaga o repositório mesmo com imagens dentro
}

# Gera e envia a imagem pelo Docker da máquina que roda o apply.
resource "terraform_data" "imagem" {
  for_each         = toset(local.servicos)
  triggers_replace = [local.tag[each.key], aws_ecr_repository.servico[each.key].repository_url]

  # Cada argumento vai separado no `interpreter`, sem passar por um shell: o caminho tem
  # espaço e acento, e o cmd do Windows estragava as aspas.
  provisioner "local-exec" {
    interpreter = [
      local.python, "${local.raiz}/scripts/publicar-imagem.py", var.regiao,
      aws_ecr_repository.servico[each.key].repository_url, local.tag[each.key],
    ]
    command = "${local.raiz}/app/${each.key}"
  }
}

locals {
  imagem = { for s in local.servicos : s => "${aws_ecr_repository.servico[s].repository_url}:${local.tag[s]}" }
}
