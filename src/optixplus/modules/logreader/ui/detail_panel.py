"""Panneau de détail de la ligne sélectionnée.

Le tableau ne montre qu'une ligne de texte par entrée ; ce panneau restitue le
message complet avec ses retours à la ligne (les tabulations du fichier), la
pile d'appels éventuelle et le chemin du nœud, le tout sélectionnable pour
pouvoir être copié.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QVBoxLayout, QWidget,
)

from ..theme import Palette
from .log_model import level_label

LEVEL_COLOR_KEYS = {"ERROR": "error", "WARNING": "warning", "INFO": "info"}


class DetailPanel(QWidget):
    """Affiche l'intégralité d'une entrée de journal."""

    def __init__(self, palette: Palette, parent=None):
        super().__init__(parent)
        self.palette_ = palette
        self._entry = None
        self._build()
        self.show_entry(None)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(10)

        self.level_badge = QLabel()
        self.level_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.level_badge.setMinimumWidth(104)
        header.addWidget(self.level_badge)

        self.timestamp_label = QLabel()
        font = QFont(self.timestamp_label.font())
        font.setBold(True)
        self.timestamp_label.setFont(font)
        self.timestamp_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        header.addWidget(self.timestamp_label)

        self.meta_label = QLabel()
        self.meta_label.setProperty("muted", True)
        self.meta_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        header.addWidget(self.meta_label, 1)

        layout.addLayout(header)

        self.message_view = QPlainTextEdit()
        self.message_view.setReadOnly(True)
        self.message_view.setFrameShape(QFrame.Shape.NoFrame)
        layout.addWidget(self.message_view, 3)

        self.details_title = QLabel("Détails techniques")
        self.details_title.setProperty("muted", True)
        layout.addWidget(self.details_title)

        self.details_view = QPlainTextEdit()
        self.details_view.setReadOnly(True)
        self.details_view.setFrameShape(QFrame.Shape.NoFrame)
        monospace = QFont("Consolas")
        monospace.setStyleHint(QFont.StyleHint.Monospace)
        monospace.setPointSizeF(max(7.5, self.font().pointSizeF() - 1.0))
        self.details_view.setFont(monospace)
        layout.addWidget(self.details_view, 2)

        self.node_label = QLabel()
        self.node_label.setWordWrap(True)
        self.node_label.setProperty("muted", True)
        self.node_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.node_label)

    def set_palette_colors(self, palette: Palette) -> None:
        self.palette_ = palette
        self.show_entry(self._entry)

    def show_entry(self, entry) -> None:
        self._entry = entry
        if entry is None:
            self.level_badge.setText("")
            self.level_badge.setStyleSheet("")
            self.timestamp_label.setText("")
            self.meta_label.setText("")
            self.message_view.setPlainText("")
            self.message_view.setPlaceholderText(
                "Sélectionnez une ligne du journal pour en afficher le détail."
            )
            self.details_title.hide()
            self.details_view.hide()
            self.node_label.setText("")
            return

        colour = getattr(self.palette_, LEVEL_COLOR_KEYS.get(entry.level, "text_muted"))
        self.level_badge.setText(level_label(entry.level).upper())
        self.level_badge.setStyleSheet(
            f"background: {colour}; color: {self.palette_.accent_text}; "
            f"border-radius: 5px; padding: 3px 10px; font-weight: 700; font-size: 11px;"
        )

        self.timestamp_label.setText(entry.timestamp_text or "horodatage absent")

        meta = [f"Source : {entry.source or '—'}"]
        if entry.code:
            meta.append(f"Code : {entry.code}")
        meta.append(f"Ligne n° {entry.index + 1}")
        self.meta_label.setText("     ".join(meta))

        self.message_view.setPlainText(entry.message_multiline)

        details = entry.details_multiline
        self.details_title.setVisible(bool(details))
        self.details_view.setVisible(bool(details))
        self.details_view.setPlainText(details)

        self.node_label.setText(f"Nœud : {entry.node_path}" if entry.node_path else "")
