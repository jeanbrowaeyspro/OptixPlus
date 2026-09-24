"""Lecteur de logs dans OptixPlus : onglets, fermeture, session mémorisée, reconstruction en l'état."""

from __future__ import annotations

import time

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QMessageBox, QToolButton

from optixplus.common import i18n, logging_setup
from optixplus.common.recent import recent_controllers
from optixplus.common.settings import Settings
from optixplus.common.theme import install_manager
from optixplus.modules.logreader import session as session_module
from optixplus.modules.logreader.core.discovery import Ipc
from optixplus.modules.logreader.session import LogSession
from optixplus.shell.context import LaunchMode
from optixplus.shell.controller import AppController


def _wait(condition, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def _line(n: int, level: str = "INFO") -> str:
    return f"07-09-2026 09:00:{n:02d}.000;{level};FTOptixRuntime;;Evenement {n};;Root/X\r\n"


@pytest.fixture
def share(tmp_path, monkeypatch):
    """Partage simulé : <racine>\\Optix\\Log\\FTOptixRuntime.0.log, lu en local."""
    log_dir = tmp_path / "share" / "Optix" / "Log"
    log_dir.mkdir(parents=True)
    lines = [_line(i) for i in range(1, 11)] + [_line(11, "ERROR")]
    (log_dir / "FTOptixRuntime.0.log").write_text("".join(lines), encoding="utf-8")
    monkeypatch.setattr(session_module.netshare, "unc_path", lambda host, share: str(tmp_path / "share" / share))
    return log_dir


@pytest.fixture
def ui(qapp, tmp_path, monkeypatch, share):
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    probes: list[str] = []
    monkeypatch.setattr(LogSession, "probe_host", lambda self, host: (probes.append(host), setattr(self, "probing_host", host)))
    i18n.install("fr")
    logging_setup.configure(to_file=False)
    settings = Settings.load(tmp_path / "settings.json")
    controller = AppController(qapp, settings, install_manager(qapp, "light"), LaunchMode.INSTALLED)
    window = controller.show_main_window()
    window.show_page("logreader")
    yield controller, window.module("logreader").page, probes
    if controller.window is not None:
        controller.window.close()
    i18n.install("en")


def _ipc(name: str) -> Ipc:
    return Ipc(host=name.lower(), netbios_name=name, project="Demo", reachable=True, share_accessible=True, log_available=True)


def test_empty_state_then_tabs(ui):
    _controller, page, _probes = ui
    assert page.tabs == []
    assert page._stack.currentIndex() == 0
    assert not page.action_export_xlsx.isEnabled()
    first = page.new_tab(_ipc("PLC-A"))
    assert _wait(lambda: first.model.rowCount() == 11)
    assert page._stack.currentIndex() == 1
    assert page.action_export_xlsx.isEnabled()
    second = page.new_tab(_ipc("PLC-B"))
    assert _wait(lambda: second.model.rowCount() == 11)
    assert page.current_tab() is second
    assert len(page.tabs) == 2


def test_close_tab_stops_its_session(ui):
    _controller, page, _probes = ui
    tab = page.new_tab(_ipc("PLC-A"))
    assert _wait(lambda: tab.model.rowCount() == 11)
    name = next(iter(page._docks))
    assert page.close_tab(name)
    assert page.tabs == []
    assert tab.session.watcher is None
    assert page._stack.currentIndex() == 0


def test_language_change_keeps_sessions_and_filters(ui):
    controller, page, _probes = ui
    first = page.new_tab(_ipc("PLC-A"))
    second = page.new_tab(_ipc("PLC-B"))
    assert _wait(lambda: first.model.rowCount() == 11 and second.model.rowCount() == 11)
    first.search_edit.setText("Evenement 1")
    assert _wait(lambda: first.proxy.rowCount() == 3)  # 1, 10 et 11
    sessions = [tab.session for tab in page.tabs]
    controller.context.settings.general.language = "en"
    controller.change_language()
    new_page = controller.window.module("logreader").page
    assert new_page is not page
    assert [tab.session for tab in new_page.tabs] == sessions  # mêmes sessions : rien n'est relu
    restored = new_page.tabs[0]
    assert restored.search_edit.text() == "Evenement 1"
    assert restored.proxy.rowCount() == 3
    assert new_page.action_new.text() == "New tab…"
    assert new_page.current_tab().session is sessions[1]


def test_open_tabs_are_reopened_next_time(ui, qapp):
    controller, page, probes = ui
    page.new_tab(_ipc("PLC-A"))
    page.new_tab(_ipc("PLC-B"))
    assert _wait(lambda: all(tab.model.rowCount() == 11 for tab in page.tabs))
    controller.window.close()
    store = controller.context.settings.store("logreader")
    assert store["open_hosts"] == ["plc-a", "plc-b"]
    window = controller.show_main_window()
    window.show_page("logreader")
    reopened = window.module("logreader").page
    assert len(reopened.tabs) == 2
    assert probes == ["plc-a", "plc-b"]


def test_open_log_command_opens_a_new_tab(ui):
    controller, page, probes = ui
    assert controller.window.module("logreader").handle_command("open-controller", ["10.0.0.5"])
    assert probes == ["10.0.0.5"]
    assert len(page.tabs) == 1


def test_unseen_errors_are_counted_on_hidden_tabs(ui, share):
    _controller, page, _probes = ui
    tab = page.new_tab(_ipc("PLC-A"))
    assert _wait(lambda: tab.model.rowCount() == 11)
    tab.session.visible = False
    with open(share / "FTOptixRuntime.0.log", "a", encoding="utf-8") as handle:
        handle.write(_line(12, "ERROR") + _line(13, "ERROR"))
    assert _wait(lambda: tab.session.unseen_errors == 2)
    dock = next(iter(page._docks.values()))[0]
    assert _wait(lambda: dock.windowTitle().endswith("(2)"))


def test_opened_controllers_appear_on_home_and_reopen(ui):
    controller, page, probes = ui
    tab = page.new_tab(_ipc("PLC-A"))
    assert _wait(lambda: tab.model.rowCount() == 11)
    assert recent_controllers(controller.context.settings) == [("plc-a", "PLC-A — Demo")]
    window = controller.window
    window.show_page("home")
    window.home.controllers.refresh()
    window.home.controllers.findChild(QToolButton).click()
    assert window.current_page == "logreader"
    assert probes == ["plc-a"]
    assert len(page.tabs) == 2


def test_two_tabs_fit_side_by_side(ui):
    _controller, page, _probes = ui
    tab = page.new_tab(_ipc("PLC-A"))
    assert _wait(lambda: tab.model.rowCount() == 11)
    # Deux onglets côte à côte doivent tenir dans une fenêtre de 1366 px de large.
    assert tab.minimumSizeHint().width() <= 620
    tab.period_button.setChecked(True)  # barre de période affichée : toujours dans la limite
    assert tab.minimumSizeHint().width() <= 620
    tab.filter_bar.resize(500, tab.filter_bar.height())
    assert not tab.filter_bar.wide  # les niveaux passent à la ligne
    tab.filter_bar.resize(1400, tab.filter_bar.height())
    assert tab.filter_bar.wide


def test_live_theme_change_keeps_application_style_on_tabs(ui):
    controller, page, _probes = ui
    page.new_tab(_ipc("PLC-A"))
    controller.context.theme.set_theme("dark")
    _wait(lambda: False, 0.3)
    assert page.dock_manager.styleSheet() == ""  # le style par défaut de QtAds est retiré
    controller.context.theme.set_theme("light")
