"""Projets FT Optix et automates récents, partagés par tous les outils et affichés sur l'accueil."""

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


def recent_controllers(settings: Settings) -> list[tuple[str, str]]:
    """Automates récents, du plus récent au plus ancien : (adresse, nom affiché)."""
    result = []
    for item in settings.general.recent_controllers:
        if isinstance(item, dict) and isinstance(item.get("host"), str) and item["host"]:
            name = item.get("name")
            result.append((item["host"], name if isinstance(name, str) and name else item["host"]))
    return result


def add_recent_controller(settings: Settings, host: str, name: str = "") -> None:
    """Place l'automate en tête de la liste (sans doublon d'adresse, casse ignorée)."""
    others = [
        {"host": h, "name": n} for h, n in recent_controllers(settings) if h.casefold() != host.casefold()
    ]
    settings.general.recent_controllers = [{"host": host, "name": name or host}, *others][:MAX_RECENT]
    settings.save()
