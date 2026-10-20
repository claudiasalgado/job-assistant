import json
import logging

# Campos que se pueden pasar con extra={...} y acaban como campos propios en Cloud Logging
CONTEXT_FIELDS = ("task_id", "application_id", "attempt")


class CloudLoggingFormatter(logging.Formatter):
    """Una línea JSON por registro: Cloud Run la convierte en un log estructurado.

    "severity" es el nombre que entiende Cloud Logging para el nivel, y los campos
    de CONTEXT_FIELDS permiten filtrar, por ejemplo, jsonPayload.task_id="...".
    """

    def format(self, record: logging.LogRecord) -> str:
        entry = {"severity": record.levelname, "message": record.getMessage(), "logger": record.name}
        for field in CONTEXT_FIELDS:
            if hasattr(record, field):
                entry[field] = str(getattr(record, field))
        if record.exc_info:
            entry["message"] += "\n" + self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def setup_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(CloudLoggingFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)
