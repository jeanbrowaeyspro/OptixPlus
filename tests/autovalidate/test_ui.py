"""Validation auto dans OptixPlus : réglages de la surveillance dans la boîte Paramètres."""

from __future__ import annotations

from optixplus.modules.autovalidate.core.config import AutoValidateSettings


def test_monitoring_settings_live_in_the_settings_window(controller):
    """Réglages de Validation auto : catégorie de la boîte Paramètres, appliqués par « Appliquer »."""
    window = controller.show_main_window()
    window.show_page("autovalidate")
    module = window.module("autovalidate")
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
