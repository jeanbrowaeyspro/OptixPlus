"""Page du Lecteur de logs : plusieurs journaux en onglets, à la façon de Visual Studio.

Les onglets sont gérés par Qt Advanced Docking System (PySide6-QtAds) : on les regroupe
côte à côte (gauche/droite, haut/bas) en les faisant glisser, on les sort dans des
fenêtres flottantes, on les pose sur un autre écran. C'est uniquement de l'organisation
visuelle : chaque onglet affiche sa propre session, sans comparaison entre journaux.

La barre d'actions agit sur l'onglet actif, sauf « Nouvel onglet » et les réglages.
"""

from __future__ import annotations

import logging

import PySide6QtAds as QtAds
from PySide6.QtCore import QByteArray, QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QLabel, QMessageBox, QPushButton, QStackedLayout, QVBoxLayout, QWidget

from ....common import icons
from ....common import theme as common_theme
from ....common.i18n import tr
from ..core.config import Settings
from ..core.discovery import Ipc
from ..session import LogSession
from .connect_dialog import ConnectDialog
from .log_tab import LogTab
from .settings_dialog import SettingsDialog
from .status_indicator import STATE_CONNECTING, STATE_LOST, STATE_ONLINE

log = logging.getLogger("optixplus.logreader")

_FLAGS_SET = False


def _configure_docking() -> None:
    """Comportement des onglets, fixé une fois avant la création du premier gestionnaire."""
    global _FLAGS_SET
    if _FLAGS_SET:
        return
    manager = QtAds.CDockManager
    flag = manager.eConfigFlag
    for name, value in (
        (flag.OpaqueSplitterResize, True),
        (flag.FocusHighlighting, True),
        (flag.AllTabsHaveCloseButton, True),
        (flag.AlwaysShowTabs, True),
        (flag.DockAreaHasTabsMenuButton, True),
        (flag.DockAreaHasCloseButton, False),
        (flag.DockAreaHasUndockButton, True),
        (flag.MiddleMouseButtonClosesTab, True),
        (flag.FloatingContainerHasWidgetTitle, True),
        (flag.FloatingContainerHasWidgetIcon, True),
        (flag.XmlCompressionEnabled, False),
        (flag.EqualSplitOnInsertion, True),
    ):
        manager.setConfigFlag(name, value)
    _FLAGS_SET = True


