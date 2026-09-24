"""Export du rapport en Markdown et en HTML sur le couple synthétique."""

from __future__ import annotations

from optixplus.modules.compare.core.analysis import Comparison
from optixplus.modules.compare.report.html import build_html, markdown_to_html
from optixplus.modules.compare.report.markdown import build_markdown, table

SECTIONS = ("1. Synthèse", "2. Fichiers divergents", "3. Résumé sémantique", "4. Vues spécialisées")


def test_markdown_complet(demo: Comparison) -> None:
    md = build_markdown(demo)
    assert md.startswith("# OptixPlus — rapport de comparaison")
    for section in SECTIONS:
        assert f"## {section}" in md
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


def test_html(demo: Comparison) -> None:
    page = build_html(demo)
    assert page.startswith("<!DOCTYPE html>")
    for section in SECTIONS:
        assert f"<h2>{section}</h2>" in page
    assert "<td><code>AvecScanner</code></td><td>Model/AvecScanner</td>" in page, "tableau du résumé sémantique"
    assert "Value: <code>false</code> → <code>true</code>" in page, "code en ligne dans une cellule"
    assert "<p>Présents dans le <strong>runtime</strong>, absents du projet :</p>" in page, "gras dans un paragraphe"
