"""Vue diff côte à côte : rangées alignées, replis, navigation d'un hunk à l'autre."""

from __future__ import annotations

import random
from difflib import SequenceMatcher

import pytest

from optixplus.modules.compare.core.analysis import Comparison
from optixplus.modules.compare.ui.diff_view import CONTEXTE, DiffModel, DiffRow, DiffView

from .conftest import TAGS


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
def test_rangees_compactes_identiques_a_l_original(qapp, seed: int) -> None:
    """Les rangées construites à la demande sont identiques à celles de FTOCompare, repliées ou non."""
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


def test_alignement_et_repli(qapp, demo: Comparison) -> None:
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
    model.toggle_fold(kinds.index("pli"))
    assert len(model.rows) > n_before
    model.set_folding(False)
    assert all(r.kind != "pli" for r in model.rows)
    assert len(model.rows) == sum(max(i2 - i1, j2 - j1) for _t, i1, i2, j1, j2 in fd.opcodes)


def test_navigation(qapp, demo: Comparison) -> None:
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
