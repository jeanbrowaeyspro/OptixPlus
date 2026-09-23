"""Mises à jour : versions, API GitHub simulée, planification, téléchargement vérifié, Nouveautés."""

from __future__ import annotations

import hashlib
import io
import json
import time
import urllib.error
from datetime import datetime, timedelta, timezone

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QMessageBox

from optixplus.common import i18n, logging_setup
from optixplus.common.progress import Cancelled
from optixplus.common.settings import Settings
from optixplus.common.theme import install_manager
from optixplus.shell.context import LaunchMode
from optixplus.shell.controller import AppController
from optixplus.update import changelog, github, installer
from optixplus.update.github import Release, UpdateError, Version, is_check_due


# --------------------------------------------------------------------------- HTTP simulé
class _Response(io.BytesIO):
    def __init__(self, data: bytes, headers: dict | None = None) -> None:
        super().__init__(data)
        self.headers = headers or {}


class FakeGitHub:
    """Répond aux URL connues ; lève l'erreur prévue pour les autres."""

    def __init__(self, routes: dict[str, object]) -> None:
        self.routes = routes
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        answer = self.routes.get(request.full_url)
        if isinstance(answer, Exception):
            raise answer
        if answer is None:
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)
        data = answer if isinstance(answer, bytes) else json.dumps(answer).encode()
        return _Response(data, {"Content-Length": str(len(data))})


def _release_json(tag: str, prerelease: bool = False, draft: bool = False, assets: bool = True) -> dict:
    version = tag.lstrip("v")
    base = f"https://example.invalid/{version}"
    return {
        "tag_name": tag,
        "name": f"OptixPlus {version}",
        "body": f"## Nouveautés {version}",
        "html_url": f"https://github.com/x/releases/{tag}",
        "prerelease": prerelease,
        "draft": draft,
        "assets": [
            {"name": f"OptixPlus-Setup-{version}.exe", "browser_download_url": f"{base}/setup.exe", "size": 3},
            {"name": f"OptixPlus-Setup-{version}.exe.sha256", "browser_download_url": f"{base}/setup.sha256"},
        ] if assets else [],
    }


# --------------------------------------------------------------------------- versions
@pytest.mark.parametrize(
    ("older", "newer"),
    [
        ("1.0.0", "1.0.1"),
        ("1.0.9", "1.1.0"),
        ("1.9.0", "2.0.0"),
        ("1.0.0-beta.2", "1.0.0-beta.10"),
        ("1.0.0-beta.10", "1.0.0-rc.1"),
        ("1.0.0-rc.1", "1.0.0"),
        ("v0.9.0", "1.0.0"),
    ],
)
def test_semantic_version_order(older, newer):
    assert Version.parse(older) < Version.parse(newer)
    assert Version.parse(newer) > Version.parse(older)


def test_version_parsing():
    assert str(Version.parse("v1.2.3")) == "1.2.3"
    assert Version.parse("1.2.3-beta.1").is_prerelease
    assert Version.parse("1.2.3") == Version.parse("v1.2.3")
    with pytest.raises(ValueError):
        Version.parse("1.2")


# --------------------------------------------------------------------------- API GitHub
def test_latest_release_is_read_with_a_user_agent_only():
    fake = FakeGitHub({f"{github.API_URL}/latest": _release_json("v1.2.0")})
    release = github.latest_release(opener=fake)
    assert release.version == Version.parse("1.2.0")
    assert release.installable and release.installer.name == "OptixPlus-Setup-1.2.0.exe"
    request = fake.requests[0]
    assert request.get_header("User-agent").startswith("OptixPlus/")
    assert request.get_header("Authorization") is None


def test_prereleases_only_when_asked():
    listing = [_release_json("v1.2.0"), _release_json("v1.3.0-beta.1", prerelease=True), _release_json("v9.0.0", draft=True)]
    fake = FakeGitHub({f"{github.API_URL}/latest": _release_json("v1.2.0"), f"{github.API_URL}?per_page=20": listing})
    assert str(github.latest_release(False, fake).version) == "1.2.0"
    assert str(github.latest_release(True, fake).version) == "1.3.0-beta.1"  # le brouillon est ignoré


def test_available_update_rules():
    fake = FakeGitHub({f"{github.API_URL}/latest": _release_json("v1.2.0")})
    assert github.available_update("1.1.0", opener=fake).version == Version.parse("1.2.0")
    assert github.available_update("1.2.0", opener=fake) is None
    assert github.available_update("1.3.0", opener=fake) is None
    assert github.available_update("1.1.0", skipped="1.2.0", opener=fake) is None


