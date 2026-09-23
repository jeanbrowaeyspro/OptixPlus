"""Interface PySide6 : page d'accueil, thread d'analyse, arbre des fichiers et résumé sémantique.

Ces tests tournent hors écran (``QT_QPA_PLATFORM=offscreen``) sur le couple synthétique.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import QEventLoop, QSettings, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QTreeWidgetItem  # noqa: E402

from optixplus.modules.compare.ui.main_window import MainWindow, ProgressPage  # noqa: E402
from optixplus.modules.compare.ui.results_page import BRANCHE_ATTENDUS, ROLE_KIND  # noqa: E402
from optixplus.modules.compare.ui.semantic_view import SemanticModel  # noqa: E402
from optixplus.modules.compare.ui.setup_page import SetupPage  # noqa: E402
from optixplus.modules.compare.ui.workers import CompareWorker  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
RUNTIME = FIXTURES / "runtime" / "IHM_Demo"
PROJET = FIXTURES / "projet" / "IHM_Demo"


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def settings(tmp_path: Path) -> QSettings:
    return QSettings(str(tmp_path / "ftocompare.ini"), QSettings.Format.IniFormat)


def _wait(signal, timeout_ms: int = 15000) -> None:
    loop = QEventLoop()
    signal.connect(loop.quit)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()


def _find(item: QTreeWidgetItem, name: str) -> QTreeWidgetItem | None:
    if item.text(0) == name:
        return item
    for k in range(item.childCount()):
        found = _find(item.child(k), name)
        if found is not None:
            return found
    return None


# -- Page d'accueil -------------------------------------------------------------------


def test_accueil_detection_et_versions(app: QApplication, settings: QSettings, tmp_path: Path) -> None:
    page = SetupPage(settings)
    assert not page.compare_button.isEnabled()

    page.runtime.set_path(RUNTIME)
    assert page.runtime.path == RUNTIME and page.runtime.version == "1.3.2.9-Stable"
    assert not page.compare_button.isEnabled(), "il manque le projet"

    page.projet.set_path(tmp_path)
    assert page.projet.path is None and "pas un projet Optix" in page.projet.status.text()

    page.projet.set_path(FIXTURES / "projet")  # dossier parent : proposer de descendre
    assert page.projet.path is None
    assert page.projet.suggest_button.isVisible() or page.projet.suggest_button.text().startswith("Descendre")
    page.projet.suggest_button.click()
    assert page.projet.path == PROJET
    assert page.compare_button.isEnabled()
    assert "identiques" in page.hint.text()

    page.projet.set_path(RUNTIME)  # même dossier des deux côtés
    assert not page.compare_button.isEnabled() and "identiques" in page.hint.text()


def test_accueil_versions_differentes_bloquant_franchissable(app: QApplication, settings: QSettings) -> None:
    page = SetupPage(settings)
    page.runtime.set_path(RUNTIME)
    page.projet.set_path(PROJET)
    page.projet._version = "1.4.0.1-Stable"
    page._update_state()
    assert page.versions_differ()
    assert page.warning.isVisibleTo(page)
    assert not page.compare_button.isEnabled()
    page.override.setChecked(True)
    assert page.compare_button.isEnabled()


def test_accueil_historique(app: QApplication, settings: QSettings) -> None:
    page = SetupPage(settings)
    page.runtime.set_path(RUNTIME)
    page.projet.set_path(PROJET)
    received: list[tuple[str, str]] = []
    page.compare_requested.connect(lambda r, p: received.append((r, p)))
    page.compare_button.click()
    assert received == [(str(RUNTIME.resolve()), str(PROJET.resolve()))]
    assert page.couples() == [(str(RUNTIME.resolve()), str(PROJET.resolve()))]
    assert page.history.count() == 1

    autre = SetupPage(settings)  # l'historique survit à la page
    assert autre.history.count() == 1
    autre.runtime.set_path("")
    autre._pick_history(autre.history.item(0))
    assert autre.runtime.path == RUNTIME.resolve() and autre.projet.path == PROJET.resolve()


# -- Thread d'analyse ------------------------------------------------------------------


def test_worker_progression_et_resultat(app: QApplication) -> None:
    worker = CompareWorker(RUNTIME, PROJET)
    steps: list[tuple[str, str, int, int]] = []
    results: list[object] = []
    worker.progressed.connect(lambda *args: steps.append(args))
    worker.succeeded.connect(results.append)
    worker.start()
    _wait(worker.finished)
    assert len(results) == 1
    assert {s[0] for s in steps} == {"inventaire", "hash", "diff", "analyse"}


def test_worker_annulation(app: QApplication) -> None:
    worker = CompareWorker(RUNTIME, PROJET)
    outcomes: list[str] = []
    worker.cancelled.connect(lambda: outcomes.append("annulé"))
    worker.succeeded.connect(lambda _r: outcomes.append("succès"))
    worker.request_cancel()
    worker.start()
    _wait(worker.finished)
    assert outcomes == ["annulé"]


def test_worker_echec(app: QApplication, tmp_path: Path) -> None:
    worker = CompareWorker(tmp_path / "absent", PROJET)
    errors: list[str] = []
    worker.failed.connect(errors.append)
    worker.start()
    _wait(worker.finished)
    assert len(errors) == 1 and "Traceback" in errors[0]


def test_page_progression(app: QApplication) -> None:
    page = ProgressPage()
    page.update("hash", "Nodes/A.yaml", 3, 10)
    assert page.bar.maximum() == 10 and page.bar.value() == 3
    assert "3/10" in page.current.text() and "empreintes" in page.phase.text()
    page.update("inventaire", "", 0, 0)
    assert page.bar.maximum() == 0, "barre indéterminée"


# -- Fenêtre principale et résultats -----------------------------------------------------


@pytest.fixture
def window(app: QApplication, settings: QSettings) -> MainWindow:
    win = MainWindow(settings)
    win.setup_page.runtime.set_path(RUNTIME)
    win.setup_page.projet.set_path(PROJET)
    win.setup_page.compare_button.click()
    assert win.worker is not None
    _wait(win.worker.finished)
    app.processEvents()
    assert win.stack.currentWidget() is win.results_page
    yield win
    win.close()


def test_bandeau_et_arbre(window: MainWindow) -> None:
    banner = window.results_page.banner.label.text()
    assert "1.3.2.9-Stable" in banner and "14</b> fichiers comparés" in banner
    assert "3</b> ajouts runtime" in banner and "4</b> branche projet" in banner and "3</b> valeurs modifiées" in banner
    assert "1 YAML orphelin" in banner

    tree = window.results_page.tree
    root = tree.topLevelItem(0)
    assert root.text(0) == "Tous les fichiers" and root.text(1) == "10"
    tags = _find(root, "Tags.yaml")
    assert tags is not None and tags.text(1) == "3" and tags.text(2) == "mixte"
    assert _find(root, "Orphelin.yaml").text(2) == "projet seul"
    assert _find(root, "logo.svg") is None, "filtre « divergences seules »"

    attendus = [tree.topLevelItem(k) for k in range(tree.topLevelItemCount()) if tree.topLevelItem(k).text(0) == BRANCHE_ATTENDUS]
    assert len(attendus) == 1 and not attendus[0].isExpanded()
    assert attendus[0].data(0, ROLE_KIND) == "attendus"
    noms = {attendus[0].child(k).text(0) for k in range(attendus[0].childCount())}
    assert "IHM_Demo.optix" in noms and "ApplicationFiles/RetentivityStorage.db" in noms


def test_filtres_de_l_arbre(window: MainWindow) -> None:
    page = window.results_page
    page.filter_combo.setCurrentIndex(1)  # tout
    assert _find(page.tree.topLevelItem(0), "logo.svg") is not None
    page.search.setText("tags")
    root = page.tree.topLevelItem(0)
    assert _find(root, "Tags.yaml") is not None and _find(root, "Model.yaml") is None
    page.search.setText("")
    page.filter_combo.setCurrentIndex(0)


def test_resume_semantique_pilote_par_l_arbre(window: MainWindow) -> None:
    page = window.results_page
    sem = page.semantic
    assert sem.visible_count() == 10 and sem.model.rowCount() == 12
    assert not sem.table.isColumnHidden(SemanticModel.COL_FICHIER)

    page.tree.setCurrentItem(_find(page.tree.topLevelItem(0), "Tags.yaml"))
    assert sem.visible_count() == 3 and sem.table.isColumnHidden(SemanticModel.COL_FICHIER)
    sem.table.selectRow(0)
    row = sem.current_row()
    assert row is not None and row.rel.endswith("Tags.yaml")
    assert "+ " in sem.detail.toPlainText() and "Acquit_Z1" in sem.detail.toPlainText()

    page.tree.setCurrentItem(_find(page.tree.topLevelItem(0), "Model.yaml"))
    assert sem.visible_count() == 1, "l'Id non significatif est masqué"
    sem.show_all.setChecked(True)
    assert sem.visible_count() == 2
    sem.search.setText("avecscanner")
    assert sem.visible_count() == 1
    sem.search.setText("")
    sem.show_all.setChecked(False)

    page.tree.setCurrentItem(_find(page.tree.topLevelItem(0), "Nodes"))
    assert sem.visible_count() == 9


def test_modele_semantique_affichage(window: MainWindow) -> None:
    sem = window.results_page.semantic
    window.results_page.tree.setCurrentItem(_find(window.results_page.tree.topLevelItem(0), "Model.yaml"))
    sem.show_all.setChecked(True)
    model = sem.model
    textes = {model.index(r, SemanticModel.COL_NOEUD).data(): model.index(r, SemanticModel.COL_SENS).data() for r in range(model.rowCount())}
    assert textes["AvecScanner"].endswith("valeur modifiée")
    assert textes["Enum_Taille"].endswith("branche projet")
    genres = {model.index(r, SemanticModel.COL_GENRE).data() for r in range(model.rowCount())}
    assert genres == {"valeur", "identifiant"}
    sem.show_all.setChecked(False)


def test_nouvelle_comparaison_et_journal(window: MainWindow) -> None:
    window.action_new.trigger()
    assert window.stack.currentWidget() is window.setup_page
    assert "Comparaison" in window.log_panel.toPlainText()


def test_export_rapport(window: MainWindow, tmp_path: Path) -> None:
    md = window.export_report(str(tmp_path / "rapport.md"))
    html = window.export_report(str(tmp_path / "rapport.html"))
    assert md and Path(md).read_text(encoding="utf-8").startswith("# FTOCompare")
    assert html and Path(html).read_text(encoding="utf-8").startswith("<!DOCTYPE html>")
    assert window.action_export.isEnabled()
