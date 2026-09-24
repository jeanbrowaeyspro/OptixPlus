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


TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


if IS_WINDOWS:
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.restype = wintypes.BOOL


def process_running(exe_name: str) -> bool:
    """Vrai si un processus de ce nom d'exécutable tourne (ex. ``FTOptixStudio.exe``)."""
    if not IS_WINDOWS:
        return False
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == INVALID_HANDLE_VALUE:
        return False
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        wanted = exe_name.lower()
        while ok:
            if entry.szExeFile.lower() == wanted:
                return True
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        return False
    finally:
        kernel32.CloseHandle(snapshot)


# --------------------------------------------------------------------------- droits élevés
def is_elevated() -> bool:
    """Vrai si le processus tourne avec les droits administrateur (UAC élevé)."""
    if not IS_WINDOWS:
        return False
    try:
        return bool(shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False
