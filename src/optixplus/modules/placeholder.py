"""Page d'attente des outils pas encore portés dans OptixPlus."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..common.i18n import tr
from .base import ToolModule


class PlaceholderModule(ToolModule):
    """Outil annoncé mais pas encore intégré."""

    def create_page(self, parent: QWidget) -> QWidget:
        page = QWidget(parent)
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel(tr(self.spec.title))
        title.setProperty("title", True)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text = QLabel(tr("This tool is being integrated into OptixPlus and will be available soon."))
        text.setProperty("muted", True)
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        layout.addWidget(text)
        return page
