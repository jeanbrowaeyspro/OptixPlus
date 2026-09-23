"""Fenêtre de résultats : bandeau de synthèse, arbre des fichiers, onglets (résumé sémantique en tête)."""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QSplitter,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
    QVBoxLayout,
    QWidget,
)

from ..core.analysis import Comparison, FileDiff
from ..core.plan import Plan, Preview
from ..core.scan import FileEntry
from .apply_dialog import ApplyDialog
from .diff_view import DiffView
from .plan_dialog import PlanDialog
from .search_view import SearchView
from .semantic_view import SemanticRow, SemanticView
from .specialized.views import SpecializedTabs
from ....common import theme
from ....common.i18n import tr
from ..core.labels import etat_label, sens_label
from .style import couleur_etat, couleur_sens, pastille, taille_lisible

ROLE_REL = Qt.ItemDataRole.UserRole
ROLE_KIND = Qt.ItemDataRole.UserRole + 1  # "file" | "dir" | "root" | "attendus"


def branche_attendus() -> str:
    """Libellé de la branche des fichiers attendus d'un seul côté."""
    return tr("Normal structural differences")


@dataclass(slots=True)
class _DirNode:
    rel: str
    item: QTreeWidgetItem
    files: list[str] = field(default_factory=list)


class FileTree(QTreeWidget):
    """L'arborescence réelle des fichiers, avec pastille d'état et compteur de hunks."""

    selection_changed = Signal(list)  # liste de chemins relatifs de fichiers (diffs) à afficher

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setHeaderLabels([tr("File"), tr("Hunks"), tr("State"), tr("Project"), tr("Runtime")])
        self.setAlternatingRowColors(True)
        self.setUniformRowHeights(True)
        self.setIndentation(14)
        header = self.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(0, 300)
        for col in range(1, 5):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.comparison: Comparison | None = None
        self._only_divergent = True
        self._search = ""
        self._entries: dict[str, FileEntry] = {}
        self.currentItemChanged.connect(self._on_current_changed)

    # -- API -----------------------------------------------------------------

    def set_comparison(self, comparison: Comparison) -> None:
        self.comparison = comparison
        self._entries = {e.rel: e for e in comparison.inventory.entries}
        self.rebuild()

    def set_filter(self, only_divergent: bool, search: str) -> None:
        self._only_divergent = only_divergent
        self._search = search.strip().lower()
        self.rebuild()

    def rebuild(self) -> None:
        self.clear()
        if self.comparison is None:
            return
        inv = self.comparison.inventory
        root = QTreeWidgetItem([tr("All files"), "", "", "", ""])
        root.setData(0, ROLE_KIND, "root")
        root.setData(0, ROLE_REL, "")
        self.addTopLevelItem(root)
        dirs: dict[str, _DirNode] = {"": _DirNode("", root)}

        def dir_item(rel_dir: str) -> QTreeWidgetItem:
            node = dirs.get(rel_dir)
            if node is not None:
                return node.item
            parent_rel = rel_dir.rsplit("/", 1)[0] if "/" in rel_dir else ""
            parent = dir_item(parent_rel)
            item = QTreeWidgetItem(parent, [rel_dir.rsplit("/", 1)[-1], "", "", "", ""])
            item.setData(0, ROLE_KIND, "dir")
            item.setData(0, ROLE_REL, rel_dir)
            dirs[rel_dir] = _DirNode(rel_dir, item)
            return item

        attendus_item: QTreeWidgetItem | None = None
        total_hunks = 0
        for entry in inv.entries:
            if entry.status == "identique" and self._only_divergent:
                continue
            if self._search and self._search not in entry.rel.lower():
                continue
            if entry.attendu:
                if attendus_item is None:
                    attendus_item = QTreeWidgetItem([branche_attendus(), "", "", "", ""])
                    attendus_item.setData(0, ROLE_KIND, "attendus")
                    attendus_item.setData(0, ROLE_REL, "")
                    attendus_item.setIcon(0, pastille(couleur_etat("attendu")))
                item = QTreeWidgetItem(attendus_item, [entry.rel, "", etat_label(entry.status), "", ""])
                item.setToolTip(0, entry.raison_attendu)
                item.setForeground(0, couleur_etat("attendu"))
                item.setIcon(0, pastille(couleur_etat("attendu")))
                item.setData(0, ROLE_KIND, "file")
                item.setData(0, ROLE_REL, entry.rel)
                self._fill_sizes(item, entry)
                continue
            parent_rel = entry.rel.rsplit("/", 1)[0] if "/" in entry.rel else ""
            parent = dir_item(parent_rel)
            item = QTreeWidgetItem(parent, [entry.name, "", etat_label(entry.status), "", ""])
            item.setData(0, ROLE_KIND, "file")
            item.setData(0, ROLE_REL, entry.rel)
            item.setIcon(0, pastille(couleur_etat(entry.status)))
            self._fill_sizes(item, entry)
            diff = self.comparison.diffs.get(entry.rel)
            if diff is not None:
                nb = len(diff.significatifs)
                total_hunks += nb
                item.setText(1, str(nb))
                item.setText(2, sens_label(diff.sens))
                item.setForeground(2, couleur_sens(diff.sens))
                item.setToolTip(0, entry.rel + "\n" + tr("{significant} significant difference(s), {hunks} hunk(s)").format(significant=nb, hunks=len(diff.semantic)))
                rel_dir = parent_rel
                while True:
                    dirs[rel_dir].files.append(entry.rel)
                    if not rel_dir:
                        break
                    rel_dir = rel_dir.rsplit("/", 1)[0] if "/" in rel_dir else ""
            else:
                item.setToolTip(0, entry.rel)
        for node in dirs.values():
            if node.rel and node.files:
                node.item.setText(1, str(sum(len(self.comparison.diffs[f].significatifs) for f in node.files)))
        root.setText(1, str(total_hunks))
        if attendus_item is not None:
            self.addTopLevelItem(attendus_item)
            attendus_item.setExpanded(False)
        root.setExpanded(True)
        self._expand_all(root)
        self.setCurrentItem(root)

    def _expand_all(self, item: QTreeWidgetItem) -> None:
        item.setExpanded(True)
        for k in range(item.childCount()):
            child = item.child(k)
            if child.data(0, ROLE_KIND) == "dir":
                self._expand_all(child)

    @staticmethod
    def _fill_sizes(item: QTreeWidgetItem, entry: FileEntry) -> None:
        item.setText(3, taille_lisible(entry.size_projet))
        item.setText(4, taille_lisible(entry.size_runtime))
        item.setTextAlignment(3, Qt.AlignmentFlag.AlignRight)
        item.setTextAlignment(4, Qt.AlignmentFlag.AlignRight)

    # -- Sélection ---------------------------------------------------------------

    def _files_under(self, item: QTreeWidgetItem) -> list[str]:
        kind = item.data(0, ROLE_KIND)
        if kind == "file":
            rel = item.data(0, ROLE_REL)
            return [rel] if self.comparison and rel in self.comparison.diffs else []
        result: list[str] = []
        for k in range(item.childCount()):
            result.extend(self._files_under(item.child(k)))
        return result

    def _on_current_changed(self, current: QTreeWidgetItem | None, _previous) -> None:
        if current is None:
            self.selection_changed.emit([])
            return
        self.selection_changed.emit(self._files_under(current))

    def current_rel(self) -> str:
        item = self.currentItem()
        return item.data(0, ROLE_REL) if item is not None else ""

    def select_rel(self, rel: str) -> bool:
        """Sélectionne l'élément (fichier ou dossier) de chemin relatif ``rel`` ; vrai s'il existe."""
        iterator = QTreeWidgetItemIterator(self)
        while iterator.value() is not None:
            item = iterator.value()
            if item.data(0, ROLE_REL) == rel:
                self.setCurrentItem(item)
                self.scrollToItem(item)
                return True
            iterator += 1
        return False


