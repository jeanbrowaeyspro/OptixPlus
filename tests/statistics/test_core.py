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
    assert ("FTOptix.UI", "18.1") in result.modules
    assert ("FTOptix.Core.Net", "2.2") in result.modules
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
    assert (home.links, home.tags, home.subviews, home.approximate) == (2, 2, 0, False)  # le lien vers le modèle est ignoré
    work = page(result, "IType_01_Work")
    # Pressure, Counters/Count1 (relatif), Motor (pointeur d'équipement) + Level, Motor/Speed (sous-vue)
    assert (work.links, work.tags, work.subviews, work.approximate) == (5, 5, 1, False)


def test_dynamic_path_and_converter(result):
    sup = page(result, "IType_02_Supervision")
    # Level, Motor/Speed (sous-vue partagée), Motor/{0} (chemin dynamique), Temp via le convertisseur
    assert sup.tags == 4
    assert sup.links == 4
    assert sup.subviews == 3  # deux onglets et la sous-vue partagée
    assert sup.approximate is True
    assert not page(result, "IType_01_Work").approximate
    assert any("approximate" in w for w in result.warnings)


def test_average_and_busiest_page(result):
    assert result.average_tags_per_main_page == pytest.approx((2 + 5 + 4) / 3)
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


def test_default_tab_first_without_explicit_index(result):
    assert result.supervision_default_tab == "Axes"


def test_default_tab_from_scalar_index(tmp_path):
    assert stats.compute(str(make_project(tmp_path, current_tab=1))).supervision_default_tab == "Alarms"
    other = make_project(tmp_path, current_tab=7, name="Demo3")
    assert stats.compute(str(other)).supervision_default_tab == ""  # indice hors limites : inconnu


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


def test_memory_estimate(result):
    mem = result.memory
    assert 0 < mem.low_mib < mem.high_mib
    labels = [label for label, _ in mem.detail]
    assert stats.MEM_BASE in labels and stats.MEM_NODES in labels and stats.MEM_IMAGES in labels
    assert stats.MEM_DATABASES not in labels
    assert sum(v for _, v in mem.detail) == pytest.approx((mem.low_mib + mem.high_mib) / 2)


def test_image_size_from_header(tmp_path):
    folder = make_project(tmp_path)
    assert stats.image_size(str(folder / "ProjectFiles" / "Images" / "a.png")) == (100, 50)
    assert stats.image_size(str(folder / "ProjectFiles" / "notes.txt")) is None


def test_runtime_variant(tmp_path):
    result = stats.compute(str(make_project(tmp_path, runtime=True)))
    assert result.kind == KIND_RUNTIME
    names = [n for n, _ in result.runtime_files]
    assert names == ["Data.sqlite", "RetentivityStorage.db", "log.txt"]  # par taille décroissante
    assert result.runtime_files[0][1] == 20000
    assert not any(n.endswith(".source") for n in names)
    assert stats.MEM_DATABASES in [label for label, _ in result.memory.detail]
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
