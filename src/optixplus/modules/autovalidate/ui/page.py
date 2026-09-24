"""Page de l'outil Auto Validate : état et journal de la surveillance.

Reprend la boîte « Journal » de l'ancien Auto Validate ; ses réglages sont dans la
boîte Paramètres de l'application (``settings_page``).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QFontDatabase
from PySide6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from ....common import signals, theme
from ....shell.log_panel import append_colored
from ....common.i18n import tr

if TYPE_CHECKING:
    from ..service import AutoValidateService


class AutoValidatePage(QWidget):
    def __init__(self, service: AutoValidateService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(16)

        # ---- en-tête : état --------------------------------------------------------
        header = QFrame()
        header.setProperty("card", True)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 12, 16, 12)
        texts = QVBoxLayout()
        self.state_label = QLabel()
        self.state_label.setProperty("heading", True)
        explanation = QLabel(
            tr(
                "Automatically confirms the “Project already exists” prompt that FT Optix Studio shows "
                "at each deployment, by pressing Enter (default button “Update”)."
            )
        )
        explanation.setProperty("muted", True)
        explanation.setWordWrap(True)
        texts.addWidget(self.state_label)
        texts.addWidget(explanation)
        if not service.persistent:
            discovery = QLabel(
                tr(
                    "Discovery mode: monitoring stops when the window is closed. Install OptixPlus "
                    "to keep it running in the notification area."
                )
            )
            discovery.setProperty("muted", True)
            discovery.setWordWrap(True)
            texts.addWidget(discovery)
        header_layout.addLayout(texts, 1)
        outer.addWidget(header)

        outer.addWidget(self._build_journal(), 1)

        # Signaux du service (durable) : relayés tant que la page existe.
        signals.follow(service.state_changed, self, self.refresh_state)
        signals.follow(service.activity.relay.entry_added, self, self._append)
        signals.follow(service.activity.relay.cleared, self, self._clear_journal)
        self.refresh_state()
        self._recolor()
        theme.follow(self, self._recolor)

    def snapshot(self) -> dict:
        """Défilement du journal (les réglages sont dans la boîte Paramètres)."""
        bar = self.journal.verticalScrollBar()
        return {"journal_scroll": bar.value(), "journal_at_end": bar.value() >= bar.maximum()}

    def restore(self, state: dict) -> None:
        bar = self.journal.verticalScrollBar()
        bar.setValue(bar.maximum() if state.get("journal_at_end", True) else state.get("journal_scroll", 0))

    # ---- journal -----------------------------------------------------------------
    def _build_journal(self) -> QWidget:
        box = QGroupBox(tr("Monitoring log"))
        layout = QVBoxLayout(box)
        self.journal = QPlainTextEdit()
        self.journal.setReadOnly(True)
        self.journal.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.journal.setMaximumBlockCount(2000)
        self.journal.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        layout.addWidget(self.journal, 1)
        return box

    def open_log_file(self) -> None:
        path = self._service.activity.file_path
        if not path.exists():
            try:
                path.touch()
            except OSError:
                return
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.fspath(path)))

    def open_log_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.fspath(self._service.activity.file_path.parent)))

    def _clear_journal(self) -> None:
        self.journal.clear()

    def _append(self, line: str, level: int) -> None:
        append_colored(self.journal, line, level)
        bar = self.journal.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _recolor(self, _palette=None) -> None:
        """Les couleurs sont figées dans le texte : on le reconstruit au changement de thème."""
        self.journal.clear()
        for line, level in self._service.activity.entries():
            append_colored(self.journal, line, level)

    # ---- état --------------------------------------------------------------------
    def refresh_state(self) -> None:
        service = self._service
        self.state_label.setText(service.status_text())
