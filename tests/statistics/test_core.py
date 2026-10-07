"""Calcul des statistiques sur un projet synthétique (sans interface)."""

from __future__ import annotations

import pytest

from optixplus.common.progress import Cancelled
from optixplus.modules.statistics.core import stats
from optixplus.modules.statistics.core.config import parse_keywords
from optixplus.modules.statistics.core.model import (
    KIND_PROJECT,
    KIND_RUNTIME,
    VIEW_DIALOG,
    VIEW_SCREEN,
    VIEW_WINDOW,
    StatisticsOptions,
)
from statistics_project import make_project


@pytest.fixture
def result(tmp_path):
    return stats.compute(str(make_project(tmp_path)))


def page(result, name):
    return next(p for p in result.pages if p.name == name)


def test_versions_and_studio_counts(result):
    assert result.name == "Demo"
    assert result.kind == KIND_PROJECT
    assert result.ide_version == "1.6.4.11-Stable"
    assert result.product_version == "1.6"
    assert result.core_version == "4.2"
    assert result.studio_counts["TotalNodeCount"] == 123
    assert result.nodes > 50
    assert result.files >= 8


def test_stations_and_tags(result):
    by_name = {s.name: s for s in result.stations}
    assert set(by_name) == {"PlcA", "PlcB"}
    a = by_name["PlcA"]
    assert (a.tags, a.structures) == (10, 2)  # 8 tags simples + 2 structures
    assert (a.address, a.port, a.driver_type, a.station_type) == ("10.0.0.1", "1217", "CODESYSDriver", "CODESYSStation")
    assert by_name["PlcB"].tags == 1
    assert result.tags_total == 11
    assert result.structures_total == 2


def test_main_pages(result):
    mains = [p.name for p in result.pages if p.is_main]
    assert sorted(mains) == ["IType_00_Home", "IType_01_Alpha", "IType_02_Beta"]
    assert result.main_pages == 3
    assert [p.is_main for p in result.pages] == [True, True, True, False, False]  # principales d'abord
    assert page(result, "IType_Dlg").kind == VIEW_DIALOG
    assert page(result, "IType_MainWindow").kind == VIEW_WINDOW
    assert page(result, "IType_00_Home").kind == VIEW_SCREEN


def test_titles(result):
    assert page(result, "IType_00_Home").title == "Home"  # texte du bouton de menu
    assert page(result, "IType_01_Alpha").title == "Alpha machine"  # DisplayName prioritaire
    assert page(result, "IType_Dlg").title == "IType_Dlg"  # repli sur le nom du nœud


def test_tags_per_page_with_shared_subview(result):
    home = page(result, "IType_00_Home")
    assert (home.links, home.tags, home.subviews, home.approximate) == (3, 2, 0, False)  # Pressure lié à deux objets : 2 liaisons, 1 tag ; le lien vers le modèle est ignoré
    work = page(result, "IType_01_Alpha")
    # Pressure, Counters/Count1 (relatif), Motor (pointeur d'équipement) + Level, Motor/Speed (sous-vue)
    assert (work.links, work.tags, work.subviews, work.approximate) == (5, 5, 1, False)


def test_dynamic_path_and_converter(result):
    sup = page(result, "IType_02_Beta")
    # Level, Motor/Speed (sous-vue partagée), Slot{0} (chemin dynamique), Temp via le convertisseur, Pressure
    assert sup.tags == 5
    assert sup.links == 6  # Level lié deux fois (sous-vue de l'onglet 1 et sous-onglet History)
    assert sup.subviews == 5  # deux onglets, deux sous-onglets et la sous-vue partagée
    assert sup.approximate is True
    assert not page(result, "IType_01_Alpha").approximate
    assert any("approximate" in w for w in result.warnings)


def test_average_and_busiest_are_per_row_not_per_page_total(result):
    # lignes : Home 2, Alpha machine 5, Beta/Axes 3, Alarms/Active 1, Alarms/History 2
    assert result.average_tags_per_view == pytest.approx((2 + 5 + 3 + 1 + 2) / 5)
    assert result.busiest_row is not None and result.busiest_row.label == "Alpha machine"
    assert result.busiest_row in result.rows


def _options(*entries: str) -> StatisticsOptions:
    return StatisticsOptions(tuple(parse_keywords(e) for e in entries))