class LogReaderPage(QWidget):
    """Onglets de journaux et actions sur l'onglet actif."""

    #: Nombre d'onglets ou onglet actif changé (barre d'actions à mettre à jour).
    tabsChanged = Signal()
    #: Journal d'un automate ouvert dans un onglet : (adresse, nom affiché).
    controllerOpened = Signal(str, str)

    def __init__(self, settings: Settings, parent: QWidget | None = None, restore_session: bool = True) -> None:
        super().__init__(parent)
        _configure_docking()
        self.settings = settings
        self._docks: dict[str, tuple[QtAds.CDockWidget, LogTab]] = {}
        self._counter = 0
        self._current: str | None = None

        self._stack = QStackedLayout(self)
        self._stack.addWidget(self._build_empty_state())
        self.dock_manager = QtAds.CDockManager(self)
        self.dock_manager.setStyleSheet("")  # style commun de l'application (common.theme)
        self.dock_manager.installEventFilter(self)
        self.dock_manager.focusedDockWidgetChanged.connect(self._on_focus_changed)
        self._stack.addWidget(self.dock_manager)
        self._build_actions()
        common_theme.follow(self, self._on_theme_changed)
        if restore_session:
            self._restore_previous_session()
        self._update_state()

    # ------------------------------------------------------------------ construction
    def _build_empty_state(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel(tr("No log open"))
        title.setProperty("title", True)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text = QLabel(
            tr("Open the runtime log of an FT Optix controller. Several logs can be opened side by side in tabs.")
        )
        text.setProperty("muted", True)
        text.setWordWrap(True)
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        button = QPushButton(tr("Open a log…"))
        button.setProperty("accent", True)
        button.clicked.connect(lambda: self.new_tab())
        layout.addWidget(title)
        layout.addWidget(text)
        layout.addSpacing(8)
        layout.addWidget(button, 0, Qt.AlignmentFlag.AlignCenter)
        return page

    def _action(self, text: str, icon: str, tooltip: str, slot, shortcut: str | None = None, checkable=False) -> QAction:
        action = icons.themed_action(QAction(text, self), icon)
        action.setToolTip(tooltip)
        action.setCheckable(checkable)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            self.addAction(action)
        if checkable:
            action.toggled.connect(slot)
        else:
            action.triggered.connect(lambda _checked=False: slot())
        return action

    def _build_actions(self) -> None:
        self.action_new = self._action(
            tr("New tab…"), "plus", tr("Opens the log of another controller in a new tab (Ctrl+T)."), self.new_tab, "Ctrl+T"
        )
        self.action_connect = self._action(
            tr("Change controller…"), "plc",
            tr("Active tab: reads the log of another controller in this tab (Ctrl+O)."), self.change_controller, "Ctrl+O",
        )
        self.action_pause = self._action(
            tr("Suspend following"), "pause",
            tr("Active tab: suspends or resumes the live following of the log (Ctrl+P)."), self._toggle_pause, "Ctrl+P",
            checkable=True,
        )
        self.action_autoscroll = self._action(
            tr("Follow the bottom"), "follow",
            tr("All tabs: scrolls automatically to the last received line."), self._toggle_autoscroll, checkable=True,
        )
        self.action_autoscroll.blockSignals(True)
        self.action_autoscroll.setChecked(self.settings.autoscroll)
        self.action_autoscroll.blockSignals(False)
        self.action_archives = self._action(
            tr("Load history"), "history",
            tr("Active tab: adds the rotation files (.1, .2, .3) before the current lines."), self._load_archives,
        )
        self.action_export_xlsx = self._action(
            tr("Export to Excel"), "export",
            tr("Active tab: exports the displayed lines (current filters) to an Excel workbook (Ctrl+E)."),
            lambda: self._current_tab_call("export_log", False), "Ctrl+E",
        )
        self.action_export_csv = self._action(
            tr("Export to CSV"), "table",
            tr("Active tab: exports the displayed lines (current filters) to a CSV file."),
            lambda: self._current_tab_call("export_log", True),
        )
        self.action_settings = self._action(
            tr("Reader settings…"), "settings",
            tr("Controllers, credentials, highlighting and reading settings, common to all tabs."), self.open_settings,
        )

    def toolbar_actions(self) -> list[QAction | None]:
        return [
            self.action_new,
            self.action_connect,
            None,
            self.action_pause,
            self.action_autoscroll,
            self.action_archives,
            None,
            self.action_export_xlsx,
            self.action_export_csv,
            None,
            self.action_settings,
        ]

    # ------------------------------------------------------------------ onglets
    @property
    def tabs(self) -> list[LogTab]:
        return [tab for _dock, tab in self._docks.values()]

    def current_tab(self) -> LogTab | None:
        if self._current in self._docks:
            return self._docks[self._current][1]
        # À défaut de focus, le dernier onglet visible.
        for dock, tab in reversed(list(self._docks.values())):
            if dock.isCurrentTab():
                return tab
        return None

    def _add_tab(self, session: LogSession, name: str | None = None) -> LogTab:
        if name is None:
            self._counter += 1
            name = f"log-{self._counter}"
            while name in self._docks:
                self._counter += 1
                name = f"log-{self._counter}"
        session.setParent(self)
        tab = LogTab(session)
        dock = QtAds.CDockWidget(self.dock_manager, session.display_name)
        dock.setObjectName(name)
        dock.setWidget(tab)
        dock.setFeature(QtAds.CDockWidget.DockWidgetFeature.CustomCloseHandling, True)
        dock.setFeature(QtAds.CDockWidget.DockWidgetFeature.DockWidgetPinnable, False)
        dock.closeRequested.connect(lambda n=name: self.close_tab(n))
        dock.visibilityChanged.connect(lambda visible, n=name: self._on_visibility(n, visible))
        session.identityChanged.connect(lambda n=name: self._refresh_title(n))
        session.liveChanged.connect(lambda n=name: self._refresh_title(n))
        session.archivesFinished.connect(lambda *_args: self._update_state())
        session.opened.connect(lambda s=session: self.controllerOpened.emit(s.ipc.host, s.display_name))
        self._docks[name] = (dock, tab)
        area = None
        if self._current in self._docks and self._current != name:
            area = self._docks[self._current][0].dockAreaWidget()
        if area is not None:
            self.dock_manager.addDockWidgetTabToArea(dock, area)
        else:
            self.dock_manager.addDockWidget(QtAds.CenterDockWidgetArea, dock)
        self._current = name
        dock.setAsCurrentTab()
        self._refresh_title(name)
        self._update_state()
        return tab

    def new_tab(self, ipc: Ipc | None = None, host: str | None = None) -> LogTab | None:
        """Nouvel onglet : automate donné, hôte à sonder, ou choisi dans la boîte de découverte."""
        if ipc is None and not host:
            ipc = self._choose_ipc()
            if ipc is None:
                return None
        session = LogSession(self.settings)
        tab = self._add_tab(session)
        if ipc is not None:
            tab.connect_to(ipc)
        else:
            session.probe_host(host)
        return tab

    def _choose_ipc(self, auto_connect: bool = False) -> Ipc | None:
        dialog = ConnectDialog(self.settings, common_theme.current(), self, auto_connect=auto_connect)
        dialog.settingsRequested.connect(lambda: self._open_settings_from(dialog))
        if dialog.exec() != ConnectDialog.DialogCode.Accepted or dialog.selected is None:
            return None
        return dialog.selected

    def _open_settings_from(self, dialog: ConnectDialog) -> None:
        if self.open_settings():
            dialog.start_scan()

    def change_controller(self) -> None:
        tab = self.current_tab()
        if tab is None:
            self.new_tab()
            return
        ipc = self._choose_ipc()
        if ipc is not None:
            tab.connect_to(ipc)

    def close_tab(self, name: str, ask: bool = True) -> bool:
        entry = self._docks.get(name)
        if entry is None:
            return True
        dock, tab = entry
        if ask and tab.busy:
            answer = QMessageBox.question(
                self, tr("Log Reader"), tr("An export or a history load is in progress in this tab. Close it anyway?")
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
        del self._docks[name]
        tab.session.shutdown()
        self.dock_manager.removeDockWidget(dock)
        dock.deleteLater()
        if self._current == name:
            self._current = None
        self._update_state()
        return True

    def _on_focus_changed(self, _old, now) -> None:
        if now is not None and now.objectName() in self._docks:
            self._current = now.objectName()
            self._update_state()

    def _on_visibility(self, name: str, visible: bool) -> None:
        entry = self._docks.get(name)
        if entry is None:
            return
        session = entry[1].session
        session.visible = visible
        if visible and session.unseen_errors:
            session.unseen_errors = 0
            self._refresh_title(name)

    def _refresh_title(self, name: str) -> None:
        entry = self._docks.get(name)
        if entry is None:
            return
        dock, tab = entry
        session = tab.session
        title = session.display_name
        if session.unseen_errors:
            title += f"  ({session.unseen_errors})"
        dock.setWindowTitle(title)
        state, detail = session.connection_state()
        p = common_theme.current()
        colour = {STATE_ONLINE: p.success, STATE_LOST: p.error, STATE_CONNECTING: p.warning}.get(state, p.text_muted)
        dock.setIcon(icons.pastille(colour))
        tooltip = [session.display_name]
        if session.ipc is not None:
            tooltip.append(session.path)
        if detail:
            tooltip.append(detail)
        if session.unseen_errors:
            tooltip.append(tr("{n} new error(s) since the tab was last shown").format(n=session.unseen_errors))
        dock.setTabToolTip("\n".join(tooltip))
        if name == self._current:
            self._update_state()

    def _refresh_all_titles(self, _palette=None) -> None:
        for name in list(self._docks):
            self._refresh_title(name)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 (API Qt)
        # QtAds remet sa feuille de style par défaut après un changement de palette
        # (événement différé) : on la retire dès qu'elle revient.
        if watched is self.dock_manager and event.type() == QEvent.Type.StyleChange and watched.styleSheet():
            QTimer.singleShot(0, self.dock_manager, self._drop_docking_stylesheet)  # annulé avec lui
        return super().eventFilter(watched, event)

    def _drop_docking_stylesheet(self) -> None:
        if self.dock_manager.styleSheet():
            self.dock_manager.setStyleSheet("")
            self._on_theme_changed()

    def _on_theme_changed(self, _palette=None) -> None:
        # Les widgets de QtAds (onglets, séparateurs, fenêtres flottantes) ne sont pas
        # repolis par le changement de feuille de style de l'application.
        roots = [self.dock_manager, *self.dock_manager.floatingWidgets()]
        for root in roots:
            for widget in (root, *root.findChildren(QWidget)):
                widget.style().unpolish(widget)
                widget.style().polish(widget)
                widget.update()
        self._refresh_all_titles()

    # ------------------------------------------------------------------ actions
    def _current_tab_call(self, method: str, *args) -> None:
        tab = self.current_tab()
        if tab is not None:
            getattr(tab, method)(*args)

    def _toggle_pause(self, paused: bool) -> None:
        tab = self.current_tab()
        if tab is not None:
            tab.session.set_paused(paused)
        self.action_pause.setText(tr("Resume following") if paused else tr("Suspend following"))

    def _toggle_autoscroll(self, enabled: bool) -> None:
        self.settings.autoscroll = enabled
        self.settings.save()
        for tab in self.tabs:
            tab.set_autoscroll(enabled)

    def _load_archives(self) -> None:
        self._current_tab_call("load_archives")

    def _update_state(self) -> None:
        self._stack.setCurrentIndex(1 if self._docks else 0)
        tab = self.current_tab()
        session = tab.session if tab is not None else None
        connected = session is not None and session.ipc is not None
        self.action_connect.setEnabled(tab is not None)
        for action in (self.action_pause, self.action_export_xlsx, self.action_export_csv):
            action.setEnabled(connected)
        self.action_archives.setEnabled(connected and not session.archives_loaded and not session.busy)
        paused = bool(session and session.paused)
        if self.action_pause.isChecked() != paused:
            self.action_pause.blockSignals(True)
            self.action_pause.setChecked(paused)
            self.action_pause.blockSignals(False)
        self.action_pause.setText(tr("Resume following") if paused else tr("Suspend following"))
        self.tabsChanged.emit()

    # ------------------------------------------------------------------ réglages
    def open_settings(self) -> bool:
        """Paramètres du lecteur ; vrai si des réglages ont été enregistrés."""
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() != SettingsDialog.DialogCode.Accepted:
            return False
        new = dialog.result_settings().copy_binding_from(self.settings)
        new.save()
        self.settings = new
        for tab in self.tabs:
            tab.session.apply_settings(new)
        self.action_autoscroll.setChecked(new.autoscroll)
        return True

    # ------------------------------------------------------------------ session précédente
    def _restore_previous_session(self) -> None:
        if not self.settings.reopen_logs or not self.settings.open_hosts:
            return
        for index, host in enumerate(self.settings.open_hosts, 1):
            self._counter = index - 1
            session = LogSession(self.settings)
            self._add_tab(session, name=f"log-{index}")
            session.probe_host(host)
        self._counter = len(self.settings.open_hosts)
        if self.settings.dock_state:
            self.dock_manager.restoreState(QByteArray.fromBase64(self.settings.dock_state.encode("ascii")))
        log.info("Lecteur de logs : %d journal(aux) rouvert(s)", len(self.settings.open_hosts))

    def save_session(self) -> None:
        """Mémorise les onglets ouverts et leur disposition, pour la prochaine ouverture."""
        hosts = []
        for dock, tab in self._docks.values():
            session = tab.session
            host = session.ipc.host if session.ipc is not None else session.probing_host
            if host:
                hosts.append(host)
        self.settings.open_hosts = hosts
        self.settings.dock_state = bytes(self.dock_manager.saveState().toBase64().data()).decode("ascii") if hosts else ""
        self.settings.save()

    # ------------------------------------------------------------------ cycle de vie
    @property
    def busy(self) -> bool:
        return any(tab.busy for tab in self.tabs)

    def handle_open_log(self, host: str = "") -> None:
        """Demande venue d'ailleurs (tray, accueil) : ouvre un journal dans un nouvel onglet."""
        if host:
            self.new_tab(host=host)
        else:
            self.new_tab()

    def shutdown(self) -> None:
        """Fermeture de la fenêtre : mémorise la session, puis arrête toutes les sessions encore rattachées."""
        self.save_session()
        for name in list(self._docks):
            dock, tab = self._docks[name]
            if tab.session.parent() is self:  # une session confiée à un instantané survit
                tab.session.shutdown()
        self._docks.clear()

    def snapshot(self) -> dict | None:
        if self.busy:
            return None
        tabs = []
        for name, (dock, tab) in self._docks.items():
            tabs.append((name, tab.session, tab.snapshot()))
            # La session quitte la page : elle survivra à la destruction de la fenêtre.
            tab.session.setParent(None)
        return {
            "settings": self.settings,
            "tabs": tabs,
            "dock": bytes(self.dock_manager.saveState().toBase64().data()),
            "current": self._current,
            "counter": self._counter,
        }

    def restore(self, state: dict) -> None:
        if state.get("settings") is not None:
            self.settings = state["settings"]  # le même objet que celui des sessions reprises
        for name, session, tab_state in state.get("tabs", []):
            tab = self._add_tab(session, name=name)
            tab.restore(tab_state)
        self._counter = max(self._counter, state.get("counter", 0))
        if state.get("dock"):
            self.dock_manager.restoreState(QByteArray.fromBase64(state["dock"]))
        current = state.get("current")
        if current in self._docks:
            self._current = current
            self._docks[current][0].setAsCurrentTab()
        self._update_state()
