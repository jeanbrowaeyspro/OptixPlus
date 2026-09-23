"""Remontée de progression et annulation, sans dépendance à Qt (repris de FTOCompare).

Le moteur reçoit un rappel de progression et une fonction d'annulation ; l'interface les branche
sur ses signaux. Le moteur ne sait pas qui l'écoute.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Progress:
    """Un pas de progression : phase en cours, élément traité, position dans la phase."""

    phase: str
    current: str
    index: int
    total: int


ProgressCallback = Callable[[Progress], None]
CancelCheck = Callable[[], bool]


class Cancelled(Exception):
    """Levée par le moteur quand l'utilisateur a annulé le traitement."""


def report(callback: ProgressCallback | None, phase: str, current: str, index: int, total: int) -> None:
    """Appelle le rappel de progression s'il existe."""
    if callback is not None:
        callback(Progress(phase, current, index, total))


def check_cancel(cancel: CancelCheck | None) -> None:
    """Lève ``Cancelled`` si l'annulation a été demandée."""
    if cancel is not None and cancel():
        raise Cancelled()
