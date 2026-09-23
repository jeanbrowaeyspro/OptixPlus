"""Auto Validate : décisions, réglages et séquence de validation, avec une API Windows simulée.

Aucune vraie fenêtre n'est touchée : ``FakeWindows`` remplace le module ``winapi``.
"""

from __future__ import annotations

import time

import pytest
from PySide6.QtCore import QCoreApplication

from optixplus.common.settings import Settings
from optixplus.modules import spec
from optixplus.modules.autovalidate.core import matching
from optixplus.modules.autovalidate.core.config import DEFAULT_TITLES, AutoValidateSettings
from optixplus.modules.autovalidate.service import AutoValidateService
from optixplus.shell.context import AppContext, LaunchMode

STUDIO = "FTOptixStudio.exe"


# ---- décisions pures -------------------------------------------------------------
def test_title_matching_is_substring_and_case_insensitive():
    patterns = matching.normalize_patterns(["Le projet existe déjà", "  ", "Project already exists"])
    assert patterns == ("le projet existe déjà", "project already exists")
    assert matching.title_matches("FT Optix — LE PROJET EXISTE DÉJÀ", patterns)
    assert not matching.title_matches("Autre fenêtre", patterns)
    assert not matching.title_matches("", patterns)


def test_same_process():
    assert matching.same_process("ftoptixstudio.EXE", STUDIO)
    assert not matching.same_process("", STUDIO)
    assert not matching.same_process("notepad.exe", STUDIO)


def test_cooldowns_expire_and_forget_dead_windows():
    cooldowns = matching.Cooldowns()
    cooldowns.add(1, 5, now=100)
    cooldowns.add(2, 5, now=100)
    assert cooldowns.active(1, now=104)
    assert not cooldowns.active(1, now=106)
    cooldowns.prune(now=101, alive=lambda h: h != 2)
    assert len(cooldowns) == 1


def test_settings_are_normalized():
    s = AutoValidateSettings(titles=["", "  "], process_name=" ", max_retries=50, retry_delay_ms=1, fallback_scan_ms=10)
    s.normalized()
    assert s.titles == list(DEFAULT_TITLES)
    assert s.process_name == STUDIO
    assert (s.max_retries, s.retry_delay_ms, s.fallback_scan_ms) == (10, 50, 500)


def test_restore_defaults_keeps_state():
    s = AutoValidateSettings(enabled=False, titles=["x"], notify=True)
    s.restore_defaults()
    assert s.enabled is False
    assert s.titles == list(DEFAULT_TITLES)
    assert s.notify is False  # notification désactivée par défaut


# ---- API Windows simulée ---------------------------------------------------------
class FakeWindows:
    """Bureau simulé : fenêtres (titre, processus), premier plan, touche Entrée."""

    def __init__(self) -> None:
        self.windows: dict[int, tuple[str, str]] = {}
        self.foreground = 0
        self.can_focus = True
        self.enter_closes = True
        self.enter_count = 0
        self.hook: FakeWindows.WinEventHook | None = None
        fake = self

        class WinEventHook:
            def __init__(self, callback) -> None:
                self.callback = callback
                self.installed = False
                fake.hook = self

            def install(self) -> bool:
                self.installed = True
                return True

            def uninstall(self) -> None:
                self.installed = False

        self.WinEventHook = WinEventHook

    # fenêtres
    def open(self, hwnd: int, title: str, process: str = STUDIO) -> None:
        self.windows[hwnd] = (title, process)
        if self.hook is not None and self.hook.installed:
            self.hook.callback(0x8002, hwnd)

    def is_top_level(self, hwnd: int) -> bool:
        return hwnd in self.windows

    def window_title(self, hwnd: int) -> str:
        return self.windows.get(hwnd, ("", ""))[0]

    def window_class_name(self, hwnd: int) -> str:
        return "#32770"

    def window_process_name(self, hwnd: int) -> str:
        return self.windows.get(hwnd, ("", ""))[1]

    def is_window(self, hwnd: int) -> bool:
        return hwnd in self.windows

    def is_window_alive(self, hwnd: int) -> bool:
        return hwnd in self.windows

    def enum_visible_windows(self) -> list[tuple[int, str]]:
        return [(h, t) for h, (t, _p) in self.windows.items()]

    # focus et clavier
    def get_foreground_window(self) -> int:
        return self.foreground

    def force_foreground(self, hwnd: int) -> bool:
        if self.can_focus and hwnd in self.windows:
            self.foreground = hwnd
            return True
        return False

    def send_enter(self) -> bool:
        self.enter_count += 1
        if self.enter_closes and self.foreground in self.windows:
            del self.windows[self.foreground]
            self.foreground = 0
        return True


