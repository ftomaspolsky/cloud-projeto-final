"""Gera o .zip que vai para o CloudShell: o repositório é privado, e clonar lá exigiria um token.

Leva só o que o git conhece e não ignora, então o .env não entra. Rodar na raiz do repositório:
    python scripts/gerar-zip.py
"""

import pathlib
import subprocess
import zipfile

DESTINO = pathlib.Path("../cloud-projeto-final.zip")

saida = subprocess.run(
    ["git", "ls-files", "-c", "-o", "--exclude-standard", "-z"],
    capture_output=True,
    check=True,
).stdout
arquivos = sorted({a for a in saida.decode("utf-8").split("\0") if a and pathlib.Path(a).is_file()})

with zipfile.ZipFile(DESTINO, "w", zipfile.ZIP_DEFLATED) as pacote:
    for arquivo in arquivos:
        pacote.write(arquivo, arquivo)

print(f"{len(arquivos)} arquivos em {DESTINO.resolve()}")
