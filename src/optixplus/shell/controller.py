"""Contrôleur de l'application : cycle de vie de la fenêtre, du tray et des dialogues.

En mode installé, le processus reste résident : la fenêtre est créée à la demande et
détruite à la fermeture. En mode découverte, fermer la fenêtre arrête l'application.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon, QWidget

from ..common import i18n, qt_translation, workers
from ..common.i18n import tr
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
        self._rebuilding = False
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
        if self._rebuilding:
            return
        log.info("Fenêtre principale fermée")
        if self.context.mode is LaunchMode.DISCOVERY or self.tray is None:
            self.quit()

    # ---- langue ------------------------------------------------------------------
    def change_language(self, settings_state: dict | None = None) -> None:
        """Applique à chaud la langue des réglages, en rouvrant tout **en l'état**.

        Chaque texte est traduit à la construction de son widget : plutôt que de
        réappliquer chaque libellé, la fenêtre est reconstruite dans la nouvelle langue.
        Avant, chaque outil ouvert livre un instantané de sa page (saisies non
        enregistrées comprises) ; après, les mêmes outils sont rouverts et restaurés, sur
        la même page, avec les mêmes boîtes de dialogue ouvertes.

        ``settings_state`` : la demande vient de la boîte Paramètres, rouverte sur la même
        catégorie. Un outil qui ne sait pas se reconstruire en l'état (traitement en cours)
        passe par la confirmation de fermeture habituelle ; en cas de refus, la fenêtre
        garde l'ancienne langue jusqu'à sa prochaine ouverture.
        """
        language = i18n.resolve_language(self.context.settings.general.language)
        if language == i18n.current_language():
            return
        i18n.install(language)
        qt_translation.apply(self._app, language)
        log.info("Langue de l'interface : %s", language)
        if self.tray is not None:
            self.tray.rebuild_menu()
        for service in self.context.services.values():
            service.state_changed.emit()

        window = self._window
        about_open = self._is_open(self._about_dialog)
        if window is None:
            self._reopen_dialogs(settings_state, about_open)
            return
        snapshot = window.snapshot()
        if about_open:
            self._about_dialog.close()
            self._about_dialog = None
        self._rebuilding = True
        try:
            closed = window.close_for_rebuild() if snapshot is not None else window.close()
        finally:
            self._rebuilding = False
        if not closed:
            QMessageBox.information(
                window, "OptixPlus", tr("The window will switch to the new language when it is reopened.")
            )
            return
        rebuilt = self.show_main_window()
        if snapshot is not None:
            rebuilt.restore(snapshot)
        self._reopen_dialogs(settings_state, about_open)

    def _reopen_dialogs(self, settings_state: dict | None, about_open: bool) -> None:
        if about_open:
            self.open_about()
        if settings_state is not None:
            self.open_settings()
            if self._settings_dialog is not None:
                self._settings_dialog.restore(settings_state)

    # ---- dialogues ---------------------------------------------------------------
    @staticmethod
    def _is_open(dialog: QWidget | None) -> bool:
        # Une boîte fermée mais pas encore détruite (destruction différée) compte comme absente.
        return dialog is not None and dialog.isVisible()

    @staticmethod
    def _show(dialog: QWidget) -> None:
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _raise_existing(self, dialog: QWidget | None) -> bool:
        if not self._is_open(dialog):
            return False
        self._show(dialog)
        return True

    def open_settings(self) -> None:
        if self._raise_existing(self._settings_dialog):
            return
        from .settings_dialog import SettingsDialog

        dialog = SettingsDialog(self.context, self._window)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.destroyed.connect(lambda: setattr(self, "_settings_dialog", None))
        self._settings_dialog = dialog
        self._show(dialog)

    def open_about(self) -> None:
        if self._raise_existing(self._about_dialog):
            return
        from .about_dialog import AboutDialog

        dialog = AboutDialog(self._window)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.destroyed.connect(lambda: setattr(self, "_about_dialog", None))
        self._about_dialog = dialog
        self._show(dialog)

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
