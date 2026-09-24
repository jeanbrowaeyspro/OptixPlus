"""Fermeture de la fenêtre en mode installé : reste dans le tray seulement si la surveillance tourne."""

from __future__ import annotations

import pytest

from optixplus.common import i18n, logging_setup
from optixplus.common.settings import Settings
from optixplus.common.theme import install_manager
from optixplus.shell.context import LaunchMode
from optixplus.shell.controller import AppController


@pytest.fixture
def installed(qapp, tmp_path, monkeypatch):
    from optixplus.shell.tray import TrayIcon

    i18n.install("fr")
    logging_setup.configure(to_file=False)
    controller = AppController(qapp, Settings.load(tmp_path / "s.json"), install_manager(qapp, "light"), LaunchMode.INSTALLED)
    if controller.tray is None:  # rendu hors écran : pas de zone de notification, on en crée une
        controller.tray = TrayIcon(controller, controller)
    quits, notices = [], []
    monkeypatch.setattr(controller, "quit", lambda: quits.append(True))
    monkeypatch.setattr(controller.tray, "notify", lambda message, title="", msecs=0, on_click=None: notices.append((title, message)))
    service = controller.context.services["autovalidate"]
    yield controller, service, quits, notices, monkeypatch
    controller.tray.hide()
    i18n.install("en")


def test_active_monitoring_keeps_running_and_says_so(installed):
    controller, service, quits, notices, monkeypatch = installed
    monkeypatch.setattr(type(service), "suspended", property(lambda s: False))
    controller.show_main_window().close()
    assert quits == []
    assert len(notices) == 1
    title, message = notices[0]
    assert title == "OptixPlus reste actif"
    assert "Le projet existe déjà" in message and "Quitter" in message


def test_suspended_monitoring_quits_completely(installed):
    controller, service, quits, notices, monkeypatch = installed
    monkeypatch.setattr(type(service), "suspended", property(lambda s: True))
    controller.show_main_window().close()
    assert quits == [True]
    assert notices == []
