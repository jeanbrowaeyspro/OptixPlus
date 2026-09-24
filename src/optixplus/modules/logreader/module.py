"""Point d'entrée du Lecteur de logs dans la fenêtre principale."""

from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMessageBox, QWidget

from ...common.i18n import tr
from ...common.recent import add_recent_controller
from ..base import ToolModule
from .core.config import Settings
from .ui.page import LogReaderPage


class LogReaderModule(ToolModule):
    def __init__(self, spec, context, parent=None) -> None:
        super().__init__(spec, context, parent)
        self.page: LogReaderPage | None = None

    def create_page(self, parent: QWidget) -> QWidget:
        settings = Settings.bound(self.context.settings.store("logreader"), self.context.settings.save)
        self.page = LogReaderPage(settings, parent)
        self.page.controllerOpened.connect(
            lambda host, name: add_recent_controller(self.context.settings, host, name)
        )
        self.page.settingsRequested.connect(self._open_settings)
        return self.page

    def _open_settings(self) -> None:
        self.context.controller.open_settings(self.spec.id)

    def toolbar_actions(self) -> list[QAction | None]:
        return self.page.toolbar_actions() if self.page is not None else []

    def handle_command(self, command: str, args: list[str]) -> bool:
        if command == "open-controller" and self.page is not None:
            self.page.handle_open_log(args[0] if args else "")
            return True
        return False

    def can_close(self) -> bool:
        if self.page is None or not self.page.busy:
            return True
        answer = QMessageBox.question(
            self.page, tr(self.spec.title), tr("An export or a history load is in progress. Stop it and close?")
        )
        return answer == QMessageBox.StandardButton.Yes

    def shutdown(self) -> None:
        if self.page is not None:
            self.page.shutdown()

    def snapshot(self) -> dict | None:
        return self.page.snapshot() if self.page is not None else {}

    def restore(self, state: dict) -> None:
        if self.page is not None and state:
            self.page.restore(state)
