output "zonas" {
  description = "As 2 zonas escolhidas na região, lidas da própria AWS."
  value       = local.zonas
}

output "vpc_id" {
  value = aws_vpc.principal.id
}

output "subnets_publicas" {
  value = aws_subnet.publica[*].cidr_block
}

output "subnets_privadas" {
  value = aws_subnet.privada[*].cidr_block
}

output "endereco_do_chat" {
  description = "Abrir no navegador com http:// (o ALB só escuta na porta 80)."
  value       = "http://${aws_lb.principal.dns_name}"
}

output "imagens" {
  value = local.imagem
}
