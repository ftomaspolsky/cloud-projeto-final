"""Logs em JSON, uma linha por evento, com o correlation_id: é o que os torna correlacionáveis."""

import contextvars
import json
import logging
import sys
import time

SERVICO = "atendimento"
correlation_id = contextvars.ContextVar("correlation_id", default="-")


class JsonFormatter(logging.Formatter):
    def format(self, record):
        evento = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "nivel": record.levelname,
            "servico": SERVICO,
            "correlation_id": correlation_id.get(),
            "msg": record.getMessage(),
        }
        evento.update(getattr(record, "extra_campos", {}))
        return json.dumps(evento, ensure_ascii=False, default=str)


handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JsonFormatter())
log = logging.getLogger(SERVICO)
log.addHandler(handler)
log.setLevel(logging.INFO)


def registrar(nivel, msg, **campos):
    log.log(nivel, msg, extra={"extra_campos": campos})
