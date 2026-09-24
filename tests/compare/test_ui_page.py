"""Page Compare : progression, nouvelle comparaison, export, relance et arbitrages mémorisés."""

from __future__ import annotations

from pathlib import Path

from optixplus.common.logging_setup import memory_handler
from optixplus.modules.compare.ui.page import ComparePage, ProgressPage

from .conftest import compared_page, ini_settings, wait_until


def test_page_progression(qapp) -> None:
    page = ProgressPage()
    page.update("hash", "Nodes/A.yaml", 3, 10)
    assert page.bar.maximum() == 10 and page.bar.value() == 3
    assert "3/10" in page.current.text() and "empreintes" in page.phase.text()
    page.update("inventaire", "", 0, 0)
    assert page.bar.maximum() == 0, "barre indéterminée"


def test_comparaison_journalisee_puis_nouvelle(qapp, tmp_path: Path) -> None:
    def journal() -> list[str]:
        return [text for text, _level in memory_handler().buffer if "Comparaison" in text]

    avant = len(journal())
    window = compared_page(ini_settings(tmp_path / "s.ini"))
    assert len(journal()) > avant
    window.action_new.trigger()
    assert window.stack.currentWidget() is window.setup_page
    window.close()


def test_export_rapport(window, tmp_path: Path) -> None:
    assert window.action_export.isEnabled()
    md = window.export_report(str(tmp_path / "rapport.md"))
    html = window.export_report(str(tmp_path / "rapport.html"))
    assert md and Path(md).read_text(encoding="utf-8").startswith("# OptixPlus")
    assert html and Path(html).read_text(encoding="utf-8").startswith("<!DOCTYPE html>")


def test_relancer_la_comparaison_conserve_le_plan(qapp, tmp_path: Path) -> None:
    window = compared_page(ini_settings(tmp_path / "s.ini"))
    assert window.action_relaunch.isEnabled()
    window.results_page.semantic.mass_action("ajouts", tout=True)
    premiere = window.comparison
    window.action_relaunch.trigger()
    assert window.stack.currentWidget() is window.progress_page
    assert wait_until(lambda: window.comparison is not premiere and not window.busy)
    assert window.stack.currentWidget() is window.results_page
    assert window.results_page.plan.nb_pris() == 3
    assert "Décisions conservées : 3" in window.status.text()
    window.close()


def test_relance_indisponible_avant_comparaison(qapp, tmp_path: Path) -> None:
    window = ComparePage(ini_settings(tmp_path / "s.ini"))
    assert not window.action_relaunch.isEnabled()
    window.close()


def test_arbitrage_memorise_par_couple(qapp, tmp_path: Path) -> None:
    settings = ini_settings(tmp_path / "s.ini")
    window = compared_page(settings)
    assert not window.action_replay.isEnabled()
    window.results_page.semantic.mass_action("ajouts", tout=True)
    assert window.stored_plan() is not None and window.action_replay.isEnabled()
    window.close()

    # Nouvelle session, même couple : le dernier arbitrage se rejoue.
    autre = compared_page(settings)
    assert autre.action_replay.isEnabled() and autre.results_page.plan.est_vide()
    assert autre.replay_last_plan() == []
    assert autre.results_page.plan.nb_pris() == 3
    autre.close()
