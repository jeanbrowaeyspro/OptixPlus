"""Contrat commun des outils intégrés à OptixPlus.

Chaque outil est décrit par un ``ModuleSpec`` léger (titre, icône, raccourci, chemin
d'import) : la barre latérale s'en sert sans importer l'outil. L'outil lui-même
(``ToolModule``) n'est importé qu'à la première ouverture de sa page.

Un ``ToolModule`` appartient à la fenêtre principale : il est détruit avec elle. Ce qui
doit survivre à la fenêtre (la surveillance d'Auto Validate) est un service porté par
le contrôleur de l'application, pas par le module.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QWidget

if TYPE_CHECKING:
    from ..shell.context import AppContext


@dataclass(frozen=True)
class ModuleSpec:
    """Description d'un outil, disponible sans l'importer."""

    id: str
    title: str  # texte source anglais, traduit à l'affichage
    description: str  # idem
    icon: str  # nom du SVG dans resources/icons
    shortcut: str
    import_path: str  # "paquet.module:Classe"
    # Service d'arrière-plan facultatif, créé au démarrage et indépendant de la fenêtre.
    service_path: str = ""

    def load(self) -> type[ToolModule]:
        return _import(self.import_path)

    def load_service(self) -> type[BackgroundService] | None:
        return _import(self.service_path) if self.service_path else None


def _import(path: str):
    module_name, class_name = path.split(":")
    return getattr(importlib.import_module(module_name), class_name)


class ToolModule(QObject):
    """Un outil affiché dans la fenêtre principale."""

    def __init__(self, spec: ModuleSpec, context: AppContext, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.spec = spec
        self.context = context

    def create_page(self, parent: QWidget) -> QWidget:
        """Construit la page de l'outil (appelé une seule fois)."""
        raise NotImplementedError

    def toolbar_actions(self) -> list[QAction | None]:
        """Actions de la barre d'outils contextuelle ; ``None`` insère un séparateur."""
        return []

    def on_activated(self) -> None:
        """La page devient visible : reprendre rafraîchissements et minuteurs."""

    def on_deactivated(self) -> None:
        """La page est masquée : suspendre ce qui ne sert qu'à l'affichage."""

    def can_close(self) -> bool:
        """Faux pour refuser la fermeture (traitement en cours que l'utilisateur veut garder)."""
        return True

    def shutdown(self) -> None:
        """Arrêt propre : threads arrêtés sans ``terminate()``, réglages enregistrés."""

    def handle_command(self, command: str, args: list[str]) -> bool:
        """Demande venue d'ailleurs (tray, second lancement) ; vrai si traitée."""
        return False

    def settings_page(self, parent: QWidget) -> QWidget | None:
        """Page de réglages de l'outil dans la boîte Paramètres (facultatif)."""
        return None


class BackgroundService(QObject):
    """Partie d'un outil qui vit tant que l'application tourne, fenêtre ouverte ou non.

    La coquille ne connaît les services qu'à travers cette interface : icône et menu du
    tray, carte de l'accueil, barre d'état.
    """

    state_changed = Signal()
    notification = Signal(str)  # message à afficher en bulle du tray

    def __init__(self, spec: ModuleSpec, context: AppContext, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.spec = spec
        self.context = context

    def start(self) -> None:
        """Démarrage de l'application."""

    def stop(self) -> None:
        """Arrêt de l'application : libérer les ressources système."""

    @property
    def suspended(self) -> bool:
        """Vrai si le service est en pause (icône du tray grisée)."""
        return False

    def status_text(self) -> str:
        """État court pour la barre d'état et l'infobulle du tray."""
        return ""

    def tray_actions(self, parent: QObject) -> list[QAction | None]:
        """Entrées ajoutées au menu du tray ; ``None`` insère un séparateur."""
        return []

    def summary_widget(self, parent: QWidget) -> QWidget | None:
        """Carte affichée sur la page d'accueil (facultatif)."""
        return None
