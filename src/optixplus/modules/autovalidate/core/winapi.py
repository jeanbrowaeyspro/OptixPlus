"""Accès Win32 de la surveillance (ctypes, sans dépendance), repris d'Auto Validate.

Nouveauté : ``WinEventHook``. Au lieu de parcourir toutes les fenêtres toutes les 150 ms,
Windows prévient l'application quand une fenêtre apparaît ou qu'une boîte de dialogue
s'ouvre. Le rappel est livré par la boucle de messages du thread qui a posé le crochet
(le thread de l'interface Qt) : aucun thread supplémentaire, aucune attente active.
"""

from __future__ import annotations

import ctypes
import os
import sys
from collections.abc import Callable
from ctypes import wintypes

IS_WINDOWS = sys.platform == "win32"

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
VK_RETURN = 0x0D
VK_MENU = 0x12  # ALT
MAPVK_VK_TO_VSC = 0
SW_RESTORE = 9
GA_ROOT = 2

# Événements WinEvent utiles (les autres ne sont pas écoutés).
EVENT_SYSTEM_FOREGROUND = 0x0003
EVENT_SYSTEM_DIALOGSTART = 0x0010
EVENT_OBJECT_SHOW = 0x8002
WINEVENT_OUTOFCONTEXT = 0x0000
WINEVENT_SKIPOWNPROCESS = 0x0002
OBJID_WINDOW = 0
CHILDID_SELF = 0

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
WINEVENTPROC = ctypes.WINFUNCTYPE(
    None,
    wintypes.HANDLE,  # hWinEventHook
    wintypes.DWORD,  # event
    wintypes.HWND,  # hwnd
    wintypes.LONG,  # idObject
    wintypes.LONG,  # idChild
    wintypes.DWORD,  # idEventThread
    wintypes.DWORD,  # dwmsEventTime
)

ULONG_PTR = ctypes.c_size_t


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]


