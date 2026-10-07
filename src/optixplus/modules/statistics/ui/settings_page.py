"""Catégorie « Statistics » de la boîte Paramètres : pages à mettre en évidence (mots-clés).

Les choix s'appliquent par « OK » ou « Appliquer » de la boîte Paramètres, jamais à la saisie ;
la page Statistiques les lit à chaque « Analyser ».
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ....common.i18n import tr
from ..core.config import StatisticsSettings, normalise_entries, parse_keywords

if TYPE_CHECKING:
    from ....shell.context import AppContext


class NamesEditor(QWidget):
    """Une liste d'entrées modifiables sur place, avec Ajouter / Retirer."""

    changed = Signal()

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._loading = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(QLabel(title))
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.SelectedClicked
        )
        self.list.setMaximumHeight(100)
        self.list.itemChanged.connect(self._on_changed)
        layout.addWidget(self.list)
        buttons = QHBoxLayout()
        self.add_button = QPushButton(tr("Add"))
        self.add_button.clicked.connect(self._add)
        self.remove_button = QPushButton(tr("Remove"))
        self.remove_button.clicked.connect(self._remove)
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.remove_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

    def set_names(self, names: list[str]) -> None:
        """Remplace le contenu sans signaler de modification."""
        self._loading = True
        self.list.clear()
        for name in names:
            self._append(name)
        self._loading = False

    def texts(self) -> list[str]:
        """Textes tels que saisis (vides et doublons compris)."""
        return [self.list.item(i).text() for i in range(self.list.count())]

    def names(self) -> list[str]:
        return clean_names(self.texts())

    def _append(self, text: str) -> QListWidgetItem:
        item = QListWidgetItem(text)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        self.list.addItem(item)
        return item

    def _on_changed(self, *_args) -> None:
        if not self._loading:
            self.changed.emit()

    def _add(self) -> None:
        item = self._append("")
        self.list.setCurrentItem(item)
        self.list.editItem(item)
        self.changed.emit()

    def _remove(self) -> None:
        row = self.list.currentRow()
        if row >= 0:
            self.list.takeItem(row)
            self.changed.emit()


class StatisticsSettingsPage(QWidget):
    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._section = context.settings.section(StatisticsSettings)
        self._dirty = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.entries = NamesEditor(tr("Highlighted pages"))
        self.entries.list.setMaximumHeight(160)
        self.entries.changed.connect(self._mark_dirty)
        layout.addWidget(self.entries)

        hint = QLabel(
            tr(
                "Each entry is a page to highlight in the Pages summary. Write one or more keywords separated by "
                "commas: the first page whose displayed name or technical name (without the IType_NN_ prefix) is "
                "one of them is used, ignoring case. Double-click an entry to edit it. "
                "Empty keywords and duplicates are ignored. The list is empty by default and is used at the next analysis."
            )
        )
        hint.setProperty("muted", True)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        self._load(self._section)

    # ---- formulaire ----------------------------------------------------------------
    def _load(self, settings: StatisticsSettings) -> None:
        self.entries.set_names(list(settings.highlighted))
        self._dirty = False

    def _mark_dirty(self) -> None:
        self._dirty = True

    # ---- contrat de la boîte Paramètres -----------------------------------------------
    def has_unsaved_changes(self) -> bool:
        return self._dirty

    def validate(self) -> str:
        """Message d'erreur si une entrée n'a aucun mot-clé, sinon vide."""
        if any(not parse_keywords(text) for text in self.entries.texts()):
            return tr("Every highlighted page needs at least one keyword.")
        return ""

    def apply(self) -> None:
        """Range les entrées dans les réglages (enregistrés par la boîte Paramètres)."""
        if not self._dirty:
            return
        self._section.highlighted = normalise_entries(self.entries.texts())
        self._load(self._section)  # affiche les valeurs normalisées

    def snapshot(self) -> dict:
        """Formulaire tel qu'affiché, même non appliqué."""
        return {"entries": self.entries.texts(), "row": self.entries.list.currentRow(), "dirty": self._dirty}

    def restore(self, state: dict) -> None:
        self.entries.set_names(state.get("entries", self.entries.texts()))
        self.entries.list.setCurrentRow(state.get("row", -1))
        self._dirty = bool(state.get("dirty"))
