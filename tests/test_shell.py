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
def controller(qapp, tmp_path, monkeypatch):
    # Hors écran, personne ne peut répondre à une boîte modale : on répond « Oui ».
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
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
    controller.change_language(settings_state={})
    dialogs = [d for d in controller.window.findChildren(QDialog) if d.isVisible()]
    assert [d.windowTitle() for d in dialogs] == ["Settings"]
    dialogs[0].close()
    controller.context.settings.general.language = "fr"
    controller.change_language()


def test_language_change_restores_everything_as_it_was(controller):
    from PySide6.QtWidgets import QDialog

    """Après un changement de langue : mêmes outils ouverts, même page, saisies non enregistrées
    conservées (sans demande de confirmation), mêmes boîtes de dialogue ouvertes."""
    window = controller.show_main_window()
    window.show_page("linkcheck")
    window.show_page("autovalidate")
    window.show_page("compare")
    controller.open_about()
    controller.open_settings("autovalidate")
    form = controller._settings_dialog.tool_page("autovalidate")
    form.process.setText("AutreStudio.exe")
    form._mark_dirty()
    form.retries.setValue(7)
    settings_state = controller._settings_dialog.snapshot()
    controller._settings_dialog.close()

    controller.context.settings.general.language = "en"
    controller.change_language(settings_state=settings_state)

    rebuilt = controller.window
    assert rebuilt is not window
    assert rebuilt.current_page == "compare"
    assert {"linkcheck", "autovalidate", "compare"} <= set(rebuilt._modules)
    new_form = controller._settings_dialog.tool_page("autovalidate")
    assert new_form is not form
    assert controller._settings_dialog._categories.currentItem().text() == "Auto Validate"
    assert new_form.process.text() == "AutreStudio.exe"
    assert new_form.retries.value() == 7
    assert new_form.has_unsaved_changes()
    # Rien n'a été enregistré : la saisie n'est que conservée à l'écran.
    from optixplus.modules.autovalidate.core.config import AutoValidateSettings

    assert controller.context.settings.section(AutoValidateSettings).process_name == "FTOptixStudio.exe"
    titles = sorted(d.windowTitle() for d in rebuilt.findChildren(QDialog) if d.isVisible())
    assert titles == ["About OptixPlus", "Settings"]
    for dialog in rebuilt.findChildren(QDialog):
        dialog.close()
    controller.context.settings.general.language = "fr"
    controller.change_language()


def test_monitoring_settings_live_in_the_settings_window(controller):
    """Réglages de Validation auto : catégorie de la boîte Paramètres, appliqués par « Appliquer »."""
    from optixplus.modules.autovalidate.core.config import AutoValidateSettings

    window = controller.show_main_window()
    window.show_page("autovalidate")
    module = window.module("autovalidate")
    assert not hasattr(module.page, "process")  # plus de formulaire sur la page
    settings_action = next(a for a in module.toolbar_actions() if a is not None and a.text() == "Paramètres de la surveillance…")
    settings_action.trigger()
    dialog = controller._settings_dialog
    assert dialog._categories.currentItem().text() == "Validation auto"
    form = dialog.tool_page("autovalidate")
    form.process.setText("AutreStudio.exe")
    form._mark_dirty()
    assert controller.context.settings.section(AutoValidateSettings).process_name == "FTOptixStudio.exe"
    dialog._apply()
    assert controller.context.services["autovalidate"].settings.process_name == "AutreStudio.exe"
    assert not form.has_unsaved_changes()
    dialog.close()


def test_tool_shortcuts_work_as_soon_as_the_tool_is_shown(controller, qapp, monkeypatch):
    """F5 (Analyser) répond dès l'affichage de l'outil, sans cliquer d'abord dans sa page."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMessageBox

    # Sans projet, Analyser avertit « dossier à saisir » : boîte modale, sans personne pour répondre.
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))

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


def test_theme_change_after_startup_recolours_without_error(controller, qapp, monkeypatch):
    """Changer de thème une fois la fenêtre installée : aucune erreur, toutes les icônes suivent."""
    import sys

    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *exc: errors.append(exc))
    window = controller.show_main_window()
    window.show_page("linkcheck")
    qapp.processEvents()
    controller.context.theme.set_theme("dark")
    qapp.processEvents()
    assert errors == []


def test_vertical_scrollbars_start_below_column_headers(controller, qapp):
    """Ascenseur vertical d'un tableau ou d'un arbre : sa poignée commence sous l'en-tête."""
    from PySide6.QtGui import QStandardItemModel
    from PySide6.QtWidgets import QStyle, QStyleOptionSlider, QTableView, QTreeView

    from optixplus.common.widgets import scrollbar_below_header

    model = QStandardItemModel(200, 3)
    for view in (QTableView(), QTreeView()):
        scrollbar_below_header(view)
        view.setModel(model)
        view.resize(400, 200)
        view.show()
        qapp.processEvents()
        header = view.horizontalHeader() if isinstance(view, QTableView) else view.header()
        bar = view.verticalScrollBar()
        bar.setValue(0)
        option = QStyleOptionSlider()
        bar.initStyleOption(option)
        handle = bar.style().subControlRect(QStyle.ComplexControl.CC_ScrollBar, option, QStyle.SubControl.SC_ScrollBarSlider, bar)
        top = bar.mapTo(view, handle.topLeft()).y()
        assert top >= header.mapTo(view, header.rect().topLeft()).y() + header.height()
        view.close()


def test_every_tool_table_has_its_scrollbar_below_the_header(controller):
    """Tous les tableaux et arbres des outils (en-tête visible) sont concernés."""
    from PySide6.QtWidgets import QTableView, QTreeView

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