if IS_WINDOWS:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _prototypes: dict[str, tuple[list, object]] = {
        "EnumWindows": ([WNDENUMPROC, wintypes.LPARAM], wintypes.BOOL),
        "IsWindow": ([wintypes.HWND], wintypes.BOOL),
        "IsWindowVisible": ([wintypes.HWND], wintypes.BOOL),
        "IsIconic": ([wintypes.HWND], wintypes.BOOL),
        "ShowWindow": ([wintypes.HWND, ctypes.c_int], wintypes.BOOL),
        "GetWindowTextLengthW": ([wintypes.HWND], ctypes.c_int),
        "GetWindowTextW": ([wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
        "GetClassNameW": ([wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
        "GetWindowThreadProcessId": ([wintypes.HWND, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
        "GetForegroundWindow": ([], wintypes.HWND),
        "SetForegroundWindow": ([wintypes.HWND], wintypes.BOOL),
        "BringWindowToTop": ([wintypes.HWND], wintypes.BOOL),
        "AttachThreadInput": ([wintypes.DWORD, wintypes.DWORD, wintypes.BOOL], wintypes.BOOL),
        "MapVirtualKeyW": ([wintypes.UINT, wintypes.UINT], wintypes.UINT),
        "GetAncestor": ([wintypes.HWND, wintypes.UINT], wintypes.HWND),
        "SendInput": ([wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int], wintypes.UINT),
        "SetWinEventHook": (
            [wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE, WINEVENTPROC, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD],
            wintypes.HANDLE,
        ),
        "UnhookWinEvent": ([wintypes.HANDLE], wintypes.BOOL),
    }
    for _name, (_args, _res) in _prototypes.items():
        _fn = getattr(user32, _name)
        _fn.argtypes = _args
        _fn.restype = _res

    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.GetCurrentThreadId.argtypes = []
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD


# ---- Fenêtres ---------------------------------------------------------------
def window_title(hwnd: int) -> str:
    """Titre d'une fenêtre (lu sans envoyer de message : ne bloque pas sur une application figée)."""
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def window_class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def is_top_level(hwnd: int) -> bool:
    return bool(hwnd) and int(user32.GetAncestor(hwnd, GA_ROOT) or 0) == int(hwnd)


def is_visible(hwnd: int) -> bool:
    return bool(user32.IsWindowVisible(hwnd))


def is_window(hwnd: int) -> bool:
    return bool(user32.IsWindow(hwnd))


def is_window_alive(hwnd: int) -> bool:
    """La fenêtre existe encore et reste visible."""
    return is_window(hwnd) and is_visible(hwnd)


def enum_visible_windows() -> list[tuple[int, str]]:
    """(hwnd, titre) des fenêtres de premier niveau visibles ayant un titre."""
    result: list[tuple[int, str]] = []

    @WNDENUMPROC
    def _callback(hwnd, _lparam):
        try:
            if user32.IsWindowVisible(hwnd):
                title = window_title(hwnd)
                if title:
                    result.append((int(hwnd), title))
        except Exception:
            pass
        return True

    user32.EnumWindows(_callback, 0)
    return result


def window_thread_and_pid(hwnd: int) -> tuple[int, int]:
    pid = wintypes.DWORD(0)
    tid = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(tid), int(pid.value)


def process_image_path(pid: int) -> str:
    """Chemin de l'exécutable d'un processus (chaîne vide si inaccessible)."""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        kernel32.CloseHandle(handle)


def window_process_name(hwnd: int) -> str:
    """Nom de l'exécutable propriétaire d'une fenêtre (ex. ``FTOptixStudio.exe``)."""
    _tid, pid = window_thread_and_pid(hwnd)
    return os.path.basename(process_image_path(pid)) if pid else ""


def get_foreground_window() -> int:
    return int(user32.GetForegroundWindow() or 0)


# ---- Clavier et focus -----------------------------------------------------------
def _key_input(vk: int, up: bool) -> INPUT:
    scan = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
    event = INPUT(type=INPUT_KEYBOARD)
    event.ki = KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=KEYEVENTF_KEYUP if up else 0, time=0, dwExtraInfo=0)
    return event


def _send(*events: INPUT) -> int:
    array = (INPUT * len(events))(*events)
    return int(user32.SendInput(len(events), array, ctypes.sizeof(INPUT)))


def send_enter() -> bool:
    """Envoie Entrée (appui + relâchement) à la fenêtre au premier plan."""
    return _send(_key_input(VK_RETURN, False), _key_input(VK_RETURN, True)) == 2


def force_foreground(hwnd: int) -> bool:
    """Met ``hwnd`` au premier plan.

    ``SetForegroundWindow`` seul échoue quand notre processus n'est pas au premier plan.
    On attache donc temporairement notre file d'entrée à celles de la cible et de la
    fenêtre active. En dernier recours, ALT est enfoncée **avant** le changement de
    premier plan et relâchée **après** : le relâchement arrive ainsi à la cible (une boîte
    de dialogue sans menu) et non à l'application de l'utilisateur, dont la barre de menus
    se serait sinon activée — défaut de l'ancien Auto Validate.
    """
    if not user32.IsWindow(hwnd):
        return False
    if get_foreground_window() == hwnd:
        return True
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)

    current = int(kernel32.GetCurrentThreadId())
    target_tid, _pid = window_thread_and_pid(hwnd)
    foreground = get_foreground_window()
    foreground_tid = window_thread_and_pid(foreground)[0] if foreground else 0
    attached: list[int] = []
    for tid in {target_tid, foreground_tid}:
        if tid and tid != current and user32.AttachThreadInput(current, tid, True):
            attached.append(tid)
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        for tid in attached:
            user32.AttachThreadInput(current, tid, False)
    if get_foreground_window() == hwnd:
        return True

    _send(_key_input(VK_MENU, False))
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        _send(_key_input(VK_MENU, True))
    return get_foreground_window() == hwnd


# ---- Événements de fenêtres ------------------------------------------------------
WinEventCallback = Callable[[int, int], None]  # (événement, hwnd)


class WinEventHook:
    """Écoute l'apparition des fenêtres de premier niveau des autres processus.

    Le rappel ne reçoit que les événements portant sur une fenêtre elle-même
    (``OBJID_WINDOW`` / ``CHILDID_SELF``) ; le tri fin est laissé à l'appelant, qui doit
    rester rapide : il s'exécute dans la boucle de messages de l'interface.
    """

    EVENTS = (EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_DIALOGSTART, EVENT_OBJECT_SHOW)

    def __init__(self, callback: WinEventCallback) -> None:
        self._callback = callback
        self._handles: list[int] = []
        # Référence conservée : si le pointeur ctypes était libéré, Windows appellerait
        # une adresse invalide.
        self._proc = WINEVENTPROC(self._dispatch)

    @property
    def installed(self) -> bool:
        return bool(self._handles)

    def install(self) -> bool:
        if self._handles or not IS_WINDOWS:
            return bool(self._handles)
        flags = WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS
        for event in self.EVENTS:
            handle = user32.SetWinEventHook(event, event, None, self._proc, 0, 0, flags)
            if handle:
                self._handles.append(int(handle))
        return bool(self._handles)

    def uninstall(self) -> None:
        for handle in self._handles:
            user32.UnhookWinEvent(handle)
        self._handles.clear()

    def __del__(self) -> None:
        # Même raison que pour ``_proc`` : jamais de crochet posé sur un rappel libéré.
        self.uninstall()

    def _dispatch(self, _hook, event, hwnd, id_object, id_child, _thread, _time) -> None:
        if id_object != OBJID_WINDOW or id_child != CHILDID_SELF or not hwnd:
            return
        try:
            self._callback(int(event), int(hwnd))
        except Exception:
            # Une exception ne doit jamais remonter dans Windows.
            pass
