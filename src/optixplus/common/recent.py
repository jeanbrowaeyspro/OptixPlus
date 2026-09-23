"""Projets FT Optix récents, partagés par tous les outils et affichés sur l'accueil."""

from __future__ import annotations

import os

from .settings import Settings

MAX_RECENT = 10


def _key(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def add_recent_project(settings: Settings, path: str) -> None:
    """Place ``path`` en tête de la liste (sans doublon, casse de Windows ignorée)."""
    path = os.path.normpath(path)
    recent = [p for p in settings.general.recent_projects if _key(p) != _key(path)]
    settings.general.recent_projects = [path, *recent][:MAX_RECENT]
    settings.save()


def recent_projects(settings: Settings) -> list[str]:
    return list(settings.general.recent_projects)


def remove_recent_project(settings: Settings, path: str) -> None:
    settings.general.recent_projects = [p for p in settings.general.recent_projects if _key(p) != _key(path)]
    settings.save()
