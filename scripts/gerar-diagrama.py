"""Gera docs/arquitetura-ohio.drawio a partir de coordenadas absolutas.

Cada celula tem pai e posicao absoluta; o gerador converte para relativa ao pai,
que e o que o draw.io espera. Assim, mover um grupo no editor move o que esta dentro.
"""
import sys
from xml.sax.saxutils import escape

PTS = ("points=[[0,0],[0.25,0],[0.5,0],[0.75,0],[1,0],[1,0.25],[1,0.5],[1,0.75],"
       "[1,1],[0.75,1],[0.5,1],[0.25,1],[0,1],[0,0.75],[0,0.5],[0,0.25]];")
N4 = PTS + "sketch=0;outlineConnect=0;gradientColor=none;html=1;whiteSpace=wrap;fontSize=12;fontStyle=0;shape=mxgraph.aws4."
GRUPO = "container=1;collapsible=0;"


def recurso(nome, cor):
    return ("sketch=0;outlineConnect=0;fontColor=#232F3E;gradientColor=none;fillColor=" + cor +
            ";strokeColor=none;dashed=0;verticalLabelPosition=bottom;verticalAlign=top;align=center;"
            "html=1;fontSize=11;fontStyle=0;aspect=fixed;pointerEvents=1;shape=mxgraph.aws4." + nome + ";")


LADO = "labelPosition=right;verticalLabelPosition=middle;align=left;verticalAlign=middle;spacingLeft=4;"


def servico(nome, cor):
    return ("sketch=0;outlineConnect=0;fontColor=#232F3E;gradientColor=none;fillColor=" + cor +
            ";strokeColor=none;dashed=0;verticalLabelPosition=bottom;verticalAlign=top;align=center;"
            "html=1;fontSize=11;fontStyle=0;aspect=fixed;shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4." + nome + ";")


S_CLOUD = N4 + "group;grIcon=mxgraph.aws4.group_aws_cloud_alt;strokeColor=#232F3E;fillColor=none;verticalAlign=top;align=left;spacingLeft=30;fontColor=#232F3E;dashed=0;fontStyle=1;" + GRUPO
S_REGIAO = N4 + "group;grIcon=mxgraph.aws4.group_region;strokeColor=#00A4A6;fillColor=none;verticalAlign=top;align=left;spacingLeft=30;fontColor=#147EBA;dashed=1;fontStyle=1;" + GRUPO
S_VPC = N4 + "group;grIcon=mxgraph.aws4.group_vpc2;strokeColor=#8C4FFF;fillColor=none;verticalAlign=top;align=left;spacingLeft=30;fontColor=#8C4FFF;dashed=0;fontStyle=1;" + GRUPO
S_AZ = "fillColor=none;strokeColor=#147EBA;dashed=1;verticalAlign=top;fontStyle=1;fontColor=#147EBA;whiteSpace=wrap;html=1;" + GRUPO
S_PRIV = N4 + "group;grIcon=mxgraph.aws4.group_security_group;grStroke=0;strokeColor=#00A4A6;fillColor=#E6F6F7;verticalAlign=top;align=left;spacingLeft=30;fontColor=#147EBA;dashed=0;" + GRUPO
S_PUB = N4 + "group;grIcon=mxgraph.aws4.group_security_group;grStroke=0;strokeColor=#7AA116;fillColor=#F2F6E8;verticalAlign=top;align=left;spacingLeft=30;fontColor=#248814;dashed=0;" + GRUPO
S_ASG = N4 + "group;grIcon=mxgraph.aws4.group_auto_scaling_group;strokeColor=#D86613;fillColor=none;verticalAlign=bottom;align=right;spacingRight=10;spacingBottom=6;fontColor=#D86613;dashed=1;" + GRUPO
S_EC2 = N4 + "group;grIcon=mxgraph.aws4.group_ec2_instance_contents;strokeColor=#D86613;fillColor=#FFFFFF;verticalAlign=top;align=left;spacingLeft=30;fontColor=#D86613;dashed=0;" + GRUPO
S_REGIONAIS = "rounded=1;arcSize=2;fillColor=#FAFAFA;strokeColor=#AAB7B8;dashed=1;verticalAlign=top;align=left;spacingLeft=10;spacingTop=4;fontStyle=1;fontColor=#545B64;whiteSpace=wrap;html=1;" + GRUPO
S_NOTA = "rounded=1;arcSize=3;fillColor=#FFFFFF;strokeColor=#AAB7B8;align=left;verticalAlign=top;spacing=10;fontSize=11;fontColor=#232F3E;whiteSpace=wrap;html=1;"
S_TITULO = "text;html=1;align=left;verticalAlign=middle;fontSize=20;fontStyle=1;fontColor=#232F3E;whiteSpace=wrap;"
S_SUB = "text;html=1;align=left;verticalAlign=middle;fontSize=12;fontColor=#545B64;whiteSpace=wrap;"

