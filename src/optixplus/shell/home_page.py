"""Page d'accueil : accès aux outils et tableau de bord.

Les cartes « Surveillance », « Projets récents » et « Automates récents » sont
alimentées au fil du portage des outils.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..common import icons
from ..common.i18n import tr
from ..modules import MODULES
from ..version import __version__


class _ToolTile(QFrame):
    """Tuile cliquable d'un outil : icône, titre, description.

    Un ``QFrame`` et non un ``QPushButton`` : la feuille de style impose aux boutons une
    hauteur minimale qui écraserait la tuile, et un bouton ne sait pas replier son texte.
    """

    clicked = Signal()

    def __init__(self, icon_name: str, title: str, description: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("tile", True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._icon_name = icon_name
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(14)
        self._icon = QLabel()
        self._icon.setFixedSize(36, 36)
        self._icon.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignTop)
        texts = QVBoxLayout()
        texts.setSpacing(4)
        name = QLabel(title)
        name.setProperty("heading", True)
        desc = QLabel(description)
        desc.setProperty("muted", True)
        desc.setWordWrap(True)
        for label in (name, desc):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            texts.addWidget(label)
        texts.addStretch(1)
        layout.addLayout(texts, 1)
        self.refresh_icon()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (API Qt)
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 (API Qt)
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit()
            return
        super().keyPressEvent(event)

    def refresh_icon(self) -> None:
        icon = icons.themed_icon(self._icon_name, highlight_when_checked=True)
        self._icon.setPixmap(icon.pixmap(QSize(32, 32), QIcon.Mode.Normal, QIcon.State.On))


class _Card(QFrame):
    """Carte du tableau de bord : titre et contenu libre."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(16, 14, 16, 14)
        self.body.setSpacing(8)
        heading = QLabel(title)
        heading.setProperty("heading", True)
        self.body.addWidget(heading)

    def add_muted(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("muted", True)
        label.setWordWrap(True)
        self.body.addWidget(label)
        return label


class HomePage(QScrollArea):
    """Accueil de la fenêtre principale."""

    tool_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        self.setWidget(content)
        outer = QVBoxLayout(content)
        outer.setContentsMargins(32, 28, 32, 28)
        outer.setSpacing(20)

        header = QHBoxLayout()
        header.setSpacing(16)
        logo = QLabel()
        logo.setPixmap(icons.app_icon().pixmap(QSize(56, 56)))
        header.addWidget(logo)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = QLabel(tr("Welcome to OptixPlus"))
        title.setProperty("title", True)
        subtitle = QLabel(tr("Your FactoryTalk Optix toolbox · version {version}").format(version=__version__))
        subtitle.setProperty("muted", True)
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header.addLayout(titles, 1)
        outer.addLayout(header)

        tools_label = QLabel(tr("Tools"))
        tools_label.setProperty("heading", True)
        outer.addWidget(tools_label)
        grid = QGridLayout()
        grid.setSpacing(12)
        self._tiles: list[_ToolTile] = []
        for index, module in enumerate(MODULES):
            tile = _ToolTile(module.icon, tr(module.title), tr(module.description))
            tile.setToolTip(f"{tr(module.title)} ({module.shortcut})")
            tile.clicked.connect(lambda mid=module.id: self.tool_requested.emit(mid))
            grid.addWidget(tile, index // 2, index % 2)
            self._tiles.append(tile)
        outer.addLayout(grid)

        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.watch_card = _Card(tr("FT Optix Studio monitoring"))
        self.watch_card.add_muted(tr("Available once Auto Validate is integrated."))
        self.projects_card = _Card(tr("Recent projects"))
        self.projects_card.add_muted(tr("No recent project."))
        self.plcs_card = _Card(tr("Recent controllers"))
        self.plcs_card.add_muted(tr("No recent controller."))
        for card in (self.watch_card, self.projects_card, self.plcs_card):
            cards.addWidget(card, 1)
        outer.addLayout(cards)
        outer.addStretch(1)

    def refresh_icons(self) -> None:
        for tile in self._tiles:
            tile.refresh_icon()
