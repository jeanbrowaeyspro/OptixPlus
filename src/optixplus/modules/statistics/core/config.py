"""Réglages de l'outil Statistiques (section ``statistics`` de ``settings.json``, sans Qt)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from .model import StatisticsOptions


def _defaults() -> StatisticsOptions:
    return StatisticsOptions()


@dataclass
class StatisticsSettings:
    """Noms des pages « Travail » et « Supervision » (page de la fenêtre Paramètres : catégorie Statistics)."""

    SECTION: ClassVar[str] = "statistics"

    work_names: list[str] = field(default_factory=lambda: list(_defaults().work_names))
    supervision_names: list[str] = field(default_factory=lambda: list(_defaults().supervision_names))

    def options(self) -> StatisticsOptions:
        """Options du calcul ; une liste vide retombe sur les noms par défaut."""
        defaults = _defaults()
        work = tuple(n for n in self.work_names if isinstance(n, str) and n.strip())
        supervision = tuple(n for n in self.supervision_names if isinstance(n, str) and n.strip())
        return StatisticsOptions(work or defaults.work_names, supervision or defaults.supervision_names)