def test_no_published_release_is_not_an_error():
    assert github.latest_release(opener=FakeGitHub({})) is None


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (urllib.error.HTTPError("u", 403, "rate limited", {}, None), "hour"),
        (urllib.error.HTTPError("u", 500, "boom", {}, None), "500"),
        (urllib.error.URLError("no route"), "no route"),
        (TimeoutError("timed out"), "timed out"),
    ],
)
def test_network_errors_become_readable_messages(error, message):
    fake = FakeGitHub({f"{github.API_URL}/latest": error})
    with pytest.raises(UpdateError, match=message):
        github.latest_release(opener=fake)


# --------------------------------------------------------------------------- planification
NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("last", "frequency", "at_startup", "due"),
    [
        ("", "daily", True, True),
        ("", "startup", False, False),
        ("", "startup", True, True),
        ((NOW - timedelta(minutes=20)).isoformat(), "startup", True, False),  # moins d'une heure
        ((NOW - timedelta(hours=5)).isoformat(), "daily", False, False),
        ((NOW - timedelta(hours=25)).isoformat(), "daily", False, True),
        ((NOW - timedelta(days=3)).isoformat(), "weekly", True, False),
        ((NOW - timedelta(days=8)).isoformat(), "weekly", False, True),
        ("n'importe quoi", "daily", False, True),
    ],
)
def test_check_schedule(last, frequency, at_startup, due):
    assert is_check_due(last, frequency, NOW, at_startup) is due


# --------------------------------------------------------------------------- téléchargement vérifié
PAYLOAD = b"MZ fake installer"


def _download_routes(checksum: str) -> FakeGitHub:
    return FakeGitHub({
        "https://example.invalid/1.2.0/setup.exe": PAYLOAD,
        "https://example.invalid/1.2.0/setup.sha256": f"{checksum}  OptixPlus-Setup-1.2.0.exe\n".encode(),
    })


def _release() -> Release:
    return github.release_from_json(_release_json("v1.2.0"))


def test_installer_is_downloaded_and_verified(tmp_path):
    steps = []
    path = installer.fetch_installer(_release(), steps.append, None, _download_routes(hashlib.sha256(PAYLOAD).hexdigest()), tmp_path)
    assert path.read_bytes() == PAYLOAD
    assert steps and steps[0].total == len(PAYLOAD)


def test_wrong_checksum_removes_the_file(tmp_path):
    with pytest.raises(UpdateError, match="checksum"):
        installer.fetch_installer(_release(), None, None, _download_routes("0" * 64), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_cancelled_download_leaves_nothing(tmp_path):
    with pytest.raises(Cancelled):
        installer.fetch_installer(_release(), None, lambda: True, _download_routes(hashlib.sha256(PAYLOAD).hexdigest()), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_checksum_file_formats():
    digest = "a" * 64
    assert installer.expected_checksum(digest, "x.exe") == digest
    assert installer.expected_checksum(f"{'b' * 64}  other.exe\n{digest} *x.exe", "x.exe") == digest
    with pytest.raises(UpdateError):
        installer.expected_checksum("pas d'empreinte", "x.exe")


def test_installer_is_launched_silently(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(installer.subprocess, "Popen", lambda args, **kw: calls.append(args))
    installer.launch(tmp_path / "setup.exe")
    assert calls[0][1:] == ["/SILENT", "/CLOSEAPPLICATIONS"]


# --------------------------------------------------------------------------- Nouveautés
CHANGELOG = """# Nouveautés

Intro.

## [Non publié]
- à venir

## [1.2.0] - 2026-10-01
- deux

## [1.1.0] - 2026-09-01
- un

## [1.0.0] - 2026-08-01
- zéro
"""


def test_changelog_sections_since_last_seen():
    sections = changelog.parse(CHANGELOG)
    assert [s.title for s in sections] == ["Non publié", "1.2.0", "1.1.0", "1.0.0"]
    assert [s.title for s in changelog.news_since(sections, "1.0.0", "1.2.0")] == ["1.2.0", "1.1.0"]
    assert [s.title for s in changelog.news_since(sections, "", "1.1.0")] == ["1.1.0"]  # premier lancement
    assert [s.title for s in changelog.news_since(sections, "1.2.0", "1.3.0")] == ["Non publié"]  # sources
    assert "2026-10-01" in sections[1].markdown()


def test_embedded_changelog_is_found():
    assert changelog.changelog_path() is not None
    assert changelog.load()


# --------------------------------------------------------------------------- interface
def _wait(condition, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return condition()


@pytest.fixture
def ui(qapp, tmp_path, monkeypatch):
    messages = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: messages.append(("info", a[2]))))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: messages.append(("warning", a[2]))))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    i18n.install("fr")
    logging_setup.configure(to_file=False)
    settings = Settings.load(tmp_path / "settings.json")
    controller = AppController(qapp, settings, install_manager(qapp, "light"), LaunchMode.INSTALLED)
    yield controller, messages, monkeypatch
    if controller.window is not None:
        controller.window.close()
    for dialog in (controller._changelog_dialog, controller.updates.dialog):
        if dialog is not None:
            dialog.close()
    i18n.install("en")


