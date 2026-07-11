import contextvars
import json
import logging

correlation_id_var = contextvars.ContextVar("correlation_id", default="-")


def set_correlation_id(correlation_id: str) -> None:
    correlation_id_var.set(correlation_id or "-")


class CorrelationIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = correlation_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def __init__(self, service_name: str):
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "service": self.service_name,
            "correlation_id": getattr(record, "correlation_id", "-"),
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(service_name: str, level: int = logging.INFO) -> None:
    """Every log line is a JSON object carrying the current correlation id, so a single
    request/event can be grepped end-to-end across services."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter(service_name))
    handler.addFilter(CorrelationIdFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