class Banner(QFrame):
    """Le bandeau de synthèse au-dessus des résultats."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.label = QLabel()
        self.label.setTextFormat(Qt.TextFormat.RichText)
        self.label.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.addWidget(self.label)
        theme.follow(self, self._render)

    def set_comparison(self, comparison: Comparison) -> None:
        self._comparison = comparison
        self._render()

    def _render(self, _palette=None) -> None:
        comparison = getattr(self, "_comparison", None)
        if comparison is None:
            return
        s = comparison.synthese()
        pal = theme.current()
        versions = tr("runtime <b>{runtime}</b> ⇄ project <b>{project}</b>").format(
            runtime=s.version_runtime or "?", project=s.version_projet or "?"
        )
        if not s.versions_compatibles:
            versions += f' <span style="color:{pal.error}"><b>— {tr("different IDE versions, be careful")}</b></span>'
            self.setStyleSheet(f"Banner {{ border: 2px solid {pal.warning}; border-radius: 8px; background: {pal.surface}; }}")
        else:
            self.setStyleSheet(f"Banner {{ border: 1px solid {pal.border}; border-radius: 8px; background: {pal.surface}; }}")

        def colored(sens: str, symbol: str, text: str) -> str:
            return f'<span style="color:{couleur_sens(sens).name()}">{symbol} {text}</span>'

        parts = [
            tr("IDE versions: {versions}").format(versions=versions),
            tr("<b>{files}</b> files compared, including <b>{yaml}</b> YAML").format(
                files=s.nb_fichiers_compares, yaml=s.nb_yaml_communs
            ),
            tr("<b>{n}</b> differences (<b>{yaml}</b> YAML)").format(n=s.nb_divergents, yaml=s.nb_yaml_divergents),
            colored("ajout_runtime", "➕", tr("<b>{n}</b> runtime additions").format(n=s.nb_ajouts_runtime)),
            colored("branche_projet", "➖", tr("<b>{n}</b> project branch").format(n=s.nb_branche_projet)),
            colored("valeur_modifiee", "✏️", tr("<b>{n}</b> modified values").format(n=s.nb_valeurs_modifiees)),
            f'<span style="color:{pal.text_muted}">'
            + tr("{n} not significant").format(n=s.nb_non_significatifs)
            + "</span>",
            tr("{n} files expected on one side only").format(n=s.nb_attendus),
            f"{s.duree_s:.1f} s",
        ]
        if comparison.orphelins_projet or comparison.orphelins_runtime:
            n = len(comparison.orphelins_projet) + len(comparison.orphelins_runtime)
            parts.append(f'<span style="color:{pal.error}">⚠ ' + tr("{n} unreferenced orphan YAML file(s)").format(n=n) + "</span>")
        self.label.setText("  ·  ".join(parts))


class ResultsPage(QWidget):
    """Bandeau + arbre à gauche + onglets à droite."""

    applied = Signal(object)  # ApplyReport : l'utilisateur peut relancer la comparaison

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.comparison: Comparison | None = None
        self.plan = Plan()

        self.banner = Banner()
        self.tree = FileTree()
        self.tree.selection_changed.connect(self._on_files_selected)

        self.filter_combo = QComboBox()
        self.filter_combo.addItems([tr("Differences only"), tr("Everything")])
        self.filter_combo.currentIndexChanged.connect(self._apply_filter)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Search for a file…"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        filters = QHBoxLayout()
        filters.addWidget(self.filter_combo)
        filters.addWidget(self.search, 1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addLayout(filters)
        left_layout.addWidget(self.tree, 1)

        self.semantic = SemanticView()
        self.semantic.hunk_selected.connect(self._on_hunk_selected)
        self.diff = DiffView()
        self._diff_rel = ""
        self.tabs = QTabWidget()
        self.tabs.addTab(self.semantic, tr("Semantic summary"))
        self.tabs.addTab(self.diff, tr("Diff"))
        self.specialized = SpecializedTabs()
        self.tabs.addTab(self.specialized, tr("Specialised views"))
        self.search_view = SearchView()
        self.search_view.hit_activated.connect(self.show_hit)
        self.tabs.addTab(self.search_view, tr("Search"))
        self.semantic.hunk_activated.connect(self.open_diff_tab)
        self.semantic.preview_requested.connect(self.open_plan_dialog)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 5)
        splitter.setSizes([520, 880])
        self.splitter = splitter

        top = QHBoxLayout()
        top.addWidget(self.banner, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 4)
        layout.addLayout(top)
        layout.addWidget(splitter, 1)

    def set_comparison(self, comparison: Comparison) -> None:
        self.comparison = comparison
        self.plan = Plan()
        self.semantic.set_comparison(comparison, self.plan)
        self.banner.set_comparison(comparison)
        self.specialized.load(comparison)
        self.search_view.set_inventory(comparison.inventory)
        self.tree.set_comparison(comparison)

    def snapshot(self) -> dict:
        """Affichage courant : filtre, recherche, onglet, fichier sélectionné, séparation."""
        return {
            "filter": self.filter_combo.currentIndex(),
            "search": self.search.text(),
            "tab": self.tabs.currentIndex(),
            "rel": self.tree.current_rel(),
            "splitter": self.splitter.sizes(),
        }

    def restore(self, state: dict) -> None:
        self.filter_combo.setCurrentIndex(state.get("filter", 0))
        self.search.setText(state.get("search", ""))
        if state.get("rel"):
            self.tree.select_rel(state["rel"])
        self.tabs.setCurrentIndex(state.get("tab", 0))
        if state.get("splitter"):
            self.splitter.setSizes(state["splitter"])

    def _apply_filter(self, *_args) -> None:
        self.tree.set_filter(self.filter_combo.currentIndex() == 0, self.search.text())

    def _on_files_selected(self, rels: list[str]) -> None:
        if self.comparison is None:
            return
        diffs: list[FileDiff] = [self.comparison.diffs[r] for r in rels if r in self.comparison.diffs]
        self.semantic.set_diffs(diffs)
        if len(rels) == 1:
            self.specialized.activate_for(rels[0], self.comparison)
        if len(diffs) == 1:
            self.show_diff(diffs[0])
        elif not diffs:
            self.diff.clear()
            self._diff_rel = ""

    def show_diff(self, fd: FileDiff) -> None:
        """Charge un fichier dans la vue diff (sans rien faire s'il y est déjà)."""
        if fd.rel == self._diff_rel:
            return
        self._diff_rel = fd.rel
        titre = f"<b>{fd.rel}</b> — " + tr("{hunks} hunk(s), project {project} l. ⇄ runtime {runtime} l.").format(
            hunks=len(fd.hunks), project=len(fd.projet.lines), runtime=len(fd.runtime.lines)
        )
        self.diff.set_content(fd.projet.lines, fd.runtime.lines, fd.opcodes, titre)

    def _on_hunk_selected(self, row: SemanticRow | None) -> None:
        if row is None:
            return
        self.show_diff(row.diff)
        self.diff.go_to_opcode(row.hunk.hunk.as_opcode())

    def open_diff_tab(self) -> None:
        self.tabs.setCurrentWidget(self.diff)

    def show_hit(self, side: str, rel: str, line_no: int) -> bool:
        """Ouvre une occurrence de recherche dans la vue diff ; vrai si le fichier y est affichable."""
        if self.comparison is None:
            return False
        fd = self.comparison.diffs.get(rel)
        if fd is None:
            entry = self.comparison.inventory.get(rel)
            if entry is None or entry.status != "identique":
                return False
            from ..core.analysis import diff_file

            fd = diff_file(entry, self.comparison.projet_root / rel, self.comparison.runtime_root / rel)
        self.show_diff(fd)
        self.diff.go_to_line(side, line_no)
        self.open_diff_tab()
        return True

    def open_plan_dialog(self) -> PlanDialog | None:
        """Prévisualisation (phase 2). Retourne la boîte pour les tests ; l'ouvre sinon."""
        if self.comparison is None:
            return None
        dialog = PlanDialog(self.comparison, self.plan, self)
        dialog.apply_requested.connect(lambda preview: self.open_apply_dialog(preview, dialog))
        dialog.plan_loaded.connect(self.semantic.model.refresh_decisions)
        dialog.show()
        return dialog

    def open_apply_dialog(self, preview: Preview, parent: QWidget | None = None) -> ApplyDialog | None:
        """Application (phase 3)."""
        if self.comparison is None:
            return None
        dialog = ApplyDialog(preview, self.plan, self.comparison, parent or self)
        dialog.applied.connect(self.applied)
        dialog.show()
        return dialog
