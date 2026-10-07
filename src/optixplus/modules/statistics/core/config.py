"""Réglages de l'outil Statistiques (section ``statistics`` de ``settings.json``, sans Qt)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from .model import StatisticsOptions


def parse_keywords(text: str) -> tuple[str, ...]:
    """Mots-clés d'une entrée (séparés par des virgules) : sans espaces superflus, sans vides ni doublons
    (casse ignorée), dans l'ordre saisi."""
    seen: set[str] = set()
    keywords: list[str] = []
    for part in text.split(","):
        word = part.strip()
        if word and word.lower() not in seen:
            seen.add(word.lower())
            keywords.append(word)
    return tuple(keywords)


def normalise_entries(entries: list[str]) -> list[str]:
    """Entrées normalisées (``mot, mot``), sans entrée vide ni entrée en double."""
    seen: set[tuple[str, ...]] = set()
    result: list[str] = []
    for entry in entries:
        keywords = parse_keywords(entry)
        key = tuple(k.lower() for k in keywords)
        if keywords and key not in seen:
            seen.add(key)
            result.append(", ".join(keywords))
    return result


@dataclass
class StatisticsSettings:
    """Pages à mettre en évidence (catégorie Statistics de la fenêtre Paramètres).

    Chaque entrée est un texte de mots-clés séparés par des virgules (``Alpha, Beta``) ; la liste est vide
    par défaut. Les anciennes clés d'un ``settings.json`` existant sont ignorées, puis disparaissent à l'écriture.
    """

    SECTION: ClassVar[str] = "statistics"

    highlighted: list[str] = field(default_factory=list)

    def options(self) -> StatisticsOptions:
        """Options du calcul : un tuple de mots-clés par entrée exploitable."""
        entries = (parse_keywords(e) for e in self.highlighted if isinstance(e, str))
        return StatisticsOptions(tuple(k for k in entries if k))
