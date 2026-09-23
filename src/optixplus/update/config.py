"""Réglages des mises à jour (section ``updates`` de settings.json)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from .github import FREQUENCY_DAILY


@dataclass
class UpdateSettings:
    SECTION: ClassVar[str] = "updates"

    auto_check: bool = True
    frequency: str = FREQUENCY_DAILY  # startup | daily | weekly
    include_prereleases: bool = False
    last_check: str = ""  # ISO 8601, UTC
    skipped_version: str = ""
