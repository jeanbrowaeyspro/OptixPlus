"""Calcul des statistiques sur un projet synthétique (sans interface)."""

from __future__ import annotations

import pytest

from optixplus.common.progress import Cancelled
from optixplus.modules.statistics.core import stats
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
    assert (a.tags, a.structures) == (7, 2)  # 5 tags simples + 2 structures
    assert (a.address, a.port, a.driver_type, a.station_type) == ("10.0.0.1", "1217", "CODESYSDriver", "CODESYSStation")
    assert by_name["PlcB"].tags == 1
    assert result.tags_total == 8
    assert result.structures_total == 2


def test_main_pages(result):
    mains = [p.name for p in result.pages if p.is_main]
    assert sorted(mains) == ["IType_00_Home", "IType_01_Work", "IType_02_Supervision"]
    assert result.main_pages == 3
    assert [p.is_main for p in result.pages] == [True, True, True, False, False]  # principales d'abord
    assert page(result, "IType_Dlg").kind == VIEW_DIALOG
    assert page(result, "IType_MainWindow").kind == VIEW_WINDOW
    assert page(result, "IType_00_Home").kind == VIEW_SCREEN


def test_titles(result):
    assert page(result, "IType_00_Home").title == "Home"  # texte du bouton de menu
    assert page(result, "IType_01_Work").title == "Work machine"  # DisplayName prioritaire
    assert page(result, "IType_Dlg").title == "IType_Dlg"  # repli sur le nom du nœud


def test_tags_per_page_with_shared_subview(result):
    home = page(result, "IType_00_Home")
    assert (home.links, home.tags, home.subviews, home.approximate) == (3, 2, 0, False)  # Pressure lié à deux objets : 2 liaisons, 1 tag ; le lien vers le modèle est ignoré
    work = page(result, "IType_01_Work")
    # Pressure, Counters/Count1 (relatif), Motor (pointeur d'équipement) + Level, Motor/Speed (sous-vue)
    assert (work.links, work.tags, work.subviews, work.approximate) == (5, 5, 1, False)


def test_dynamic_path_and_converter(result):
    sup = page(result, "IType_02_Supervision")
    # Level, Motor/Speed (sous-vue partagée), Motor/{0} (chemin dynamique), Temp via le convertisseur, Pressure
    assert sup.tags == 5
    assert sup.links == 6  # Level lié deux fois (sous-vue de l'onglet 1 et sous-onglet History)
    assert sup.subviews == 5  # deux onglets, deux sous-onglets et la sous-vue partagée
    assert sup.approximate is True
    assert not page(result, "IType_01_Work").approximate
    assert any("approximate" in w for w in result.warnings)


def test_average_and_busiest_page(result):
    assert result.average_tags_per_main_page == pytest.approx((2 + 5 + 5) / 3)
    assert result.busiest_page is not None
    assert result.busiest_page.name == "IType_01_Work"


def test_work_and_supervision_pages(result):
    assert result.work_page is not None and result.work_page.name == "IType_01_Work"  # nom technique sans IType_NN_
    assert result.supervision_page is not None and result.supervision_page.name == "IType_02_Supervision"


def test_custom_names(tmp_path):
    options = StatisticsOptions(work_names=("home",), supervision_names=("work machine",))
    result = stats.compute(str(make_project(tmp_path)), options=options)
    assert result.work_page.name == "IType_00_Home"
    assert result.supervision_page.name == "IType_01_Work"  # nom affiché, casse ignorée
    unknown = stats.compute(str(make_project(tmp_path, name="Demo2")), options=StatisticsOptions(work_names=("nothing",)))
    assert unknown.work_page is None


def test_supervision_is_also_named_overwatch(tmp_path):
    assert StatisticsOptions().supervision_names == ("Supervision", "Overwatch")
    assert StatisticsOptions().work_names == ("Work", "Travail")
    folder = str(make_project(tmp_path))
    only = stats.compute(folder, options=StatisticsOptions(supervision_names=("OVERWATCH",)))
    assert only.supervision_page is None  # aucune page de ce nom
    both = stats.compute(folder, options=StatisticsOptions(supervision_names=("OverWatch", "supervision")))
    assert both.supervision_page is not None and both.supervision_page.name == "IType_02_Supervision"


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
    assert result.tags_total == 8 and result.main_pages == 3


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
        "Work machine",
        "Supervision/Axes",
        "Supervision/Alarms/Active",
        "Supervision/Alarms/History",
    ]  # ni dialogue, ni fenêtre, ni sous-vue (IType_Gauge, IType_TabA…), ni total de page à onglets
    rows = _rows(result)
    assert rows["Home"] == (2, 3, False)
    assert rows["Supervision/Axes"] == (3, 3, True)  # Level, Motor/Speed, Motor/{0}
    assert rows["Supervision/Alarms/Active"] == (1, 1, False)  # Temp via le convertisseur
    assert rows["Supervision/Alarms/History"] == (2, 2, False)
    assert [r.tabs for r in result.rows][2:] == [["Axes"], ["Alarms", "Active"], ["Alarms", "History"]]


def test_summary_rows_use_the_default_tab_of_the_rows(tmp_path):
    first = stats.compute(str(make_project(tmp_path)))  # pas d'indice : premier onglet
    assert first.supervision_row in first.rows  # même structure que le tableau
    assert first.supervision_row.label == "Supervision/Axes" and first.supervision_row.tags == 3
    assert first.supervision_page.tags == 5  # la page entière compte aussi les autres onglets
    assert first.work_row.label == "Work machine"  # pas de NavigationPanel : page entière
    second = stats.compute(str(make_project(tmp_path, current_tab=1, name="Demo4")))
    assert second.supervision_row.label == "Supervision/Alarms/Active"  # onglets par défaut suivis jusqu'à la feuille
    assert second.supervision_row.tags == 1


def test_unknown_default_tab_keeps_page_total(tmp_path):
    unknown = stats.compute(str(make_project(tmp_path, current_tab=7)))
    row = unknown.supervision_row
    assert row.tab_unknown and row.label == "Supervision" and row.tags == 5
    assert row not in unknown.rows
    assert len([r for r in unknown.rows if r.page == "Supervision"]) == 3  # les feuilles restent listées
