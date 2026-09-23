"""Link Checker dans OptixPlus : page, corrections en arrière-plan, reconstruction en l'état, CLI."""

from __future__ import annotations

import subprocess
import sys
import time

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QMessageBox

from linkcheck_fixture import make_project
from optixplus.common import i18n, logging_setup
from optixplus.common.recent import recent_projects
from optixplus.common.settings import Settings
from optixplus.common.theme import install_manager
from optixplus.shell.context import LaunchMode
from optixplus.shell.controller import AppController


def _wait(condition, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return condition()


@pytest.fixture
def ui(qapp, tmp_path, monkeypatch):
    answers = {"question": QMessageBox.StandardButton.Yes}
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: answers["question"]))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    i18n.install("fr")
    logging_setup.configure(to_file=False)
    settings = Settings.load(tmp_path / "settings.json")
    controller = AppController(qapp, settings, install_manager(qapp, "light"), LaunchMode.INSTALLED)
    project = make_project(tmp_path)
    window = controller.show_main_window()
    window.show_page("linkcheck")
    page = window.module("linkcheck").page
    yield controller, page, project, answers
    if controller.window is not None:
        controller.window.close()
    i18n.install("en")


def test_analysis_runs_in_background_and_fills_table(ui):
    controller, page, project, _ = ui
    page.open_project(str(project))
    assert page.busy
    assert _wait(lambda: not page.busy and page.project is not None)
    assert page.model.rowCount() == 5
    assert "Liens cassés : 5" in page.summary.text()
    assert "1 vers des objets internes" in page.summary.text()
    assert recent_projects(controller.context.settings) == [str(project)]
    page.filter.setCurrentIndex(1)  # vers un autre projet
    assert page.model.rowCount() == 3


def test_prefix_fix_in_background_then_reanalyse(ui):
    _controller, page, project, _ = ui
    page.open_project(str(project))
    assert _wait(lambda: not page.busy and page.project is not None)
    assert page.act_prefix.isEnabled()
    page.fix_prefix()
    assert _wait(lambda: not page.busy and len(page.broken) == 3)
    assert "OldProject/Model/Speed" not in (project / "Nodes" / "UI" / "UI.yaml").read_text(encoding="utf-8-sig")


def test_refused_confirmation_writes_nothing(ui):
    _controller, page, project, answers = ui
    page.open_project(str(project))
    assert _wait(lambda: not page.busy and page.project is not None)
    before = (project / "Nodes" / "UI" / "UI.yaml").read_bytes()
    answers["question"] = QMessageBox.StandardButton.No
    page.fix_prefix()
    assert not page.busy
    assert (project / "Nodes" / "UI" / "UI.yaml").read_bytes() == before


def test_language_change_keeps_results_and_selection(ui):
    controller, page, project, _ = ui
    page.open_project(str(project))
    assert _wait(lambda: not page.busy and page.project is not None)
    page.table.selectRow(2)
    controller.context.settings.general.language = "en"
    controller.change_language()
    new_page = controller.window.module("linkcheck").page
    assert new_page is not page
    assert new_page.model.rowCount() == 5
    assert [i.row() for i in new_page.table.selectionModel().selectedRows()] == [2]
    assert new_page.summary.text().startswith("Project Demo:")
    assert new_page.model.headerData(0, __import__("PySide6.QtCore").QtCore.Qt.Orientation.Horizontal) == "Screen / area"


def test_home_recent_project_opens_link_checker(ui):
    controller, page, project, _ = ui
    page.open_project(str(project))
    assert _wait(lambda: not page.busy and page.project is not None)
    window = controller.window
    window.show_page("home")
    window.home.recent.requested.emit("linkcheck", str(project))
    assert window.current_page == "linkcheck"
    assert _wait(lambda: not page.busy)


def test_cli_lists_broken_links(tmp_path):
    project = make_project(tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "optixplus", "linkcheck", str(project)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "Demo" in result.stdout
    assert result.stdout.count("OldProject") >= 3