ARESTA = ("edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;endArrow=block;endFill=1;strokeWidth=1.5;"
          "fontSize=10;labelBackgroundColor=#FFFFFF;fontColor=#232F3E;")
A_REQ = ARESTA + "strokeColor=#232F3E;"          # caminho da requisicao
A_DADOS = ARESTA + "strokeColor=#C925D1;"        # banco
A_FILA = ARESTA + "strokeColor=#E7157B;"         # mensageria
A_IA = ARESTA + "strokeColor=#01A88D;"           # modelo
A_APOIO = ARESTA + "strokeColor=#879196;dashed=1;strokeWidth=1;"  # suporte: imagem, segredo, logs, NAT

celulas = {}   # id -> (pai, x, y, w, h) absolutos
ordem = []


def v(id_, pai, x, y, w, h, rotulo, estilo):
    celulas[id_] = (pai, x, y, w, h)
    ordem.append(("v", id_, pai, x, y, w, h, rotulo, estilo))


def e(id_, origem, destino, rotulo, estilo, extra="", pontos=None):
    ordem.append(("e", id_, origem, destino, rotulo, estilo + extra, pontos))


# ---------------------------------------------------------------- titulo
v("titulo", "1", 40, 10, 1100, 32, "Projeto Final de Cloud — arquitetura em Ohio (etapa 1)", S_TITULO)
v("sub", "1", 40, 40, 1300, 22,
  "Atendente de condomínio com IA generativa: o morador conversa, o modelo consulta e reserva, "
  "a cobrança sai de forma assíncrona. Tudo criado pelo console e pela AWS CLI, sem IaC.", S_SUB)

# ---------------------------------------------------------------- fora da AWS
v("morador", "1", 40, 260, 60, 60, "Morador<br>(navegador)", recurso("users", "#232F3D"))

# ---------------------------------------------------------------- nuvem / regiao
v("cloud", "1", 150, 80, 1530, 1010, "AWS Cloud", S_CLOUD)
v("regiao", "cloud", 170, 115, 1490, 955, "Região Ohio (us-east-2)", S_REGIAO)
v("vpc", "regiao", 230, 160, 910, 880, "VPC 10.0.0.0/16", S_VPC)
v("igw", "regiao", 200, 260, 60, 60, "Internet<br>Gateway", recurso("internet_gateway", "#8C4FFF"))

v("aza", "vpc", 260, 200, 410, 820, "Zona us-east-2a", S_AZ)
v("azb", "vpc", 700, 200, 410, 820, "Zona us-east-2b", S_AZ)

v("puba", "aza", 280, 235, 370, 175, "Sub-rede pública 10.0.0.0/20", S_PUB)
v("pubb", "azb", 720, 235, 370, 175, "Sub-rede pública 10.0.16.0/20", S_PUB)
v("priva", "aza", 280, 430, 370, 570, "Sub-rede privada 10.0.128.0/20", S_PRIV)
v("privb", "azb", 720, 430, 370, 570, "Sub-rede privada 10.0.144.0/20", S_PRIV)

v("nat", "puba", 320, 330, 60, 60, "NAT Gateway<br>+ Elastic IP<br>(saída das privadas)", recurso("nat_gateway", "#8C4FFF") + LADO)
v("alb", "vpc", 655, 260, 60, 60,
  "<b>Application Load Balancer</b><br>HTTP :80, nas 2 sub-redes públicas<br>health check GET /health<br>repassa às tasks por porta dinâmica",
  recurso("application_load_balancer", "#8C4FFF") + LADO)

# ASG atravessa as duas zonas: e filho da VPC, por cima das sub-redes privadas
v("asg", "vpc", 295, 480, 780, 325,
  "<b>Auto Scaling Group</b>: 2 a 4 × t3.small, uma por zona<br><b>Capacity Provider</b> do cluster ECS, escala gerenciada a 100%",
  S_ASG)
v("ec2a", "asg", 315, 545, 340, 210, "EC2 t3.small · AMI otimizada para ECS", S_EC2)
v("ec2b", "asg", 715, 545, 340, 210, "EC2 t3.small · AMI otimizada para ECS", S_EC2)

v("atda", "ec2a", 446, 600, 37, 48, "task<br><b>atendimento</b>", recurso("ecs_task", "#ED7100"))
v("opb", "ec2b", 800, 600, 37, 48, "task<br><b>operacoes</b>", recurso("ecs_task", "#ED7100"))
v("atdb", "ec2b", 960, 600, 37, 48, "task<br><b>atendimento</b>", recurso("ecs_task", "#ED7100"))

