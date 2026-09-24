"""Recherche plein texte dans les fichiers des deux côtés."""

from __future__ import annotations

import pytest

from optixplus.common.progress import Cancelled
from optixplus.modules.compare.core.analysis import Comparison
from optixplus.modules.compare.core.search import compile_pattern, search_inventory

from .conftest import TAGS


def test_recherche(demo: Comparison) -> None:
    hits = search_inventory(demo.inventory, "acquit_z1")
    assert [(h.side, h.rel, h.line_no) for h in hits] == [("runtime", TAGS, 21), ("runtime", TAGS, 29)]
    assert hits[0].text == "- Name: Acquit_Z1"
    assert search_inventory(demo.inventory, "acquit_z1", casse=True) == []
    assert {h.side for h in search_inventory(demo.inventory, "AvecScanner")} == {"runtime", "projet"}
    regex = search_inventory(demo.inventory, r"Name: Fault_\w+GHDel", regex=True)
    assert [(h.side, h.rel) for h in regex] == [("projet", "Nodes/Alarms/Alarms.yaml")]
    assert search_inventory(demo.inventory, "TypeMapping") == [], "Nodes/ seulement par défaut"
    assert len(search_inventory(demo.inventory, "TypeMapping", only_nodes=False)) > 0
    assert search_inventory(demo.inventory, "") == []


def test_annulation(demo: Comparison) -> None:
    with pytest.raises(Cancelled):
        search_inventory(demo.inventory, "Name", cancel=lambda: True)


def test_motif_litteral_ou_regex() -> None:
    assert compile_pattern("a.b").match(b"a.b") and not compile_pattern("a.b").match(b"axb")
    assert compile_pattern("a.b", regex=True).match(b"axb")
