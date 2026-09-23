"""Point d'entrée de l'outil Auto Validate dans la fenêtre principale."""

from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMessageBox, QWidget

from ...common import icons
from ...common.i18n import tr
from ..base import ToolModule
from .service import AutoValidateService
from .ui.page import AutoValidatePage


class AutoValidateModule(ToolModule):
    """La page n'est qu'une vue : la surveillance elle-même est le service, qui survit à la fenêtre."""

    def __init__(self, spec, context, parent=None) -> None:
        super().__init__(spec, context, parent)
        self.service: AutoValidateService = context.services[spec.id]
        self.page: AutoValidatePage | None = None

    def create_page(self, parent: QWidget) -> QWidget:
        self.page = AutoValidatePage(self.service, parent)
        self._toggle = QAction(icons.themed_icon("autovalidate"), tr("Monitoring active"), self)
        self._toggle.setCheckable(True)
        self._toggle.toggled.connect(self.service.set_enabled)
        self._clear = QAction(tr("Clear log"), self)
        self._clear.triggered.connect(self.service.activity.clear)
        self._open = QAction(icons.themed_icon("journal"), tr("Open log file"), self)
        self._open.triggered.connect(self.page.open_log_file)
        self.service.state_changed.connect(self._sync_toggle)
        self._sync_toggle()
        return self.page

    def _sync_toggle(self) -> None:
        self._toggle.blockSignals(True)
        self._toggle.setChecked(self.service.enabled)
        self._toggle.blockSignals(False)

    def toolbar_actions(self) -> list[QAction | None]:
        return [self._toggle, None, self._open, self._clear]

    def can_close(self) -> bool:
        if self.page is None or not self.page.has_unsaved_changes():
            return True
        answer = QMessageBox.question(
            self.page,
            tr(self.spec.title),
            tr("The monitoring settings have unsaved changes. Close anyway?"),
        )
        return answer == QMessageBox.StandardButton.Yes
