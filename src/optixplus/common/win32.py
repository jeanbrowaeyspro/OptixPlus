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


# --------------------------------------------------------------------------- touche Impr. écran
VK_SNAPSHOT = 0x2C
SCAN_PRINT_SCREEN = 0x37  # avec le drapeau « étendu » : Impr. écran (sans lui : * du pavé numérique)
SCAN_SYSRQ = 0x54  # Alt+Impr. écran (touche Syst)
_LLKHF_EXTENDED = 0x01
_LLKHF_ALTDOWN = 0x20
# Maj, Ctrl, Alt, Windows gauche et droite (Fn est gérée par le clavier : Windows ne la voit pas).
_MODIFIER_KEYS = (0x10, 0x11, 0x12, 0x5B, 0x5C)
_WH_KEYBOARD_LL = 13
_KEY_MESSAGES = (0x0100, 0x0101, 0x0104, 0x0105)  # WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP


class _KbdLLHookStruct(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_void_p),
    ]


if IS_WINDOWS:
    _LRESULT = ctypes.c_ssize_t
    _HOOKPROC = ctypes.WINFUNCTYPE(_LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
    user32.SetWindowsHookExW.argtypes = [ctypes.c_int, _HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
    user32.SetWindowsHookExW.restype = wintypes.HHOOK
    user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
    user32.CallNextHookEx.restype = _LRESULT
    user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
    user32.UnhookWindowsHookEx.restype = wintypes.BOOL
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE


def modifier_down() -> bool:
    """Vrai si Alt, Ctrl, Maj ou Windows est enfoncée en ce moment."""
    if not IS_WINDOWS:
        return False
    return any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in _MODIFIER_KEYS)


def foreground_is_own_window() -> bool:
    """Vrai si la fenêtre au premier plan appartient à ce processus."""
    if not IS_WINDOWS:
        return False
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return False
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value == kernel32.GetCurrentProcessId()


class PrintScreenWatcher:
    """Crochet clavier de bas niveau limité à la touche Impr. écran (la touche n'est pas consommée).

    Windows traite Impr. écran à part (raccourci système) : une fenêtre ne la reçoit pas comme
    une touche ordinaire. Le crochet la voit avant ce traitement. Le rappel doit rester bref
    (Windows retire un crochet trop lent) : ``on_press`` ne fait que programmer une action.
    Le crochet vit dans le fil qui l'installe, dont la boucle de messages doit tourner (Qt).
    """

    def __init__(self, on_press) -> None:
        self._on_press = on_press
        self._handle = None
        self._proc = _HOOKPROC(self._callback) if IS_WINDOWS else None  # garder la référence

    def start(self) -> bool:
        if not IS_WINDOWS or self._handle:
            return bool(self._handle)
        self._handle = user32.SetWindowsHookExW(_WH_KEYBOARD_LL, self._proc, kernel32.GetModuleHandleW(None), 0)
        return bool(self._handle)

    def stop(self) -> None:
        if self._handle:
            user32.UnhookWindowsHookEx(self._handle)
            self._handle = None

    @staticmethod
    def is_print_screen(vk: int, scan: int, flags: int) -> bool:
        """Touche Impr. écran, quelle que soit la combinaison (Fn, Alt, Ctrl, Maj, Win)."""
        return (
            vk == VK_SNAPSHOT
            or scan == SCAN_SYSRQ
            or (scan == SCAN_PRINT_SCREEN and flags & _LLKHF_EXTENDED)
        )

    def _callback(self, code: int, wparam: int, lparam: int) -> int:
        if code == 0 and wparam in _KEY_MESSAGES:
            info = ctypes.cast(lparam, ctypes.POINTER(_KbdLLHookStruct)).contents
            if self.is_print_screen(info.vkCode, info.scanCode, info.flags):
                alone = not (info.scanCode == SCAN_SYSRQ or info.flags & _LLKHF_ALTDOWN or modifier_down())
                try:
                    self._on_press(wparam in (0x0100, 0x0104), info.vkCode, info.scanCode, alone)
                except Exception:  # jamais d'exception à travers le crochet
                    pass
        return user32.CallNextHookEx(self._handle, code, wparam, lparam)