v("rdsa", "priva", 435, 880, 60, 60, "<b>RDS MySQL 8.4</b><br>primária*", recurso("rds_mysql_instance", "#C925D1"))
v("rdsb", "privb", 855, 880, 60, 60, "<b>RDS MySQL 8.4</b><br>espera síncrona*", recurso("rds_mysql_instance", "#C925D1"))

# ---------------------------------------------------------------- servicos regionais
v("regionais", "regiao", 1170, 160, 470, 880,
  "Serviços regionais, fora da VPC (alcançados pelo NAT)", S_REGIONAIS)
cx1, cx2 = 1235, 1480
v("bedrock", "regionais", cx1, 220, 60, 60, "<b>Amazon Bedrock</b><br>Claude Haiku 5.5<br>perfil us.anthropic…", servico("bedrock", "#01A88D"))
v("ecr", "regionais", cx2, 220, 60, 60, "<b>ECR</b><br>atendimento, operacoes", servico("ecr", "#ED7100"))
v("sqs", "regionais", cx1, 400, 60, 60, "<b>SQS eventos</b><br>visibilidade 60 s<br>long polling 20 s", servico("sqs", "#E7157B"))
v("dlq", "regionais", cx2, 400, 60, 60, "<b>SQS eventos-dlq</b><br>retenção 14 dias", servico("sqs", "#E7157B"))
v("segredo", "regionais", cx1, 580, 60, 60, "<b>Secrets Manager</b><br>senha do RDS", servico("secrets_manager", "#DD344C"))
v("iam", "regionais", cx2, 580, 60, 60, "<b>IAM</b><br>4 roles: instância, execução<br>e uma por serviço", servico("identity_and_access_management", "#DD344C"))
v("cw", "regionais", cx1, 760, 60, 60, "<b>CloudWatch</b><br>logs JSON, 2 filtros<br>12 alarmes", servico("cloudwatch_2", "#E7157B"))
v("sns", "regionais", cx2, 760, 60, 60, "<b>SNS</b><br>tópico de alertas", servico("sns", "#E7157B"))
v("aas", "regionais", cx1, 935, 60, 60, "<b>Application Auto Scaling</b><br>2 políticas, uma por serviço", servico("application_auto_scaling", "#E7157B"))
v("email", "regionais", cx2, 935, 60, 60, "e-mail inscrito", recurso("email_notification", "#E7157B"))

# ---------------------------------------------------------------- notas
v("nota_sg", "1", 40, 1110, 520, 120,
  "<b>Security groups encadeados</b><br>"
  "• <b>sg-alb</b>: entra HTTP 80 de qualquer lugar.<br>"
  "• <b>sg-ecs</b>: entra TCP 32768–65535 só do sg-alb (porta dinâmica do modo bridge). Sem SSH.<br>"
  "• <b>sg-rds</b>: entra MySQL 3306 só do sg-ecs. Nenhuma saída.<br>"
  "Instâncias e banco ficam em sub-rede privada, sem IP público.", S_NOTA)
v("nota_escala", "1", 580, 1110, 540, 120,
  "<b>Escala em dois níveis</b><br>"
  "• <b>atendimento</b>: 2 a 16 tasks, alvo de 100 requisições por task (ALBRequestCountPerTarget).<br>"
  "• <b>operacoes</b>: 1 a 4 tasks, alvo de 100 mensagens visíveis na fila por task.<br>"
  "• <b>instâncias</b>: o Capacity Provider sobe o ASG quando falta lugar para task.<br>"
  "Tasks espalhadas por zona; drenagem e proteção de encerramento gerenciadas.", S_NOTA)
v("nota_falha", "1", 1140, 1110, 540, 120,
  "<b>Como cada falha é absorvida</b><br>"
  "• Modelo fora: o morador cai no menu guiado, com as mesmas regras.<br>"
  "• Fila fora: o evento fica na caixa de saída do banco e é publicado depois.<br>"
  "• Evento repetido: descartado por idempotência; não processável vai para a DLQ.<br>"
  "• Instância perdida: o ASG repõe e o ECS reagenda. Banco: failover Multi-AZ.<br>"
  "* primária e espera trocam de zona no failover.", S_NOTA)

