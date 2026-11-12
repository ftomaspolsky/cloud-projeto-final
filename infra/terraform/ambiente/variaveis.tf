variable "regiao" {
  description = "Região onde o ambiente inteiro é criado."
  type        = string
  default     = "sa-east-1"
}

variable "projeto" {
  description = "Prefixo dos nomes e valor da tag projeto."
  type        = string
  default     = "cloud-projeto-final"
}

variable "cidr_vpc" {
  description = "Faixa de endereços da VPC. As sub-redes são /20 recortadas dela."
  type        = string
  default     = "10.0.0.0/16"
}

variable "perfil_do_modelo" {
  description = "ID do perfil de inferência do Bedrock. Em São Paulo só existe o global."
  type        = string
  default     = "global.anthropic.claude-haiku-5-5"
}

variable "email_alertas" {
  description = "E-mail inscrito no tópico de alertas. Vazio: o tópico existe, sem inscrito. A inscrição precisa ser confirmada pelo link que a AWS manda."
  type        = string
  default     = ""
}
