"""Contrôleur de l'application : cycle de vie de la fenêtre, du tray et des dialogues.

En mode installé, le processus reste résident : la fenêtre est créée à la demande et
détruite à la fermeture. En mode découverte, fermer la fenêtre arrête l'application.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QWidget

from ..common import workers
from ..common.settings import Settings
from ..common.single_instance import SingleInstance
from ..common.theme import ThemeManager
from .context import AppContext, LaunchMode

log = logging.getLogger("optixplus.app")


class AppController(QObject):
    def __init__(
        self,
        app: QApplication,
        settings: Settings,
        theme: ThemeManager,
        mode: LaunchMode,
        instance: SingleInstance | None = None,
    ) -> None:
        super().__init__(app)
        self._app = app
        self.context = AppContext(settings=settings, theme=theme, mode=mode, controller=self)
        self._window = None
        self._settings_dialog: QWidget | None = None
        self._about_dialog: QWidget | None = None
        self._quitting = False
        self.tray = None
        self._create_services()
        if mode is LaunchMode.INSTALLED:
            if QSystemTrayIcon.isSystemTrayAvailable():
                from .tray import TrayIcon

                self.tray = TrayIcon(self, self)
            else:
                log.warning("Zone de notification indisponible : fonctionnement sans tray")
        if instance is not None:
            instance.message_received.connect(self.handle_message)
        app.aboutToQuit.connect(self._on_about_to_quit)

    # ---- services d'arrière-plan -----------------------------------------------------
    def _create_services(self) -> None:
        from ..modules import MODULES

        for spec in MODULES:
            try:
                service_class = spec.load_service()
                if service_class is None:
                    continue
                service = service_class(spec, self.context, self)
            except Exception:
                log.exception("Service de l'outil %s indisponible", spec.id)
                continue
            self.context.services[spec.id] = service

    def start_services(self) -> None:
        for service in self.context.services.values():
            service.start()

    def _stop_services(self) -> None:
        for spec_id, service in self.context.services.items():
            try:
                service.stop()
            except Exception:
                log.exception("Arrêt du service %s en erreur", spec_id)

    # ---- fenêtre principale ------------------------------------------------------
    @property
    def window(self):
        return self._window

    def show_main_window(self):
        if self._window is None:
            from .main_window import MainWindow

            self._window = MainWindow(self.context)
            self._window.closed.connect(self._on_window_closed)
            self._window.show()
        window = self._window
        if window.isMinimized():
            window.setWindowState(window.windowState() & ~Qt.WindowState.WindowMinimized)
        window.show()
        window.raise_()
        window.activateWindow()
        return window

    def open_tool(self, module_id: str) -> None:
        self.show_main_window().show_page(module_id)

    def _on_window_closed(self) -> None:
        self._window = None
        log.info("Fenêtre principale fermée")
        if self.context.mode is LaunchMode.DISCOVERY or self.tray is None:
            self.quit()

    # ---- dialogues ---------------------------------------------------------------
    def _raise_existing(self, dialog: QWidget | None) -> bool:
        if dialog is None:
            return False
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return True

    def open_settings(self) -> None:
        if self._raise_existing(self._settings_dialog):
            return
        from .settings_dialog import SettingsDialog

        dialog = SettingsDialog(self.context, self._window)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.destroyed.connect(lambda: setattr(self, "_settings_dialog", None))
        self._settings_dialog = dialog
        self._raise_existing(dialog)

    def open_about(self) -> None:
        if self._raise_existing(self._about_dialog):
            return
        from .about_dialog import AboutDialog

        dialog = AboutDialog(self._window)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.destroyed.connect(lambda: setattr(self, "_about_dialog", None))
        self._about_dialog = dialog
        self._raise_existing(dialog)

    # ---- demandes externes ---------------------------------------------------------
    def handle_message(self, message: list[str]) -> None:
        """Demande d'un second lancement ou du tray : ``["show"]``, ``["open-tool", id]``…"""
        log.info("Demande reçue : %s", message)
        if not message or message[0] == "show":
            self.show_main_window()
            return
        window = self.show_main_window()
        window.handle_command(message[0], message[1:])

    # ---- sortie ------------------------------------------------------------------
    def quit(self) -> None:
        if self._quitting:
            return
        if self._window is not None:
            self._quitting = True
            closed = self._window.close()
            if not closed:
                self._quitting = False
                return
        self._quitting = True
        log.info("Arrêt d'OptixPlus")
        self.context.settings.save()
        if self.tray is not None:
            self.tray.hide()
        self._app.quit()

    def _on_about_to_quit(self) -> None:
        self._stop_services()
        workers.wait_retired()
