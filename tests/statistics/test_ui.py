"""Statistiques dans OptixPlus : page, analyse en arrière-plan, tri, export, reconstruction en l'état."""

from __future__ import annotations

import os

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog, QLabel, QMessageBox

from optixplus.common.i18n import tr
from optixplus.common.progress import Cancelled, Progress
from optixplus.common.recent import recent_projects
from optixplus.modules.statistics.core.config import StatisticsSettings
from optixplus.modules.statistics.core.model import HighlightResult, PageRow, StatisticsOptions
from optixplus.modules.statistics.ui import page as page_module
from statistics_fixture import make_statistics
from support import wait_until


@pytest.fixture
def ui(controller, monkeypatch):
    """Page Statistiques dont le calcul est remplacé ; ``calls`` relève les appels (dossier, options)."""
    calls: list[tuple[str, StatisticsOptions]] = []

    def fake_compute(folder, progress, cancel, options):
        calls.append((folder, options))
        progress(Progress("Reading", "UI.yaml", 1, 2))
        return make_statistics(folder)

    monkeypatch.setattr(page_module, "_load_compute", lambda: fake_compute)
    window = controller.show_main_window()
    window.show_page("statistics")
    return controller, window.module("statistics").page, calls


def _analysed(page, folder="C:/demo/Demo") -> None:
    page.open_project(folder)
    assert wait_until(lambda: not page.busy and page.result is not None, 30)


def test_analysis_runs_in_background_and_shows_cards(ui):
    controller, page, calls = ui
    page.open_project("C:/demo/Demo")
    assert page.busy
    assert wait_until(lambda: not page.busy and page.result is not None, 30)
    assert calls[0][0] == "C:/demo/Demo"
    assert calls[0][1] == StatisticsOptions()
    assert "150 tags synchronisés" in page.summary.text()
    assert page.tables["stations"].displayed(2) == ["192.0.2.10:11740", ""]
    assert page.tables["stations"].displayed(5) == ["≈ 100", "20"]
    assert page.tables["pages"].displayed(0) == ["Home", "Alpha", "Beta/Axes", "Beta/Overview/Detail"]  # ordre du calcul, sans dialogue
    assert page.tables["pages"].displayed(1)[1] == "≈ 40"  # page approximative
    assert recent_projects(controller.context.settings) == [os.path.normpath("C:/demo/Demo")]
    assert page.act_export.isEnabled()
    assert page.act_analyse.toolTip().endswith("(F5)")


def test_pages_table_sorts_by_column(ui):
    _controller, page, _calls = ui
    _analysed(page)
    table = page.tables["pages"]
    table.sortByColumn(1, Qt.SortOrder.DescendingOrder)  # tags distincts : nombres, pas texte
    assert table.displayed(0) == ["Alpha", "Beta/Axes", "Beta/Overview/Detail", "Home"]
    table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
    assert table.displayed(0) == ["Alpha", "Beta/Axes", "Beta/Overview/Detail", "Home"]


def test_runtime_shows_database_files(ui, monkeypatch):
    _controller, page, _calls = ui
    monkeypatch.setattr(page_module, "_load_compute", lambda: lambda f, p, c, o: make_statistics(f, runtime=True))
    _analysed(page)
    files = page.tables["runtime_files"]
    assert files.displayed(0) == ["Retentive.db", "Data.sqlite"]
    assert files.displayed(1) == ["2,0 Kio", "4,0 Mio"]


def test_export_csv_writes_stations_and_pages(ui, monkeypatch, tmp_path):
    _controller, page, _calls = ui
    target = tmp_path / "out.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), "")))
    assert not page.act_export.isEnabled()
    _analysed(page)
    page.act_export.trigger()
    lines = target.read_text(encoding="utf-8-sig").splitlines()
    assert lines[0] == "Automates"
    assert lines[2] == "Station1;CODESYSDriver;192.0.2.10:11740;120;6;100"
    assert "Pages" in lines
    assert "Alpha;40;60;3;1" in lines
    assert "Beta/Overview/Detail;12;14;0;0" in lines
    assert not any(line.startswith("Confirm") for line in lines)  # dialogue exclu


def test_export_cancelled_writes_nothing(ui, monkeypatch, tmp_path):
    _controller, page, _calls = ui
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("", "")))
    _analysed(page)
    page.act_export.trigger()
    assert list(tmp_path.glob("*.csv")) == []


def test_cancel_stops_the_analysis(ui, monkeypatch):
    _controller, page, _calls = ui
    started = []

    def slow(folder, progress, cancel, options):
        started.append(True)
        while not cancel():
            progress(Progress("Reading", "x", 0, 0))
            QTest.qWait(5)
        raise Cancelled()

    monkeypatch.setattr(page_module, "_load_compute", lambda: slow)
    page.open_project("C:/demo/Demo")
    assert wait_until(lambda: started)
    assert not page.summary.isVisibleTo(page)  # la progression prend la place de la synthèse
    page.cancel_button.click()
    assert wait_until(lambda: not page.busy)
    assert page.result is None
    assert page.summary.text() == "Analyse annulée."


def test_failure_shows_message(ui, monkeypatch):
    _controller, page, _calls = ui
    shown = []

    def fail(*args):
        raise RuntimeError("boom")

    monkeypatch.setattr(page_module, "_load_compute", lambda: fail)
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: shown.append(a[2])))
    page.open_project("C:/demo/Demo")
    assert wait_until(lambda: not page.busy)
    assert shown == ["boom"]
    assert page.summary.text() == "Échec de l'analyse."


