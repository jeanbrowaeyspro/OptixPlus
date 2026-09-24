"""Catégorie « Lecteur de logs » de la boîte Paramètres : automates, général, surlignage.

Chaque automate est décrit par l'utilisateur : nom, adresse IP, identifiant, mot de passe
et dossier des journaux (relatif au partage de l'automate, ou dossier local / réseau
complet). « Dupliquer » crée un automate à partir de celui sélectionné.

Rien n'est appliqué à la saisie : la page travaille sur une copie des réglages, appliquée
par « OK » ou « Appliquer » de la boîte Paramètres, après ``validate()``.
"""

from __future__ import annotations

import copy
from dataclasses import asdict
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from ....common.i18n import tr
from ....common.widgets import ElidedLabel, scrollbar_below_header
from ..core.config import DEFAULT_LOG_FILENAME, Controller, HighlightRule, Settings, default_rules

if TYPE_CHECKING:
    from ....shell.context import AppContext

MODULE_ID = "logreader"


def scope_labels() -> dict[str, str]:
    return {"line": tr("Whole line"), "message": tr("Message only")}


RULE_COLUMN_ENABLED = 0
RULE_COLUMN_NAME = 1
RULE_COLUMN_COLOR = 2
RULE_COLUMN_KEYWORDS = 3
RULE_COLUMN_WHOLE_WORD = 4
RULE_COLUMN_SCOPE = 5

TAB_CONTROLLERS, TAB_GENERAL, TAB_RULES = range(3)


def _checkbox_item(checked: bool) -> QTableWidgetItem:
    item = QTableWidgetItem()
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
    item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    return item


def stored_settings(context: AppContext) -> Settings:
    """Réglages en service : ceux de la page ouverte, sinon ceux du fichier."""
    page = live_page(context)
    if page is not None:
        return page.settings
    return Settings.bound(context.settings.store(MODULE_ID), context.settings.save)


def live_page(context: AppContext):
    """Page du Lecteur de logs si elle est ouverte dans la fenêtre, sinon ``None``."""
    window = getattr(context.controller, "window", None) if context.controller is not None else None
    module = window.module(MODULE_ID) if window is not None else None
    return getattr(module, "page", None)


