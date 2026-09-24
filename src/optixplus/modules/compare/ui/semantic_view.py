"""Résumé sémantique : une ligne par hunk, nommée par nœud Optix, avec le détail brut en dessous.

C'est la vue par défaut et le cœur de l'outil. Chaque ligne est sélectionnable ; la sélection
émet ``hunk_selected`` pour piloter la vue diff.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QBrush, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QMenu,
    QMessageBox,
    QPushButton,
    QStyledItemDelegate,
    QToolButton,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..core.analysis import Comparison, FileDiff
from ..core.nodes import SemanticHunk
from ....common.i18n import tr
from ....common.widgets import scrollbar_below_header
from ..core.labels import SYMBOLE_SENS, decision_label, genre_label, sens_label
from ..core.plan import DECISIONS, Plan
from .style import couleur_sens

MAX_LIGNES_DETAIL = 400


@dataclass(slots=True)
class SemanticRow:
    """Un hunk et le fichier dont il vient."""

    diff: FileDiff
    hunk: SemanticHunk

    @property
    def rel(self) -> str:
        return self.diff.rel


class SemanticModel(QAbstractTableModel):
    """Modèle en lecture seule des lignes du résumé sémantique."""

    @staticmethod
    def colonnes() -> tuple[str, ...]:
        return (tr("Decision"), tr("Direction"), tr("Node"), tr("Kind"), tr("Detail"), tr("File"))

    COL_DECISION, COL_SENS, COL_NOEUD, COL_GENRE, COL_DETAIL, COL_FICHIER = range(6)
    ROLE_ROW = Qt.ItemDataRole.UserRole + 1

    decision_changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[SemanticRow] = []
        self.plan: Plan = Plan()

    def set_plan(self, plan: Plan) -> None:
        self.plan = plan
        if self._rows:
            self.dataChanged.emit(self.index(0, self.COL_DECISION), self.index(len(self._rows) - 1, self.COL_DECISION))

    def decision_of(self, row: SemanticRow) -> str:
        return self.plan.decision(row.rel, row.hunk.hunk.as_opcode())

    def flags(self, index: QModelIndex):
        base = super().flags(index)
        if index.isValid() and index.column() == self.COL_DECISION:
            return base | Qt.ItemFlag.ItemIsEditable
        return base

    def setData(self, index: QModelIndex, value, role: int = Qt.ItemDataRole.EditRole) -> bool:  # noqa: N802
        if not index.isValid() or index.column() != self.COL_DECISION or role != Qt.ItemDataRole.EditRole:
            return False
        if value not in DECISIONS:
            return False
        row = self._rows[index.row()]
        self.plan.set_decision(row.rel, row.hunk.hunk.as_opcode(), value)
        self.dataChanged.emit(index, index)
        self.decision_changed.emit()
        return True

    def refresh_decisions(self) -> None:
        if self._rows:
            self.dataChanged.emit(self.index(0, self.COL_DECISION), self.index(len(self._rows) - 1, self.COL_DECISION))
        self.decision_changed.emit()

    def set_rows(self, rows: list[SemanticRow]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def row_at(self, row: int) -> SemanticRow:
        return self._rows[row]

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 6

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.colonnes()[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        hunk = row.hunk
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if col == self.COL_DECISION:
                return decision_label(self.decision_of(row))
            if col == self.COL_SENS:
                sens = hunk.sens if hunk.significatif else "non_significatif"
                return f"{SYMBOLE_SENS[sens]} {sens_label(hunk.sens)}"
            if col == self.COL_NOEUD:
                return ", ".join(hunk.noeuds) if hunk.noeuds else "—"
            if col == self.COL_GENRE:
                return genre_label(hunk.genre)
            if col == self.COL_DETAIL:
                return hunk.detail
            if col == self.COL_FICHIER:
                return row.rel
        elif role == Qt.ItemDataRole.ToolTipRole:
            lignes = tr("project l.{p1}-{p2} ⇄ runtime l.{r1}-{r2}").format(
                p1=hunk.hunk.i1 + 1, p2=hunk.hunk.i2, r1=hunk.hunk.j1 + 1, r2=hunk.hunk.j2
            )
            return "\n".join(
                (hunk.libelle, tr("Path: {path}").format(path=hunk.chemin), lignes, tr("File: {file}").format(file=row.rel))
            )
        elif role == Qt.ItemDataRole.EditRole and col == self.COL_DECISION:
            return self.decision_of(row)
        elif role == Qt.ItemDataRole.ForegroundRole:
            if col == self.COL_DECISION:
                decision = self.decision_of(row)
                if decision == "prendre_runtime":
                    return QBrush(couleur_sens("ajout_runtime"))
                if decision == "garder_projet":
                    return QBrush(couleur_sens("branche_projet"))
                return QBrush(couleur_sens("non_significatif"))
            if not hunk.significatif:
                return QBrush(couleur_sens("non_significatif"))
            if col == self.COL_SENS:
                return QBrush(couleur_sens(hunk.sens))
        elif role == Qt.ItemDataRole.FontRole:
            font = QFont()
            if not hunk.significatif:
                font.setItalic(True)
            elif col == self.COL_NOEUD:
                font.setBold(True)
            return font
        elif role == self.ROLE_ROW:
            return row
        elif role == Qt.ItemDataRole.UserRole:
            # clé de tri : sens puis fichier puis position
            return (hunk.sens, row.rel, hunk.hunk.i1, hunk.hunk.j1)
        return None


class SemanticProxy(QSortFilterProxyModel):
    """Filtre texte + masquage des écarts non significatifs."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.hide_non_significant = True
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:  # noqa: N802
        model = self.sourceModel()
        assert isinstance(model, SemanticModel)
        row = model.row_at(source_row)
        if self.hide_non_significant and not row.hunk.significatif:
            return False
        pattern = self.filterRegularExpression().pattern()
        if not pattern:
            return True
        haystack = " ".join((*row.hunk.noeuds, row.hunk.chemin, row.hunk.detail, row.rel)).lower()
        return pattern.lower() in haystack


