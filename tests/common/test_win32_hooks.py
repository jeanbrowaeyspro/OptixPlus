"""Crochets Windows : décodage de la touche Impr. écran, pose et retrait des vrais crochets.

Le décodage appelle directement le rappel du crochet clavier avec une frappe fabriquée :
aucun crochet n'est posé. Un seul test par crochet utilise l'API Windows réelle.
"""

from __future__ import annotations

import ctypes

import pytest

from optixplus.common import win32

WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN = 0x0100, 0x0101, 0x0104


@pytest.mark.parametrize(
    ("vk", "scan", "flags", "modifier", "message", "expected"),
    [
        # Reconnue (appui ou relâchement), seule :
        (0x2C, 0x37, 0x01, False, WM_KEYDOWN, (True, True)),  # Impr. écran (ou Fn+Impr. écran)
        (0x2C, 0x37, 0x01, False, WM_KEYUP, (False, True)),
        (0xFF, 0x37, 0x01, False, WM_SYSKEYDOWN, (True, True)),  # code virtuel inhabituel, code matériel d'Impr. écran
        # Reconnue, mais combinée : pas seule.
        (0x2C, 0x54, 0x00, False, WM_SYSKEYDOWN, (True, False)),  # Alt+Impr. écran : touche Syst
        (0x2C, 0x54, 0x20, False, WM_KEYUP, (False, False)),  # Syst avec le drapeau Alt
        (0x00, 0x54, 0x00, False, WM_KEYUP, (False, False)),  # Syst sans code virtuel
        (0x2C, 0x37, 0x01, True, WM_KEYUP, (False, False)),  # Ctrl, Maj ou Windows enfoncée
        # Autres touches : ignorées.
        (0x41, 0x1E, 0x00, False, WM_KEYUP, None),  # A
        (0x6A, 0x37, 0x00, False, WM_KEYUP, None),  # * du pavé numérique : même code matériel, non étendu
    ],
)
def test_print_screen_key_is_decoded(vk, scan, flags, modifier, message, expected, monkeypatch):
    seen = []
    watcher = win32.PrintScreenWatcher(lambda pressed, vk, scan, alone: seen.append((pressed, alone)))
    monkeypatch.setattr(win32.user32, "CallNextHookEx", lambda *a: 0)
    monkeypatch.setattr(win32, "modifier_down", lambda: modifier)
    info = win32._KbdLLHookStruct(vkCode=vk, scanCode=scan, flags=flags)
    watcher._callback(0, message, ctypes.addressof(info))
    assert seen == ([] if expected is None else [expected])


@pytest.mark.windows_only
def test_real_keyboard_hook_is_installed_and_removed():
    watcher = win32.PrintScreenWatcher(lambda *a: None)
    try:
        assert watcher.start()
    finally:
        watcher.stop()


@pytest.mark.windows_only
def test_real_win_event_hook_is_installed_and_removed(qapp):
    """Crochet d'événements de fenêtres de Validation auto (aucune fenêtre affichée)."""
    from optixplus.modules.autovalidate.core import winapi

    hook = winapi.WinEventHook(lambda _event, _hwnd: None)
    assert hook.install()
    assert hook.installed
    hook.uninstall()
    assert not hook.installed
