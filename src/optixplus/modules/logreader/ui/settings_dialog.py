"""Fenêtre de paramètres : général, automates, identifiants et surlignage.

Les modifications ne sont appliquées qu'à la validation : la boîte travaille sur
une copie des réglages, ce qui rend « Annuler » réellement sans effet.
"""

from __future__ import annotations

import copy

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QListWidgetItem,
    QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget,
    QVBoxLayout, QWidget,
)

from ..core.config import Credential, HighlightRule, Settings, default_rules
from ....common.i18n import tr
from ....common.widgets import scrollbar_below_header


def scope_labels() -> dict[str, str]:
    return {"line": tr("Whole line"), "message": tr("Message only")}

RULE_COLUMN_ENABLED = 0
RULE_COLUMN_NAME = 1
RULE_COLUMN_COLOR = 2
RULE_COLUMN_KEYWORDS = 3
RULE_COLUMN_WHOLE_WORD = 4
RULE_COLUMN_SCOPE = 5

CREDENTIAL_COLUMN_ENABLED = 0
CREDENTIAL_COLUMN_LABEL = 1
CREDENTIAL_COLUMN_USERNAME = 2
CREDENTIAL_COLUMN_PASSWORD = 3


def _checkbox_item(checked: bool) -> QTableWidgetItem:
    item = QTableWidgetItem()
    item.setFlags(
        Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable
    )
    item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    return item


