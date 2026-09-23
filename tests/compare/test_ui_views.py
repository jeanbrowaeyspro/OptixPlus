"""Vue diff côte à côte et vues spécialisées, hors écran, sur le couple synthétique."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from optixplus.modules.compare.core.analysis import compare  # noqa: E402
from optixplus.modules.compare.ui.diff_view import DiffModel, DiffView  # noqa: E402
from optixplus.modules.compare.ui.results_page import ResultsPage  # noqa: E402
from optixplus.modules.compare.ui.specialized.views import SpecializedTabs  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
TAGS = "Nodes/CommDrivers/CODESYSDriver/API_Demo/Tags/Tags.yaml"


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def demo(app):
    return compare(FIXTURES / "runtime" / "IHM_Demo", FIXTURES / "projet" / "IHM_Demo")


def test_diff_model_alignement_et_repli(app, demo) -> None:
    fd = demo.diffs[TAGS]
    model = DiffModel()
    model.set_content(fd.projet.lines, fd.runtime.lines, fd.opcodes)
    kinds = [r.kind for r in model.rows]
    assert "pli" in kinds and "insert" in kinds and "delete" in kinds
    assert len(model.hunk_rows) == 3
    # une ligne insert : projet vide, runtime rempli
    first = model.rows[model.hunk_rows[0]]
    assert first.kind == "insert" and first.a_text is None and first.b_text is not None
    assert model.data(model.index(model.hunk_rows[0], DiffModel.COL_B)).strip().startswith("- Name: Acquit_Z1")
    assert model.data(model.index(model.hunk_rows[0], DiffModel.COL_A)) == ""
    # dépliage : plus de "pli" pour ce bloc, et le nombre de lignes grandit
    n_before = len(model.rows)
    pli_row = kinds.index("pli")
    model.toggle_fold(pli_row)
    assert len(model.rows) > n_before
    model.set_folding(False)
    assert all(r.kind != "pli" for r in model.rows)
    assert len(model.rows) == sum(max(i2 - i1, j2 - j1) for _t, i1, i2, j1, j2 in fd.opcodes)


def test_diff_view_navigation(app, demo) -> None:
    fd = demo.diffs[TAGS]
    view = DiffView()
    view.set_content(fd.projet.lines, fd.runtime.lines, fd.opcodes, "Tags")
    assert view.nb_hunks() == 3 and view.current_hunk() == 0
    assert not view.prev_button.isEnabled() and view.next_button.isEnabled()
    view.next_hunk()
    assert view.current_hunk() == 1
    view.go_to_opcode(fd.hunks[2].as_opcode())
    assert view.current_hunk() == 2 and not view.next_button.isEnabled()
    assert view.position.text() == "3 / 3"
    view.fold_box.setChecked(False)
    assert view.current_hunk() == 2
    view.clear()
    assert view.nb_hunks() == 0 and view.position.text() == "—"


def test_vues_specialisees(app, demo) -> None:
    tabs = SpecializedTabs()
    tabs.load(demo)
    assert tabs.tabText(0).startswith("Tags CoDeSys (6)")
    assert tabs.tags.visible_count() == 6  # écarts seuls : 3 ajouts + 1 structure projet et ses 2 membres
    tabs.tags.only_gaps.setChecked(False)
    assert tabs.tags.visible_count() == tabs.tags.model.rowCount() > 6
    tabs.tags.search.setText("Acquit")
    assert tabs.tags.visible_count() == 2

    assert tabs.tabText(1) == "Traductions (1)"
    assert tabs.translations.colonnes == ["Clé", "en-US", "fr-FR", "it-IT", "État"]
    assert tabs.translations.visible_count() == 1
    assert "[3, 4]" in tabs.translations.note.text() and "[4, 4]" in tabs.translations.note.text()

    assert tabs.tabText(2) == "Types utilisateur (1)"
    assert tabs.types.visible_count() == 1
    assert tabs.types.model.item(0, 1).text() in ("IType_Div_BP_Prog", "IType_Manual", "IType_TextErreurDivision")

    assert tabs.stats.model.rowCount() >= 7 and not tabs.stats.only_gaps.isChecked()
    assert tabs.netlogic.model.rowCount() == 0 and "Aucune DLL" in tabs.netlogic.note.text()

    tabs.activate_for(TAGS, demo)
    assert tabs.currentWidget() is tabs.tags
    tabs.activate_for("IHM_Demo.optix", demo)
    assert tabs.currentWidget() is tabs.stats


def test_page_resultats_pilote_diff_et_vues(app, demo) -> None:
    page = ResultsPage()
    page.set_comparison(demo)
    tree = page.tree

    def find(item, name):
        if item.text(0) == name:
            return item
        for k in range(item.childCount()):
            r = find(item.child(k), name)
            if r is not None:
                return r
        return None

    tree.setCurrentItem(find(tree.topLevelItem(0), "Tags.yaml"))
    assert page.diff.nb_hunks() == 3 and page.specialized.currentWidget() is page.specialized.tags
    page.semantic.table.selectRow(2)
    row = page.semantic.current_row()
    assert row is not None
    assert page.diff.current_hunk() == 2
    tree.setCurrentItem(tree.topLevelItem(0))
    page.semantic.table.sortByColumn(4, Qt.SortOrder.AscendingOrder)
    page.semantic.table.selectRow(0)
    row = page.semantic.current_row()
    assert row is not None and page.diff.title.text().startswith(f"<b>{row.rel}</b>")