class DecisionDelegate(QStyledItemDelegate):
    """Liste déroulante Ignorer / Prendre le runtime / Garder le projet."""

    def createEditor(self, parent, option, index):  # noqa: N802
        combo = QComboBox(parent)
        for decision in DECISIONS:
            combo.addItem(decision_label(decision), decision)
        return combo

    def setEditorData(self, editor, index):  # noqa: N802
        current = index.data(Qt.ItemDataRole.EditRole)
        pos = editor.findData(current)
        editor.setCurrentIndex(max(pos, 0))

    def setModelData(self, editor, model, index):  # noqa: N802
        model.setData(index, editor.currentData(), Qt.ItemDataRole.EditRole)


class SemanticView(QWidget):
    """Table des hunks + panneau du contenu brut du hunk sélectionné + décisions du plan."""

    hunk_selected = Signal(object)  # SemanticRow ou None
    hunk_activated = Signal()  # double-clic : ouvrir la vue diff
    plan_changed = Signal()
    preview_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.comparison: Comparison | None = None
        self.model = SemanticModel(self)
        self.model.decision_changed.connect(self.plan_changed)
        self.proxy = SemanticProxy(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setSortRole(Qt.ItemDataRole.UserRole)

        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Filter by node, path, detail or file…"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.proxy.setFilterFixedString)
        self.show_all = QCheckBox(tr("Show non-significant differences (Id:, derived counters)"))
        self.show_all.toggled.connect(self._toggle_non_significant)
        self.counter = QLabel("")

        self.table = QTableView()
        scrollbar_below_header(self.table)
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)
        header.setSectionResizeMode(SemanticModel.COL_DETAIL, QHeaderView.ResizeMode.Stretch)
        self.table.setItemDelegateForColumn(SemanticModel.COL_DECISION, DecisionDelegate(self.table))
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.table.setColumnWidth(SemanticModel.COL_DECISION, 150)
        self.table.setColumnWidth(SemanticModel.COL_SENS, 150)
        self.table.setColumnWidth(SemanticModel.COL_NOEUD, 240)
        self.table.setColumnWidth(SemanticModel.COL_GENRE, 120)
        self.table.setColumnWidth(SemanticModel.COL_FICHIER, 260)
        self.table.selectionModel().currentRowChanged.connect(self._on_current_changed)
        self.table.doubleClicked.connect(self._on_double_click)

        # Barre des décisions : actions de masse (sélection ou tout) et prévisualisation.
        self.mass_button = QToolButton()
        self.mass_button.setText(tr("Bulk actions") + " ▾")
        self.mass_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.mass_button)
        self.act_ajouts_sel = menu.addAction(tr("Take the runtime additions — displayed files"), lambda: self.mass_action("ajouts", False))
        self.act_ajouts_tout = menu.addAction(tr("Take the runtime additions — everything"), lambda: self.mass_action("ajouts", True))
        menu.addSeparator()
        self.act_valeurs_sel = menu.addAction(tr("Align the values — displayed files"), lambda: self.mass_action("valeurs", False))
        self.act_valeurs_tout = menu.addAction(tr("Align the values — everything"), lambda: self.mass_action("valeurs", True))
        menu.addSeparator()
        self.act_complet_sel = menu.addAction(tr("Full alignment on the runtime — displayed files…"), lambda: self.mass_action("complet", False))
        self.act_complet_tout = menu.addAction(tr("Full alignment on the runtime — everything…"), lambda: self.mass_action("complet", True))
        menu.addSeparator()
        self.act_ignorer_sel = menu.addAction(tr("Ignore all — displayed files"), lambda: self.mass_action("ignorer", False))
        self.act_ignorer_tout = menu.addAction(tr("Ignore all — everything"), lambda: self.mass_action("ignorer", True))
        self.mass_button.setMenu(menu)
        self.plan_label = QLabel(tr("Plan: no decision"))
        self.preview_button = QPushButton(tr("Preview / apply…"))
        self.preview_button.setEnabled(False)
        self.preview_button.clicked.connect(self.preview_requested)
        self.plan_changed.connect(self._update_plan_label)

        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setFont(QFont("Consolas", 9))
        self.detail.setPlaceholderText(tr("Select a row to see the raw lines of the difference."))
        self.detail.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setProperty("cards", True)  # séparation sans trait, même écart
        splitter.addWidget(self.table)
        splitter.addWidget(self.detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        top = QHBoxLayout()
        top.addWidget(self.search, 1)
        top.addWidget(self.show_all)
        top.addWidget(self.counter)
        bar = QHBoxLayout()
        bar.addWidget(self.mass_button)
        bar.addWidget(self.plan_label, 1)
        bar.addWidget(self.preview_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(top)
        layout.addWidget(splitter, 1)
        layout.addLayout(bar)
        self.proxy.rowsInserted.connect(self._update_counter)
        self.proxy.rowsRemoved.connect(self._update_counter)
        self.proxy.modelReset.connect(self._update_counter)

    # -- API -----------------------------------------------------------------

    def set_diffs(self, diffs: list[FileDiff]) -> None:
        """Affiche les hunks de ces fichiers. La colonne Fichier est masquée pour un seul fichier."""
        rows = [SemanticRow(diff, hunk) for diff in diffs for hunk in diff.semantic]
        self.model.set_rows(rows)
        self.table.setColumnHidden(SemanticModel.COL_FICHIER, len(diffs) <= 1)
        self.table.sortByColumn(SemanticModel.COL_FICHIER, Qt.SortOrder.AscendingOrder)
        self.detail.clear()
        self._update_counter()

    def set_comparison(self, comparison: Comparison, plan: Plan) -> None:
        self.comparison = comparison
        self.model.set_plan(plan)
        self._update_plan_label()

    @property
    def plan(self) -> Plan:
        return self.model.plan

    def displayed_rels(self) -> list[str]:
        return sorted({r.rel for r in self.model._rows})

    def mass_action(self, action: str, tout: bool) -> int:
        """Pose une décision sur les fichiers affichés (ou tous). L'alignement complet demande confirmation."""
        if self.comparison is None:
            return 0
        rels = None if tout else self.displayed_rels()
        plan = self.plan
        n = 0
        if action == "ajouts":
            n = plan.recuperer_ajouts(self.comparison, rels)
        elif action == "valeurs":
            n = plan.aligner_valeurs(self.comparison, rels)
        elif action == "complet":
            supprimes = plan.blocs_supprimes(self.comparison, rels)
            if supprimes and not self._confirm_deletion(supprimes):
                return 0
            n = plan.aligner_complet(self.comparison, rels)
        elif action == "ignorer":
            plan.tout_ignorer(self.comparison, rels)
        self.model.refresh_decisions()
        return n

    def _confirm_deletion(self, supprimes) -> bool:
        lignes = [f"{rel} : {', '.join(s.noeuds) or s.detail}" for rel, s in supprimes]
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(tr("Full alignment on the runtime"))
        box.setText(
            tr("The project will become identical to the runtime. <b>{n} block(s) present on the project side only will be deleted</b>:").format(
                n=len(supprimes)
            )
        )
        box.setDetailedText("\n".join(lignes))
        box.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        return box.exec() == QMessageBox.StandardButton.Ok

    def _update_plan_label(self) -> None:
        plan = self.plan
        n = plan.nb_pris()
        garder = sum(1 for d in plan.decisions.values() if d == "garder_projet")
        parts = [tr("{n} difference(s) to take from the runtime").format(n=n)]
        if garder:
            parts.append(tr("{n} kept on the project side").format(n=garder))
        if plan.alignement_complet:
            parts.append(tr("{n} file(s) in full alignment").format(n=len(plan.alignement_complet)))
        self.plan_label.setText(tr("Plan: {content}").format(content=", ".join(parts)) if n or garder else tr("Plan: no decision"))
        self.preview_button.setEnabled(n > 0 or bool(plan.alignement_complet))

    def _on_double_click(self, index: QModelIndex) -> None:
        if index.column() != SemanticModel.COL_DECISION:
            self.hunk_activated.emit()

    def current_row(self) -> SemanticRow | None:
        index = self.table.currentIndex()
        if not index.isValid():
            return None
        return self.proxy.data(index, SemanticModel.ROLE_ROW)

    def visible_count(self) -> int:
        return self.proxy.rowCount()

    # -- Interne ---------------------------------------------------------------

    def _toggle_non_significant(self, checked: bool) -> None:
        if hasattr(self.proxy, "beginFilterChange"):  # Qt ≥ 6.10
            self.proxy.beginFilterChange()
            self.proxy.hide_non_significant = not checked
            self.proxy.endFilterChange()
        else:
            self.proxy.hide_non_significant = not checked
            self.proxy.invalidateFilter()
        self._update_counter()

    def _update_counter(self, *_args) -> None:
        total = self.model.rowCount()
        self.counter.setText(tr("{shown} / {total} differences").format(shown=self.proxy.rowCount(), total=total))

    def _on_current_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        row = self.proxy.data(current, SemanticModel.ROLE_ROW) if current.isValid() else None
        self.detail.setPlainText(_hunk_text(row) if row else "")
        self.hunk_selected.emit(row)


def _hunk_text(row: SemanticRow) -> str:
    """Les lignes brutes du hunk : ``-`` côté projet, ``+`` côté runtime, tronquées si énormes."""
    h = row.hunk.hunk
    projet = row.diff.projet.lines[h.i1 : h.i2]
    runtime = row.diff.runtime.lines[h.j1 : h.j2]
    out = [f"{row.hunk.libelle}", tr("path: {path}").format(path=row.hunk.chemin), ""]
    if projet:
        out.append("--- " + tr("project l.{start}-{end}  ({n} lines)").format(start=h.i1 + 1, end=h.i2, n=len(projet)))
        out += ["- " + line.decode("utf-8", "replace") for line in projet[:MAX_LIGNES_DETAIL]]
        if len(projet) > MAX_LIGNES_DETAIL:
            out.append("  … " + tr("{n} more lines").format(n=len(projet) - MAX_LIGNES_DETAIL))
    if runtime:
        out.append("+++ " + tr("runtime l.{start}-{end}  ({n} lines)").format(start=h.j1 + 1, end=h.j2, n=len(runtime)))
        out += ["+ " + line.decode("utf-8", "replace") for line in runtime[:MAX_LIGNES_DETAIL]]
        if len(runtime) > MAX_LIGNES_DETAIL:
            out.append("  … " + tr("{n} more lines").format(n=len(runtime) - MAX_LIGNES_DETAIL))
    return "\n".join(out)

