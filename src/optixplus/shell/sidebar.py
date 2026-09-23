"""Barre latérale de navigation : Accueil, les outils, puis Paramètres en bas."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QButtonGroup, QFrame, QScrollArea, QToolButton, QVBoxLayout, QWidget

from ..common import icons
from ..common.i18n import tr
from ..modules import MODULES

HOME_ID = "home"
SIDEBAR_WIDTH = 84
ICON_SIZE = 24


def wrap_label(text: str, metrics: QFontMetrics, width: int) -> str:
    """Coupe un libellé trop large en deux lignes, à l'espace qui équilibre le mieux.

    ``QToolButton`` ne replie pas son texte : sans cela, « Lecteur de logs » serait
    tronqué en « Lecteu…e logs ».
    """
    if metrics.horizontalAdvance(text) <= width or " " not in text:
        return text
    words = text.split(" ")
    best = text
    best_width = None
    for i in range(1, len(words)):
        first, second = " ".join(words[:i]), " ".join(words[i:])
        widest = max(metrics.horizontalAdvance(first), metrics.horizontalAdvance(second))
        if best_width is None or widest < best_width:
            best, best_width = f"{first}\n{second}", widest
    return best


class Sidebar(QFrame):
    """Boutons exclusifs : un clic émet l'identifiant de la page demandée."""

    page_requested = Signal(str)
    settings_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(SIDEBAR_WIDTH)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 6, 0, 6)
        outer.setSpacing(2)
        # Les outils défilent si la fenêtre est trop basse (prévu pour de futurs outils) ;
        # Paramètres reste toujours visible en bas.
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        scroll.setWidget(container)
        outer.addWidget(scroll, 1)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QToolButton] = {}
        self._icon_names: dict[str, str] = {}

        entries = [(HOME_ID, tr("Home"), "home", "Ctrl+0")]
        entries += [(m.id, tr(m.title), m.icon, m.shortcut) for m in MODULES]
        for page_id, label, icon_name, shortcut in entries:
            button = self._make_button(label, icon_name, f"{label} ({shortcut})")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, pid=page_id: self.page_requested.emit(pid))
            self._group.addButton(button)
            self._buttons[page_id] = button
            self._icon_names[page_id] = icon_name
            layout.addWidget(button)
        layout.addStretch(1)

        self._settings = self._make_button(tr("Settings"), "settings", tr("Settings"))
        self._settings.clicked.connect(self.settings_requested)
        outer.addWidget(self._settings)

    def _make_button(self, label: str, icon_name: str, tooltip: str) -> QToolButton:
        button = QToolButton(self)
        button.setText(wrap_label(label, button.fontMetrics(), SIDEBAR_WIDTH - 12))
        button.setToolTip(tooltip)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        button.setIcon(icons.themed_icon(icon_name, highlight_when_checked=True))
        button.setFixedWidth(SIDEBAR_WIDTH)
        button.setMinimumHeight(64)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def set_current(self, page_id: str) -> None:
        button = self._buttons.get(page_id)
        if button is not None:
            button.setChecked(True)

    def refresh_icons(self) -> None:
        """Recolore les icônes après un changement de thème."""
        for page_id, button in self._buttons.items():
            button.setIcon(icons.themed_icon(self._icon_names[page_id], highlight_when_checked=True))
        self._settings.setIcon(icons.themed_icon("settings", highlight_when_checked=True))
