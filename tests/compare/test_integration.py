"""Compare dans OptixPlus : corrections apportées au portage et intégration à la coquille."""

from __future__ import annotations

import random
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication

from optixplus.modules.compare.core.analysis import compare
from optixplus.modules.compare.ui.diff_view import CONTEXTE, DiffModel, DiffRow

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _naive_rows(model: DiffModel) -> list[DiffRow]:
    """L'algorithme d'origine de FTOCompare : un objet par rangée."""
    rows: list[DiffRow] = []
    hunk_index = -1
    for k, (tag, i1, i2, j1, j2) in enumerate(model.opcodes):
        if tag == "equal":
            n = i2 - i1
            head = 0 if k == 0 else CONTEXTE
            tail = 0 if k == len(model.opcodes) - 1 else CONTEXTE
            if model.fold and k not in model.expanded and n > head + tail + 2:
                rows += [DiffRow("equal", i1 + d + 1, j1 + d + 1, model.a[i1 + d], model.b[j1 + d], -1) for d in range(head)]
                rows.append(DiffRow("pli", None, None, None, None, -1, pli=k, pli_taille=n - head - tail))
                rows += [DiffRow("equal", i1 + d + 1, j1 + d + 1, model.a[i1 + d], model.b[j1 + d], -1) for d in range(n - tail, n)]
            else:
                rows += [DiffRow("equal", i1 + d + 1, j1 + d + 1, model.a[i1 + d], model.b[j1 + d], -1) for d in range(n)]
            continue
        hunk_index += 1
        na, nb = i2 - i1, j2 - j1
        for d in range(max(na, nb)):
            a_ok, b_ok = d < na, d < nb
            rows.append(DiffRow(tag, i1 + d + 1 if a_ok else None, j1 + d + 1 if b_ok else None,
                                model.a[i1 + d] if a_ok else None, model.b[j1 + d] if b_ok else None, hunk_index))
    return rows


@pytest.mark.parametrize("seed", range(8))
def test_compact_diff_rows_match_the_original(qapp, seed: int) -> None:
    """Les rangées construites à la demande sont identiques à celles de FTOCompare, repliées ou non."""
    from difflib import SequenceMatcher

    rng = random.Random(seed)
    a = [f"ligne {rng.randint(0, 30)}".encode() for _ in range(rng.randint(20, 200))]
    b = list(a)
    for _ in range(rng.randint(1, 12)):
        pos = rng.randint(0, len(b))
        op = rng.choice(("ins", "del", "rep"))
        if op == "ins":
            b[pos:pos] = [f"ajout {rng.random()}".encode()] * rng.randint(1, 4)
        elif op == "del" and b:
            del b[pos:pos + rng.randint(1, 4)]
        elif b:
            b[min(pos, len(b) - 1)] = f"modif {rng.random()}".encode()
    opcodes = SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
    model = DiffModel()
    model.set_content(a, b, opcodes)
    for fold in (True, False):
        model.set_folding(fold)
        assert list(model.rows) == _naive_rows(model)
    for side, lines in (("projet", a), ("runtime", b)):
        for line_no in (1, len(lines) // 2, len(lines)):
            row = model.rows.row_of_line(side, line_no)
            assert getattr(model.rows[row], "a_no" if side == "projet" else "b_no") == line_no


def _wait(condition, timeout: float = 60.0) -> bool:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return condition()


@pytest.fixture
def shell(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from optixplus.common import i18n, logging_setup
    from optixplus.common.settings import Settings
    from optixplus.common.theme import install_manager
    from optixplus.shell.context import LaunchMode
    from optixplus.shell.controller import AppController

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    logging_setup.configure(to_file=False)
    controller = AppController(qapp, Settings.load(tmp_path / "s.json"), install_manager(qapp, "light"), LaunchMode.INSTALLED)
    window = controller.show_main_window()
    window.show_page("compare")
    yield controller
    if controller.window is not None:
        controller.window.close()
    i18n.install("fr")


def test_compare_page_is_rebuilt_as_it_was(shell) -> None:
    """Changement de langue : la comparaison, le fichier choisi et l'onglet sont conservés."""
    page = shell.window.module("compare").page
    page.setup_page.runtime.set_path(FIXTURES / "runtime" / "IHM_Demo")
    page.setup_page.projet.set_path(FIXTURES / "projet" / "IHM_Demo")
    page.setup_page.compare_button.click()
    assert _wait(lambda: page.comparison is not None and not page.busy)
    rel = next(iter(page.comparison.diffs))
    assert page.results_page.tree.select_rel(rel)
    page.results_page.tabs.setCurrentIndex(1)
    page.results_page.semantic.mass_action("ajouts", tout=True)
    taken = page.results_page.plan.nb_pris()
    assert taken > 0

    shell.context.settings.general.language = "en"
    shell.change_language()
    new = shell.window.module("compare").page
    assert new is not page and new.comparison is page.comparison
    assert new.stack.currentWidget() is new.results_page
    assert new.results_page.tree.current_rel() == rel
    assert new.results_page.tabs.currentIndex() == 1
    assert new.results_page.plan.nb_pris() == taken
    assert new.action_export.isEnabled() and new.results_page.tabs.tabText(0) == "Semantic summary"
    shell.context.settings.general.language = "fr"
    shell.change_language()


def test_recent_project_opens_in_compare(shell) -> None:
    from optixplus.common.recent import recent_projects

    page = shell.window.module("compare").page
    page.setup_page.runtime.set_path(FIXTURES / "runtime" / "IHM_Demo")
    page.setup_page.projet.set_path(FIXTURES / "projet" / "IHM_Demo")
    page.setup_page.compare_button.click()
    assert _wait(lambda: page.comparison is not None and not page.busy)
    projet = str((FIXTURES / "projet" / "IHM_Demo").resolve())
    assert recent_projects(shell.context.settings)[0] == projet
    shell.window.handle_command("open-project", ["compare", projet])
    assert page.stack.currentWidget() is page.setup_page
    assert str(page.setup_page.projet.path) == projet
