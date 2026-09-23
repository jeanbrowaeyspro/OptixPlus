"""Résolution des chemins : ressources embarquées et dossier de données utilisateur."""

from __future__ import annotations

import os
import sys
from functools import cache
from pathlib import Path

from ..version import APP_NAME

PACKAGE_DIR = Path(__file__).resolve().parent.parent


def is_frozen() -> bool:
    """Vrai dans l'exécutable PyInstaller."""
    return bool(getattr(sys, "frozen", False))


def resource_path(*parts: str) -> Path:
    """Chemin d'une ressource du paquet (icônes, catalogues de traduction…).

    Les ressources vivent dans le paquet lui-même : PyInstaller les place au même
    endroit relatif, ce qui évite toute gestion particulière de ``_MEIPASS``.
    """
    return PACKAGE_DIR.joinpath("resources", *parts)


@cache
def data_dir() -> Path:
    """``%APPDATA%\\OptixPlus``, créé au premier appel."""
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


@cache
def log_dir() -> Path:
    """Dossier des journaux de l'application."""
    path = data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return data_dir() / "settings.json"


def executable_command(*args: str) -> str:
    """Ligne de commande qui relance l'application (clé Run, relance après mise à jour)."""
    extra = "".join(f' "{a}"' for a in args)
    if is_frozen():
        return f'"{sys.executable}"{extra}'
    # Depuis les sources : pythonw.exe évite l'ouverture d'une console.
    python = Path(sys.executable)
    pythonw = python.with_name("pythonw.exe")
    interp = pythonw if pythonw.exists() else python
    return f'"{interp}" -m optixplus{extra}'