def test_no_highlighted_page_by_default(result):
    assert StatisticsOptions().highlights == ()
    assert result.highlights == []


def test_highlighted_pages_search_title_technical_name_and_short_name(tmp_path):
    folder = str(make_project(tmp_path))
    result = stats.compute(folder, options=_options("alpha machine", "beta", "IType_00_Home", "nothing, nowhere"))
    rows = [h.row for h in result.highlights]
    assert [h.keywords for h in result.highlights] == [("alpha machine",), ("beta",), ("IType_00_Home",), ("nothing", "nowhere")]
    assert rows[0].page == "Alpha machine"  # nom affiché, casse ignorée
    assert rows[1].page == "Beta"  # nom technique sans IType_NN_
    assert rows[2].page == "Home"  # nom technique complet
    assert rows[3] is None  # aucune page de ce nom


def test_highlight_keywords_are_alternatives_and_exact_first(tmp_path):
    folder = str(make_project(tmp_path))
    found = stats.compute(folder, options=_options("Gamma, ALPHA MACHINE")).highlights[0]
    assert found.row.page == "Alpha machine"  # un seul mot-clé suffit
    partial = stats.compute(folder, options=_options("machin")).highlights[0]
    assert partial.row is not None and partial.row.page == "Alpha machine"  # sous-chaîne en dernier recours


def test_bindings_count_objects_and_tags_count_distinct_paths(result):
    home = page(result, "IType_00_Home")
    assert home.links > home.tags  # un tag lié à deux objets : deux liaisons, un tag
    for p in result.pages:
        assert p.tags <= p.links


def test_alarms_netlogic_loggers(result):
    assert result.alarms == 2  # les deux instances, pas le type
    assert result.netlogic == 1
    assert result.loggers == 2


def test_project_files(result):
    assert result.image_files == 2
    assert result.font_files == 1
    assert result.font_bytes == 10
    assert result.project_files_bytes >= result.image_bytes + result.font_bytes
    assert result.runtime_files == []
    assert result.kind == KIND_PROJECT


def test_runtime_variant(tmp_path):
    result = stats.compute(str(make_project(tmp_path, runtime=True)))
    assert result.kind == KIND_RUNTIME
    names = [n for n, _ in result.runtime_files]
    assert names == ["Data.sqlite", "RetentivityStorage.db", "log.txt"]  # par taille décroissante
    assert result.runtime_files[0][1] == 20000
    assert not any(n.endswith(".source") for n in names)
    # même contenu que le projet
    assert result.tags_total == 11 and result.main_pages == 3


def test_unknown_driver_is_a_warning_and_still_counted(tmp_path):
    folder = make_project(tmp_path)
    path = folder / "Nodes" / "CommDrivers" / "CommDrivers.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("CODESYSDriver\n  Children", "OtherDriver\n  Children", 1), encoding="utf-8")
    result = stats.compute(str(folder))
    assert any("OtherDriver" in w or "CODESYSDriver" in w for w in result.warnings)
    assert result.tags_total > 0
    assert len(result.stations) == 2


def test_cancel(tmp_path):
    folder = str(make_project(tmp_path))
    with pytest.raises(Cancelled):
        stats.compute(folder, cancel=lambda: True)


def test_cancel_during_analysis(tmp_path, monkeypatch):
    folder = str(make_project(tmp_path))
    monkeypatch.setattr(stats, "CHECK_EVERY", 5)
    calls = []

    def cancel():
        calls.append(1)
        return len(calls) > 3

    with pytest.raises(Cancelled):
        stats.compute(folder, cancel=cancel)


def test_progress_by_phase(tmp_path):
    steps = []
    stats.compute(str(make_project(tmp_path)), progress=steps.append)
    phases = []
    for step in steps:
        if step.phase not in phases:
            phases.append(step.phase)
    assert phases[0] == "Loading project files"
    assert "Analysing nodes" in phases
    assert "Reading project files" in phases
    assert steps[-1].index == steps[-1].total == 1  # fin de traitement


def test_core_does_not_import_qt():
    import sys

    assert stats.__name__ in sys.modules
    source = open(stats.__file__, encoding="utf-8").read()
    assert "PySide6" not in source


def _rows(result):
    return {r.label: (r.tags, r.links, r.approximate) for r in result.rows}


