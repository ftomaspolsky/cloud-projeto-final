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
