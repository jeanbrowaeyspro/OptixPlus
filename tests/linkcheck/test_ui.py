"""Link Checker dans OptixPlus : page, corrections en arrière-plan, reconstruction en l'état."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from linkcheck_fixture import make_project
from optixplus.common.recent import recent_projects
from support import wait_until


@pytest.fixture
def ui(controller, tmp_path):
    """Contrôle des liens ouvert sur un projet de démonstration (pas encore analysé)."""
    project = make_project(tmp_path)
    window = controller.show_main_window()
    window.show_page("linkcheck")
    return controller, window.module("linkcheck").page, project


def _analysed(page, project) -> None:
    page.open_project(str(project))
    assert wait_until(lambda: not page.busy and page.project is not None, 30)


def test_analysis_runs_in_background_and_fills_table(ui):
    controller, page, project = ui
    page.open_project(str(project))
    assert page.busy
    assert wait_until(lambda: not page.busy and page.project is not None, 30)
    assert page.model.rowCount() == 5
    assert "Liens cassés : 5" in page.summary.text()
    assert "1 vers des objets internes" in page.summary.text()
    assert recent_projects(controller.context.settings) == [str(project)]
    page.filter.setCurrentIndex(1)  # vers un autre projet
    assert page.model.rowCount() == 3


def test_prefix_fix_in_background_then_reanalyse(ui):
    _controller, page, project = ui
    _analysed(page, project)
    assert page.act_prefix.isEnabled()
    page.fix_prefix()
    assert wait_until(lambda: not page.busy and len(page.broken) == 3, 30)
    assert "OldProject/Model/Speed" not in (project / "Nodes" / "UI" / "UI.yaml").read_text(encoding="utf-8-sig")


def test_refused_confirmation_writes_nothing(ui, message_boxes):
    _controller, page, project = ui
    _analysed(page, project)
    before = (project / "Nodes" / "UI" / "UI.yaml").read_bytes()
    message_boxes.answer = QMessageBox.StandardButton.No
    page.fix_prefix()
    assert not page.busy
    assert (project / "Nodes" / "UI" / "UI.yaml").read_bytes() == before


def test_language_change_keeps_results_and_selection(ui):
    controller, page, project = ui
    _analysed(page, project)
    page.table.selectRow(2)
    controller.context.settings.general.language = "en"
    controller.change_language()
    new_page = controller.window.module("linkcheck").page
    assert new_page is not page
    assert new_page.model.rowCount() == 5
    assert [i.row() for i in new_page.table.selectionModel().selectedRows()] == [2]
    assert new_page.summary.text().startswith("Project Demo:")
    assert new_page.model.headerData(0, Qt.Orientation.Horizontal) == "Screen / area"


def test_home_recent_project_opens_link_checker(ui):
    controller, page, project = ui
    _analysed(page, project)
    window = controller.window
    window.show_page("home")
    window.home.recent.requested.emit("linkcheck", str(project))
    assert window.current_page == "linkcheck"
    assert wait_until(lambda: not page.busy, 30)
