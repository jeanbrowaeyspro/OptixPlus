"""Contexte partagé par la coquille et les outils : réglages, thème, mode de lancement."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from ..common.settings import Settings
from ..common.theme import ThemeManager

if TYPE_CHECKING:
    from ..modules.base import BackgroundService
    from .controller import AppController


class LaunchMode(Enum):
    """Mode de lancement, détecté au démarrage."""

    INSTALLED = "installed"  # résident dans le tray, surveillance active
    DISCOVERY = "discovery"  # sans tray : fermer la fenêtre arrête tout


@dataclass
class AppContext:
    settings: Settings
    theme: ThemeManager
    mode: LaunchMode
    controller: AppController
    services: dict[str, BackgroundService] = field(default_factory=dict)

    @property
    def installed(self) -> bool:
        return self.mode is LaunchMode.INSTALLED
