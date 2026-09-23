"""Point d'entrée de Compare dans la fenêtre principale."""

from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMessageBox, QWidget

from ...common.i18n import tr
from ...common import recent
from ...common.kvstore import KeyValueStore
from ..base import ToolModule
from .ui.page import ComparePage


class CompareModule(ToolModule):
    def __init__(self, spec, context, parent=None) -> None:
        super().__init__(spec, context, parent)
        self.page: ComparePage | None = None

    def create_page(self, parent: QWidget) -> QWidget:
        self.page = ComparePage(
            KeyValueStore(self.context.settings, "compare"),
            parent,
            on_project_used=lambda path: recent.add_recent_project(self.context.settings, path),
        )
        return self.page

    def toolbar_actions(self) -> list[QAction | None]:
        return self.page.toolbar_actions() if self.page is not None else []

    def handle_command(self, command: str, args: list[str]) -> bool:
        if command == "open-project" and args and self.page is not None:
            self.page.open_project(args[0])
            return True
        return False

    def can_close(self) -> bool:
        if self.page is None or not self.page.busy:
            return True
        answer = QMessageBox.question(self.page, tr(self.spec.title), tr("A comparison is in progress. Stop it and close?"))
        if answer != QMessageBox.StandardButton.Yes:
            return False
        self.page.stop()
        return True

    def shutdown(self) -> None:
        if self.page is not None:
            self.page.stop()

    def snapshot(self) -> dict | None:
        return self.page.snapshot() if self.page is not None else {}

    def restore(self, state: dict) -> None:
        if self.page is not None and state:
            self.page.restore(state)
