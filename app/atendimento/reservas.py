"""As regras da reserva. Não sabem que existe IA: o chat e o menu guiado chamam as mesmas funções."""

import json
import logging
import uuid
from datetime import date, datetime, timedelta, timezone

import pymysql

import eventos
from banco import PERIODOS, conectar
from observabilidade import correlation_id, registrar

ERRO_DUPLICADO = 1062
LIMITE_RESERVAS_FUTURAS_POR_UNIDADE = 3
MAXIMO_DIAS_ANTECEDENCIA = 180
FUSO_DO_CONDOMINIO = timezone(timedelta(hours=-3))


class ReservaRecusada(Exception):
    """O pedido é válido como pedido, mas a regra do condomínio diz não."""

    def __init__(self, motivo):
        super().__init__(motivo)
        self.motivo = motivo


def hoje():
    return datetime.now(FUSO_DO_CONDOMINIO).date()


def _validar_data(texto):
    try:
        data = date.fromisoformat(texto)
    except (TypeError, ValueError):
        raise ReservaRecusada("data_invalida") from None
    if data < hoje():
        raise ReservaRecusada("data_no_passado")
    if data > hoje() + timedelta(days=MAXIMO_DIAS_ANTECEDENCIA):
        raise ReservaRecusada("data_muito_distante")
    return data


def _buscar_area(cursor, nome):
    cursor.execute("SELECT id, nome, taxa FROM area_comum WHERE nome = %s", (nome,))
    area = cursor.fetchone()
    if area is None:
        raise ReservaRecusada("area_inexistente")
    return area


def listar_areas():
    with conectar() as conexao, conexao.cursor() as cursor:
        cursor.execute("SELECT nome, taxa FROM area_comum ORDER BY id")
        return [{"nome": a["nome"], "taxa": str(a["taxa"])} for a in cursor.fetchall()]


def consultar_disponibilidade(area, data):
    dia = _validar_data(data)
    with conectar() as conexao, conexao.cursor() as cursor:
        encontrada = _buscar_area(cursor, area)
        cursor.execute(
            "SELECT periodo FROM reserva WHERE area_comum_id = %s AND data = %s AND status = 'ativa'",
            (encontrada["id"], dia),
        )
        ocupados = {linha["periodo"] for linha in cursor.fetchall()}
    return {
        "area": encontrada["nome"],
        "data": dia.isoformat(),
        "periodos_livres": [p for p in PERIODOS if p not in ocupados],
        "taxa": str(encontrada["taxa"]),
    }


def _gravar_reserva(cursor, area_id, unidade_id, morador_id, dia, periodo):
    cursor.execute(
        """INSERT INTO reserva (area_comum_id, unidade_id, morador_id, data, periodo)
           VALUES (%s, %s, %s, %s, %s)""",
        (area_id, unidade_id, morador_id, dia, periodo),
    )
    return cursor.lastrowid


def _gravar_lancamento(cursor, reserva_id, unidade_id, area, dia, periodo):
    cursor.execute(
        """INSERT INTO lancamento_financeiro (reserva_id, unidade_id, descricao, valor)
           VALUES (%s, %s, %s, %s)""",
        (reserva_id, unidade_id, f"Reserva {area['nome']} {dia} {periodo}", area["taxa"]),
    )
    return cursor.lastrowid


def _gravar_evento(cursor, reserva_id, lancamento_id, tipo="ReservaSolicitada"):
    evento_id = str(uuid.uuid4())
    corpo = {
        "evento_id": evento_id,
        "tipo": tipo,
        "reserva_id": reserva_id,
        "lancamento_id": lancamento_id,
    }
    cursor.execute(
        "INSERT INTO evento_saida (evento_id, corpo, correlation_id) VALUES (%s, %s, %s)",
        (evento_id, json.dumps(corpo), correlation_id.get()),
    )


