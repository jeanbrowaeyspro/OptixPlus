"""Magasin clé → valeur au comportement de ``QSettings`` (``value`` / ``setValue``), adossé à
``settings.json``.

Permet de reprendre tel quel le code des outils qui utilisaient ``QSettings`` (registre),
tout en rangeant leurs données dans le fichier de réglages unique d'OptixPlus.
"""

from __future__ import annotations

from typing import Any

from .settings import Settings


class KeyValueStore:
    def __init__(self, settings: Settings, section: str) -> None:
        self._settings = settings
        self._data = settings.store(section)

    def value(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def setValue(self, key: str, value: Any) -> None:  # noqa: N802 (même nom que QSettings)
        self._data[key] = value
        self._settings.save()

    def remove(self, key: str) -> None:
        if self._data.pop(key, None) is not None:
            self._settings.save()

    def keys(self) -> list[str]:
        return list(self._data)
