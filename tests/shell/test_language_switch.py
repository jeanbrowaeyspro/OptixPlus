"""Changement de langue à chaud : la fenêtre est reconstruite et tout est rouvert en l'état."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog

from fakes import release
from optixplus.modules.autovalidate.core.config import AutoValidateSettings
from support import wait_until


def _menu_titles(window) -> list[str]:
    return [a.text() for a in window.menuBar().actions()]


def test_language_change_restores_everything_as_it_was(controller):
    """Après un changement de langue : fenêtre traduite, mêmes outils ouverts, même page, saisies
    non enregistrées conservées (sans demande de confirmation), mêmes boîtes de dialogue ouvertes."""
    window = controller.show_main_window()
    window.show_page("linkcheck")
    window.show_page("autovalidate")
    window.show_page("compare")
    assert window.windowTitle() == "Comparaison — OptixPlus"
    assert _menu_titles(window)[0] == "&Fichier"
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
    assert rebuilt is not None and rebuilt is not window
    assert rebuilt.current_page == "compare"
    assert rebuilt.windowTitle() == "Compare — OptixPlus"
    assert _menu_titles(rebuilt)[0] == "&File"
    assert {"linkcheck", "autovalidate", "compare"} <= set(rebuilt._modules)
    new_form = controller._settings_dialog.tool_page("autovalidate")
    assert new_form is not form
    assert controller._settings_dialog._categories.currentItem().text() == "Auto Validate"
    assert new_form.process.text() == "AutreStudio.exe"
    assert new_form.retries.value() == 7
    assert new_form.has_unsaved_changes()
    # Rien n'a été enregistré : la saisie n'est que conservée à l'écran.
    assert controller.context.settings.section(AutoValidateSettings).process_name == "FTOptixStudio.exe"
    titles = sorted(d.windowTitle() for d in rebuilt.findChildren(QDialog) if d.isVisible())
    assert titles == ["About OptixPlus", "Settings"]


def test_language_change_reopens_news_and_update_dialogs(controller, monkeypatch):
    from optixplus.shell import updates

    monkeypatch.setattr(updates, "available_update", lambda current, include, skipped: release())
    controller.show_main_window()
    controller.open_whats_new(full=True)
    controller.check_for_updates()
    assert wait_until(lambda: controller.updates.dialog is not None)
    controller.context.settings.general.language = "en"
    controller.change_language()
    assert wait_until(lambda: controller._changelog_dialog is not None and controller._changelog_dialog.isVisible())
    assert controller._changelog_dialog.full_history.isChecked()
    assert controller._changelog_dialog.windowTitle() == "What's new in OptixPlus"
    assert controller.updates.dialog is not None and controller.updates.dialog.windowTitle() == "Update available"