# ---------------------------------------------------------------- arestas
e("e1", "morador", "igw", "HTTP :80", A_REQ)
e("e2", "igw", "alb", "", A_REQ, "exitX=1;exitY=0.5;entryX=0;entryY=0.5;")
e("e3", "alb", "atda", "", A_REQ, "exitX=0.5;exitY=1;entryX=0.5;entryY=0;")
e("e4", "alb", "atdb", "", A_REQ, "exitX=0.5;exitY=1;entryX=0.5;entryY=0;")
e("e5", "atda", "rdsa", "3306, TLS<br>reserva numa transação", A_DADOS, "exitX=0.5;exitY=1;entryX=0.5;entryY=0;")
e("e6", "opb", "rdsa", "cobrança idempotente", A_DADOS, "exitX=0;exitY=0.5;entryX=1;entryY=0.5;",
  pontos=[(690, 624), (690, 910)])
e("e7", "rdsa", "rdsb", "replicação síncrona", A_DADOS, "endArrow=none;dashed=1;exitX=1;exitY=0.75;entryX=0;entryY=0.75;")
e("e11", "atdb", "bedrock", "Converse + ferramentas", A_IA, "exitX=1;exitY=0.25;entryX=0;entryY=0.5;",
  pontos=[(1100, 612), (1100, 250)])
e("e8", "atdb", "sqs", "evento depois do commit", A_FILA, "exitX=1;exitY=0.75;entryX=0;entryY=0.3;",
  pontos=[(1120, 636), (1120, 418)])
e("e9", "sqs", "opb", "consome", A_FILA, "exitX=0;exitY=0.7;entryX=0.5;entryY=1;",
  pontos=[(1090, 442), (1090, 720), (818, 720)])
e("e10", "sqs", "dlq", "após 3 recebimentos", A_FILA, "exitX=1;exitY=0.5;entryX=0;entryY=0.5;")
e("e12", "ec2a", "nat", "", A_APOIO, "exitX=0.1;exitY=0;entryX=0.5;entryY=1;")
e("e13", "ecr", "asg", "imagens", A_APOIO, "exitX=0.5;exitY=1;entryX=1;entryY=0.1;",
  pontos=[(1510, 335), (1150, 335), (1150, 510)])
e("e14", "segredo", "asg", "senha na subida da task", A_APOIO, "exitX=0;exitY=0.5;entryX=1;entryY=0.6;",
  pontos=[(1150, 610), (1150, 660)])
e("e15", "asg", "cw", "logs", A_APOIO, "exitX=1;exitY=0.85;entryX=0;entryY=0.5;",
  pontos=[(1150, 756), (1150, 790)])
e("e16", "cw", "sns", "ALARM / OK", A_APOIO, "exitX=1;exitY=0.5;entryX=0;entryY=0.5;")
e("e17", "sns", "email", "", A_APOIO, "exitX=0.5;exitY=1;entryX=0.5;entryY=0;")
e("e18", "cw", "aas", "", A_APOIO, "exitX=0.5;exitY=1;entryX=0.5;entryY=0;")

def xml():
    linhas = ['<mxfile host="app.diagrams.net" type="device">',
              '  <diagram id="arquitetura-ohio" name="Ohio (etapa 1)">',
              '    <mxGraphModel dx="1700" dy="1300" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" '
              'arrows="1" fold="1" page="1" pageScale="1" pageWidth="1720" pageHeight="1300" math="0" shadow="0">',
              '      <root>', '        <mxCell id="0" />', '        <mxCell id="1" parent="0" />']
    for item in ordem:
        if item[0] == "v":
            _, id_, pai, x, y, w, h, rot, est = item
            if pai != "1":
                px, py = celulas[pai][1], celulas[pai][2]
                x, y = x - px, y - py
            linhas.append(f'        <mxCell id="{id_}" value="{escape(rot, {chr(34): "&quot;"})}" style="{est}" '
                          f'vertex="1" parent="{pai}">')
            linhas.append(f'          <mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry" />')
            linhas.append('        </mxCell>')
        else:
            _, id_, ori, dst, rot, est, pontos = item
            linhas.append(f'        <mxCell id="{id_}" value="{escape(rot, {chr(34): "&quot;"})}" style="{est}" '
                          f'edge="1" parent="1" source="{ori}" target="{dst}">')
            if pontos:
                linhas.append('          <mxGeometry relative="1" as="geometry">')
                linhas.append('            <Array as="points">')
                for px, py in pontos:
                    linhas.append(f'              <mxPoint x="{px}" y="{py}" />')
                linhas.append('            </Array>')
                linhas.append('          </mxGeometry>')
            else:
                linhas.append('          <mxGeometry relative="1" as="geometry" />')
            linhas.append('        </mxCell>')
    linhas += ['      </root>', '    </mxGraphModel>', '  </diagram>', '</mxfile>', '']
    return "\n".join(linhas)


if __name__ == "__main__":
    with open(sys.argv[1], "w", encoding="utf-8", newline="\n") as f:
        f.write(xml())
    print("ok", sys.argv[1])
