"""Décisions de la surveillance, sans Qt ni Win32 : correspondance des titres, anti-rebond."""

from __future__ import annotations

from collections.abc import Callable, Iterable

SUCCESS_COOLDOWN_S = 1.0  # une fenêtre validée n'est pas retraitée pendant 1 s
FAIL_COOLDOWN_S = 5.0  # après les tentatives épuisées, on la laisse tranquille 5 s
FOREIGN_COOLDOWN_S = 60.0  # bon titre mais autre processus : signalée une fois par minute


def normalize_patterns(titles: Iterable[str]) -> tuple[str, ...]:
    """Motifs en minuscules, calculés une fois (et non à chaque fenêtre examinée)."""
    return tuple(t.strip().lower() for t in titles if t and t.strip())


def title_matches(title: str, patterns: tuple[str, ...]) -> bool:
    """Correspondance en sous-chaîne, insensible à la casse."""
    if not title:
        return False
    lowered = title.lower()
    return any(p in lowered for p in patterns)


def same_process(name: str, expected: str) -> bool:
    return bool(name) and name.lower() == expected.lower()


class Cooldowns:
    """Fenêtres à ne pas retraiter avant une échéance."""

    def __init__(self) -> None:
        self._until: dict[int, float] = {}

    def add(self, hwnd: int, seconds: float, now: float) -> None:
        self._until[hwnd] = now + seconds

    def active(self, hwnd: int, now: float) -> bool:
        return self._until.get(hwnd, 0.0) > now

    def prune(self, now: float, alive: Callable[[int], bool]) -> None:
        """Oublie les échéances passées et les fenêtres détruites."""
        self._until = {h: t for h, t in self._until.items() if t > now and alive(h)}

    def clear(self) -> None:
        self._until.clear()

    def __len__(self) -> int:
        return len(self._until)
