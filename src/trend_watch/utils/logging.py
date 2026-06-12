import logging

from rich.console import Console
from rich.logging import RichHandler

_console = Console(stderr=True)


def setup_logging(level: str = "INFO", debug: bool = False) -> None:
    log_level = logging.DEBUG if debug else getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=_console, rich_tracebacks=True, show_path=debug)],
    )
    for noisy in ("httpx", "httpcore", "urllib3", "charset_normalizer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


class LoggerMixin:
    @property
    def log(self) -> logging.Logger:
        return get_logger(type(self).__module__ + "." + type(self).__qualname__)
