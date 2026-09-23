"""Page d'accueil : accès aux outils et tableau de bord.

Les cartes « Surveillance », « Projets récents » et « Automates récents » sont
alimentées au fil du portage des outils.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame,
    QMenu,
    QToolButton,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..common import icons
from ..common.i18n import tr
from ..common.recent import recent_controllers, recent_projects
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


class _RecentProjects(QWidget):
    """Projets récents : un clic ouvre le projet dans l'outil choisi."""

    requested = Signal(str, str)  # (outil, dossier)

    def __init__(self, settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)
        self.refresh()

    def refresh(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        projects = recent_projects(self._settings)[:6]
        if not projects:
            empty = QLabel(tr("No recent project."))
            empty.setProperty("muted", True)
            self._layout.addWidget(empty)
            return
        for path in projects:
            button = QToolButton()
            button.setText(os.path.basename(path.rstrip("\\/")) or path)
            button.setToolTip(path)
            button.setProperty("link", True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            button.clicked.connect(lambda _c=False, p=path, b=button: self._open(p, b))
            self._layout.addWidget(button)

    def _open(self, path: str, button: QToolButton) -> None:
        tools = [m for m in MODULES if m.opens_projects]
        if len(tools) == 1:
            self.requested.emit(tools[0].id, path)
            return
        menu = QMenu(self)
        for tool in tools:
            menu.addAction(icons.themed_icon(tool.icon), tr(tool.title), lambda t=tool.id: self.requested.emit(t, path))
        menu.exec(button.mapToGlobal(button.rect().bottomLeft()))


class _RecentControllers(QWidget):
    """Automates récents : un clic ouvre l'automate dans l'outil choisi."""

    requested = Signal(str, str)  # (outil, adresse)

    def __init__(self, settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)
        self.refresh()

    def refresh(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        controllers = recent_controllers(self._settings)[:6]
        if not controllers:
            empty = QLabel(tr("No recent controller."))
            empty.setProperty("muted", True)
            self._layout.addWidget(empty)
            return
        for host, name in controllers:
            button = QToolButton()
            button.setText(name)
            button.setToolTip(host)
            button.setProperty("link", True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            button.clicked.connect(lambda _c=False, h=host, b=button: self._open(h, b))
            self._layout.addWidget(button)

    def _open(self, host: str, button: QToolButton) -> None:
        tools = [m for m in MODULES if m.controller_action]
        if len(tools) == 1:
            self.requested.emit(tools[0].id, host)
            return
        menu = QMenu(self)
        for tool in tools:
            menu.addAction(icons.themed_icon(tool.icon), tr(tool.title), lambda t=tool.id: self.requested.emit(t, host))
        menu.exec(button.mapToGlobal(button.rect().bottomLeft()))


class HomePage(QScrollArea):
    """Accueil de la fenêtre principale."""

    tool_requested = Signal(str)
    project_requested = Signal(str, str)  # (outil, dossier)
    controller_requested = Signal(str, str)  # (outil, adresse de l'automate)

    def __init__(self, services: dict | None = None, settings=None, parent: QWidget | None = None) -> None:
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
        service_cards = []
        for service in (services or {}).values():
            card = _Card(tr(service.spec.title))
            widget = service.summary_widget(card)
            if widget is None:
                continue
            card.body.addWidget(widget)
            card.body.addStretch(1)
            service_cards.append(card)
        self.projects_card = _Card(tr("Recent projects"))
        self.recent = _RecentProjects(settings) if settings is not None else None
        if self.recent is not None:
            self.recent.requested.connect(self.project_requested)
            self.projects_card.body.addWidget(self.recent)
            self.projects_card.body.addStretch(1)
        self.plcs_card = _Card(tr("Recent controllers"))
        self.controllers = _RecentControllers(settings) if settings is not None else None
        if self.controllers is not None:
            self.controllers.requested.connect(self.controller_requested)
            self.plcs_card.body.addWidget(self.controllers)
            self.plcs_card.body.addStretch(1)
        for card in (*service_cards, self.projects_card, self.plcs_card):
            cards.addWidget(card, 1)
        outer.addLayout(cards)
        outer.addStretch(1)

    def showEvent(self, event) -> None:  # noqa: N802 (API Qt)
        # La liste a pu changer pendant qu'un outil était affiché.
        if self.recent is not None:
            self.recent.refresh()
        if self.controllers is not None:
            self.controllers.refresh()
        super().showEvent(event)

    def refresh_icons(self) -> None:
        for tile in self._tiles:
            tile.refresh_icon()
