"""Catégorie « Validation auto » de la boîte Paramètres : réglages de la surveillance.

Reprend la boîte « Paramètres » de l'ancien Auto Validate. Les choix s'appliquent par
« OK » ou « Appliquer » de la boîte Paramètres, jamais à la saisie.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ....common.i18n import tr
from ..core.config import AutoValidateSettings

if TYPE_CHECKING:
    from ..service import AutoValidateService


class AutoValidateSettingsPage(QWidget):
    def __init__(self, service: AutoValidateService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._dirty = False
        self._loading = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        layout.addWidget(QLabel(tr("Watched window titles")))
        self.titles = QListWidget()
        self.titles.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.titles.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.SelectedClicked
        )
        self.titles.setMaximumHeight(110)
        self.titles.itemChanged.connect(self._mark_dirty)
        layout.addWidget(self.titles)
        hint = QLabel(tr("Case-insensitive match on part of the title. Double-click an entry to edit it."))
        hint.setProperty("muted", True)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        title_buttons = QHBoxLayout()
        add = QPushButton(tr("Add"))
        add.clicked.connect(self._add_title)
        remove = QPushButton(tr("Remove"))
        remove.clicked.connect(self._remove_title)
        title_buttons.addWidget(add)
        title_buttons.addWidget(remove)
        title_buttons.addStretch(1)
        layout.addLayout(title_buttons)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.process = QLineEdit()
        self.process.setPlaceholderText("FTOptixStudio.exe")
        self.process.textEdited.connect(self._mark_dirty)
        form.addRow(tr("Owner process"), self.process)
        self.retries = QSpinBox()
        self.retries.setRange(1, 10)
        self.retries.valueChanged.connect(self._mark_dirty)
        form.addRow(tr("Attempts"), self.retries)
        self.retry_delay = QSpinBox()
        self.retry_delay.setRange(50, 5000)
        self.retry_delay.setSingleStep(50)
        self.retry_delay.setSuffix(" ms")
        self.retry_delay.valueChanged.connect(self._mark_dirty)
        form.addRow(tr("Delay between attempts"), self.retry_delay)
        self.fallback = QSpinBox()
        self.fallback.setRange(500, 60_000)
        self.fallback.setSingleStep(500)
        self.fallback.setSuffix(" ms")
        self.fallback.setToolTip(
            tr("Windows reports new windows instantly; this slow check only catches a missed event.")
        )
        self.fallback.valueChanged.connect(self._mark_dirty)
        form.addRow(tr("Safety check every"), self.fallback)
        layout.addLayout(form)

        self.restore_focus = QCheckBox(tr("Give focus back to the previous window after confirming"))
        self.restore_focus.toggled.connect(self._mark_dirty)
        self.notify = QCheckBox(tr("Show a notification at each confirmation"))
        self.notify.toggled.connect(self._mark_dirty)
        layout.addWidget(self.restore_focus)
        layout.addWidget(self.notify)
        layout.addStretch(1)

        defaults = QPushButton(tr("Restore defaults"))
        defaults.setToolTip(tr("Puts back the default monitoring settings in this form (applied with OK or Apply)."))
        defaults.clicked.connect(self._restore_defaults)
        buttons = QHBoxLayout()
        buttons.addWidget(defaults)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self._load(service.settings)

    # ---- formulaire ----------------------------------------------------------------
    def _load(self, settings: AutoValidateSettings) -> None:
        self._loading = True
        self.titles.clear()
        for title in settings.titles:
            self._append_title(title)
        self.process.setText(settings.process_name)
        self.retries.setValue(settings.max_retries)
        self.retry_delay.setValue(settings.retry_delay_ms)
        self.fallback.setValue(settings.fallback_scan_ms)
        self.restore_focus.setChecked(settings.restore_focus)
        self.notify.setChecked(settings.notify)
        self._loading = False
        self._dirty = False

    def _mark_dirty(self, *_args) -> None:
        if not self._loading:
            self._dirty = True

    def _append_title(self, text: str) -> QListWidgetItem:
        item = QListWidgetItem(text)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        self.titles.addItem(item)
        return item

    def _add_title(self) -> None:
        item = self._append_title(tr("New title"))
        self.titles.setCurrentItem(item)
        self.titles.editItem(item)
        self._mark_dirty()

    def _remove_title(self) -> None:
        row = self.titles.currentRow()
        if row >= 0:
            self.titles.takeItem(row)
            self._mark_dirty()

    def _restore_defaults(self) -> None:
        self._load(AutoValidateSettings())
        self._dirty = True

    # ---- contrat de la boîte Paramètres -----------------------------------------------
    def has_unsaved_changes(self) -> bool:
        return self._dirty

    def apply(self) -> None:
        """Enregistre le formulaire et l'applique à la surveillance en cours."""
        if not self._dirty:
            return
        settings = self._service.settings
        settings.titles = [
            self.titles.item(i).text().strip()
            for i in range(self.titles.count())
            if self.titles.item(i).text().strip()
        ]
        settings.process_name = self.process.text().strip()
        settings.max_retries = self.retries.value()
        settings.retry_delay_ms = self.retry_delay.value()
        settings.fallback_scan_ms = self.fallback.value()
        settings.restore_focus = self.restore_focus.isChecked()
        settings.notify = self.notify.isChecked()
        self._service.apply_settings()
        self._load(settings)  # affiche les valeurs normalisées (titres vides retirés…)

    def snapshot(self) -> dict:
        """Formulaire tel qu'affiché, même non appliqué."""
        return {
            "titles": [self.titles.item(i).text() for i in range(self.titles.count())],
            "current_title": self.titles.currentRow(),
            "process": self.process.text(),
            "retries": self.retries.value(),
            "retry_delay": self.retry_delay.value(),
            "fallback": self.fallback.value(),
            "restore_focus": self.restore_focus.isChecked(),
            "notify": self.notify.isChecked(),
            "dirty": self._dirty,
        }

    def restore(self, state: dict) -> None:
        self._loading = True
        self.titles.clear()
        for title in state.get("titles", []):
            self._append_title(title)
        self.titles.setCurrentRow(state.get("current_title", -1))
        self.process.setText(state.get("process", self.process.text()))
        self.retries.setValue(state.get("retries", self.retries.value()))
        self.retry_delay.setValue(state.get("retry_delay", self.retry_delay.value()))
        self.fallback.setValue(state.get("fallback", self.fallback.value()))
        self.restore_focus.setChecked(state.get("restore_focus", self.restore_focus.isChecked()))
        self.notify.setChecked(state.get("notify", self.notify.isChecked()))
        self._loading = False
        self._dirty = bool(state.get("dirty"))
