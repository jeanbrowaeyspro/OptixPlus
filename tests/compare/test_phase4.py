"""Phase 4 : recherche plein texte, thème sombre, arbitrages mémorisés, deux projets."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEventLoop, QSettings, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from optixplus.modules.compare.core.analysis import compare  # noqa: E402
from optixplus.common.progress import Cancelled  # noqa: E402
from optixplus.modules.compare.core.search import compile_pattern, search_inventory  # noqa: E402
from optixplus.modules.compare.ui.page import ComparePage as MainWindow  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
RUNTIME = FIXTURES / "runtime" / "IHM_Demo"
PROJET = FIXTURES / "projet" / "IHM_Demo"
TAGS = "Nodes/CommDrivers/CODESYSDriver/API_Demo/Tags/Tags.yaml"


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def demo():
    return compare(RUNTIME, PROJET)


def _wait(signal, timeout_ms: int = 15000) -> None:
    loop = QEventLoop()
    signal.connect(loop.quit)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()


def test_recherche_moteur(demo) -> None:
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
    with pytest.raises(Cancelled):
        search_inventory(demo.inventory, "Name", cancel=lambda: True)
    assert compile_pattern("a.b").match(b"a.b") and not compile_pattern("a.b").match(b"axb")
    assert compile_pattern("a.b", regex=True).match(b"axb")


def test_onglet_recherche_pilote_la_vue_diff(app: QApplication, demo, tmp_path: Path) -> None:
    window = MainWindow(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    window.setup_page.runtime.set_path(RUNTIME)
    window.setup_page.projet.set_path(PROJET)
    window.setup_page.compare_button.click()
    _wait(window.worker.finished)
    app.processEvents()
    page = window.results_page
    view = page.search_view
    view.input.setText("Acquit_Z1")
    view.start()
    _wait(view.worker.finished)
    app.processEvents()
    assert view.model.rowCount() == 2 and "2 occurrence(s)" in view.status.text()
    assert page.show_hit("runtime", TAGS, 21)
    assert page.tabs.currentWidget() is page.diff
    row = page.diff.table.currentIndex().row()
    assert page.diff.model.rows[row].b_no == 21 and not page.diff.fold_box.isChecked()
    # Un fichier identique des deux côtés s'ouvre aussi (diff calculé à la volée), un fichier absent non.
    assert page.show_hit("projet", "Nodes/UI/Parents/IO/IO.yaml", 1)
    assert not page.show_hit("projet", "inexistant.yaml", 1)
    window.close()


def test_relancer_la_comparaison_conserve_le_plan(app: QApplication, tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings)
    assert not window.action_relaunch.isEnabled()
    window.setup_page.runtime.set_path(RUNTIME)
    window.setup_page.projet.set_path(PROJET)
    window.setup_page.compare_button.click()
    _wait(window.worker.finished)
    app.processEvents()
    assert window.action_relaunch.isEnabled()
    window.results_page.semantic.mass_action("ajouts", tout=True)
    premiere = window.comparison
    window.action_relaunch.trigger()
    assert window.stack.currentWidget() is window.progress_page
    _wait(window.worker.finished)
    app.processEvents()
    assert window.comparison is not premiere and window.stack.currentWidget() is window.results_page
    assert window.results_page.plan.nb_pris() == 3
    assert "Décisions conservées : 3" in window.status.text()
    window.close()


def test_arbitrage_memorise_par_couple(app: QApplication, tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings)
    window.setup_page.runtime.set_path(RUNTIME)
    window.setup_page.projet.set_path(PROJET)
    window.setup_page.compare_button.click()
    _wait(window.worker.finished)
    app.processEvents()
    assert not window.action_replay.isEnabled()
    window.results_page.semantic.mass_action("ajouts", tout=True)
    assert window.stored_plan() is not None and window.action_replay.isEnabled()
    window.close()

    # Nouvelle session, même couple : le dernier arbitrage se rejoue.
    autre = MainWindow(settings)
    autre.setup_page.runtime.set_path(RUNTIME)
    autre.setup_page.projet.set_path(PROJET)
    autre.setup_page.compare_button.click()
    _wait(autre.worker.finished)
    app.processEvents()
    assert autre.action_replay.isEnabled() and autre.results_page.plan.est_vide()
    assert autre.replay_last_plan() == []
    assert autre.results_page.plan.nb_pris() == 3
    autre.close()


def test_libelles_deux_projets(app: QApplication, tmp_path: Path) -> None:
    window = MainWindow(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    assert "autre projet" in window.setup_page.runtime.title()
    window.close()
