"""Appels Win32 communs, via ctypes (aucune dépendance externe).

Les appels propres à la surveillance des fenêtres (SendInput, WinEventHook…) vivent dans
le module Auto Validate.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

IS_WINDOWS = sys.platform == "win32"
ERROR_ALREADY_EXISTS = 183
ASFW_ANY = 0xFFFFFFFF

if IS_WINDOWS:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)

    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    user32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
    user32.AllowSetForegroundWindow.restype = wintypes.BOOL
    shell32.SetCurrentProcessExplicitAppUserModelID.argtypes = [wintypes.LPCWSTR]
    shell32.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long


def create_mutex(name: str) -> tuple[int, bool]:
    """Crée un mutex nommé. Renvoie (handle, déjà_existant)."""
    if not IS_WINDOWS:
        return 0, False
    handle = kernel32.CreateMutexW(None, False, name)
    already = ctypes.get_last_error() == ERROR_ALREADY_EXISTS
    return int(handle or 0), already


def close_handle(handle: int) -> None:
    if IS_WINDOWS and handle:
        kernel32.CloseHandle(handle)


def allow_any_foreground() -> None:
    """Autorise un autre processus (l'instance principale) à passer au premier plan."""
    if IS_WINDOWS:
        user32.AllowSetForegroundWindow(ASFW_ANY)


def set_app_user_model_id(app_id: str) -> None:
    """Regroupe les fenêtres sous notre icône dans la barre des tâches (et non celle de Python)."""
    if IS_WINDOWS:
        try:
            shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
        except OSError:
            pass
