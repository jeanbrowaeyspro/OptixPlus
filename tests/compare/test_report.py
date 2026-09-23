"""Export Markdown / HTML sur le couple synthétique."""

from __future__ import annotations

from pathlib import Path

import pytest

from optixplus.modules.compare.core.analysis import compare
from optixplus.modules.compare.report.html import build_html, markdown_to_html
from optixplus.modules.compare.report.markdown import build_markdown, table

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="module")
def demo():
    return compare(FIXTURES / "runtime" / "IHM_Demo", FIXTURES / "projet" / "IHM_Demo")


def test_markdown_complet(demo) -> None:
    md = build_markdown(demo)
    assert md.startswith("# FTOCompare")
    for section in ("## 1. Synthèse", "## 2. Fichiers divergents", "## 3. Résumé sémantique", "## 4. Vues spécialisées"):
        assert section in md
    assert "`1.3.2.9-Stable`" in md and "✅ identiques" in md
    assert "`Acquit_Z1`, `Acquit_Z2`" in md and "Value: `false` → `true`" in md
    assert "Nodes/UI/Parents/Orphelin/Orphelin.yaml" in md
    assert "App_Demo.GVL_IO.Acquit_Z1" in md and "PlanSciage_Manu" in md
    assert "[3, 4]" in md and "[4, 4]" in md and "Créer bois" in md
    assert "IType_Div_BP_Prog" in md and "TotalNodeCount" in md
    assert "Différences structurelles normales" in md


def test_table_echappe_les_barres() -> None:
    md = table(("a", "b"), [("x|y", "z")])
    assert "x\\|y" in md
    html = markdown_to_html(md)
    assert "<td>x|y</td>" in html


def test_html(demo) -> None:
    page = build_html(demo)
    assert page.startswith("<!DOCTYPE html>") and "<table>" in page and "<h2>" in page
    assert "<code>AvecScanner</code>" in page
    assert "<strong>" in page