class SettingsDialog(QDialog):
    """Édition complète de la configuration."""

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.original = settings
        self.settings = copy.deepcopy(settings)

        self.setWindowTitle(tr("Log Reader settings"))
        self.setMinimumSize(760, 560)
        self._build()
        self._load()

    # ----------------------------------------------------------- composition

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_general_tab(), tr("General"))
        self.tabs.addTab(self._build_hosts_tab(), tr("Controllers"))
        self.tabs.addTab(self._build_credentials_tab(), tr("Credentials"))
        self.tabs.addTab(self._build_rules_tab(), tr("Highlighting"))
        layout.addWidget(self.tabs, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Save"))
        buttons.button(QDialogButtonBox.StandardButton.Ok).setProperty("accent", True)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("Cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------- onglet 1

    def _build_general_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 16, 14, 14)
        layout.setSpacing(14)

        display = QGroupBox(tr("Display"))
        form = QFormLayout(display)
        form.setSpacing(10)
        self.autoscroll_check = QCheckBox(tr("Automatically follow the new lines"))
        form.addRow("", self.autoscroll_check)
        self.reopen_check = QCheckBox(tr("Reopen the logs of the previous session"))
        form.addRow("", self.reopen_check)
        layout.addWidget(display)

        live = QGroupBox(tr("Live following"))
        form = QFormLayout(live)
        form.setSpacing(10)

        self.poll_spin = QSpinBox()
        self.poll_spin.setRange(100, 30000)
        self.poll_spin.setSingleStep(100)
        self.poll_spin.setSuffix(" ms")
        form.addRow(tr("Reading period"), self.poll_spin)

        self.ping_spin = QSpinBox()
        self.ping_spin.setRange(100, 10000)
        self.ping_spin.setSingleStep(100)
        self.ping_spin.setSuffix(" ms")
        form.addRow(tr("Ping timeout"), self.ping_spin)

        self.max_rows_spin = QSpinBox()
        self.max_rows_spin.setRange(0, 5_000_000)
        self.max_rows_spin.setSingleStep(10_000)
        self.max_rows_spin.setSpecialValueText(tr("unlimited"))
        self.max_rows_spin.setToolTip(tr("Per tab: the oldest lines are dropped beyond this limit."))
        form.addRow(tr("Lines kept in memory (per tab)"), self.max_rows_spin)

        self.remember_check = QCheckBox(tr("Remember the last controller used"))
        form.addRow("", self.remember_check)
        layout.addWidget(live)

        location = QGroupBox(tr("Location of the log on the controller"))
        form = QFormLayout(location)
        form.setSpacing(10)
        self.share_edit = QLineEdit()
        form.addRow(tr("Share name"), self.share_edit)
        self.subdir_edit = QLineEdit()
        form.addRow(tr("Subfolder"), self.subdir_edit)
        self.filename_edit = QLineEdit()
        form.addRow(tr("Log file"), self.filename_edit)
        hint = QLabel(
            tr("The full path is of the form {pattern}.").format(pattern="\\\\<address>\\<share>\\<subfolder>\\<file>")
        )
        hint.setProperty("muted", True)
        hint.setWordWrap(True)
        form.addRow("", hint)
        layout.addWidget(location)

        layout.addStretch(1)
        return page

    # ------------------------------------------------------------- onglet 2

    def _build_hosts_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 16, 14, 14)
        layout.setSpacing(10)

        description = QLabel(
            tr(
                "Addresses tested at each controller search. They are probed in parallel: "
                "a somewhat long list does not slow the start down."
            )
        )
        description.setProperty("muted", True)
        description.setWordWrap(True)
        layout.addWidget(description)

        self.hosts_list = QListWidget()
        self.hosts_list.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        layout.addWidget(self.hosts_list, 1)

        entry = QHBoxLayout()
        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText(tr("IP address or machine name, then Enter"))
        self.host_edit.returnPressed.connect(self._add_host)
        entry.addWidget(self.host_edit, 1)
        add = QPushButton(tr("Add"))
        add.clicked.connect(self._add_host)
        entry.addWidget(add)
        layout.addLayout(entry)

        actions = QHBoxLayout()
        for label, slot in (
            (tr("Move up"), lambda: self._move_list_item(self.hosts_list, -1)),
            (tr("Move down"), lambda: self._move_list_item(self.hosts_list, 1)),
            (tr("Remove"), self._remove_host),
        ):
            button = QPushButton(label)
            button.clicked.connect(slot)
            actions.addWidget(button)
        actions.addStretch(1)
        layout.addLayout(actions)
        return page

    def _append_host_item(self, host: str) -> None:
        item = QListWidgetItem(host)
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable
        )
        self.hosts_list.addItem(item)

    def _add_host(self) -> None:
        host = self.host_edit.text().strip()
        self.host_edit.clear()
        if not host:
            return
        existing = {self.hosts_list.item(i).text() for i in range(self.hosts_list.count())}
        if host in existing:
            return
        self._append_host_item(host)
        self.hosts_list.setCurrentRow(self.hosts_list.count() - 1)

    def _remove_host(self) -> None:
        row = self.hosts_list.currentRow()
        if row >= 0:
            self.hosts_list.takeItem(row)

    @staticmethod
    def _move_list_item(widget: QListWidget, offset: int) -> None:
        row = widget.currentRow()
        target = row + offset
        if row < 0 or not 0 <= target < widget.count():
            return
        item = widget.takeItem(row)
        widget.insertItem(target, item)
        widget.setCurrentRow(target)

    # ------------------------------------------------------------- onglet 3

    def _build_credentials_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 16, 14, 14)
        layout.setSpacing(10)

        description = QLabel(
            tr(
                "Credentials tried in order when connecting to the share. The current Windows session "
                "is always tried first. Passwords are encrypted by the Windows DPAPI: only your account, "
                "on this computer, can read them."
            )
        )
        description.setProperty("muted", True)
        description.setWordWrap(True)
        layout.addWidget(description)

        self.credentials_table = QTableWidget(0, 4)
        scrollbar_below_header(self.credentials_table)
        self.credentials_table.setHorizontalHeaderLabels(
            [tr("Active"), tr("Label"), tr("User"), tr("Password")]
        )
        header = self.credentials_table.horizontalHeader()
        header.setSectionResizeMode(CREDENTIAL_COLUMN_ENABLED, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(CREDENTIAL_COLUMN_LABEL, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(CREDENTIAL_COLUMN_USERNAME, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(CREDENTIAL_COLUMN_PASSWORD, QHeaderView.ResizeMode.Stretch)
        self.credentials_table.verticalHeader().setVisible(False)
        layout.addWidget(self.credentials_table, 1)

        actions = QHBoxLayout()
        for label, slot in (
            (tr("Add"), self._add_credential),
            (tr("Remove"), self._remove_credential),
            (tr("Move up"), lambda: self._move_table_row(self.credentials_table, -1)),
            (tr("Move down"), lambda: self._move_table_row(self.credentials_table, 1)),
        ):
            button = QPushButton(label)
            button.clicked.connect(slot)
            actions.addWidget(button)
        actions.addStretch(1)
        self.show_passwords_check = QCheckBox(tr("Show the passwords"))
        self.show_passwords_check.toggled.connect(self._refresh_password_visibility)
        actions.addWidget(self.show_passwords_check)
        layout.addLayout(actions)
        return page

    def _append_credential_row(self, credential: Credential) -> None:
        row = self.credentials_table.rowCount()
        self.credentials_table.insertRow(row)
        self.credentials_table.setItem(row, CREDENTIAL_COLUMN_ENABLED, _checkbox_item(credential.enabled))
        self.credentials_table.setItem(row, CREDENTIAL_COLUMN_LABEL, QTableWidgetItem(credential.label))
        self.credentials_table.setItem(row, CREDENTIAL_COLUMN_USERNAME, QTableWidgetItem(credential.username))

        password = QLineEdit(credential.password)
        password.setEchoMode(
            QLineEdit.EchoMode.Normal if self.show_passwords_check.isChecked()
            else QLineEdit.EchoMode.Password
        )
        password.setFrame(False)
        self.credentials_table.setCellWidget(row, CREDENTIAL_COLUMN_PASSWORD, password)

    def _add_credential(self) -> None:
        self._append_credential_row(Credential(label=tr("New"), username="", password=""))
        self.credentials_table.setCurrentCell(
            self.credentials_table.rowCount() - 1, CREDENTIAL_COLUMN_LABEL
        )

    def _remove_credential(self) -> None:
        row = self.credentials_table.currentRow()
        if row >= 0:
            self.credentials_table.removeRow(row)

    def _refresh_password_visibility(self, visible: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        for row in range(self.credentials_table.rowCount()):
            widget = self.credentials_table.cellWidget(row, CREDENTIAL_COLUMN_PASSWORD)
            if widget is not None:
                widget.setEchoMode(mode)

    # ------------------------------------------------------------- onglet 4

    def _build_rules_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 16, 14, 14)
        layout.setSpacing(10)

        description = QLabel(
            tr(
                "A line containing one of the keywords of a rule takes its colour. Rules are evaluated from "
                "top to bottom: the first one that matches wins. The chosen tint is automatically lightened "
                "or darkened according to the theme."
            )
        )
        description.setProperty("muted", True)
        description.setWordWrap(True)
        layout.addWidget(description)

        self.rules_table = QTableWidget(0, 6)
        scrollbar_below_header(self.rules_table)
        self.rules_table.setHorizontalHeaderLabels(
            [tr("Active"), tr("Name"), tr("Colour"), tr("Keywords (comma separated)"), tr("Whole word"), tr("Scope")]
        )
        header = self.rules_table.horizontalHeader()
        header.setSectionResizeMode(RULE_COLUMN_ENABLED, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(RULE_COLUMN_NAME, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(RULE_COLUMN_COLOR, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(RULE_COLUMN_KEYWORDS, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(RULE_COLUMN_WHOLE_WORD, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(RULE_COLUMN_SCOPE, QHeaderView.ResizeMode.ResizeToContents)
        self.rules_table.verticalHeader().setVisible(False)
        self.rules_table.cellDoubleClicked.connect(self._maybe_pick_color)
        layout.addWidget(self.rules_table, 1)

        actions = QHBoxLayout()
        for label, slot in (
            (tr("Add"), self._add_rule),
            (tr("Remove"), self._remove_rule),
            (tr("Colour…"), self._pick_color),
            (tr("Move up"), lambda: self._move_table_row(self.rules_table, -1)),
            (tr("Move down"), lambda: self._move_table_row(self.rules_table, 1)),
        ):
            button = QPushButton(label)
            button.clicked.connect(slot)
            actions.addWidget(button)
        actions.addStretch(1)
        restore = QPushButton(tr("Restore the default rules"))
        restore.clicked.connect(self._restore_rules)
        actions.addWidget(restore)
        layout.addLayout(actions)
        return page

    def _append_rule_row(self, rule: HighlightRule) -> None:
        row = self.rules_table.rowCount()
        self.rules_table.insertRow(row)
        self.rules_table.setItem(row, RULE_COLUMN_ENABLED, _checkbox_item(rule.enabled))
        self.rules_table.setItem(row, RULE_COLUMN_NAME, QTableWidgetItem(rule.name))

        colour_item = QTableWidgetItem(rule.color.upper())
        colour_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        colour_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self._paint_colour_item(colour_item, rule.color)
        self.rules_table.setItem(row, RULE_COLUMN_COLOR, colour_item)

        self.rules_table.setItem(
            row, RULE_COLUMN_KEYWORDS, QTableWidgetItem(", ".join(rule.keywords))
        )
        self.rules_table.setItem(row, RULE_COLUMN_WHOLE_WORD, _checkbox_item(rule.whole_word))

        scope = QComboBox()
        for value, label in scope_labels().items():
            scope.addItem(label, value)
        scope_index = scope.findData(rule.scope)
        scope.setCurrentIndex(scope_index if scope_index >= 0 else 0)
        self.rules_table.setCellWidget(row, RULE_COLUMN_SCOPE, scope)

    @staticmethod
    def _paint_colour_item(item: QTableWidgetItem, colour: str) -> None:
        colour_obj = QColor(colour)
        if not colour_obj.isValid():
            return
        item.setBackground(colour_obj)
        # Texte noir ou blanc selon la clarté du fond, pour rester lisible.
        luminance = (
            0.299 * colour_obj.red() + 0.587 * colour_obj.green() + 0.114 * colour_obj.blue()
        )
        item.setForeground(QColor("#101114" if luminance > 150 else "#FFFFFF"))

    def _add_rule(self) -> None:
        self._append_rule_row(HighlightRule(name=tr("New rule"), keywords=[], color="#7C4DFF"))
        self.rules_table.setCurrentCell(self.rules_table.rowCount() - 1, RULE_COLUMN_NAME)

    def _remove_rule(self) -> None:
        row = self.rules_table.currentRow()
        if row >= 0:
            self.rules_table.removeRow(row)

    def _maybe_pick_color(self, row: int, column: int) -> None:
        if column == RULE_COLUMN_COLOR:
            self._pick_color()

    def _pick_color(self) -> None:
        row = self.rules_table.currentRow()
        if row < 0:
            return
        item = self.rules_table.item(row, RULE_COLUMN_COLOR)
        chosen = QColorDialog.getColor(
            QColor(item.text()), self, tr("Highlighting colour")
        )
        if not chosen.isValid():
            return
        item.setText(chosen.name().upper())
        self._paint_colour_item(item, chosen.name())

    def _restore_rules(self) -> None:
        confirm = QMessageBox.question(
            self,
            tr("Restore the default rules"),
            tr("The current highlighting rules will be replaced. Continue?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self.rules_table.setRowCount(0)
        for rule in default_rules():
            self._append_rule_row(rule)

    @staticmethod
    def _move_table_row(table: QTableWidget, offset: int) -> None:
        """Déplace la ligne courante, en préservant les widgets de cellule."""
        row = table.currentRow()
        target = row + offset
        if row < 0 or not 0 <= target < table.rowCount():
            return

        table.insertRow(target + (1 if offset > 0 else 0))
        source = row + (1 if offset < 0 else 0)
        destination = target + (1 if offset > 0 else 0)

        for column in range(table.columnCount()):
            item = table.takeItem(source, column)
            if item is not None:
                table.setItem(destination, column, item)
            widget = table.cellWidget(source, column)
            if widget is not None:
                # On recrée le widget : Qt le détruit avec sa ligne d'origine.
                table.setCellWidget(destination, column, _clone_cell_widget(widget))
        table.removeRow(source)
        table.setCurrentCell(target, 1)

    # -------------------------------------------------------- chargement

    def _load(self) -> None:
        s = self.settings
        self.autoscroll_check.setChecked(s.autoscroll)
        self.reopen_check.setChecked(s.reopen_logs)
        self.poll_spin.setValue(s.poll_interval_ms)
        self.ping_spin.setValue(s.ping_timeout_ms)
        self.max_rows_spin.setValue(s.max_rows)
        self.remember_check.setChecked(s.remember_last_host)
        self.share_edit.setText(s.share_name)
        self.subdir_edit.setText(s.log_subdir)
        self.filename_edit.setText(s.log_filename)

        for host in s.hosts:
            self._append_host_item(host)
        for credential in s.credentials:
            self._append_credential_row(credential)
        for rule in s.highlight_rules:
            self._append_rule_row(rule)

    # -------------------------------------------------------- enregistrement

    def result_settings(self) -> Settings:
        """Réglages issus de la boîte, à appliquer après ``accept()``."""
        s = self.settings
        s.autoscroll = self.autoscroll_check.isChecked()
        s.reopen_logs = self.reopen_check.isChecked()
        s.poll_interval_ms = self.poll_spin.value()
        s.ping_timeout_ms = self.ping_spin.value()
        s.max_rows = self.max_rows_spin.value()
        s.remember_last_host = self.remember_check.isChecked()
        s.share_name = self.share_edit.text().strip() or "Optix"
        s.log_subdir = self.subdir_edit.text().strip()
        s.log_filename = self.filename_edit.text().strip() or "FTOptixRuntime.0.log"

        s.hosts = [
            text for text in (
                self.hosts_list.item(row).text().strip()
                for row in range(self.hosts_list.count())
            ) if text
        ]

        credentials = []
        for row in range(self.credentials_table.rowCount()):
            username = self.credentials_table.item(row, CREDENTIAL_COLUMN_USERNAME)
            password_widget = self.credentials_table.cellWidget(row, CREDENTIAL_COLUMN_PASSWORD)
            label = self.credentials_table.item(row, CREDENTIAL_COLUMN_LABEL)
            enabled = self.credentials_table.item(row, CREDENTIAL_COLUMN_ENABLED)
            name = (username.text().strip() if username else "")
            if not name:
                continue
            credentials.append(
                Credential(
                    label=(label.text().strip() if label else ""),
                    username=name,
                    password=(password_widget.text() if password_widget else ""),
                    enabled=(enabled.checkState() == Qt.CheckState.Checked if enabled else True),
                )
            )
        s.credentials = credentials

        rules = []
        for row in range(self.rules_table.rowCount()):
            name_item = self.rules_table.item(row, RULE_COLUMN_NAME)
            colour_item = self.rules_table.item(row, RULE_COLUMN_COLOR)
            keywords_item = self.rules_table.item(row, RULE_COLUMN_KEYWORDS)
            enabled_item = self.rules_table.item(row, RULE_COLUMN_ENABLED)
            whole_item = self.rules_table.item(row, RULE_COLUMN_WHOLE_WORD)
            scope_widget = self.rules_table.cellWidget(row, RULE_COLUMN_SCOPE)

            keywords = [
                part.strip()
                for part in (keywords_item.text() if keywords_item else "").split(",")
                if part.strip()
            ]
            rules.append(
                HighlightRule(
                    name=(name_item.text().strip() if name_item else ""),
                    keywords=keywords,
                    color=(colour_item.text().strip() if colour_item else "#E53935"),
                    enabled=(
                        enabled_item.checkState() == Qt.CheckState.Checked if enabled_item else True
                    ),
                    whole_word=(
                        whole_item.checkState() == Qt.CheckState.Checked if whole_item else False
                    ),
                    scope=(scope_widget.currentData() if scope_widget else "line"),
                )
            )
        s.highlight_rules = rules
        return s


def _clone_cell_widget(widget):
    """Recrée un widget de cellule lors d'un déplacement de ligne."""
    if isinstance(widget, QComboBox):
        clone = QComboBox()
        for index in range(widget.count()):
            clone.addItem(widget.itemText(index), widget.itemData(index))
        clone.setCurrentIndex(widget.currentIndex())
        return clone
    if isinstance(widget, QLineEdit):
        clone = QLineEdit(widget.text())
        clone.setEchoMode(widget.echoMode())
        clone.setFrame(widget.hasFrame())
        return clone
    return widget
