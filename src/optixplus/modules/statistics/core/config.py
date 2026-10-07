"""Réglages de l'outil Statistiques (section ``statistics`` de ``settings.json``, sans Qt)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from .model import StatisticsOptions

#: Ancienne valeur par défaut de la supervision, enregistrée à tort dans des ``settings.json``.
_LEGACY_SUPERVISION = ["Supervision"]


def _same_names(a: list, b: tuple[str, ...]) -> bool:
    return [str(n).strip().lower() for n in a] == [n.lower() for n in b]


@dataclass
class StatisticsSettings:
    """Noms des pages « Travail » et « Supervision » (page de la fenêtre Paramètres : catégorie Statistics).

    ``None`` (valeur par défaut, écrite ``null``) = noms par défaut du calcul : on ne fige jamais une liste
    que l'utilisateur n'a pas personnalisée, pour que les noms par défaut ajoutés plus tard soient pris en compte.
    """

    SECTION: ClassVar[str] = "statistics"

    work_names: list[str] | None = None
    supervision_names: list[str] | None = None

    def migrate(self) -> None:
        """Après lecture du fichier : une liste égale aux valeurs par défaut (ou à l'ancienne valeur par
        défaut de la supervision, « Supervision » seule) redevient « par défaut »."""
        defaults = StatisticsOptions()
        if isinstance(self.work_names, list) and _same_names(self.work_names, defaults.work_names):
            self.work_names = None
        if isinstance(self.supervision_names, list) and (
            _same_names(self.supervision_names, defaults.supervision_names)
            or _same_names(self.supervision_names, tuple(_LEGACY_SUPERVISION))
        ):
            self.supervision_names = None

    def set_names(self, work: list[str], supervision: list[str]) -> None:
        """Enregistre les noms saisis ; une liste égale aux valeurs par défaut n'est pas figée."""
        self.work_names = list(work)
        self.supervision_names = list(supervision)
        defaults = StatisticsOptions()
        if _same_names(self.work_names, defaults.work_names):
            self.work_names = None
        if _same_names(self.supervision_names, defaults.supervision_names):
            self.supervision_names = None

    def options(self) -> StatisticsOptions:
        """Options du calcul ; une valeur absente ou vide retombe sur les noms par défaut."""
        defaults = StatisticsOptions()

        def names(value, fallback: tuple[str, ...]) -> tuple[str, ...]:
            if not isinstance(value, list):
                return fallback
            return tuple(n for n in value if isinstance(n, str) and n.strip()) or fallback

        return StatisticsOptions(
            names(self.work_names, defaults.work_names), names(self.supervision_names, defaults.supervision_names)
        )
