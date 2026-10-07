"""Calcul sur un projet de style 1.3 : pages ``Panel``, onglets par ``PanelLoader`` (sans ``NavigationPanel``)."""

from __future__ import annotations

import pytest

from optixplus.modules.statistics.core import stats
from optixplus.modules.statistics.core.model import StatisticsOptions
from statistics_project_v13 import make_project_v13


@pytest.fixture
def result(tmp_path):
    return stats.compute(str(make_project_v13(tmp_path)), options=StatisticsOptions((("beta",), ("gamma",), ("nothing",))))


def test_main_pages_are_panels_not_splash_nor_subviews(result):
    mains = sorted(p.name for p in result.pages if p.is_main)
    assert mains == ["IType_00_Alpha", "IType_01_Beta", "IType_02_Gamma"]
    assert result.main_pages == 3
    names = {p.name for p in result.pages}
    assert "SplashPanel" not in names  # page d'attente : panneau initial de la fenêtre, visée par aucun bouton
    assert not names & {"IType_TabOne", "IType_TabTwo", "IType_SubA", "IType_SubB", "IType_Gauge", "IType_GammaPanel"}
    assert "IType_Confirm" in names and not next(p for p in result.pages if p.name == "IType_Confirm").is_main
    assert [p.title for p in result.pages if p.is_main] == ["Alpha", "Beta", "Gamma"]  # texte du bouton de menu


def test_rows_follow_loader_tabs_with_nesting(result):
    assert [r.label for r in result.rows] == [
        "Alpha",
        "Beta/One",
        "Beta/Two/SubA",
        "Beta/Two/SubB",
        "Gamma/Gamma panel",  # aucun bouton ne vise le loader : une ligne « Page/<panneau par défaut> »
    ]
    by_label = {r.label: (r.tags, r.links, r.subviews) for r in result.rows}
    assert by_label["Alpha"] == (2, 3, 0)
    assert by_label["Beta/One"] == (3, 3, 1)  # Pressure + sous-vue (Level, Motor/Speed)
    assert by_label["Beta/Two/SubA"] == (2, 2, 0)
    assert by_label["Beta/Two/SubB"] == (1, 1, 0)  # tag de l'autre station
    assert by_label["Gamma/Gamma panel"] == (1, 1, 1)  # page entière : le panneau par défaut est une sous-vue
    assert not any(r.label in ("Beta", "Beta/Two") for r in result.rows)  # pas de ligne de total


def test_highlights_use_the_default_tab(result):
    beta, gamma, missing = result.highlights
    assert beta.row.label == "Beta/One" and beta.row.tags == 3  # panneau initial du loader
    assert gamma.row.label == "Gamma/Gamma panel"
    assert missing.row is None


def test_dialog_is_not_a_row(result):
    assert all(not r.label.startswith("IType_Confirm") for r in result.rows)


def test_loader_tabs_need_navigation_buttons_in_the_project(tmp_path):
    """Sans bouton ``PanelToLoad`` dans le projet, un ``PanelLoader`` n'est pas un onglet (même résultat qu'en 1.6)."""
    folder = make_project_v13(tmp_path, name="Demo14")
    screens = folder / "Nodes" / "UI" / "Parts" / "Parts.yaml"
    screens.write_text(screens.read_text(encoding="utf-8").replace("PanelToLoad", "OtherName"), encoding="utf-8")
    top = folder / "Nodes" / "UI" / "Screens" / "Screens.yaml"
    top.write_text(top.read_text(encoding="utf-8").replace("PanelToLoad", "OtherName"), encoding="utf-8")
    result = stats.compute(str(folder))
    assert [r.label for r in result.rows] == ["Alpha", "Beta", "Gamma"]
