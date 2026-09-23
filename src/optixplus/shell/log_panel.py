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


def append_colored(view: QPlainTextEdit, text: str, level: int) -> None:
    """Ajoute une ligne de journal : avertissements et erreurs colorés, le reste à la couleur du texte."""
    p = theme.current()
    if level >= logging.ERROR:
        view.appendHtml(f'<span style="color:{p.error}">{html.escape(text)}</span>')
    elif level >= logging.WARNING:
        view.appendHtml(f'<span style="color:{p.warning}">{html.escape(text)}</span>')
    else:
        # Texte brut : il suit la palette, sans couleur figée.
        view.appendPlainText(text)


class LogPanel(QPlainTextEdit):
    """Zone de texte en lecture seule branchée sur le logger ``optixplus``."""

    MAX_LINES = 5000

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(self.MAX_LINES)
        self.setPlaceholderText(tr("Application log"))
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        handler = logging_setup.memory_handler()
        self._handler = handler
        self._recolor()
        handler.relay.record.connect(self._append)
        theme.follow(self, self._recolor)

    def _append(self, text: str, level: int) -> None:
        append_colored(self, text, level)

    def _recolor(self, _palette=None) -> None:
        """Les couleurs sont figées dans le texte : on le reconstruit au changement de thème."""
        self.clear()
        for text, level in list(self._handler.buffer):
            append_colored(self, text, level)

    def detach(self) -> None:
        try:
            self._handler.relay.record.disconnect(self._append)
        except (RuntimeError, TypeError):
            pass
