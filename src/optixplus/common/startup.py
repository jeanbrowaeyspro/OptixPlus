"""Démarrage automatique avec Windows (clé Run de l'utilisateur), repris d'Auto Validate."""

from __future__ import annotations

import logging

from . import paths
from ..version import APP_NAME

log = logging.getLogger("optixplus.startup")

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_ARG = "--demarrage"


def is_enabled() -> bool:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            value, _kind = winreg.QueryValueEx(key, APP_NAME)
            return bool(value)
    except OSError:
        return False


def set_enabled(enabled: bool) -> None:
    """Active ou désactive le démarrage automatique ; lève ``OSError`` en cas d'échec."""
    import winreg

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, paths.executable_command(AUTOSTART_ARG))
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass


def refresh_command_if_enabled() -> None:
    """Réécrit le chemin enregistré si l'exécutable a été déplacé (appelé au démarrage)."""
    try:
        if is_enabled():
            set_enabled(True)
    except OSError as exc:
        log.warning("Mise à jour de la clé de démarrage impossible : %s", exc)