def _answer(monkeypatch, result):
    from optixplus.shell import updates

    def fake(current, include, skipped):
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(updates, "available_update", fake)


def test_manual_check_offers_the_release(ui):
    controller, _messages, monkeypatch = ui
    _answer(monkeypatch, _release())
    controller.show_main_window()
    controller.check_for_updates()
    assert _wait(lambda: controller.updates.dialog is not None)
    dialog = controller.updates.dialog
    assert dialog.release.version == Version.parse("1.2.0")
    # Depuis les sources, pas d'installation automatique : lien vers la page de téléchargement.
    assert dialog.install_button.text() == "Ouvrir la page de téléchargement"
    assert controller.updates.settings.last_check


def test_skip_this_version_is_remembered(ui):
    controller, _messages, monkeypatch = ui
    _answer(monkeypatch, _release())
    controller.check_for_updates()
    assert _wait(lambda: controller.updates.dialog is not None)
    controller.updates.dialog.skip_button.click()
    assert controller.updates.settings.skipped_version == "1.2.0"
    assert json.loads(controller.context.settings.path.read_text(encoding="utf-8"))["updates"]["skipped_version"] == "1.2.0"


def test_manual_check_says_when_up_to_date_or_failed(ui):
    controller, messages, monkeypatch = ui
    _answer(monkeypatch, None)
    controller.check_for_updates()
    assert _wait(lambda: messages)
    assert messages[-1][0] == "info" and "à jour" in messages[-1][1]
    _answer(monkeypatch, UpdateError("GitHub est injoignable : test"))
    controller.check_for_updates()
    assert _wait(lambda: len(messages) == 2)
    assert messages[-1][0] == "warning" and "injoignable" in messages[-1][1]


def test_automatic_check_is_silent_without_news(ui):
    controller, messages, monkeypatch = ui
    _answer(monkeypatch, None)
    controller.updates.check(interactive=False)
    assert _wait(lambda: not controller.updates.busy)
    QCoreApplication.processEvents()
    assert messages == []


def test_download_page_opens_outside_the_installed_exe(ui):
    controller, _messages, monkeypatch = ui
    from optixplus.shell import updates

    opened = []
    monkeypatch.setattr(updates.QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url.toString())))
    controller.updates.install(_release())
    assert opened == ["https://github.com/x/releases/v1.2.0"]


def test_settings_page_saves_update_choices(ui):
    controller, _messages, _monkeypatch = ui
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


def test_whats_new_on_first_launch_of_a_version(ui):
    controller, _messages, _monkeypatch = ui
    controller.context.settings.general.last_seen_version = "0.0.1"
    controller.whats_new_pending = True
    controller.show_main_window()
    assert _wait(lambda: controller._changelog_dialog is not None)
    from optixplus.version import __version__

    assert controller.context.settings.general.last_seen_version == __version__
    assert controller._changelog_dialog.browser.toPlainText().strip()


def test_language_change_reopens_news_and_update_dialogs(ui):
    controller, _messages, monkeypatch = ui
    _answer(monkeypatch, _release())
    controller.show_main_window()
    controller.open_whats_new(full=True)
    controller.check_for_updates()
    assert _wait(lambda: controller.updates.dialog is not None)
    controller.context.settings.general.language = "en"
    controller.change_language()
    assert _wait(lambda: controller._changelog_dialog is not None and controller._changelog_dialog.isVisible())
    assert controller._changelog_dialog.full_history.isChecked()
    assert controller._changelog_dialog.windowTitle() == "What's new in OptixPlus"
    assert controller.updates.dialog is not None and controller.updates.dialog.windowTitle() == "Update available"