def test_rows_are_main_pages_and_tab_leaves_only(result):
    assert [r.label for r in result.rows] == [
        "Home",
        "Alpha machine",
        "Beta/Axes",
        "Beta/Alarms/Active",
        "Beta/Alarms/History",
    ]  # ni dialogue, ni fenêtre, ni sous-vue (IType_Gauge, IType_TabA…), ni total de page à onglets
    rows = _rows(result)
    assert rows["Home"] == (2, 3, False)
    assert rows["Beta/Axes"] == (3, 3, True)  # Level, Motor/Speed, Slot{0}
    assert rows["Beta/Alarms/Active"] == (1, 1, False)  # Temp via le convertisseur
    assert rows["Beta/Alarms/History"] == (2, 2, False)
    assert [r.tabs for r in result.rows][2:] == [["Axes"], ["Alarms", "Active"], ["Alarms", "History"]]


def test_highlight_rows_use_the_default_tab_of_the_rows(tmp_path):
    options = _options("beta", "alpha machine")
    first = stats.compute(str(make_project(tmp_path)), options=options)  # pas d'indice : premier onglet
    beta, alpha = (h.row for h in first.highlights)
    assert beta in first.rows  # même structure que le tableau
    assert beta.label == "Beta/Axes" and beta.tags == 3
    assert alpha.label == "Alpha machine"  # pas de NavigationPanel : page entière
    second = stats.compute(str(make_project(tmp_path, current_tab=1, name="Demo4")), options=options)
    assert second.highlights[0].row.label == "Beta/Alarms/Active"  # onglets par défaut suivis jusqu'à la feuille
    assert second.highlights[0].row.tags == 1


def test_unknown_default_tab_keeps_page_total(tmp_path):
    unknown = stats.compute(str(make_project(tmp_path, current_tab=7)), options=_options("beta"))
    row = unknown.highlights[0].row
    assert row.tab_unknown and row.label == "Beta" and row.tags == 5  # total de la page entière
    assert row not in unknown.rows
    assert len([r for r in unknown.rows if r.page == "Beta"]) == 3  # les feuilles restent listées


def test_used_tags(result):
    """Direct, relatif, pointeur sur structure (descendants compris), convertisseur, motif ``{0}`` ; un tag ciblé
    n'utilise pas sa structure parente ; le reste est inutilisé."""
    a = next(s for s in result.stations if s.name == "PlcA")
    b = next(s for s in result.stations if s.name == "PlcB")
    # Pressure, Level, Count1 (relatif), Motor + Speed + Run (pointeur de structure), Slot1, Slot2 (motif)
    assert a.tags_used == 8 and a.tags_used_approximate
    assert b.tags_used == 1 and not b.tags_used_approximate  # Temp, via le convertisseur
    assert result.tags_used == 9 and result.tags_used_approximate
    assert result.tags_total - result.tags_used == 2  # Counters (seulement son membre est lié) et Spare


def test_warns_that_netlogic_access_is_not_detected(result):
    assert any("NetLogic" in w for w in result.warnings)  # le projet contient un NetLogic


def test_exact_when_no_dynamic_path(tmp_path):
    folder = make_project(tmp_path, name="Demo5")
    path = folder / "Nodes" / "UI" / "UI.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("Slot{0}", "Pressure"), encoding="utf-8")
    result = stats.compute(str(folder))
    assert not result.tags_used_approximate and result.tags_used == 7


def test_relative_link_is_resolved_from_the_variable_that_carries_it(tmp_path):
    """``..`` part de la variable liée (parent du ``DynamicLink``), comme dans Studio et le Link Checker."""
    from statistics_project import _label

    base = stats.compute(str(make_project(tmp_path))).tags_used
    folder = make_project(tmp_path, name="Demo6")
    path = folder / "Nodes" / "UI" / "UI.yaml"
    text = path.read_text(encoding="utf-8")
    # dernier type du fichier (boîte de dialogue) : un lien relatif vers Spare, inutilisé sinon
    path.write_text(text + _label("LabelSpare", "../../../../CommDrivers/CODESYSDriver/PlcA/Tags/Spare"), encoding="utf-8")
    result = stats.compute(str(folder))
    assert result.tags_used == base + 1  # sans la correction, le chemin ne résout pas : Spare resterait inutilisé
