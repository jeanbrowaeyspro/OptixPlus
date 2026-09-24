"""Coquille : fenêtre principale, navigation, chargement à la demande, thème, raccourcis."""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMainWindow, QTableView, QToolBar, QTreeView

from optixplus.modules import MODULES


def test_window_opens_on_home(controller):
    window = controller.show_main_window()
    assert window.current_page == "home"
    assert window.windowTitle() == "OptixPlus"


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


def test_theme_change_after_startup_recolours_without_error(controller, qapp, monkeypatch):
    """Changer de thème une fois la fenêtre installée : aucune erreur, toutes les icônes suivent."""
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *exc: errors.append(exc))
    window = controller.show_main_window()
    window.show_page("linkcheck")
    qapp.processEvents()
    controller.context.theme.set_theme("dark")
    qapp.processEvents()
    assert controller.context.theme.palette.dark
    assert errors == []


def test_old_saved_layout_does_not_bring_back_window_toolbar(controller):
    """Une disposition enregistrée par une version précédente (barre d'outils au niveau de la
    fenêtre) ne doit pas recréer de bande vide sous les menus."""
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


def test_tool_shortcuts_work_as_soon_as_the_tool_is_shown(controller, qapp):
    """F5 (Analyser) répond dès l'affichage de l'outil, sans cliquer d'abord dans sa page."""
    window = controller.show_main_window()
    window.activateWindow()
    window.sidebar.setFocus()
    window.show_page("linkcheck")
    qapp.processEvents()
    page = window.module("linkcheck").page
    assert page.isAncestorOf(qapp.focusWidget())
    triggered = []
    page.act_analyse.triggered.connect(lambda: triggered.append(True))
    page.act_analyse.setEnabled(True)
    QTest.keyClick(qapp.focusWidget(), Qt.Key.Key_F5)
    assert triggered


def test_every_tool_table_has_its_scrollbar_below_the_header(controller):
    """Tous les tableaux et arbres des outils (en-tête visible) sont concernés."""
    window = controller.show_main_window()
    for spec in MODULES:
        window.show_page(spec.id)
    views = [
        v for v in window.findChildren(QTableView) + window.findChildren(QTreeView)
        if not (v.horizontalHeader() if isinstance(v, QTableView) else v.header()).isHidden()
        and type(v).__name__ != "QCalendarView"
    ]
    assert views
    unmarked = [f"{type(v).__name__} in {type(v.parent()).__name__}" for v in views if not v.verticalScrollBar().property("underHeader")]
    assert unmarked == []
