"""Panneau journal : les enregistrements ``logging`` du moteur s'affichent dans l'application."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QPlainTextEdit, QWidget


class _Relay(QObject):
    """Un QObject porteur de signal : ``logging.Handler`` ne peut pas en émettre lui-même."""

    record = Signal(str, int)


class QtLogHandler(logging.Handler):
    """Handler ``logging`` thread-safe : le texte est émis par signal et affiché dans le thread UI."""

    def __init__(self) -> None:
        super().__init__()
        self.relay = _Relay()
        self.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-8s %(name)s — %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.relay.record.emit(self.format(record), record.levelno)
        except RuntimeError:
            pass  # relais détruit à la fermeture


class LogPanel(QPlainTextEdit):
    """Zone de texte en lecture seule, branchée sur le logger ``ftocompare``."""

    MAX_LIGNES = 5000

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(self.MAX_LIGNES)
        self.setPlaceholderText("Journal de l'application")
        self.handler = QtLogHandler()
        self.handler.relay.record.connect(self._append)
        logger = logging.getLogger("optixplus.modules.compare")
        logger.addHandler(self.handler)
        if logger.getEffectiveLevel() > logging.INFO:
            logger.setLevel(logging.INFO)  # sans configuration globale, rien n'arriverait au journal

    def _append(self, text: str, level: int) -> None:
        if level >= logging.ERROR:
            self.appendHtml(f'<span style="color:#c62828">{_escape(text)}</span>')
        elif level >= logging.WARNING:
            self.appendHtml(f'<span style="color:#ef6c00">{_escape(text)}</span>')
        else:
            self.appendPlainText(text)

    def detach(self) -> None:
        logging.getLogger("optixplus.modules.compare").removeHandler(self.handler)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
