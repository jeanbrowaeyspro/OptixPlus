"""Catégorie « Statistics » de la fenêtre Paramètres : noms des pages Travail et Supervision."""

from __future__ import annotations

import json

import pytest

from optixplus.common.i18n import tr
from optixplus.modules.statistics.core.config import StatisticsSettings
from optixplus.modules.statistics.core.model import StatisticsOptions
from optixplus.modules.statistics.ui.settings_page import clean_names


@pytest.fixture
def form(controller):
    """(contrôleur, boîte Paramètres, page de la catégorie Statistics)."""
    controller.show_main_window()
    controller.open_settings("statistics")
    dialog = controller._settings_dialog
    yield controller, dialog, dialog.tool_page("statistics")
    dialog.close()


def _set(editor, texts: list[str]) -> None:
    """Remplace la liste comme le ferait une saisie (déclenche la détection de modification)."""
    editor.set_names(texts)
    editor.changed.emit()


def _section(controller) -> StatisticsSettings:
    return controller.context.settings.section(StatisticsSettings)


def test_clean_names_ignores_empty_and_duplicates():
    assert clean_names([" Work ", "", "work", "Travail ", "  "]) == ["Work", "Travail"]


def test_category_exists_and_shows_the_default_names(form):
    _controller, dialog, page = form
    assert dialog._categories.currentItem().text() == tr("Statistics")
    assert page.work.names() == ["Work", "Travail"]
    assert page.supervision.names() == ["Supervision", "Overwatch"]
    assert not page.has_unsaved_changes()


def test_names_are_applied_saved_and_read_back(form):
    controller, dialog, page = form
    page.work.add_button.click()  # nouvelle ligne en cours de saisie
    assert page.work.list.count() == 3 and page.has_unsaved_changes()
    _set(page.work, ["Work", "Travail", "  Atelier "])
    _set(page.supervision, ["Overwatch", "", "overwatch", "Pupitre"])
    assert page.has_unsaved_changes()
    assert _section(controller).work_names == ["Work", "Travail"]  # rien d'appliqué à la saisie
    assert dialog._apply()
    section = _section(controller)
    assert section.work_names == ["Work", "Travail", "Atelier"]
    assert section.supervision_names == ["Overwatch", "Pupitre"]  # vides et doublons ignorés
    assert not page.has_unsaved_changes()
    assert page.supervision.texts() == ["Overwatch", "Pupitre"]  # valeurs normalisées réaffichées
    saved = json.loads(controller.context.settings.path.read_text(encoding="utf-8"))["statistics"]
    assert saved["work_names"] == ["Work", "Travail", "Atelier"]
    assert section.options() == StatisticsOptions(("Work", "Travail", "Atelier"), ("Overwatch", "Pupitre"))


def test_empty_list_blocks_apply_with_a_message(form, message_boxes):
    controller, dialog, page = form
    _set(page.supervision, ["", "  "])
    assert page.validate()
    assert not dialog._apply()
    assert message_boxes.of("warning")
    assert _section(controller).supervision_names == ["Supervision", "Overwatch"]


def test_cancel_keeps_the_settings(form):
    controller, dialog, page = form
    _set(page.work, ["Atelier"])
    dialog.reject()
    assert _section(controller).work_names == ["Work", "Travail"]
    controller.open_settings("statistics")
    assert controller._settings_dialog.tool_page("statistics").work.names() == ["Work", "Travail"]


def test_restore_defaults_fills_the_form_without_applying(form):
    controller, dialog, page = form
    _set(page.work, ["Atelier"])
    assert dialog._apply()
    page.defaults_button.click()
    assert page.work.names() == ["Work", "Travail"] and page.supervision.names() == ["Supervision", "Overwatch"]
    assert page.has_unsaved_changes()
    assert _section(controller).work_names == ["Atelier"]  # appliqué seulement par OK / Appliquer
    assert dialog._apply()
    assert _section(controller).work_names == ["Work", "Travail"]


def test_language_change_keeps_the_unsaved_form(form):
    controller, dialog, page = form
    _set(page.work, ["Atelier", "Shop"])
    page.work.list.setCurrentRow(1)
    state = dialog.snapshot()
    dialog.close()
    controller.context.settings.general.language = "en"
    controller.change_language(settings_state=state)
    new_page = controller._settings_dialog.tool_page("statistics")
    assert new_page is not page
    assert new_page.work.texts() == ["Atelier", "Shop"]
    assert new_page.work.list.currentRow() == 1
    assert new_page.has_unsaved_changes()
    assert _section(controller).work_names == ["Work", "Travail"]  # non enregistré
    assert controller._settings_dialog._categories.currentItem().text() == "Statistics"
    controller._settings_dialog.close()
