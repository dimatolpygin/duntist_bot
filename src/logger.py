"""Слой логирования. Читаемый вывод в терминал на русском для отладки."""
from __future__ import annotations

import logging
import sys

_GREY = "\033[90m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_BOLD_RED = "\033[1;31m"
_RESET = "\033[0m"

_LEVEL_COLORS = {
    logging.DEBUG: _GREY,
    logging.INFO: _GREEN,
    logging.WARNING: _YELLOW,
    logging.ERROR: _RED,
    logging.CRITICAL: _BOLD_RED,
}


class _ColorFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        color = _LEVEL_COLORS.get(record.levelno, "")
        time_str = self.formatTime(record, "%d.%m.%Y %H:%M:%S")
        msg = record.getMessage()
        line = f"{_GREY}{time_str}{_RESET} {color}{record.levelname:<7}{_RESET} {msg}"
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Настраивает корневой логгер. Вызывается один раз при старте."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_ColorFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # Приглушаем болтливые сторонние логгеры.
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)

    return logging.getLogger("zarub_bot")


logger = logging.getLogger("zarub_bot")
