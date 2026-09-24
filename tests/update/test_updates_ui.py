"""Mises à jour dans l'interface : vérification, version ignorée, réglages, Nouveautés."""

from __future__ import annotations

import json

from PySide6.QtCore import QCoreApplication

from fakes import release
from optixplus.update.github import UpdateError, Version
from support import wait_until


def _answer(monkeypatch, result):
    """La vérification répond ``result`` (publication, None ou erreur levée)."""
    from optixplus.shell import updates

    def fake(current, include, skipped):
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(updates, "available_update", fake)


def test_manual_check_offers_the_release(controller, monkeypatch):
    _answer(monkeypatch, release())
    controller.show_main_window()
    controller.check_for_updates()
    assert wait_until(lambda: controller.updates.dialog is not None)
    dialog = controller.updates.dialog
    assert dialog.release.version == Version.parse("1.2.0")
    # Depuis les sources, pas d'installation automatique : lien vers la page de téléchargement.
    assert dialog.install_button.text() == "Ouvrir la page de téléchargement"
    assert controller.updates.settings.last_check


def test_skip_this_version_is_remembered(controller, monkeypatch):
    _answer(monkeypatch, release())
    controller.check_for_updates()
    assert wait_until(lambda: controller.updates.dialog is not None)
    controller.updates.dialog.skip_button.click()
    assert controller.updates.settings.skipped_version == "1.2.0"
    assert json.loads(controller.context.settings.path.read_text(encoding="utf-8"))["updates"]["skipped_version"] == "1.2.0"


def test_manual_check_says_when_up_to_date_or_failed(controller, message_boxes, monkeypatch):
    _answer(monkeypatch, None)
    controller.check_for_updates()
    assert wait_until(lambda: message_boxes.shown)
    kind, text = message_boxes.shown[-1]
    assert kind == "information" and "à jour" in text
    _answer(monkeypatch, UpdateError("GitHub est injoignable : test"))
    controller.check_for_updates()
    assert wait_until(lambda: len(message_boxes.shown) == 2)
    kind, text = message_boxes.shown[-1]
    assert kind == "warning" and "injoignable" in text


def test_automatic_check_is_silent_without_news(controller, message_boxes, monkeypatch):
    _answer(monkeypatch, None)
    controller.updates.check(interactive=False)
    assert wait_until(lambda: not controller.updates.busy)
    QCoreApplication.processEvents()
    assert message_boxes.shown == []


def test_download_page_opens_outside_the_installed_exe(controller, monkeypatch):
    from optixplus.shell import updates

    opened = []
    monkeypatch.setattr(updates.QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url.toString())))
    controller.updates.install(release())
    assert opened == ["https://github.com/x/releases/v1.2.0"]


def test_settings_page_saves_update_choices(controller):
    controller.show_main_window()
    controller.open_settings()
    page = controller._settings_dialog._general
    assert page.auto_update.isChecked() and page.frequency.currentData() == "daily"
    page.frequency.setCurrentIndex(page.frequency.findData("weekly"))
    page.prereleases.setChecked(True)
    controller._settings_dialog._apply()
    saved = json.loads(controller.context.settings.path.read_text(encoding="utf-8"))["updates"]
    assert saved["frequency"] == "weekly" and saved["include_prereleases"] is True
    assert page.last_check.text() == "jamais"


def test_whats_new_on_first_launch_of_a_version(controller):
    from optixplus.version import __version__

    controller.context.settings.general.last_seen_version = "0.0.1"
    controller.whats_new_pending = True
    controller.show_main_window()
    assert wait_until(lambda: controller._changelog_dialog is not None)
    assert controller.context.settings.general.last_seen_version == __version__
    assert controller._changelog_dialog.browser.toPlainText().strip()
