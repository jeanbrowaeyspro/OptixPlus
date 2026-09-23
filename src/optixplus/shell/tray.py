"""Icône du tray : lanceur de la fenêtre principale en mode installé."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ..common import icons
from ..common.i18n import tr
from ..modules import MODULES
from ..version import APP_NAME, __version__

if TYPE_CHECKING:
    from .controller import AppController


class TrayIcon(QObject):
    """Clic gauche : ouvrir OptixPlus. Clic droit : menu."""

    def __init__(self, controller: AppController, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self.tray = QSystemTrayIcon(icons.app_icon(), self)
        self.menu = QMenu()

        open_action = self.menu.addAction(tr("Open OptixPlus"))
        font = open_action.font()
        font.setBold(True)
        open_action.setFont(font)
        open_action.triggered.connect(controller.show_main_window)
        self.menu.addSeparator()
        for service in controller.context.services.values():
            for action in service.tray_actions(self.menu):
                if action is None:
                    self.menu.addSeparator()
                else:
                    self.menu.addAction(action)
            service.state_changed.connect(self.refresh)
            service.notification.connect(self.notify)
        if controller.context.services:
            self.menu.addSeparator()
        for module in MODULES:
            action = self.menu.addAction(icons.themed_icon(module.icon), tr(module.title))
            action.triggered.connect(lambda _c=False, mid=module.id: controller.open_tool(mid))
        self.menu.addSeparator()
        settings_action = self.menu.addAction(icons.themed_icon("settings"), tr("Settings…"))
        settings_action.triggered.connect(controller.open_settings)
        about_action = self.menu.addAction(tr("About OptixPlus"))
        about_action.triggered.connect(controller.open_about)
        self.menu.addSeparator()
        quit_action = self.menu.addAction(tr("Quit"))
        quit_action.triggered.connect(controller.quit)

        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._on_activated)
        self.refresh()
        self.tray.show()

    def refresh(self) -> None:
        """Icône grise si un service est en pause ; infobulle avec l'état de chaque service."""
        services = list(self._controller.context.services.values())
        self.tray.setIcon(icons.app_icon(suspended=any(s.suspended for s in services)))
        lines = [f"{APP_NAME} {__version__}"] + [s.status_text() for s in services if s.status_text()]
        self.tray.setToolTip("\n".join(lines))

    def notify(self, message: str, title: str = APP_NAME, msecs: int = 3000) -> None:
        self.tray.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, msecs)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self._controller.show_main_window()

    def hide(self) -> None:
        self.tray.hide()
