"""Compare dans la coquille OptixPlus : reconstruction en l'état et projets récents."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QMessageBox

from optixplus.common import i18n
from optixplus.common.recent import recent_projects
from optixplus.common.settings import Settings
from optixplus.common.theme import install_manager
from optixplus.shell.context import LaunchMode
from optixplus.shell.controller import AppController

from .conftest import PROJET, RUNTIME, wait_until


@pytest.fixture
def shell(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    controller = AppController(qapp, Settings.load(tmp_path / "s.json"), install_manager(qapp, "light"), LaunchMode.INSTALLED)
    window = controller.show_main_window()
    window.show_page("compare")
    yield controller
    if controller.window is not None:
        controller.window.close()
    i18n.install("fr")


def _compare_in(shell):
    page = shell.window.module("compare").page
    page.setup_page.runtime.set_path(RUNTIME)
    page.setup_page.projet.set_path(PROJET)
    page.setup_page.compare_button.click()
    assert wait_until(lambda: page.comparison is not None and not page.busy)
    return page


def test_page_reconstruite_en_l_etat(shell) -> None:
    """Changement de langue : la comparaison, le fichier choisi, l'onglet et le plan sont conservés."""
    page = _compare_in(shell)
    rel = next(iter(page.comparison.diffs))
    assert page.results_page.tree.select_rel(rel)
    page.results_page.tabs.setCurrentIndex(1)
    page.results_page.semantic.mass_action("ajouts", tout=True)
    taken = page.results_page.plan.nb_pris()
    assert taken > 0

    shell.context.settings.general.language = "en"
    shell.change_language()
    new = shell.window.module("compare").page
    assert new is not page and new.comparison is page.comparison
    assert new.stack.currentWidget() is new.results_page
    assert new.results_page.tree.current_rel() == rel
    assert new.results_page.tabs.currentIndex() == 1
    assert new.results_page.plan.nb_pris() == taken
    assert new.action_export.isEnabled() and new.results_page.tabs.tabText(0) == "Semantic summary"
    shell.context.settings.general.language = "fr"
    shell.change_language()


def test_projet_recent_ouvert_dans_compare(shell) -> None:
    page = _compare_in(shell)
    projet = str(PROJET.resolve())
    assert recent_projects(shell.context.settings)[0] == projet
    shell.window.handle_command("open-project", ["compare", projet])
    assert page.stack.currentWidget() is page.setup_page
    assert str(page.setup_page.projet.path) == projet
