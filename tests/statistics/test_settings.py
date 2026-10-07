"""Catégorie « Statistics » de la fenêtre Paramètres : pages à mettre en évidence (mots-clés)."""

from __future__ import annotations

import json

import pytest

from optixplus.common.i18n import tr
from optixplus.common.settings import section_from_dict
from optixplus.modules.statistics.core.config import StatisticsSettings, normalise_entries, parse_keywords
from optixplus.modules.statistics.core.model import StatisticsOptions


@pytest.fixture
def form(controller):
    """(contrôleur, boîte Paramètres, page de la catégorie Statistics)."""
    controller.show_main_window()
    controller.open_settings("statistics")
    dialog = controller._settings_dialog
    yield controller, dialog, dialog.tool_page("statistics")
    dialog.close()


def _set(page, texts: list[str]) -> None:
    """Remplace la liste comme le ferait une saisie (déclenche la détection de modification)."""
    page.entries.set_names(texts)
    page.entries.changed.emit()


def _section(controller) -> StatisticsSettings:
    return controller.context.settings.section(StatisticsSettings)


def test_keywords_ignore_empty_and_duplicates():
    assert parse_keywords(" Alpha ,, alpha, Beta ,") == ("Alpha", "Beta")
    assert normalise_entries(["Alpha, Beta", "", " , ", "beta,ALPHA", "alpha, beta"]) == ["Alpha, Beta", "beta, ALPHA"]


def test_list_is_empty_by_default(form):
    controller, dialog, page = form
    assert dialog._categories.currentItem().text() == tr("Statistics")
    assert page.entries.texts() == [] and not page.has_unsaved_changes()
    assert _section(controller).highlighted == []
    assert _section(controller).options() == StatisticsOptions()


def test_add_and_remove_entries(form):
    _controller, _dialog, page = form
    page.entries.add_button.click()
    assert page.entries.list.count() == 1 and page.has_unsaved_changes()
    page.entries.list.setCurrentRow(0)
    page.entries.remove_button.click()
    assert page.entries.list.count() == 0


def test_entries_are_applied_saved_and_read_back(form):
    controller, dialog, page = form
    _set(page, ["  Alpha ,, Beta ", "Gamma", "gamma"])
    assert _section(controller).highlighted == []  # rien d'appliqué à la saisie
    assert dialog._apply()
    section = _section(controller)
    assert section.highlighted == ["Alpha, Beta", "Gamma"]  # vides et doublons ignorés
    assert page.entries.texts() == ["Alpha, Beta", "Gamma"] and not page.has_unsaved_changes()
    saved = json.loads(controller.context.settings.path.read_text(encoding="utf-8"))["statistics"]
    assert saved == {"highlighted": ["Alpha, Beta", "Gamma"]}
    assert section.options() == StatisticsOptions((("Alpha", "Beta"), ("Gamma",)))


def test_entry_without_keyword_blocks_apply_with_a_message(form, message_boxes):
    controller, dialog, page = form
    _set(page, ["Alpha", " , "])
    assert page.validate()
    assert not dialog._apply()
    assert message_boxes.of("warning")
    assert _section(controller).highlighted == []


def test_cancel_keeps_the_settings(form):
    controller, dialog, page = form
    _set(page, ["Alpha"])
    dialog.reject()
    assert _section(controller).highlighted == []
    controller.open_settings("statistics")
    assert controller._settings_dialog.tool_page("statistics").entries.texts() == []


def test_old_keys_are_ignored_and_dropped_on_save(controller):
    section = section_from_dict(
        StatisticsSettings, {"work_names": ["x"], "supervision_names": ["y"], "highlighted": ["Alpha"]}
    )
    assert section.options() == StatisticsOptions((("Alpha",),))
    controller.context.settings._raw["statistics"] = {"work_names": ["x"], "supervision_names": None}
    controller.context.settings.section(StatisticsSettings)
    controller.context.settings.save()
    saved = json.loads(controller.context.settings.path.read_text(encoding="utf-8"))["statistics"]
    assert saved == {"highlighted": []}


def test_invalid_value_falls_back_to_empty_list():
    assert section_from_dict(StatisticsSettings, {"highlighted": "texte"}).options() == StatisticsOptions()
    assert StatisticsSettings(highlighted=[3, None, "Alpha"]).options() == StatisticsOptions((("Alpha",),))


def test_language_change_keeps_the_unsaved_form(form):
    controller, dialog, page = form
    _set(page, ["Alpha", "Beta, Gamma"])
    page.entries.list.setCurrentRow(1)
    state = dialog.snapshot()
    dialog.close()
    controller.context.settings.general.language = "en"
    controller.change_language(settings_state=state)
    new_page = controller._settings_dialog.tool_page("statistics")
    assert new_page is not page
    assert new_page.entries.texts() == ["Alpha", "Beta, Gamma"]
    assert new_page.entries.list.currentRow() == 1
    assert new_page.has_unsaved_changes()
    assert _section(controller).highlighted == []  # non enregistré
    assert controller._settings_dialog._categories.currentItem().text() == "Statistics"
    controller._settings_dialog.close()
