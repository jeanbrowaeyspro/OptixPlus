"""Les cinq vues spécialisées et leur conteneur à onglets.

Chaque vue est une table triable construite sur une liste de lignes ``(colonnes…, état)`` ;
un filtre « écarts seuls » masque les lignes identiques.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QSortFilterProxyModel, Qt
from PySide6.QtGui import QBrush, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...core.analysis import Comparison
from ..style import COULEUR_ETAT, COULEUR_SENS

LIBELLE_ETAT_LIGNE = {
    "identique": "identique",
    "runtime_seul": "runtime seul",
    "projet_seul": "projet seul",
    "modifie": "modifié",
}
COULEUR_ETAT_LIGNE = {
    "identique": COULEUR_ETAT["identique"],
    "runtime_seul": COULEUR_SENS["ajout_runtime"],
    "projet_seul": COULEUR_SENS["branche_projet"],
    "modifie": COULEUR_SENS["valeur_modifiee"],
}
ROLE_ETAT = Qt.ItemDataRole.UserRole + 3


class _Proxy(QSortFilterProxyModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.only_gaps = True
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setFilterKeyColumn(-1)

    def filterAcceptsRow(self, source_row: int, source_parent) -> bool:  # noqa: N802
        if self.only_gaps:
            index = self.sourceModel().index(source_row, 0, source_parent)
            if index.data(ROLE_ETAT) == "identique":
                return False
        return super().filterAcceptsRow(source_row, source_parent)


class TableView(QWidget):
    """Table générique : en-tête, note, filtre texte, case « écarts seuls », compteur."""

    def __init__(self, colonnes: Sequence[str], note: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.colonnes = list(colonnes)
        self.model = QStandardItemModel(0, len(self.colonnes), self)
        self.model.setHorizontalHeaderLabels(self.colonnes)
        self.proxy = _Proxy(self)
        self.proxy.setSourceModel(self.model)
        self.note = QLabel(note)
        self.note.setWordWrap(True)
        self.note.setTextFormat(Qt.TextFormat.RichText)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filtrer…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.proxy.setFilterFixedString)
        self.only_gaps = QCheckBox("Écarts seuls")
        self.only_gaps.setChecked(True)
        self.only_gaps.toggled.connect(self._toggle)
        self.counter = QLabel("")
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        top = QHBoxLayout()
        top.addWidget(self.search, 1)
        top.addWidget(self.only_gaps)
        top.addWidget(self.counter)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.note)
        layout.addLayout(top)
        layout.addWidget(self.table, 1)

    def set_rows(self, rows: Sequence[tuple[Sequence[str], str]]) -> None:
        """``rows`` : ``(valeurs par colonne, état)`` avec état ∈ identique / runtime_seul / projet_seul / modifie."""
        self.model.removeRows(0, self.model.rowCount())
        for values, etat in rows:
            items = [QStandardItem(str(v)) for v in values]
            couleur = COULEUR_ETAT_LIGNE.get(etat)
            for item in items:
                item.setData(etat, ROLE_ETAT)
                if couleur is not None and etat != "identique":
                    item.setForeground(QBrush(couleur))
            self.model.appendRow(items)
        self.table.resizeColumnsToContents()
        self._update_counter()

    def visible_count(self) -> int:
        return self.proxy.rowCount()

    def _toggle(self, checked: bool) -> None:
        self.proxy.only_gaps = checked
        self.proxy.invalidate()
        self._update_counter()

    def _update_counter(self) -> None:
        self.counter.setText(f"{self.proxy.rowCount()} / {self.model.rowCount()}")


class TagsView(TableView):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            ["Nom", "Type", "DataType", "SymbolName", "Chemin", "État"],
            "Tags CoDeSys des deux côtés, indexés par <b>SymbolName</b> : quelles variables l'automate a gagné ou perdu.",
            parent,
        )

    def load(self, comparison: Comparison) -> None:
        rows = []
        for rel, delta in comparison.tags.items():
            for r in delta.rows:
                tag = r.ref
                dtype = tag.data_type + (f"[{tag.array}]" if tag.array else "")
                rows.append(((tag.name, tag.type, dtype, r.symbol, tag.path, LIBELLE_ETAT_LIGNE[r.etat]), r.etat))
        self.set_rows(rows)


class TranslationsView(TableView):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(["Clé", "État"], "", parent)

    def load(self, comparison: Comparison) -> None:
        rows = []
        notes = []
        header: list[str] = []
        for rel, delta in comparison.translations.items():
            dp, dr = delta.dimensions_projet, delta.dimensions_runtime
            coh_p = "cohérent" if delta.projet and delta.projet.coherent else "INCOHÉRENT"
            coh_r = "cohérent" if delta.runtime and delta.runtime.coherent else "INCOHÉRENT"
            notes.append(
                f"<b>{rel}</b> — Dimensions projet <b>{list(dp) if dp else '?'}</b> ({coh_p}), "
                f"runtime <b>{list(dr) if dr else '?'}</b> ({coh_r})"
            )
            table = delta.runtime or delta.projet
            if table is not None and not header:
                header = list(table.header[1:])
            p_rows = delta.projet.by_key() if delta.projet else {}
            r_rows = delta.runtime.by_key() if delta.runtime else {}
            for key in list(r_rows) + [k for k in p_rows if k not in r_rows]:
                row = r_rows.get(key) or p_rows.get(key) or []
                if key not in p_rows:
                    etat = "runtime_seul"
                elif key not in r_rows:
                    etat = "projet_seul"
                elif p_rows[key] != r_rows[key]:
                    etat = "modifie"
                else:
                    etat = "identique"
                rows.append(((key, *row[1:], LIBELLE_ETAT_LIGNE[etat]), etat))
        self.model.clear()
        self.colonnes = ["Clé", *header, "État"]
        self.model.setHorizontalHeaderLabels(self.colonnes)
        self.note.setText("<br>".join(notes) if notes else "Aucun dictionnaire de traductions divergent.")
        self.set_rows(rows)


class TypesView(TableView):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            ["GUID", "Nom", "État"],
            "GUID de <b>UserDefinedModule.xml</b>, résolus en noms via <b>TypeConstants.cs</b>. "
            "L'élagage se fait toujours par GUID, jamais par nom.",
            parent,
        )

    def load(self, comparison: Comparison) -> None:
        rows = []
        if comparison.types is not None:
            t = comparison.types
            names = comparison.type_names
            runtime_set, projet_set = set(t.runtime), set(t.projet)
            for guid in list(t.projet) + [g for g in t.runtime if g not in projet_set]:
                if guid not in runtime_set:
                    etat = "projet_seul"
                elif guid not in projet_set:
                    etat = "runtime_seul"
                else:
                    etat = "identique"
                rows.append(((guid, names.get(guid, "?"), LIBELLE_ETAT_LIGNE[etat]), etat))
        self.set_rows(rows)


class StatsView(TableView):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            ["Statistique", "Projet", "Runtime"],
            "Statistiques du <b>.optix</b> : purement informatives, recalculées par l'IDE à l'ouverture. "
            "Jamais un critère de comparaison.",
            parent,
        )
        self.only_gaps.setChecked(False)

    def load(self, comparison: Comparison) -> None:
        rows = []
        if comparison.optix is not None:
            for key, p, r in comparison.optix.stats_rows():
                etat = "identique" if p == r else "modifie"
                rows.append(((key, "" if p is None else str(p), "" if r is None else str(r)), etat))
        self.set_rows(rows)


class NetLogicView(TableView):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            ["Classe", "Source côté projet", "État"],
            "Classes présentes dans chaque DLL NetLogic (table TypeDef des métadonnées CLI). "
            "Les logiques référencent les types par chaîne : un type retiré ne casse pas la compilation, "
            "mais <code>Project.Current.Find(…)</code> renverra <code>null</code>.",
            parent,
        )

    def load(self, comparison: Comparison) -> None:
        rows = []
        nl = comparison.netlogic
        if nl is not None:
            if nl.erreur:
                self.note.setText(f"Lecture des DLL impossible : {nl.erreur}")
            r_set, p_set = set(nl.runtime), set(nl.projet)
            for name in nl.projet + [c for c in nl.runtime if c not in p_set]:
                etat = "projet_seul" if name not in r_set else "runtime_seul" if name not in p_set else "identique"
                rows.append(((name, nl.sources_projet.get(name, ""), LIBELLE_ETAT_LIGNE[etat]), etat))
        else:
            self.note.setText("Aucune DLL NetLogic commune aux deux côtés.")
        self.set_rows(rows)


class SpecializedTabs(QTabWidget):
    """Les vues spécialisées ; ``activate_for(rel)`` met en avant celle qui correspond au fichier."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tags = TagsView()
        self.translations = TranslationsView()
        self.types = TypesView()
        self.stats = StatsView()
        self.netlogic = NetLogicView()
        self.addTab(self.tags, "Tags CoDeSys")
        self.addTab(self.translations, "Traductions")
        self.addTab(self.types, "Types utilisateur")
        self.addTab(self.stats, "Statistiques .optix")
        self.addTab(self.netlogic, "NetLogic")

    def load(self, comparison: Comparison) -> None:
        for view in (self.tags, self.translations, self.types, self.stats, self.netlogic):
            view.load(comparison)
        self.setTabText(0, f"Tags CoDeSys ({sum(len(d.ecarts()) for d in comparison.tags.values())})")
        n_tr = sum(len(d.runtime_seul) + len(d.projet_seul) + len(d.modifies) for d in comparison.translations.values())
        self.setTabText(1, f"Traductions ({n_tr})")
        n_ty = len(comparison.types.projet_seul) + len(comparison.types.runtime_seul) if comparison.types else 0
        self.setTabText(2, f"Types utilisateur ({n_ty})")
        n_nl = len(comparison.netlogic.projet_seul) + len(comparison.netlogic.runtime_seul) if comparison.netlogic else 0
        self.setTabText(4, f"NetLogic ({n_nl})")

    def activate_for(self, rel: str, comparison: Comparison | None) -> None:
        if comparison is None:
            return
        if rel in comparison.tags:
            self.setCurrentWidget(self.tags)
        elif rel in comparison.translations:
            self.setCurrentWidget(self.translations)
        elif rel.endswith("UserDefinedModule.xml") or rel.endswith(".cs"):
            self.setCurrentWidget(self.types)
        elif rel.endswith(".optix"):
            self.setCurrentWidget(self.stats)
        elif rel.endswith(".dll") or rel.endswith(".pdb"):
            self.setCurrentWidget(self.netlogic)
