"""Panneau Journal commun à tous les outils (repris de FTOCompare).

Le panneau affiche le tampon mémoire du journal : fermé puis rouvert, il retrouve
l'historique récent.
"""

from __future__ import annotations

import html
import logging

from PySide6.QtWidgets import QPlainTextEdit, QWidget

from ..common import logging_setup, theme
from ..common.i18n import tr


class LogPanel(QPlainTextEdit):
    """Zone de texte en lecture seule branchée sur le logger ``optixplus``."""

    MAX_LINES = 5000

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(self.MAX_LINES)
        self.setPlaceholderText(tr("Application log"))
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        handler = logging_setup.memory_handler()
        for text, level in list(handler.buffer):
            self._append(text, level)
        handler.relay.record.connect(self._append)
        self._handler = handler

    def _append(self, text: str, level: int) -> None:
        p = theme.current()
        if level >= logging.ERROR:
            self.appendHtml(f'<span style="color:{p.error}">{html.escape(text)}</span>')
        elif level >= logging.WARNING:
            self.appendHtml(f'<span style="color:{p.warning}">{html.escape(text)}</span>')
        else:
            self.appendHtml(f'<span style="color:{p.text}">{html.escape(text)}</span>')

    def detach(self) -> None:
        try:
            self._handler.relay.record.disconnect(self._append)
        except (RuntimeError, TypeError):
            pass
