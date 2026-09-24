"""Version portable : toujours en mode découverte, signalée dans l'À propos et sur la surveillance."""

from __future__ import annotations

import pytest

from optixplus import app, version
from optixplus.common import i18n, logging_setup
from optixplus.common.settings import Settings
from optixplus.common.theme import install_manager
from optixplus.shell.context import LaunchMode
from optixplus.shell.controller import AppController


@pytest.mark.parametrize("argv", [[], ["--installe"], ["--decouverte"]])
def test_portable_build_always_runs_in_discovery_mode(monkeypatch, argv):
    monkeypatch.setattr(app, "is_portable", lambda: True)
    assert app.detect_mode(app.parse_args(argv)) is LaunchMode.DISCOVERY


def test_build_marker(monkeypatch, tmp_path):
    import sys
    import types

    monkeypatch.setitem(sys.modules, "optixplus._build_info", types.SimpleNamespace(BUILD_DATE="2026-09-24", PORTABLE=True))
    assert version.is_portable() and version.build_date() == "2026-09-24"
    monkeypatch.setitem(sys.modules, "optixplus._build_info", types.SimpleNamespace(BUILD_DATE="2026-09-24", PORTABLE=False))
    assert not version.is_portable()


def test_discovery_mode_is_explained(qapp, tmp_path, monkeypatch):
    from optixplus.shell import about_dialog

    monkeypatch.setattr(about_dialog, "is_portable", lambda: True)
    i18n.install("fr")
    logging_setup.configure(to_file=False)
    controller = AppController(qapp, Settings.load(tmp_path / "s.json"), install_manager(qapp, "light"), LaunchMode.DISCOVERY)
    try:
        assert controller.tray is None
        window = controller.show_main_window()
        window.show_page("autovalidate")
        page = window.module("autovalidate").page
        from PySide6.QtWidgets import QLabel

        assert any("Mode découverte" in label.text() for label in page.findChildren(QLabel))
        assert not controller.context.services["autovalidate"].enabled  # surveillance suspendue au départ
        controller.open_about()
        assert any("Version portable" in label.text() for label in controller._about_dialog.findChildren(QLabel))
    finally:
        if controller._about_dialog is not None:
            controller._about_dialog.close()
        if controller.window is not None:
            controller.window.close()
        i18n.install("en")