class LogReaderSettingsPage(QWidget):
    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._loading = False
        self._build()
        self._load(copy.deepcopy(stored_settings(context)))

    # ================================================================= composition
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_controllers_tab(), tr("Controllers"))
        self.tabs.addTab(self._build_general_tab(), tr("General"))
        self.tabs.addTab(self._build_rules_tab(), tr("Highlighting"))
        layout.addWidget(self.tabs, 1)

    # ------------------------------------------------------------------ automates
    def _build_controllers_tab(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(14)

        left = QVBoxLayout()
        self.controllers_list = QListWidget()
        self.controllers_list.currentRowChanged.connect(self._show_controller)
        left.addWidget(self.controllers_list, 1)
        buttons = QHBoxLayout()
        self.add_button = QPushButton(tr("Add"))
        self.add_button.setToolTip(tr("Creates a new controller, with the default log folder."))
        self.add_button.clicked.connect(self._add_controller)
        self.duplicate_button = QPushButton(tr("Duplicate"))
        self.duplicate_button.setToolTip(tr("Creates a new controller from the selected one (all its fields)."))
        self.duplicate_button.clicked.connect(self._duplicate_controller)
        self.remove_button = QPushButton(tr("Delete"))
        self.remove_button.setToolTip(tr("Deletes the selected controller."))
        self.remove_button.clicked.connect(self._remove_controller)
        for button in (self.add_button, self.duplicate_button, self.remove_button):
            buttons.addWidget(button)
        left.addLayout(buttons)
        order = QHBoxLayout()
        self.up_button = QPushButton(tr("Move up"))
        self.up_button.clicked.connect(lambda: self._move_controller(-1))
        self.down_button = QPushButton(tr("Move down"))
        self.down_button.clicked.connect(lambda: self._move_controller(1))
        order.addWidget(self.up_button)
        order.addWidget(self.down_button)
        order.addStretch(1)
        left.addLayout(order)
        layout.addLayout(left, 1)

        self.form_box = QGroupBox(tr("Controller"))
        form = QFormLayout(self.form_box)
        form.setSpacing(10)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(tr("Optional: shown in the tabs and the lists"))
        form.addRow(tr("Name"), self.name_edit)
        self.host_edit = QLineEdit()
        form.addRow(tr("IP address"), self.host_edit)
        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText(tr("Empty: current Windows session"))
        form.addRow(tr("Login"), self.username_edit)
        password_row = QHBoxLayout()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.show_password_check = QCheckBox(tr("Show"))
        self.show_password_check.toggled.connect(
            lambda shown: self.password_edit.setEchoMode(
                QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password
            )
        )
        password_row.addWidget(self.password_edit, 1)
        password_row.addWidget(self.show_password_check)
        form.addRow(tr("Password"), password_row)
        folder_row = QHBoxLayout()
        self.folder_edit = QLineEdit()
        self.folder_edit.setToolTip(
            tr(
                "Relative (Optix\\Log): share and subfolder on the controller, at its IP address.\n"
                "Absolute: a local folder (C:\\…) or a full network path (\\\\server\\share\\…), used as is."
            )
        )
        browse = QPushButton(tr("Browse…"))
        browse.setToolTip(tr("Chooses a folder of this computer or of the network."))
        browse.clicked.connect(self._browse_folder)
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(browse)
        form.addRow(tr("Log folder") + " *", folder_row)
        self.filename_edit = QLineEdit()
        self.filename_edit.setPlaceholderText(DEFAULT_LOG_FILENAME)
        self.filename_edit.setToolTip(tr("File read in the log folder of this controller."))
        form.addRow(tr("Log file"), self.filename_edit)
        # Une ligne, abrégée au milieu si besoin (infobulle : texte complet). Pas de retour
        # à la ligne automatique : il couperait le chemin au premier « \ ».
        self.path_preview = ElidedLabel(mode=Qt.TextElideMode.ElideMiddle)
        self.path_preview.setProperty("muted", True)
        form.addRow(self.path_preview)
        note = QLabel(
            tr(
                "* Required. The IP address is only needed for a relative log folder (Optix\\Log), which is "
                "on the controller. Passwords are encrypted by the Windows DPAPI: only your account, on this "
                "computer, can read them."
            )
        )
        note.setProperty("muted", True)
        note.setWordWrap(True)
        form.addRow(note)
        layout.addWidget(self.form_box, 2)

        for edit in (
            self.name_edit, self.host_edit, self.username_edit, self.password_edit, self.folder_edit, self.filename_edit
        ):
            edit.textEdited.connect(self._form_edited)
        return page

    def _browse_folder(self) -> None:
        controller = self._current()
        start = controller.log_folder() if controller is not None else ""
        folder = QFileDialog.getExistingDirectory(self, tr("Log folder"), start)
        if folder:
            self.folder_edit.setText(folder.replace("/", "\\"))
            self._form_edited()

    def _current(self) -> Controller | None:
        row = self.controllers_list.currentRow()
        return self._controllers[row] if 0 <= row < len(self._controllers) else None

    def _show_controller(self, _row: int = -1) -> None:
        controller = self._current()
        self.form_box.setEnabled(controller is not None)
        for button in (self.duplicate_button, self.remove_button, self.up_button, self.down_button):
            button.setEnabled(controller is not None)
        self._loading = True
        for edit, value in (
            (self.name_edit, controller.name if controller else ""),
            (self.host_edit, controller.host if controller else ""),
            (self.username_edit, controller.username if controller else ""),
            (self.password_edit, controller.password if controller else ""),
            (self.folder_edit, controller.log_dir if controller else ""),
            (self.filename_edit, controller.log_filename if controller else ""),
        ):
            edit.setText(value)
        self._loading = False
        self._refresh_preview()

    def _form_edited(self, *_args) -> None:
        controller = self._current()
        if self._loading or controller is None:
            return
        controller.name = self.name_edit.text()
        controller.host = self.host_edit.text().strip()
        controller.username = self.username_edit.text().strip()
        controller.password = self.password_edit.text()
        controller.log_dir = self.folder_edit.text().strip()
        controller.log_filename = self.filename_edit.text().strip() or DEFAULT_LOG_FILENAME
        self._refresh_item(self.controllers_list.currentRow())
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        controller = self._current()
        if controller is None:
            self._set_preview(tr("No controller: add one, or duplicate an existing one."))
            return
        error = controller.validation_error()
        if error:
            self._set_preview(error)
            return
        path = controller.log_path()
        self._set_preview(tr("Log read: {path}").format(path=path))

    def _set_preview(self, text: str) -> None:
        self.path_preview.setText(text)
        self.path_preview.setToolTip(text)

    def _item_text(self, controller: Controller) -> str:
        text = controller.display_name or tr("New controller")
        if controller.name.strip() and controller.host.strip():
            text += f"  ({controller.host.strip()})"
        return text

    def _refresh_item(self, row: int) -> None:
        item = self.controllers_list.item(row)
        if item is not None and 0 <= row < len(self._controllers):
            controller = self._controllers[row]
            item.setText(self._item_text(controller))
            item.setToolTip(controller.validation_error())

    def _insert(self, row: int, controller: Controller) -> None:
        self._controllers.insert(row, controller)
        self.controllers_list.insertItem(row, QListWidgetItem(self._item_text(controller)))
        self._refresh_item(row)
        self.controllers_list.setCurrentRow(row)

    def _add_controller(self) -> None:
        self._insert(len(self._controllers), Controller())
        self.host_edit.setFocus()

    def _duplicate_controller(self) -> None:
        controller = self._current()
        if controller is not None:
            self._insert(self.controllers_list.currentRow() + 1, controller.duplicate())
            self.name_edit.setFocus()
            self.name_edit.selectAll()

    def _remove_controller(self) -> None:
        row = self.controllers_list.currentRow()
        if row < 0:
            return
        del self._controllers[row]
        self.controllers_list.takeItem(row)
        self.controllers_list.setCurrentRow(min(row, len(self._controllers) - 1))
        self._show_controller()

    def _move_controller(self, offset: int) -> None:
        row = self.controllers_list.currentRow()
        target = row + offset
        if row < 0 or not 0 <= target < len(self._controllers):
            return
        self._controllers.insert(target, self._controllers.pop(row))
        self.controllers_list.insertItem(target, self.controllers_list.takeItem(row))
        self.controllers_list.setCurrentRow(target)

    # --------------------------------------------------------------------- général
    def _build_general_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 12, 10, 10)
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

        layout.addStretch(1)
        return page

    # ------------------------------------------------------------------ surlignage
    def _build_rules_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 12, 10, 10)
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
        for column in (RULE_COLUMN_ENABLED, RULE_COLUMN_NAME, RULE_COLUMN_COLOR, RULE_COLUMN_WHOLE_WORD, RULE_COLUMN_SCOPE):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(RULE_COLUMN_KEYWORDS, QHeaderView.ResizeMode.Stretch)
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
        self.rules_table.setItem(row, RULE_COLUMN_KEYWORDS, QTableWidgetItem(", ".join(rule.keywords)))
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
        luminance = 0.299 * colour_obj.red() + 0.587 * colour_obj.green() + 0.114 * colour_obj.blue()
        item.setForeground(QColor("#101114" if luminance > 150 else "#FFFFFF"))

    def _add_rule(self) -> None:
        self._append_rule_row(HighlightRule(name=tr("New rule"), keywords=[], color="#7C4DFF"))
        self.rules_table.setCurrentCell(self.rules_table.rowCount() - 1, RULE_COLUMN_NAME)

    def _remove_rule(self) -> None:
        row = self.rules_table.currentRow()
        if row >= 0:
            self.rules_table.removeRow(row)

    def _maybe_pick_color(self, _row: int, column: int) -> None:
        if column == RULE_COLUMN_COLOR:
            self._pick_color()

    def _pick_color(self) -> None:
        row = self.rules_table.currentRow()
        if row < 0:
            return
        item = self.rules_table.item(row, RULE_COLUMN_COLOR)
        chosen = QColorDialog.getColor(QColor(item.text()), self, tr("Highlighting colour"))
        if chosen.isValid():
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

    # ================================================================= chargement
    def _load(self, settings: Settings) -> None:
        self._base = settings
        self._controllers: list[Controller] = copy.deepcopy(settings.controllers)
        self.controllers_list.clear()
        for controller in self._controllers:
            self.controllers_list.addItem(QListWidgetItem(self._item_text(controller)))
        for row in range(len(self._controllers)):
            self._refresh_item(row)
        self.autoscroll_check.setChecked(settings.autoscroll)
        self.reopen_check.setChecked(settings.reopen_logs)
        self.poll_spin.setValue(settings.poll_interval_ms)
        self.ping_spin.setValue(settings.ping_timeout_ms)
        self.max_rows_spin.setValue(settings.max_rows)
        self.remember_check.setChecked(settings.remember_last_host)
        self.rules_table.setRowCount(0)
        for rule in settings.highlight_rules:
            self._append_rule_row(rule)
        self.controllers_list.setCurrentRow(0 if self._controllers else -1)
        self._show_controller()
        self._original = self._comparable(self.result_settings())

    # ================================================================= résultat
    def result_settings(self) -> Settings:
        """Réglages tels que saisis (copie ; les champs non édités viennent de la base)."""
        s = copy.deepcopy(self._base)
        s.controllers = copy.deepcopy(self._controllers)
        s.autoscroll = self.autoscroll_check.isChecked()
        s.reopen_logs = self.reopen_check.isChecked()
        s.poll_interval_ms = self.poll_spin.value()
        s.ping_timeout_ms = self.ping_spin.value()
        s.max_rows = self.max_rows_spin.value()
        s.remember_last_host = self.remember_check.isChecked()
        rules = []
        for row in range(self.rules_table.rowCount()):
            name_item = self.rules_table.item(row, RULE_COLUMN_NAME)
            colour_item = self.rules_table.item(row, RULE_COLUMN_COLOR)
            keywords_item = self.rules_table.item(row, RULE_COLUMN_KEYWORDS)
            enabled_item = self.rules_table.item(row, RULE_COLUMN_ENABLED)
            whole_item = self.rules_table.item(row, RULE_COLUMN_WHOLE_WORD)
            scope_widget = self.rules_table.cellWidget(row, RULE_COLUMN_SCOPE)
            keywords = [p.strip() for p in (keywords_item.text() if keywords_item else "").split(",") if p.strip()]
            rules.append(
                HighlightRule(
                    name=name_item.text().strip() if name_item else "",
                    keywords=keywords,
                    color=colour_item.text().strip() if colour_item else "#E53935",
                    enabled=enabled_item.checkState() == Qt.CheckState.Checked if enabled_item else True,
                    whole_word=whole_item.checkState() == Qt.CheckState.Checked if whole_item else False,
                    scope=scope_widget.currentData() if scope_widget else "line",
                )
            )
        s.highlight_rules = rules
        return s

    @staticmethod
    def _comparable(settings: Settings) -> dict:
        return {k: v for k, v in asdict(settings).items() if k not in ("open_hosts", "dock_state", "last_host")}

    # ============================================================ contrat Paramètres
    def has_unsaved_changes(self) -> bool:
        return self._comparable(self.result_settings()) != self._original

    def validate(self) -> str:
        """Message si un automate est incomplet (il est alors sélectionné), chaîne vide sinon."""
        for row, controller in enumerate(self._controllers):
            error = controller.validation_error()
            if error:
                self.tabs.setCurrentIndex(TAB_CONTROLLERS)
                self.controllers_list.setCurrentRow(row)
                return tr("Controller “{name}”: {error}").format(
                    name=controller.display_name or tr("New controller"), error=error
                )
        return ""

    def apply(self) -> None:
        """Enregistre et applique aux onglets ouverts du Lecteur de logs."""
        if not self.has_unsaved_changes():
            return
        new = self.result_settings()
        page = live_page(self._context)
        if page is not None:
            # Champs tenus par la page elle-même (onglets ouverts, disposition, dernier automate).
            for name in ("open_hosts", "dock_state", "last_host", "hidden_columns"):
                setattr(new, name, getattr(page.settings, name))
        bound = Settings.bound(self._context.settings.store(MODULE_ID), self._context.settings.save)
        new.copy_binding_from(bound)
        new.save()
        if page is not None:
            page.apply_settings(new)
        self._load(copy.deepcopy(new))

    def snapshot(self) -> dict:
        return {
            "settings": asdict(self.result_settings()),
            "original": self._original,
            "tab": self.tabs.currentIndex(),
            "row": self.controllers_list.currentRow(),
        }

    def restore(self, state: dict) -> None:
        data = dict(state.get("settings") or {})
        if not data:
            return
        # asdict garde les mots de passe en clair (état en mémoire, jamais écrit) : relus tels quels.
        passwords = [c.get("password", "") for c in data.get("controllers", [])]
        settings = Settings.from_dict({**data, "controllers": [{**c, "password": ""} for c in data.get("controllers", [])]})
        for controller, password in zip(settings.controllers, passwords):
            controller.password = password
        self._load(settings)
        self._original = state.get("original", self._original)
        self.tabs.setCurrentIndex(state.get("tab", 0))
        if 0 <= state.get("row", -1) < len(self._controllers):
            self.controllers_list.setCurrentRow(state["row"])


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
