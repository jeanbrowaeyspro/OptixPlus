"""Diff ligne à ligne, sens des hunks et fusion sélective sur de petits YAML synthétiques."""

from __future__ import annotations

from difflib import SequenceMatcher

import pytest

from optixplus.modules.compare.core.diffing import (
    Hunk,
    compute_opcodes,
    diff_lines,
    hunks_from_opcodes,
    merge_lines,
    sens_global,
)
from optixplus.modules.compare.core.nodes import describe_hunks, slide_opcodes

from .conftest import tags_file

PROJET = tags_file(["A_Tag", "C_Tag", "Z_Projet"])
RUNTIME = tags_file(["A_Tag", "B_Runtime", "C_Tag"])
# Assez de lignes pour passer par l'ancrage (au-delà de 4000 lignes cumulées).
GROS_PROJET = tags_file([f"T{i:04d}" for i in range(0, 600)])
GROS_RUNTIME = tags_file([f"T{i:04d}" for i in range(0, 600) if i % 97 != 0] + ["T9999"])


def test_hunks_et_sens() -> None:
    hunks = diff_lines(PROJET, RUNTIME)
    assert [h.tag for h in hunks] == ["insert", "delete"]
    assert sens_global(hunks) == "mixte"
    assert hunks[0].sens == "ajout_runtime" and hunks[1].sens == "branche_projet"
    remplacement = Hunk("replace", 3, 5, 3, 4)
    assert remplacement.nb_a == 2 and remplacement.nb_b == 1 and remplacement.sens == "valeur_modifiee"


def test_opcodes_equivalents_a_difflib_sur_petit_fichier() -> None:
    attendu = SequenceMatcher(None, PROJET, RUNTIME, autojunk=False).get_opcodes()
    assert compute_opcodes(PROJET, RUNTIME) == attendu


@pytest.mark.parametrize(
    ("projet", "runtime"),
    [(PROJET, RUNTIME), (GROS_PROJET, GROS_RUNTIME)],
    ids=["petit", "ancrage"],
)
def test_opcodes_reconstruisent_les_deux_cotes(projet: list[bytes], runtime: list[bytes]) -> None:
    ops = compute_opcodes(projet, runtime)
    assert merge_lines(projet, runtime, ops) == projet
    assert merge_lines(projet, runtime, ops, modes={"insert", "delete", "replace"}) == runtime


def test_ancrage_gros_fichier() -> None:
    assert len(GROS_PROJET) + len(GROS_RUNTIME) > 4000, "le test doit passer par l'ancrage"
    hunks = hunks_from_opcodes(compute_opcodes(GROS_PROJET, GROS_RUNTIME))
    assert sum(1 for h in hunks if h.tag == "delete") == 7
    assert sum(1 for h in hunks if h.tag == "insert") == 1


def test_fusion_selective() -> None:
    ops = compute_opcodes(PROJET, RUNTIME)
    ajouts = merge_lines(PROJET, RUNTIME, ops, modes={"insert"})
    assert ajouts == tags_file(["A_Tag", "B_Runtime", "C_Tag", "Z_Projet"])
    hunk = hunks_from_opcodes(ops)[1]
    assert hunk.as_opcode() in ops
    retire = merge_lines(PROJET, RUNTIME, ops, retenus=[hunk])
    assert retire == tags_file(["A_Tag", "C_Tag"])


def test_glissement_sur_frontiere_de_noeud() -> None:
    """Une insertion que difflib place à cheval sur deux blocs doit glisser jusqu'au ``- Name:``."""
    projet = [b"Name: R", b"Children:", b"- Name: A", b"  Type: T", b"- Name: C", b"  Type: T"]
    runtime = [b"Name: R", b"Children:", b"- Name: A", b"  Type: T", b"- Name: B", b"  Type: T", b"- Name: C", b"  Type: T"]
    # Fenêtre décalée d'une ligne vers le haut : [``  Type: T``, ``- Name: B``], valide mais illisible.
    ops = [("equal", 0, 3, 0, 3), ("insert", 3, 3, 3, 5), ("equal", 3, 6, 5, 8)]
    assert merge_lines(projet, runtime, ops, modes={"insert"}) == runtime, "fenêtre valide"
    glisse = slide_opcodes(ops, projet, runtime)
    assert glisse == [("equal", 0, 4, 0, 4), ("insert", 4, 4, 4, 6), ("equal", 4, 6, 6, 8)]
    assert merge_lines(projet, runtime, glisse, modes={"insert"}) == runtime
    sem = describe_hunks(hunks_from_opcodes(glisse), projet, runtime)
    assert sem[0].noeud == "B" and sem[0].genre == "bloc"