def test_empty_path_asks_for_a_folder(ui, message_boxes):
    _controller, page, calls = ui
    page.path.setEditText("")
    page.analyse()
    assert not page.busy and calls == []
    assert message_boxes.of("warning")


def test_settings_entries_reach_the_options(ui):
    controller, page, calls = ui
    _analysed(page)
    assert calls[0][1].highlights == ()  # liste vide par défaut
    controller.context.settings.section(StatisticsSettings).highlighted = ["Atelier, Shop", "", "Beta"]
    _analysed(page)
    assert calls[1][1].highlights == (("Atelier", "Shop"), ("Beta",))


def test_language_change_keeps_result_and_sort(ui):
    controller, page, _calls = ui
    _analysed(page)
    page.tables["pages"].sortByColumn(1, Qt.SortOrder.DescendingOrder)
    controller.context.settings.general.language = "en"
    controller.change_language()
    new_page = controller.window.module("statistics").page
    assert new_page is not page
    assert new_page.result is not None
    table = new_page.tables["pages"]
    assert table.displayed(0)[0] == "Alpha"
    assert table.model().headerData(1, Qt.Orientation.Horizontal) == "Distinct tags"
    assert new_page.summary.text().startswith("Demo: 150 synchronised tags")


def test_home_recent_project_opens_statistics(ui):
    controller, page, _calls = ui
    _analysed(page)
    window = controller.window
    window.show_page("home")
    window.home.recent.requested.emit("statistics", "C:/demo/Demo")
    assert window.current_page == "statistics"
    assert wait_until(lambda: not page.busy, 30)


def test_f5_works_without_clicking_in_the_page(ui, qapp):
    controller, page, _calls = ui
    window = controller.window
    window.activateWindow()
    window.sidebar.setFocus()
    window.show_page("home")
    window.show_page("statistics")
    qapp.processEvents()
    assert page.isAncestorOf(qapp.focusWidget())
    triggered = []
    page.act_analyse.triggered.connect(lambda: triggered.append(True))
    QTest.keyClick(qapp.focusWidget(), Qt.Key.Key_F5)
    assert triggered


def _labels(page) -> list[str]:
    return [label.text() for label in page.cards.findChildren(QLabel)]


def test_pages_card_gives_page_tab_and_tag_count_of_highlighted_pages(ui):
    _controller, page, _calls = ui
    _analysed(page)
    labels = _labels(page)
    assert "alpha" in labels and "beta, overwatch" in labels  # mots-clés de chaque entrée
    assert "Alpha (≈ 40 tags)" in labels  # page approximative
    assert "Beta/Overview/Detail (12 tags)" in labels  # feuille de l'onglet par défaut, pas les 25 tags de la page


def test_pages_card_says_not_found(ui):
    _controller, page, _calls = ui
    result = make_statistics()
    result.highlights = [HighlightResult(("one", "two"), None)]
    page.show_result(result)
    assert _labels(page).count(tr("not found")) == 1
    assert "one, two" in _labels(page)  # les mots-clés sont cités


def test_pages_card_without_highlighted_page_shows_a_hint(ui):
    _controller, page, _calls = ui
    result = make_statistics()
    result.highlights = []
    page.show_result(result)
    assert tr("No highlighted page: add some in Settings > Statistics") in _labels(page)
    assert "alpha" not in _labels(page)



def test_bindings_and_distinct_tags_columns_explain_themselves(ui):
    _controller, page, _calls = ui
    _analysed(page)
    model = page.tables["pages"].model()
    horizontal = Qt.Orientation.Horizontal
    assert model.headerData(1, horizontal) == "Tags distincts"
    assert model.headerData(2, horizontal) == "Liaisons"
    assert "trois objets compte pour 3 liaisons et 1 tag" in model.headerData(2, horizontal, Qt.ItemDataRole.ToolTipRole)
    assert "qu'une fois" in model.headerData(1, horizontal, Qt.ItemDataRole.ToolTipRole)
    assert model.headerData(0, horizontal, Qt.ItemDataRole.ToolTipRole) is None


def test_no_memory_nor_module_list_in_the_result(ui):
    _controller, page, _calls = ui
    _analysed(page)
    texts = " ".join(_labels(page)).lower()
    assert "mémoire" not in texts and "mio (estimation)" not in texts
    assert "modules" not in texts
    assert "memory" not in page.tables


def test_pages_card_tab_variants(ui):
    _controller, page, _calls = ui
    result = make_statistics()
    result.highlights = [
        HighlightResult(("alpha",), PageRow("Alpha", "UI/Alpha", ["Gamma"], 9, 7, True)),
        HighlightResult(("beta",), PageRow("Beta", "UI/Beta", [], 30, 25, False, tab_unknown=True)),
    ]
    page.show_result(result)
    labels = _labels(page)
    assert "Alpha/Gamma (≈ 7 tags)" in labels
    assert "Beta (25 tags), onglet inconnu" in labels


def test_busiest_and_average_are_per_page_or_tab(ui):
    _controller, page, _calls = ui
    _analysed(page)
    labels = _labels(page)
    assert "Page/onglet le plus chargé" in labels and "Moyenne de tags par page/onglet" in labels
    assert labels.count("Alpha (≈ 40 tags)") == 2  # page la plus chargée et page mise en évidence
    assert "18,0" in labels


def test_used_and_unused_tags_are_shown(ui):
    _controller, page, _calls = ui
    _analysed(page)
    assert "Tags utilisés : ≈ 120 · Tags inutilisés : ≈ 30" in _labels(page)
    header = page.tables["stations"].model().headerData(5, Qt.Orientation.Horizontal, Qt.ItemDataRole.ToolTipRole)
    assert "NetLogic" in header