def criar_reserva(area, data, periodo, morador_id):
    """Conflito, reserva, taxa e evento entram na MESMA transação: ou grava tudo, ou nada."""
    dia = _validar_data(data)
    if periodo not in PERIODOS:
        raise ReservaRecusada("periodo_invalido")

    with conectar() as conexao, conexao.cursor() as cursor:
        cursor.execute("SELECT unidade_id FROM morador WHERE id = %s", (morador_id,))
        morador = cursor.fetchone()
        if morador is None:
            raise ReservaRecusada("morador_inexistente")
        unidade_id = morador["unidade_id"]

        # FOR UPDATE na unidade: dois pedidos da mesma unidade passam um de cada vez, senão os
        # dois poderiam ler a contagem antes do outro gravar e estourar o limite.
        cursor.execute("SELECT id FROM unidade WHERE id = %s FOR UPDATE", (unidade_id,))
        cursor.execute(
            "SELECT COUNT(*) AS total FROM reserva WHERE unidade_id = %s AND data >= %s AND status = 'ativa'",
            (unidade_id, hoje()),
        )
        if cursor.fetchone()["total"] >= LIMITE_RESERVAS_FUTURAS_POR_UNIDADE:
            raise ReservaRecusada("limite_da_unidade")

        encontrada = _buscar_area(cursor, area)
        try:
            reserva_id = _gravar_reserva(
                cursor, encontrada["id"], unidade_id, morador_id, dia, periodo
            )
        except pymysql.err.IntegrityError as erro:
            if erro.args[0] != ERRO_DUPLICADO:
                raise
            raise ReservaRecusada("horario_ocupado") from None

        lancamento_id = _gravar_lancamento(cursor, reserva_id, unidade_id, encontrada, dia, periodo)
        _gravar_evento(cursor, reserva_id, lancamento_id)
        conexao.commit()

    registrar(logging.INFO, "reserva gravada", reserva_id=reserva_id, lancamento_id=lancamento_id)
    eventos.publicar_pendentes()
    return {
        "reserva_id": reserva_id,
        "area": encontrada["nome"],
        "data": dia.isoformat(),
        "periodo": periodo,
        "taxa": str(encontrada["taxa"]),
    }


def _unidade_do_morador(cursor, morador_id):
    cursor.execute("SELECT unidade_id FROM morador WHERE id = %s", (morador_id,))
    morador = cursor.fetchone()
    if morador is None:
        raise ReservaRecusada("morador_inexistente")
    return morador["unidade_id"]


def listar_minhas_reservas(morador_id):
    """As reservas ativas, de hoje em diante, da unidade do morador."""
    with conectar() as conexao, conexao.cursor() as cursor:
        unidade_id = _unidade_do_morador(cursor, morador_id)
        cursor.execute(
            """SELECT r.id, a.nome, r.data, r.periodo, a.taxa, l.status AS cobranca
               FROM reserva r
               JOIN area_comum a ON a.id = r.area_comum_id
               JOIN lancamento_financeiro l ON l.reserva_id = r.id
               WHERE r.unidade_id = %s AND r.status = 'ativa' AND r.data >= %s
               ORDER BY r.data, FIELD(r.periodo, 'manha', 'tarde', 'noite')""",
            (unidade_id, hoje()),
        )
        linhas = cursor.fetchall()
    return {
        "reservas": [
            {
                "reserva_id": r["id"],
                "area": r["nome"],
                "data": r["data"].isoformat(),
                "periodo": r["periodo"],
                "taxa": str(r["taxa"]),
                "cobranca": r["cobranca"],
            }
            for r in linhas
        ],
        "limite": LIMITE_RESERVAS_FUTURAS_POR_UNIDADE,
    }


def cancelar_reserva(reserva_id, morador_id):
    """Marca a reserva como cancelada e avisa o operacoes, que cancela a cobrança.

    Não apaga nada: a reserva, a taxa e o evento ficam como histórico. O horário volta a ficar
    livre na hora, e o limite da unidade deixa de contar esta reserva.
    """
    try:
        reserva_id = int(reserva_id)
    except (TypeError, ValueError):
        raise ReservaRecusada("reserva_inexistente") from None

    with conectar() as conexao, conexao.cursor() as cursor:
        unidade_id = _unidade_do_morador(cursor, morador_id)
        # Só a própria unidade: reserva de outra unidade responde igual a inexistente.
        cursor.execute(
            """SELECT r.id, r.data, r.periodo, a.nome, l.id AS lancamento_id
               FROM reserva r
               JOIN area_comum a ON a.id = r.area_comum_id
               JOIN lancamento_financeiro l ON l.reserva_id = r.id
               WHERE r.id = %s AND r.unidade_id = %s AND r.status = 'ativa'
               FOR UPDATE""",
            (reserva_id, unidade_id),
        )
        reserva = cursor.fetchone()
        if reserva is None:
            raise ReservaRecusada("reserva_inexistente")
        if reserva["data"] < hoje():
            raise ReservaRecusada("reserva_passada")

        cursor.execute(
            "UPDATE reserva SET status = 'cancelada', cancelada_em = CURRENT_TIMESTAMP WHERE id = %s",
            (reserva_id,),
        )
        _gravar_evento(cursor, reserva_id, reserva["lancamento_id"], tipo="ReservaCancelada")
        conexao.commit()

    registrar(logging.INFO, "reserva cancelada", reserva_id=reserva_id)
    eventos.publicar_pendentes()
    return {
        "reserva_id": reserva_id,
        "area": reserva["nome"],
        "data": reserva["data"].isoformat(),
        "periodo": reserva["periodo"],
        "cancelada": True,
    }
