"""Réglages de l'application : un fichier JSON unique, découpé en sections typées.

Chaque outil déclare sa section sous forme de dataclass portant un attribut de classe
``SECTION``. Au chargement, chaque valeur est validée contre le type de la valeur par
défaut : une valeur invalide est remplacée par la valeur par défaut et signalée dans le
journal, au lieu d'être injectée telle quelle. Les sections inconnues sont conservées
intactes, pour ne rien perdre en cas de retour à une version antérieure.

L'écriture est atomique : fichier temporaire, puis remplacement.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import MISSING, asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, ClassVar, TypeVar

from . import paths

log = logging.getLogger("optixplus.settings")

SCHEMA_VERSION = 1

T = TypeVar("T")


@dataclass
class GeneralSettings:
    """Réglages communs à toute l'application."""

    SECTION: ClassVar[str] = "general"

    language: str = "auto"  # auto | fr | en
    theme: str = "system"  # system | light | dark
    last_tool: str = "home"
    window_geometry: str = ""  # base64 de QMainWindow.saveGeometry()
    window_state: str = ""  # base64 de QMainWindow.saveState()
    show_log_panel: bool = False
    recent_projects: list[str] = field(default_factory=list)
    recent_controllers: list[dict] = field(default_factory=list)  # [{"host": …, "name": …}]
    last_seen_version: str = ""
    warn_elevated_capture: bool = True  # prévenir si Impr. écran est bloquée (OptixPlus en administrateur)
    notify_on_close: bool = True  # bulle « OptixPlus reste actif » quand la fenêtre se ferme, surveillance active


LANGUAGES = ("auto", "fr", "en")
THEMES = ("system", "light", "dark")


def _default_of(f) -> Any:
    if f.default is not MISSING:
        return f.default
    if f.default_factory is not MISSING:  # type: ignore[misc]
        return f.default_factory()  # type: ignore[misc]
    return None


def _coerce(value: Any, default: Any) -> tuple[Any, bool]:
    """Renvoie (valeur retenue, valide) en comparant au type de la valeur par défaut."""
    if default is None:
        return value, True
    if isinstance(default, bool):
        return (value, True) if isinstance(value, bool) else (default, False)
    if isinstance(default, int):
        if isinstance(value, int) and not isinstance(value, bool):
            return value, True
        return default, False
    if isinstance(default, float):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value), True
        return default, False
    if isinstance(default, str):
        return (value, True) if isinstance(value, str) else (default, False)
    if isinstance(default, list):
        return (list(value), True) if isinstance(value, list) else (default, False)
    if isinstance(default, dict):
        return (dict(value), True) if isinstance(value, dict) else (default, False)
    return value, True


def section_from_dict(cls: type[T], data: Any) -> T:
    """Construit une section à partir d'un dictionnaire lu sur disque, en validant chaque champ."""
    instance = cls()
    if not isinstance(data, dict):
        if data is not None:
            log.warning("Section « %s » illisible, valeurs par défaut utilisées", cls.SECTION)  # type: ignore[attr-defined]
        return instance
    for f in fields(cls):  # type: ignore[arg-type]
        if f.name not in data:
            continue
        value, ok = _coerce(data[f.name], _default_of(f))
        if not ok:
            log.warning(
                "Réglage %s.%s invalide (%r), valeur par défaut utilisée",
                cls.SECTION,  # type: ignore[attr-defined]
                f.name,
                data[f.name],
            )
        setattr(instance, f.name, value)
    return instance


class Settings:
    """Accès aux réglages ; une instance unique est partagée par toute l'application."""

    def __init__(self, path: Path, raw: dict[str, Any] | None = None) -> None:
        self.path = path
        self._raw: dict[str, Any] = raw or {}
        self._sections: dict[str, Any] = {}

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        path = path or paths.settings_path()
        raw: dict[str, Any] = {}
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    raise ValueError("la racine n'est pas un objet JSON")
            except (OSError, ValueError) as exc:
                log.error("Réglages illisibles (%s) : valeurs par défaut utilisées", exc)
                backup = path.with_suffix(".json.corrompu")
                try:
                    path.replace(backup)
                    log.warning("Ancien fichier conservé sous %s", backup)
                except OSError:
                    pass
                raw = {}
        return cls(path, raw)

    def section(self, cls: type[T]) -> T:
        """Section typée ; la même instance est renvoyée à chaque appel."""
        name = cls.SECTION  # type: ignore[attr-defined]
        if name not in self._sections:
            self._sections[name] = section_from_dict(cls, self._raw.get(name))
        return self._sections[name]

    def store(self, name: str) -> dict[str, Any]:
        """Section libre (clé → valeur JSON), pour les données sans schéma fixe : historique,
        arbitrages mémorisés… Le dictionnaire renvoyé est modifié sur place puis enregistré
        par ``save()``."""
        value = self._raw.get(name)
        if not isinstance(value, dict):
            value = {}
            self._raw[name] = value
        return value

    @property
    def general(self) -> GeneralSettings:
        return self.section(GeneralSettings)

    def to_dict(self) -> dict[str, Any]:
        data = dict(self._raw)
        for name, section in self._sections.items():
            data[name] = asdict(section)
        data["schema"] = SCHEMA_VERSION
        return data

    def save(self) -> None:
        """Écrit le fichier de façon atomique ; une erreur est journalisée, jamais propagée."""
        data = self.to_dict()
        tmp = self.path.with_suffix(".json.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)
            self._raw = data
        except OSError as exc:
            log.error("Enregistrement des réglages impossible : %s", exc)
