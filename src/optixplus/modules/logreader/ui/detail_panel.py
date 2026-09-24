"""Panneau de détail de la ligne sélectionnée.

Le tableau ne montre qu'une ligne de texte par entrée ; ce panneau restitue le
message complet avec ses retours à la ligne (les tabulations du fichier), la
pile d'appels éventuelle et, dans l'en-tête, le chemin du nœud. Le texte est
sélectionnable pour pouvoir être copié.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QFont, QGuiApplication
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QVBoxLayout, QWidget,
)

from ....common.i18n import tr
from ....common.widgets import ElidedLabel
from ....common.theme import Palette
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
        header.addWidget(self.meta_label)

        # Chemin du nœud à droite du numéro de ligne : une ligne de moins sous le message.
        # Abrégé au milieu s'il manque de place ; l'infobulle donne le chemin complet et
        # le clic droit le copie. Pas de sélection à la souris : sur un libellé abrégé
        # (texte remplacé à chaque redimensionnement), elle fait planter Qt.
        self.node_label = ElidedLabel(mode=Qt.TextElideMode.ElideMiddle)
        self.node_label.setProperty("muted", True)
        copy_node = QAction(tr("Copy the node path"), self.node_label)
        copy_node.triggered.connect(self._copy_node_path)
        self.node_label.addAction(copy_node)
        self.node_label.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        header.addSpacing(12)
        header.addWidget(self.node_label, 1)

        layout.addLayout(header)

        self.message_view = QPlainTextEdit()
        self.message_view.setReadOnly(True)
        self.message_view.setFrameShape(QFrame.Shape.NoFrame)
        layout.addWidget(self.message_view, 3)

        self.details_title = QLabel(tr("Technical details"))
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

    def _copy_node_path(self) -> None:
        if self._entry is not None and self._entry.node_path:
            QGuiApplication.clipboard().setText(self._entry.node_path)

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
                tr("Select a line of the log to show its details.")
            )
            self.details_title.hide()
            self.details_view.hide()
            self.node_label.setText("")
            self.node_label.setToolTip("")
            return

        colour = getattr(self.palette_, LEVEL_COLOR_KEYS.get(entry.level, "text_muted"))
        self.level_badge.setText(level_label(entry.level).upper())
        self.level_badge.setStyleSheet(
            f"background: {colour}; color: {self.palette_.accent_text}; "
            f"border-radius: 5px; padding: 3px 10px; font-weight: 700; font-size: 11px;"
        )

        self.timestamp_label.setText(entry.timestamp_text or tr("no timestamp"))

        meta = [tr("Source: {source}").format(source=entry.source or "—")]
        if entry.code:
            meta.append(tr("Code: {code}").format(code=entry.code))
        meta.append(tr("Line no. {n}").format(n=entry.index + 1))
        self.meta_label.setText("     ".join(meta))

        self.message_view.setPlainText(entry.message_multiline)

        details = entry.details_multiline
        self.details_title.setVisible(bool(details))
        self.details_view.setVisible(bool(details))
        self.details_view.setPlainText(details)

        node = tr("Node: {path}").format(path=entry.node_path) if entry.node_path else ""
        self.node_label.setText(node)
        self.node_label.setToolTip(entry.node_path or "")
