"""Coquille : fenêtre principale, navigation, chargement à la demande, thème, fermeture."""

from __future__ import annotations

import pytest

from optixplus.common import i18n, logging_setup
from optixplus.common.settings import Settings
from optixplus.common.theme import install_manager
from optixplus.modules import MODULES
from optixplus.shell.context import LaunchMode
from optixplus.shell.controller import AppController


@pytest.fixture
def controller(qapp, tmp_path):
    i18n.install("fr")
    logging_setup.configure(to_file=False)
    settings = Settings.load(tmp_path / "settings.json")
    theme = install_manager(qapp, "light")
    ctrl = AppController(qapp, settings, theme, LaunchMode.INSTALLED)
    yield ctrl
    if ctrl.window is not None:
        ctrl.window.close()
    i18n.install("en")


def test_window_opens_on_home(controller):
    window = controller.show_main_window()
    assert window.current_page == "home"
    assert window.windowTitle() == "OptixPlus"
    assert not window.grab().isNull()


def test_modules_are_loaded_on_demand(controller):
    window = controller.show_main_window()
    assert window.module("compare") is None
    for module in MODULES:
        window.show_page(module.id)
        assert window.current_page == module.id
        assert window.module(module.id) is not None
    assert window.windowTitle().endswith("— OptixPlus")


def test_command_from_second_launch(controller):
    controller.handle_message(["open-tool", "linkcheck"])
    assert controller.window.current_page == "linkcheck"


def test_theme_switch_redraws(controller):
    window = controller.show_main_window()
    controller.context.theme.set_theme("dark")
    assert controller.context.theme.palette.dark
    assert not window.grab().isNull()
    controller.context.theme.set_theme("light")


def test_close_saves_layout_and_last_tool(controller):
    window = controller.show_main_window()
    window.show_page("compare")
    window.close()
    general = controller.context.settings.general
    assert general.last_tool == "compare"
    assert general.window_geometry
    reopened = controller.show_main_window()
    assert reopened.current_page == "compare"


def test_old_saved_layout_does_not_bring_back_window_toolbar(controller):
    """Une disposition enregistrée par une version précédente (barre d'outils au niveau de la
    fenêtre) ne doit pas recréer de bande vide sous les menus."""
    from PySide6.QtWidgets import QMainWindow, QToolBar

    old = QMainWindow()
    bar = QToolBar(old)
    bar.setObjectName("contextToolbar")
    old.addToolBar(bar)
    state = bytes(old.saveState().toBase64().data()).decode("ascii")
    old.deleteLater()

    controller.context.settings.general.window_state = state
    window = controller.show_main_window()
    window.show_page("autovalidate")
    toolbar = window.findChild(QToolBar, "toolPageActions")
    assert toolbar is not None
    assert window.toolBarArea(toolbar).name == "NoToolBarArea"  # reste dans la zone de l'outil
    assert all(window.toolBarArea(t).name == "NoToolBarArea" for t in window.findChildren(QToolBar))


def test_language_switch_is_live(controller):
    """Le changement de langue reconstruit la fenêtre dans la nouvelle langue, sur le même outil."""
    window = controller.show_main_window()
    window.show_page("autovalidate")
    assert window.windowTitle() == "Validation auto — OptixPlus"
    controller.context.settings.general.language = "en"
    controller.change_language()
    rebuilt = controller.window
    assert rebuilt is not None and rebuilt is not window
    assert rebuilt.current_page == "autovalidate"
    assert rebuilt.windowTitle() == "Auto Validate — OptixPlus"
    assert [a.text() for a in rebuilt.menuBar().actions()][0] == "&File"
    controller.context.settings.general.language = "fr"
    controller.change_language()
    assert [a.text() for a in controller.window.menuBar().actions()][0] == "&Fichier"


def test_settings_dialog_reopens_after_language_change(controller):
    """Changer la langue depuis les Paramètres rouvre la boîte, traduite, sur la fenêtre reconstruite."""
    from PySide6.QtWidgets import QDialog

    controller.show_main_window()
    controller.context.settings.general.language = "en"
    controller.change_language(reopen_settings=True)
    dialogs = [d for d in controller.window.findChildren(QDialog) if d.isVisible()]
    assert [d.windowTitle() for d in dialogs] == ["Settings"]
    dialogs[0].close()
    controller.context.settings.general.language = "fr"
    controller.change_language()