def _wait(condition, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return condition()


class _Controller:
    def open_tool(self, _module_id: str) -> None:
        pass


@pytest.fixture
def desktop(qapp, tmp_path):
    fake = FakeWindows()
    settings = Settings.load(tmp_path / "settings.json")
    section = settings.section(AutoValidateSettings)
    section.retry_delay_ms = 50
    context = AppContext(settings=settings, theme=None, mode=LaunchMode.INSTALLED, controller=_Controller())
    service = AutoValidateService(spec("autovalidate"), context, api=fake)
    service.start()
    yield fake, service
    service.stop()


def test_popup_is_confirmed_on_window_event(desktop):
    fake, service = desktop
    fake.windows[10] = ("FT Optix Studio", STUDIO)
    fake.foreground = 10
    validated: list[str] = []
    service.validated.connect(validated.append)
    fake.open(42, "Le projet existe déjà")
    assert _wait(lambda: validated)
    assert validated == ["Le projet existe déjà"]
    assert fake.enter_count == 1
    assert service.validation_count == 1
    assert fake.foreground == 10  # focus rendu à Studio


def test_popup_already_shown_is_found_at_start(qapp, tmp_path):
    fake = FakeWindows()
    fake.windows[7] = ("Project already exists", STUDIO)
    settings = Settings.load(tmp_path / "settings.json")
    context = AppContext(settings=settings, theme=None, mode=LaunchMode.INSTALLED, controller=_Controller())
    service = AutoValidateService(spec("autovalidate"), context, api=fake)
    service.start()
    try:
        assert _wait(lambda: service.validation_count == 1)
    finally:
        service.stop()


def test_foreign_process_is_ignored(desktop):
    fake, service = desktop
    fake.open(5, "Le projet existe déjà", process="notepad.exe")
    _wait(lambda: False, timeout=0.2)
    assert fake.enter_count == 0
    assert service.validation_count == 0


def test_enter_is_never_sent_without_focus(desktop):
    fake, service = desktop
    fake.can_focus = False
    fake.open(9, "Le projet existe déjà")
    _wait(lambda: False, timeout=0.5)
    assert fake.enter_count == 0
    assert service.validation_count == 0


def test_focus_is_not_stolen_when_user_moved_on(desktop):
    fake, service = desktop
    fake.windows[10] = ("FT Optix Studio", STUDIO)
    fake.windows[20] = ("Outlook", "outlook.exe")
    fake.foreground = 10

    def enter_then_user_clicks_outlook() -> bool:
        fake.enter_count += 1
        del fake.windows[fake.foreground]
        fake.foreground = 20
        return True

    fake.send_enter = enter_then_user_clicks_outlook
    fake.open(42, "Le projet existe déjà")
    assert _wait(lambda: service.validation_count == 1)
    assert fake.foreground == 20


def test_retries_then_gives_up(desktop):
    fake, service = desktop
    fake.enter_closes = False
    fake.open(3, "Le projet existe déjà")
    assert _wait(lambda: fake.enter_count == 3)
    _wait(lambda: False, timeout=0.2)
    assert fake.enter_count == 3  # pas de 4e tentative : max_retries = 3
    assert service.validation_count == 0


def test_suspend_stops_listening_and_persists(desktop):
    fake, service = desktop
    service.set_enabled(False)
    assert not fake.hook.installed
    assert service.suspended
    assert service.context.settings.section(AutoValidateSettings).enabled is False
    fake.open(8, "Le projet existe déjà")
    _wait(lambda: False, timeout=0.2)
    assert fake.enter_count == 0


def test_discovery_mode_starts_suspended_and_does_not_persist(qapp, tmp_path):
    fake = FakeWindows()
    settings = Settings.load(tmp_path / "settings.json")
    context = AppContext(settings=settings, theme=None, mode=LaunchMode.DISCOVERY, controller=_Controller())
    service = AutoValidateService(spec("autovalidate"), context, api=fake)
    service.start()
    try:
        assert service.suspended
        service.set_enabled(True)
        assert service.enabled
        assert settings.section(AutoValidateSettings).enabled is True  # valeur par défaut, non modifiée
        service.set_enabled(False)
        assert settings.section(AutoValidateSettings).enabled is True
    finally:
        service.stop()


def test_real_win_event_hook_installs_and_uninstalls(qapp):
    """Le vrai crochet Windows se pose et se retire proprement (aucune fenêtre affichée)."""
    from optixplus.modules.autovalidate.core import winapi

    hook = winapi.WinEventHook(lambda _event, _hwnd: None)
    assert hook.install()
    assert hook.installed
    hook.uninstall()
    assert not hook.installed
