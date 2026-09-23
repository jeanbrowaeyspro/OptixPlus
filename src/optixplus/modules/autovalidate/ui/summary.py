"""Carte « Surveillance » de la page d'accueil."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QCheckBox, QLabel, QVBoxLayout, QWidget

from ....common.i18n import tr

if TYPE_CHECKING:
    from ..service import AutoValidateService


class MonitoringSummary(QWidget):
    """État de la surveillance, interrupteur et dernière validation."""

    def __init__(self, service: AutoValidateService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.toggle = QCheckBox(tr("Monitoring active"))
        self.toggle.toggled.connect(service.set_enabled)
        self.detail = QLabel()
        self.detail.setProperty("muted", True)
        self.detail.setWordWrap(True)
        layout.addWidget(self.toggle)
        layout.addWidget(self.detail)
        service.state_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        service = self._service
        self.toggle.blockSignals(True)
        self.toggle.setChecked(service.enabled)
        self.toggle.blockSignals(False)
        text = service.status_text()
        if service.last_validation:
            text += "\n" + tr("Last confirmation at {time}").format(time=service.last_validation)
        self.detail.setText(text)
