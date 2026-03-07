import logging
from contextvars import ContextVar, Token

_request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

LOG_FORMAT = (
    "%(asctime)s | %(levelname)s | %(name)s | request_id=%(request_id)s | "
    "feature=%(feature)s | method=%(method)s | path=%(path)s | "
    "status_code=%(status_code)s | duration_ms=%(duration_ms)s | "
    "client_ip=%(client_ip)s | model=%(model)s | message_count=%(message_count)s | "
    "%(message)s"
)

DEFAULT_LOG_VALUES = {
    "request_id": "-",
    "feature": "-",
    "method": "-",
    "path": "-",
    "status_code": "-",
    "duration_ms": "-",
    "client_ip": "-",
    "model": "-",
    "message_count": "-",
}


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = getattr(record, "request_id", None) or get_request_id()
        for field_name, default_value in DEFAULT_LOG_VALUES.items():
            if not hasattr(record, field_name):
                setattr(record, field_name, default_value)
        return True


def configure_logging(log_level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format=LOG_FORMAT,
        force=True,
    )

    request_context_filter = RequestContextFilter()
    for handler in logging.getLogger().handlers:
        handler.addFilter(request_context_filter)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def set_request_id(request_id: str) -> Token[str]:
    return _request_id_var.set(request_id)


def reset_request_id(token: Token[str]) -> None:
    _request_id_var.reset(token)


def get_request_id() -> str:
    return _request_id_var.get()
