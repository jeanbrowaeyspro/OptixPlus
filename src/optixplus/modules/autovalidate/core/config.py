"""Réglages de la surveillance (section ``autovalidate`` de ``settings.json``)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

DEFAULT_TITLES = ("Le projet existe déjà", "Project already exists")
DEFAULT_PROCESS = "FTOptixStudio.exe"


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


@dataclass
class AutoValidateSettings:
    SECTION: ClassVar[str] = "autovalidate"

    enabled: bool = True
    titles: list[str] = field(default_factory=lambda: list(DEFAULT_TITLES))
    process_name: str = DEFAULT_PROCESS
    restore_focus: bool = True
    notify: bool = True
    max_retries: int = 3
    retry_delay_ms: int = 300
    # Filet de sécurité : les événements Windows suffisent normalement, une vérification
    # lente rattrape un événement manqué.
    fallback_scan_ms: int = 2000

    def normalized(self) -> AutoValidateSettings:
        titles = [t.strip() for t in self.titles if isinstance(t, str) and t.strip()]
        self.titles = titles or list(DEFAULT_TITLES)
        self.process_name = (self.process_name or "").strip() or DEFAULT_PROCESS
        self.max_retries = _clamp(self.max_retries, 1, 10)
        self.retry_delay_ms = _clamp(self.retry_delay_ms, 50, 5000)
        self.fallback_scan_ms = _clamp(self.fallback_scan_ms, 500, 60_000)
        return self

    def restore_defaults(self) -> None:
        """Remet les réglages par défaut, sans toucher à l'état actif/suspendu."""
        enabled = self.enabled
        defaults = AutoValidateSettings()
        for name in vars(defaults):
            setattr(self, name, getattr(defaults, name))
        self.enabled = enabled
