"""Page de l'outil Auto Validate : état, réglages et journal de la surveillance.

Reprend les boîtes « Paramètres » et « Journal » de l'ancien Auto Validate, réunies sur
une seule page. Les réglages s'appliquent par « Enregistrer ».
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFontDatabase
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ....common import theme
from ....shell.log_panel import append_colored
from ....common.i18n import tr
from ..core.config import AutoValidateSettings

if TYPE_CHECKING:
    from ..service import AutoValidateService


class AutoValidatePage(QWidget):
    def __init__(self, service: AutoValidateService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(16)

        # ---- en-tête : état --------------------------------------------------------
        header = QFrame()
        header.setProperty("card", True)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 12, 16, 12)
        texts = QVBoxLayout()
        self.state_label = QLabel()
        self.state_label.setProperty("heading", True)
        explanation = QLabel(
            tr(
                "Automatically confirms the “Project already exists” prompt that FT Optix Studio shows "
                "at each deployment, by pressing Enter (default button “Update”)."
            )
        )
        explanation.setProperty("muted", True)
        explanation.setWordWrap(True)
        texts.addWidget(self.state_label)
        texts.addWidget(explanation)
        header_layout.addLayout(texts, 1)
        self.toggle_button = QPushButton()
        self.toggle_button.setProperty("accent", True)
        self.toggle_button.clicked.connect(lambda: service.set_enabled(not service.enabled))
        header_layout.addWidget(self.toggle_button, 0, Qt.AlignmentFlag.AlignVCenter)
        outer.addWidget(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_settings())
        splitter.addWidget(self._build_journal())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([420, 700])
        outer.addWidget(splitter, 1)

        service.state_changed.connect(self.refresh_state)
        service.activity.relay.entry_added.connect(self._append)
        service.activity.relay.cleared.connect(self.journal.clear)
        self._load(service.settings)
        self.refresh_state()
        self._recolor()
        manager = theme.manager()
        if manager is not None:
            manager.changed.connect(self._recolor)

    # ---- réglages ----------------------------------------------------------------
    def _build_settings(self) -> QWidget:
        box = QGroupBox(tr("Settings"))
        layout = QVBoxLayout(box)
        layout.setSpacing(10)

        layout.addWidget(QLabel(tr("Watched window titles")))
        self.titles = QListWidget()
        self.titles.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.titles.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.SelectedClicked
        )
        self.titles.setMaximumHeight(120)
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

        buttons = QHBoxLayout()
        defaults = QPushButton(tr("Restore defaults"))
        defaults.clicked.connect(self._restore_defaults)
        self.save_button = QPushButton(tr("Save"))
        self.save_button.setProperty("accent", True)
        self.save_button.clicked.connect(self._save)
        buttons.addWidget(defaults)
        buttons.addStretch(1)
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)
        return box

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
        self.save_button.setEnabled(False)

    def _mark_dirty(self, *_args) -> None:
        if not getattr(self, "_loading", False):
            self.save_button.setEnabled(True)

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
        defaults = AutoValidateSettings()
        self._load(defaults)
        self.save_button.setEnabled(True)

    def _save(self) -> None:
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

    def has_unsaved_changes(self) -> bool:
        return self.save_button.isEnabled()

    # ---- journal -----------------------------------------------------------------
    def _build_journal(self) -> QWidget:
        box = QGroupBox(tr("Monitoring log"))
        layout = QVBoxLayout(box)
        self.journal = QPlainTextEdit()
        self.journal.setReadOnly(True)
        self.journal.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.journal.setMaximumBlockCount(2000)
        self.journal.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        layout.addWidget(self.journal, 1)
        buttons = QHBoxLayout()
        clear = QPushButton(tr("Clear"))
        clear.clicked.connect(self._service.activity.clear)
        open_file = QPushButton(tr("Open log file"))
        open_file.clicked.connect(self.open_log_file)
        open_folder = QPushButton(tr("Open folder"))
        open_folder.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(os.fspath(self._service.activity.file_path.parent)))
        )
        buttons.addWidget(clear)
        buttons.addWidget(open_file)
        buttons.addWidget(open_folder)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        return box

    def open_log_file(self) -> None:
        path = self._service.activity.file_path
        if not path.exists():
            try:
                path.touch()
            except OSError:
                return
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.fspath(path)))

    def _append(self, line: str, level: int) -> None:
        append_colored(self.journal, line, level)
        bar = self.journal.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _recolor(self, _palette=None) -> None:
        """Les couleurs sont figées dans le texte : on le reconstruit au changement de thème."""
        self.journal.clear()
        for line, level in self._service.activity.entries():
            append_colored(self.journal, line, level)

    # ---- état --------------------------------------------------------------------
    def refresh_state(self) -> None:
        service = self._service
        self.state_label.setText(service.status_text())
        self.toggle_button.setText(tr("Suspend monitoring") if service.enabled else tr("Start monitoring"))
