"""Journal de la surveillance : fichier dédié en rotation et historique récent en mémoire.

Les messages passent par le logger ``optixplus.autovalidate`` : ils apparaissent aussi
dans le journal général de l'application. Ce journal dédié garde en plus l'historique
propre à la surveillance, affiché sur la page de l'outil, et le fichier
``autovalidate.log`` (repris de l'ancien Auto Validate).
"""

from __future__ import annotations

import logging
from collections import deque
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from ...common import paths

LOGGER_NAME = "optixplus.autovalidate"
MAX_ENTRIES = 500
FILE_MAX_BYTES = 512 * 1024
FILE_BACKUPS = 3
FORMAT = "%(asctime)s  %(levelname)-7s %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class _Relay(QObject):
    entry_added = Signal(str, int)
    cleared = Signal()


class _MemoryHandler(logging.Handler):
    def __init__(self, entries: deque[tuple[str, int]], relay: _Relay) -> None:
        super().__init__()
        self._entries = entries
        self._relay = relay
        self.setFormatter(logging.Formatter(FORMAT, DATE_FORMAT))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
            self._entries.append((line, record.levelno))
            self._relay.entry_added.emit(line, record.levelno)
        except RuntimeError:
            pass


class ActivityLog:
    """Historique de la surveillance ; une seule instance, portée par le service."""

    def __init__(self, file_path: Path | None = None) -> None:
        self.file_path = file_path or (paths.log_dir() / "autovalidate.log")
        self.logger = logging.getLogger(LOGGER_NAME)
        self.relay = _Relay()
        self._entries: deque[tuple[str, int]] = deque(maxlen=MAX_ENTRIES)
        self._load_tail()
        self._memory = _MemoryHandler(self._entries, self.relay)
        self.logger.addHandler(self._memory)
        self._file: RotatingFileHandler | None = None
        self._open_file()

    def _open_file(self) -> None:
        try:
            handler = RotatingFileHandler(
                self.file_path, maxBytes=FILE_MAX_BYTES, backupCount=FILE_BACKUPS, encoding="utf-8"
            )
        except OSError as exc:
            logging.getLogger("optixplus").warning("Journal de la surveillance indisponible : %s", exc)
            return
        handler.setFormatter(logging.Formatter(FORMAT, DATE_FORMAT))
        self.logger.addHandler(handler)
        self._file = handler

    def _close_file(self) -> None:
        if self._file is not None:
            self.logger.removeHandler(self._file)
            self._file.close()
            self._file = None

    def _load_tail(self, max_lines: int = 200) -> None:
        """Recharge la fin du fichier : la page montre aussi l'historique des sessions précédentes."""
        try:
            with self.file_path.open("r", encoding="utf-8", errors="replace") as fh:
                lines = deque(fh, maxlen=max_lines)
        except OSError:
            return
        for line in lines:
            line = line.rstrip("\r\n")
            if line:
                level = logging.WARNING if " WARNING " in line else logging.ERROR if " ERROR " in line else logging.INFO
                self._entries.append((line, level))

    def entries(self) -> list[tuple[str, int]]:
        return list(self._entries)

    def clear(self) -> None:
        """Vide l'historique et le fichier, en rouvrant proprement le fichier (sans API privée)."""
        self._entries.clear()
        self._close_file()
        try:
            self.file_path.write_text("", encoding="utf-8")
        except OSError as exc:
            logging.getLogger("optixplus").warning("Effacement du journal de la surveillance impossible : %s", exc)
        self._open_file()
        self.relay.cleared.emit()

    def close(self) -> None:
        self.logger.removeHandler(self._memory)
        self._close_file()
