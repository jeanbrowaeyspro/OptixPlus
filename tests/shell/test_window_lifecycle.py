"""Cycle de vie de la fenêtre : disposition enregistrée à la fermeture, tray, version portable.

En mode installé, la fermeture laisse OptixPlus dans le tray seulement si la surveillance
tourne. La version portable tourne toujours en mode découverte, signalé dans l'À propos et
sur la surveillance.
"""

from __future__ import annotations

import sys
import types

import pytest
from PySide6.QtWidgets import QLabel

from optixplus import app, version
from optixplus.shell.context import LaunchMode


def test_close_saves_layout_and_last_tool(controller):
    window = controller.show_main_window()
    window.show_page("compare")
    window.close()
    general = controller.context.settings.general
    assert general.last_tool == "compare"
    assert general.window_geometry
    reopened = controller.show_main_window()
    assert reopened.current_page == "compare"


# --------------------------------------------------------------------------- tray (mode installé)
@pytest.fixture
def installed(controller, monkeypatch):
    """Contrôleur installé avec une zone de notification, fermeture et bulles relevées."""
    from optixplus.shell.tray import TrayIcon

    if controller.tray is None:  # rendu hors écran : pas de zone de notification, on en crée une
        controller.tray = TrayIcon(controller, controller)
    quits, notices = [], []
    monkeypatch.setattr(controller, "quit", lambda: quits.append(True))
    monkeypatch.setattr(controller.tray, "notify", lambda message, title="", msecs=0, on_click=None: notices.append((title, message)))
    service = controller.context.services["autovalidate"]
    yield controller, service, quits, notices
    controller.tray.hide()


def _monitoring(monkeypatch, service, state: dict) -> None:
    monkeypatch.setattr(type(service), "suspended", property(lambda s: state["suspended"]))


def test_active_monitoring_keeps_running_and_says_so(installed, monkeypatch):
    controller, service, quits, notices = installed
    _monitoring(monkeypatch, service, {"suspended": False})
    controller.show_main_window().close()
    assert quits == []
    assert len(notices) == 1
    title, message = notices[0]
    assert title == "OptixPlus reste actif"
    assert "Le projet existe déjà" in message and "Quitter" in message


def test_suspended_monitoring_quits_completely(installed, monkeypatch):
    controller, service, quits, notices = installed
    _monitoring(monkeypatch, service, {"suspended": True})
    controller.show_main_window().close()
    assert quits == [True]
    assert notices == []


def test_suspending_monitoring_from_the_tray_does_not_quit(installed, monkeypatch):
    """Fenêtre déjà fermée, OptixPlus dans le tray : suspendre la surveillance ne le ferme pas."""
    controller, service, quits, _notices = installed
    state = {"suspended": False}
    _monitoring(monkeypatch, service, state)
    controller.show_main_window().close()
    assert quits == []
    state["suspended"] = True
    service.state_changed.emit()  # ce que fait la bascule du menu du tray
    assert quits == []


# --------------------------------------------------------------------------- version portable
@pytest.mark.parametrize("argv", [[], ["--installe"], ["--decouverte"]])
def test_portable_build_always_runs_in_discovery_mode(monkeypatch, argv):
    monkeypatch.setattr(app, "is_portable", lambda: True)
    assert app.detect_mode(app.parse_args(argv)) is LaunchMode.DISCOVERY


def test_build_marker(monkeypatch):
    monkeypatch.setitem(sys.modules, "optixplus._build_info", types.SimpleNamespace(BUILD_DATE="2026-09-24", PORTABLE=True))
    assert version.is_portable() and version.build_date() == "2026-09-24"
    monkeypatch.setitem(sys.modules, "optixplus._build_info", types.SimpleNamespace(BUILD_DATE="2026-09-24", PORTABLE=False))
    assert not version.is_portable()


def test_discovery_mode_is_explained(make_controller, monkeypatch):
    from optixplus.shell import about_dialog

    monkeypatch.setattr(about_dialog, "is_portable", lambda: True)
    controller = make_controller(mode=LaunchMode.DISCOVERY)
    window = controller.show_main_window()
    window.show_page("autovalidate")
    page = window.module("autovalidate").page
    assert any("Mode découverte" in label.text() for label in page.findChildren(QLabel))
    controller.open_about()
    assert any("Version portable" in label.text() for label in controller._about_dialog.findChildren(QLabel))


def test_close_notice_can_be_turned_off(installed, monkeypatch):
    """Case décochée dans les Paramètres : OptixPlus reste actif, mais sans bulle."""
    controller, service, quits, notices = installed
    _monitoring(monkeypatch, service, {"suspended": False})
    controller.context.settings.general.notify_on_close = False
    controller.show_main_window().close()
    assert quits == [] and notices == []


def test_message_options_are_in_general_settings_and_checked_by_default(controller):
    general = controller.context.settings.general
    assert general.notify_on_close and general.warn_elevated_capture
    controller.show_main_window()
    controller.open_settings()
    page = controller._settings_dialog._general
    assert page.close_notice.isChecked() and page.capture_notice.isChecked()
    page.close_notice.setChecked(False)
    page.capture_notice.setChecked(False)
    controller._settings_dialog._apply()
    assert not general.notify_on_close and not general.warn_elevated_capture
    controller._settings_dialog.close()
