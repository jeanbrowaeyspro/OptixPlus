"""Validation auto : séquence de validation et surveillance, avec une API Windows simulée.

Aucune vraie fenêtre n'est touchée : ``FakeWindows`` remplace le module ``winapi``.
"""

from __future__ import annotations

import pytest

from fakes import STUDIO, FakeWindows
from optixplus.common.settings import Settings
from optixplus.modules import spec
from optixplus.modules.autovalidate.core.config import AutoValidateSettings
from optixplus.modules.autovalidate.service import AutoValidateService
from optixplus.shell.context import AppContext, LaunchMode
from support import settle, wait_until

POPUP = "Le projet existe déjà"


class _Controller:
    def open_tool(self, _module_id: str) -> None:
        pass


@pytest.fixture
def desktop(qapp, tmp_path):
    """Fabrique : ``desktop(mode=…, windows={hwnd: (titre, processus)})`` → ``(fake, service)``.

    Les fenêtres données existent avant le démarrage de la surveillance. Délai entre deux
    tentatives réduit au minimum (50 ms) ; les services sont arrêtés après le test.
    """
    services: list[AutoValidateService] = []

    def make(mode: LaunchMode = LaunchMode.INSTALLED, windows: dict | None = None):
        fake = FakeWindows()
        fake.windows.update(windows or {})
        settings = Settings.load(tmp_path / "settings.json")
        settings.section(AutoValidateSettings).retry_delay_ms = 50
        context = AppContext(settings=settings, theme=None, mode=mode, controller=_Controller())
        service = AutoValidateService(spec("autovalidate"), context, api=fake)
        services.append(service)
        service.start()
        return fake, service

    yield make
    for service in services:
        service.stop()


def _all_retries_elapse(service) -> None:
    """Laisse passer toutes les tentatives possibles, pour vérifier qu'aucune n'a eu d'effet."""
    settle((service.settings.max_retries + 1) * service.settings.retry_delay_ms / 1000)


def test_popup_is_confirmed_on_window_event(desktop):
    fake, service = desktop(windows={10: ("FT Optix Studio", STUDIO)})
    fake.foreground = 10
    validated: list[str] = []
    service.validated.connect(validated.append)
    fake.open(42, POPUP)
    assert wait_until(lambda: validated, 3)
    assert validated == [POPUP]
    assert fake.enter_count == 1
    assert service.validation_count == 1
    assert fake.foreground == 10  # focus rendu à Studio


def test_popup_already_shown_is_found_at_start(desktop):
    _fake, service = desktop(windows={7: ("Project already exists", STUDIO)})
    assert wait_until(lambda: service.validation_count == 1, 3)


def test_foreign_process_is_ignored(desktop):
    fake, service = desktop()
    fake.open(5, POPUP, process="notepad.exe")
    _all_retries_elapse(service)
    assert fake.enter_count == 0
    assert service.validation_count == 0


def test_enter_is_never_sent_without_focus(desktop):
    fake, service = desktop()
    fake.can_focus = False
    fake.open(9, POPUP)
    _all_retries_elapse(service)
    assert fake.enter_count == 0
    assert service.validation_count == 0


def test_focus_is_not_stolen_when_user_moved_on(desktop):
    fake, service = desktop(windows={10: ("FT Optix Studio", STUDIO), 20: ("Outlook", "outlook.exe")})
    fake.foreground = 10

    def enter_then_user_clicks_outlook() -> bool:
        fake.enter_count += 1
        del fake.windows[fake.foreground]
        fake.foreground = 20
        return True

    fake.send_enter = enter_then_user_clicks_outlook
    fake.open(42, POPUP)
    assert wait_until(lambda: service.validation_count == 1, 3)
    assert fake.foreground == 20


def test_retries_then_gives_up(desktop):
    fake, service = desktop()
    fake.enter_closes = False
    fake.open(3, POPUP)
    assert wait_until(lambda: fake.enter_count == 3, 3)
    _all_retries_elapse(service)
    assert fake.enter_count == 3  # pas de 4e tentative : max_retries = 3
    assert service.validation_count == 0


def test_suspend_stops_listening_and_persists(desktop):
    fake, service = desktop()
    service.set_enabled(False)
    assert not fake.hook.installed
    assert service.suspended
    assert service.context.settings.section(AutoValidateSettings).enabled is False
    fake.open(8, POPUP)
    _all_retries_elapse(service)
    assert fake.enter_count == 0


def test_discovery_mode_starts_suspended_and_does_not_persist(desktop):
    _fake, service = desktop(mode=LaunchMode.DISCOVERY)
    settings = service.context.settings
    assert service.suspended
    service.set_enabled(True)
    assert service.enabled
    assert settings.section(AutoValidateSettings).enabled is True  # valeur par défaut, non modifiée
    service.set_enabled(False)
    assert settings.section(AutoValidateSettings).enabled is True
