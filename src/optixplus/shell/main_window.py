"""Fenêtre principale : menus, barre d'outils contextuelle, barre latérale, pages des outils.

Les outils sont chargés à la première ouverture de leur page. Fermer la fenêtre la
détruit, avec toutes les pages : en mode installé, seuls le tray et les services
d'arrière-plan restent en mémoire.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QByteArray, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QToolBar,
    QWidget,
)

from ..common import icons
from ..common.i18n import tr
from ..common.theme import THEMES, theme_label
from ..modules import MODULES, spec
from ..modules.base import ToolModule
from ..version import APP_NAME, __version__
from .context import AppContext
from .home_page import HomePage
from .log_panel import LogPanel
from .sidebar import HOME_ID, Sidebar

log = logging.getLogger("optixplus.shell")


class _ServiceStatus(QLabel):
    """État d'un service dans la barre d'état ; la connexion meurt avec le libellé."""

    def __init__(self, service) -> None:
        super().__init__()
        self._service = service
        self.setProperty("muted", True)
        service.state_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        self.setText(self._service.status_text())


class MainWindow(QMainWindow):
    """Fenêtre unique de l'application."""

    closed = Signal()

    def __init__(self, context: AppContext) -> None:
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setObjectName("OptixPlusMainWindow")
        self.context = context
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(icons.app_icon())
        self.resize(1280, 800)
        self.setMinimumSize(900, 560)

        self._modules: dict[str, ToolModule] = {}
        self._pages: dict[str, QWidget] = {}
        self._current = ""

        self._toolbar = QToolBar(tr("Tool actions"), self)
        self._toolbar.setObjectName("contextToolbar")
        self._toolbar.setMovable(False)
        self._toolbar.setFloatable(False)
        self._toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._toolbar.toggleViewAction().setEnabled(False)
        self.addToolBar(self._toolbar)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.sidebar = Sidebar()
        self.sidebar.page_requested.connect(self.show_page)
        self.sidebar.settings_requested.connect(context.controller.open_settings)
        self._stack = QStackedWidget()
        layout.addWidget(self.sidebar)
        layout.addWidget(self._stack, 1)
        self.setCentralWidget(central)

        self.home = HomePage(context.services)
        self.home.tool_requested.connect(self.show_page)
        self._pages[HOME_ID] = self.home
        self._stack.addWidget(self.home)

        self._log_panel = LogPanel()
        self._log_dock = QDockWidget(tr("Log"), self)
        self._log_dock.setObjectName("logDock")
        self._log_dock.setWidget(self._log_panel)
        self._log_dock.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._log_dock)

        self._status = QLabel()
        self._status.setProperty("muted", True)
        self.statusBar().addWidget(self._status, 1)
        for service in context.services.values():
            self.statusBar().addPermanentWidget(_ServiceStatus(service))
        version = QLabel(f"v{__version__}")
        version.setProperty("muted", True)
        self.statusBar().addPermanentWidget(version)

        self._build_menus()
        self._restore_layout()
        context.theme.changed.connect(self._on_theme_changed)

        start = context.settings.general.last_tool
        self.show_page(start if spec(start) is not None else HOME_ID)

    # ---- menus ------------------------------------------------------------------
    def _build_menus(self) -> None:
        controller = self.context.controller
        bar = self.menuBar()

        file_menu = bar.addMenu(tr("&File"))
        close_action = file_menu.addAction(tr("Close window"))
        close_action.setShortcut(QKeySequence("Ctrl+W"))
        close_action.triggered.connect(self.close)
        file_menu.addSeparator()
        quit_action = file_menu.addAction(tr("&Quit OptixPlus"))
        quit_action.setShortcut(QKeySequence("Ctrl+Q"))
        quit_action.triggered.connect(controller.quit)

        tools_menu = bar.addMenu(tr("&Tools"))
        home_action = tools_menu.addAction(icons.themed_icon("home"), tr("Home"))
        home_action.setShortcut(QKeySequence("Ctrl+0"))
        home_action.triggered.connect(lambda: self.show_page(HOME_ID))
        tools_menu.addSeparator()
        for module in MODULES:
            action = tools_menu.addAction(icons.themed_icon(module.icon), tr(module.title))
            action.setShortcut(QKeySequence(module.shortcut))
            action.triggered.connect(lambda _c=False, mid=module.id: self.show_page(mid))
        tools_menu.addSeparator()
        settings_action = tools_menu.addAction(icons.themed_icon("settings"), tr("Settings…"))
        settings_action.setShortcut(QKeySequence("Ctrl+,"))
        settings_action.triggered.connect(controller.open_settings)

        view_menu = bar.addMenu(tr("&View"))
        theme_menu = view_menu.addMenu(tr("Theme"))
        group = QActionGroup(self)
        for code in THEMES:
            action = theme_menu.addAction(theme_label(code))
            action.setCheckable(True)
            action.setData(code)
            action.setChecked(code == self.context.theme.theme)
            action.triggered.connect(lambda _c=False, t=code: self._set_theme(t))
            group.addAction(action)
        self._theme_actions = group
        log_action = self._log_dock.toggleViewAction()
        log_action.setText(tr("Log"))
        log_action.setShortcut(QKeySequence("Ctrl+J"))
        view_menu.addAction(log_action)

        help_menu = bar.addMenu(tr("&Help"))
        about_action = help_menu.addAction(icons.themed_icon("info"), tr("About OptixPlus"))
        about_action.triggered.connect(controller.open_about)

    def _set_theme(self, theme: str) -> None:
        self.context.settings.general.theme = theme
        self.context.theme.set_theme(theme)
        self.context.settings.save()

    def _on_theme_changed(self, _palette) -> None:
        icons.clear_cache()
        self.sidebar.refresh_icons()
        self.home.refresh_icons()
        for action in self._theme_actions.actions():
            action.setChecked(action.data() == self.context.theme.theme)

    # ---- navigation ------------------------------------------------------------
    @property
    def current_page(self) -> str:
        return self._current

    def module(self, module_id: str) -> ToolModule | None:
        return self._modules.get(module_id)

    def _load_module(self, module_id: str) -> QWidget | None:
        module_spec = spec(module_id)
        if module_spec is None:
            return None
        try:
            module = module_spec.load()(module_spec, self.context, self)
            page = module.create_page(self._stack)
        except Exception:
            log.exception("Chargement de l'outil %s impossible", module_id)
            QMessageBox.critical(
                self, APP_NAME, tr("The tool “{tool}” could not be loaded. See the log for details.").format(
                    tool=tr(module_spec.title)
                )
            )
            return None
        log.info("Outil chargé : %s", module_spec.title)
        self._modules[module_id] = module
        self._pages[module_id] = page
        self._stack.addWidget(page)
        return page

    def show_page(self, page_id: str) -> None:
        if page_id == self._current:
            return
        page = self._pages.get(page_id) or self._load_module(page_id)
        if page is None:
            self.sidebar.set_current(self._current or HOME_ID)
            return
        previous = self._modules.get(self._current)
        if previous is not None:
            previous.on_deactivated()
        self._current = page_id
        self._stack.setCurrentWidget(page)
        self.sidebar.set_current(page_id)
        self._set_toolbar(self._modules.get(page_id))
        module = self._modules.get(page_id)
        title = tr(module.spec.title) if module else ""
        self.setWindowTitle(f"{title} — {APP_NAME}" if title else APP_NAME)
        if module is not None:
            module.on_activated()
        self.context.settings.general.last_tool = page_id

    def _set_toolbar(self, module: ToolModule | None) -> None:
        self._toolbar.clear()
        actions: list[QAction | None] = module.toolbar_actions() if module else []
        for action in actions:
            if action is None:
                self._toolbar.addSeparator()
            else:
                self._toolbar.addAction(action)
        self._toolbar.setVisible(bool(actions))

    def handle_command(self, command: str, args: list[str]) -> None:
        """Demande venue du tray ou d'un second lancement."""
        if command == "open-tool" and args:
            self.show_page(args[0])
            return
        module_id = args[0] if args else ""
        if module_id:
            self.show_page(module_id)
            module = self._modules.get(module_id)
            if module is not None and module.handle_command(command, args[1:]):
                return
        log.warning("Demande non reconnue : %s %s", command, args)

    def show_status(self, text: str) -> None:
        self._status.setText(text)

    # ---- fermeture -----------------------------------------------------------
    def _restore_layout(self) -> None:
        general = self.context.settings.general
        if general.window_geometry:
            self.restoreGeometry(QByteArray.fromBase64(general.window_geometry.encode("ascii")))
        if general.window_state:
            self.restoreState(QByteArray.fromBase64(general.window_state.encode("ascii")))
        self._log_dock.setVisible(general.show_log_panel)

    def _save_layout(self) -> None:
        general = self.context.settings.general
        general.window_geometry = bytes(self.saveGeometry().toBase64().data()).decode("ascii")
        general.window_state = bytes(self.saveState().toBase64().data()).decode("ascii")
        general.show_log_panel = self._log_dock.isVisible()

    def can_close(self) -> bool:
        return all(module.can_close() for module in self._modules.values())

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (API Qt)
        if not self.can_close():
            event.ignore()
            return
        self._save_layout()
        for module in self._modules.values():
            try:
                module.shutdown()
            except Exception:
                log.exception("Arrêt de l'outil %s en erreur", module.spec.id)
        self._log_panel.detach()
        self.context.settings.save()
        event.accept()
        self.closed.emit()
