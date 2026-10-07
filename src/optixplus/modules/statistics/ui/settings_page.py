"""Catégorie « Statistics » de la boîte Paramètres : noms des pages « Travail » et « Supervision ».

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
from ..core.config import StatisticsSettings

if TYPE_CHECKING:
    from ....shell.context import AppContext


def clean_names(names: list[str]) -> list[str]:
    """Noms sans espaces superflus, sans vides ni doublons (casse ignorée), dans l'ordre saisi."""
    seen: set[str] = set()
    result: list[str] = []
    for name in names:
        name = name.strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            result.append(name)
    return result


class NamesEditor(QWidget):
    """Une liste de noms modifiables sur place, avec Ajouter / Retirer."""

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
        item = self._append(tr("New name"))
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

        self.work = NamesEditor(tr("Names of the Work page"))
        self.supervision = NamesEditor(tr("Names of the Supervision page"))
        layout.addWidget(self.work)
        layout.addWidget(self.supervision)
        self.work.changed.connect(self._mark_dirty)
        self.supervision.changed.connect(self._mark_dirty)

        hint = QLabel(
            tr(
                "The search ignores case and covers the displayed name and the technical name of the page "
                "(without the IType_NN_ prefix). Double-click a name to edit it. "
                "Empty names and duplicates are ignored. The names are used at the next analysis."
            )
        )
        hint.setProperty("muted", True)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)

        self.defaults_button = defaults = QPushButton(tr("Restore defaults"))
        defaults.setToolTip(tr("Puts back the default page names in this form (applied with OK or Apply)."))
        defaults.clicked.connect(self._restore_defaults)
        buttons = QHBoxLayout()
        buttons.addWidget(defaults)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self._load(self._section)

    # ---- formulaire ----------------------------------------------------------------
    def _load(self, settings: StatisticsSettings) -> None:
        options = settings.options()  # une liste vide retombe sur les noms par défaut
        self.work.set_names(list(options.work_names))
        self.supervision.set_names(list(options.supervision_names))
        self._dirty = False

    def _mark_dirty(self) -> None:
        self._dirty = True

    def _restore_defaults(self) -> None:
        self._load(StatisticsSettings())
        self._dirty = True

    # ---- contrat de la boîte Paramètres -----------------------------------------------
    def has_unsaved_changes(self) -> bool:
        return self._dirty

    def validate(self) -> str:
        """Message d'erreur si une liste n'a aucun nom exploitable, sinon vide."""
        for editor, title in ((self.work, tr("Names of the Work page")), (self.supervision, tr("Names of the Supervision page"))):
            if not editor.names():
                return tr("The list “{title}” needs at least one name.").format(title=title)
        return ""

    def apply(self) -> None:
        """Range les noms dans les réglages (enregistrés par la boîte Paramètres)."""
        if not self._dirty:
            return
        self._section.work_names = self.work.names()
        self._section.supervision_names = self.supervision.names()
        self._load(self._section)  # affiche les valeurs normalisées

    def snapshot(self) -> dict:
        """Formulaire tel qu'affiché, même non appliqué."""
        return {
            "work": self.work.texts(),
            "work_row": self.work.list.currentRow(),
            "supervision": self.supervision.texts(),
            "supervision_row": self.supervision.list.currentRow(),
            "dirty": self._dirty,
        }

    def restore(self, state: dict) -> None:
        self.work.set_names(state.get("work", self.work.texts()))
        self.work.list.setCurrentRow(state.get("work_row", -1))
        self.supervision.set_names(state.get("supervision", self.supervision.texts()))
        self.supervision.list.setCurrentRow(state.get("supervision_row", -1))
        self._dirty = bool(state.get("dirty"))
