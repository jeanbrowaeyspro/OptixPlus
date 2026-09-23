"""Configuration du journal de l'application.

Tous les loggers sont enfants de ``optixplus``. Deux destinations :
- un fichier tournant dans ``%APPDATA%\\OptixPlus\\logs`` ;
- un tampon mémoire relayé par signal Qt, que le panneau Journal affiche. Le tampon
  survit à la fermeture de la fenêtre : à sa réouverture, le panneau reprend l'historique.
"""

from __future__ import annotations

import logging
from collections import deque
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import QObject, Signal

from . import paths

ROOT_LOGGER = "optixplus"
BUFFER_SIZE = 2000
FORMAT = "%(asctime)s  %(levelname)-8s %(name)s — %(message)s"


class _Relay(QObject):
    """Porteur de signal : ``logging.Handler`` ne peut pas en émettre lui-même."""

    record = Signal(str, int)


class MemoryLogHandler(logging.Handler):
    """Garde les derniers enregistrements et les relaie au thread de l'interface."""

    def __init__(self) -> None:
        super().__init__()
        self.relay = _Relay()
        self.buffer: deque[tuple[str, int]] = deque(maxlen=BUFFER_SIZE)
        self.setFormatter(logging.Formatter(FORMAT, "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = self.format(record)
            self.buffer.append((text, record.levelno))
            self.relay.record.emit(text, record.levelno)
        except RuntimeError:
            pass  # relais détruit à la fermeture


_memory_handler: MemoryLogHandler | None = None


def configure(to_file: bool = True) -> MemoryLogHandler:
    """Installe les destinations du journal ; appelable une seule fois par processus."""
    global _memory_handler
    if _memory_handler is not None:
        return _memory_handler
    logger = logging.getLogger(ROOT_LOGGER)
    logger.setLevel(logging.INFO)
    if to_file:
        try:
            file_handler = RotatingFileHandler(
                paths.log_dir() / "optixplus.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
            )
            file_handler.setFormatter(logging.Formatter(FORMAT, "%Y-%m-%d %H:%M:%S"))
            logger.addHandler(file_handler)
        except OSError as exc:
            logging.getLogger(ROOT_LOGGER).warning("Journal fichier indisponible : %s", exc)
    _memory_handler = MemoryLogHandler()
    logger.addHandler(_memory_handler)
    return _memory_handler


def memory_handler() -> MemoryLogHandler:
    """Tampon mémoire du journal (configuré à la demande, sans fichier, pour les tests)."""
    return _memory_handler or configure(to_file=False)
