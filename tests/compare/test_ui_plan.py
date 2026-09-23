"""Interface des phases 2 et 3 : colonne Décision, actions de masse, prévisualisation, application, restauration."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEventLoop, QSettings, Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from optixplus.modules.compare.core.analysis import compare  # noqa: E402
from optixplus.modules.compare.core.lines import md5_of_file  # noqa: E402
from optixplus.modules.compare.ui.apply_dialog import format_report  # noqa: E402
from optixplus.modules.compare.ui.page import ComparePage as MainWindow  # noqa: E402
from optixplus.modules.compare.ui.results_page import ResultsPage  # noqa: E402
from optixplus.modules.compare.ui.semantic_view import SemanticModel  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
TAGS = "Nodes/CommDrivers/CODESYSDriver/API_Demo/Tags/Tags.yaml"
TRANSLATIONS = "Nodes/Translations/Translations.yaml"


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def couple(tmp_path: Path) -> tuple[Path, Path]:
    runtime = tmp_path / "Runtime" / "IHM_Demo"
    projet = tmp_path / "Projet" / "IHM_Demo"
    shutil.copytree(FIXTURES / "runtime" / "IHM_Demo", runtime)
    shutil.copytree(FIXTURES / "projet" / "IHM_Demo", projet)
    return runtime, projet


def _wait(signal, timeout_ms: int = 15000) -> None:
    loop = QEventLoop()
    signal.connect(loop.quit)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()


def _find(item, name):
    if item.text(0) == name:
        return item
    for k in range(item.childCount()):
        found = _find(item.child(k), name)
        if found is not None:
            return found
    return None


def test_colonne_decision_et_actions_de_masse(app: QApplication, couple: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, projet = couple
    page = ResultsPage()
    page.set_comparison(compare(runtime, projet))
    sem = page.semantic
    model = sem.model
    assert not sem.preview_button.isEnabled() and "aucune décision" in sem.plan_label.text()

    # Décision individuelle via le modèle (ce que fait la liste déroulante).
    page.tree.setCurrentItem(_find(page.tree.topLevelItem(0), "Tags.yaml"))
    index = model.index(0, SemanticModel.COL_DECISION)
    assert model.data(index) == "Ignorer" and model.flags(index) & Qt.ItemFlag.ItemIsEditable
    assert model.setData(index, "prendre_runtime")
    assert model.data(index) == "Prendre le runtime"
    assert page.plan.nb_pris() == 1 and sem.preview_button.isEnabled()
    assert model.setData(index, "garder_projet") and "gardé" in sem.plan_label.text()
    assert not model.setData(index, "n_importe_quoi")

    # Actions de masse sur les fichiers affichés puis sur tout.
    assert sem.mass_action("ajouts", tout=False) == 2  # Acquit_Z1+Z2, EnHaut
    assert sem.mass_action("ajouts", tout=True) == 3
    assert sem.mass_action("valeurs", tout=True) == 3
    assert page.plan.nb_pris() == 6
    sem.mass_action("ignorer", tout=False)
    assert page.plan.nb_pris() == 4
    sem.mass_action("ignorer", tout=True)
    assert page.plan.est_vide()

    # Alignement complet : confirmation avec la liste des blocs supprimés, refusée puis acceptée.
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Cancel)
    assert sem.mass_action("complet", tout=True) == 0 and page.plan.est_vide()
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Ok)
    assert sem.mass_action("complet", tout=True) > 0
    assert page.plan.alignement_complet == set(page.comparison.diffs)
    assert "alignement complet" in sem.plan_label.text()


def test_previsualisation_puis_application_et_restauration(app: QApplication, couple: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, projet = couple
    avant = {p.relative_to(projet).as_posix(): md5_of_file(p) for p in projet.rglob("*") if p.is_file()}
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings)
    window.setup_page.runtime.set_path(runtime)
    window.setup_page.projet.set_path(projet)
    window.setup_page.compare_button.click()
    _wait(window.worker.finished)
    app.processEvents()
    assert window.action_preview.isEnabled()
    page = window.results_page
    page.semantic.mass_action("ajouts", tout=True)

    dialog = page.open_plan_dialog()
    assert dialog is not None
    assert dialog.wait_ready()  # la prévisualisation est calculée en arrière-plan
    assert dialog.files.count() == 2 and "2</b> fichier(s)" in dialog.summary.text()
    assert dialog.diff.nb_hunks() >= 1 and dialog.apply_button.isEnabled()
    dialog.files.setCurrentRow(1)
    assert "Dimensions" in dialog.notes.toPlainText() or "Origine" in dialog.notes.toPlainText()

    # Plan JSON : enregistrer, vider, recharger.
    plan_path = str(tmp_path / "plan.json")
    assert dialog.save_plan_file(plan_path) == plan_path
    page.plan.tout_ignorer(page.comparison)
    dialog.refresh()
    assert dialog.wait_ready()
    assert dialog.files.count() == 0 and not dialog.apply_button.isEnabled()
    assert dialog.load_plan_file(plan_path) == []
    assert dialog.wait_ready()
    assert page.plan.nb_pris() == 3 and dialog.files.count() == 2
    assert page.semantic.preview_button.isEnabled()

    # Options dérivées.
    dialog.copy_stats.setChecked(True)
    assert dialog.wait_ready()
    assert dialog.files.count() == 3 and any("optix" in dialog.files.item(k).text() for k in range(3))
    dialog.copy_stats.setChecked(False)
    assert dialog.wait_ready()

    # Application : confirmation obligatoire, puis rapport, puis proposition de relance (refusée ici).
    apply_dialog = page.open_apply_dialog(dialog.preview, dialog)
    assert apply_dialog is not None and not apply_dialog.start_button.isEnabled()
    assert "Aucun verrou" in apply_dialog.intro.text()
    apply_dialog.confirm.setChecked(True)
    assert apply_dialog.start_button.isEnabled()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    reports = []
    apply_dialog.applied.connect(reports.append)
    apply_dialog.start()
    _wait(apply_dialog.worker.finished)
    app.processEvents()
    assert len(reports) == 1 and reports[0].succes
    assert "Fichiers écrits et vérifiés" in apply_dialog.output.toPlainText()
    assert (projet / TRANSLATIONS).read_bytes() == (runtime / TRANSLATIONS).read_bytes()
    assert b"Acquit_Z1" in (projet / TAGS).read_bytes()
    assert window.last_backup is not None and window.last_backup.is_dir()
    texte = format_report(reports[0])
    assert TAGS in texte and "Reste à faire" in texte

    # Restauration depuis le menu Plan.
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    restaures = window.restore_backup(str(window.last_backup))
    assert sorted(restaures) == sorted([TAGS, TRANSLATIONS])
    apres = {p.relative_to(projet).as_posix(): md5_of_file(p) for p in projet.rglob("*") if p.is_file()}
    assert apres == avant
    dialog.close()
    apply_dialog.close()
    window.close()


def test_application_refusee_si_verrou(app: QApplication, couple: tuple[Path, Path]) -> None:
    import stat

    runtime, projet = couple
    cible = projet / TAGS
    cible.chmod(stat.S_IREAD)
    try:
        page = ResultsPage()
        page.set_comparison(compare(runtime, projet))
        page.semantic.mass_action("ajouts", tout=True)
        dialog = page.open_plan_dialog()
        assert dialog.wait_ready()
        apply_dialog = page.open_apply_dialog(dialog.preview, dialog)
        assert "verrouillés" in apply_dialog.intro.text()
        apply_dialog.confirm.setChecked(True)
        assert not apply_dialog.start_button.isEnabled()
        dialog.close()
        apply_dialog.close()
    finally:
        os.chmod(cible, stat.S_IWRITE | stat.S_IREAD)
