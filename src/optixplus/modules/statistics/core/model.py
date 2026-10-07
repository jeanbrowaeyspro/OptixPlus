"""Résultat d'une analyse statistique d'un projet ou d'un runtime FT Optix (sans Qt).

Contrat entre le calcul (``stats.compute``) et la page : les noms de champs ci-dessous sont figés.
"""

from __future__ import annotations

from dataclasses import dataclass, field

KIND_PROJECT = "project"
KIND_RUNTIME = "runtime"

#: Types de vues retenus pour ``PageStats.kind``.
VIEW_SCREEN = "screen"
VIEW_DIALOG = "dialog"
VIEW_POPUP = "popup"
VIEW_WINDOW = "window"


@dataclass(frozen=True)
class StatisticsOptions:
    """Réglages de l'analyse."""

    #: Noms (affichés ou techniques, insensibles à la casse) qui désignent la page « Travail ».
    work_names: tuple[str, ...] = ("Work", "Travail")
    #: Idem pour la page « Supervision ».
    supervision_names: tuple[str, ...] = ("Supervision", "Overwatch")


@dataclass
class StationStats:
    """Une connexion à un automate (station d'un pilote de communication)."""

    name: str
    path: str
    driver_type: str = ""  # ex. CODESYSDriver
    station_type: str = ""  # ex. CODESYSStation
    address: str = ""  # adresse IP ou nom lu dans la station, vide si absent
    port: str = ""
    tags: int = 0  # variables synchronisées avec l'automate (tags simples + structures)
    structures: int = 0  # dont structures (TagStructure)


@dataclass
class PageStats:
    """Une vue de l'interface (écran, boîte de dialogue, popup, fenêtre)."""

    name: str  # nom technique du nœud
    title: str  # nom affiché (DisplayName ou texte du bouton de menu qui l'ouvre), sinon ``name``
    kind: str  # VIEW_*
    path: str
    is_main: bool = False  # page principale : écran ouvert depuis le menu ou le démarrage
    #: Liaisons : propriétés d'objets de la page et de ses sous-vues liées à un tag d'automate
    #: (nœuds ``DynamicLink`` ou pointeurs distincts) ; un tag lié à trois objets compte pour 3.
    links: int = 0
    #: Tags d'automate distincts liés (chemins distincts) ; un tag lié à trois objets compte pour 1.
    tags: int = 0
    approximate: bool = False  # vrai si des chemins dynamiques n'ont pas pu être résolus
    subviews: int = 0  # sous-vues (panneaux) utilisées par la page


@dataclass
class PageRow:
    """Une ligne du tableau des pages : une page principale sans onglet, ou une feuille d'onglet.

    ``tabs`` donne les titres affichés des onglets traversés (vide pour une page sans onglet) ; une page à
    onglets n'a pas de ligne de total. Les chiffres comptent la sous-vue de la ligne et ses propres sous-vues.
    """

    page: str  # titre affiché de la page
    path: str  # chemin du nœud de la page
    tabs: list[str] = field(default_factory=list)
    links: int = 0  # liaisons (propriétés d'objets liées à un tag d'automate)
    tags: int = 0  # tags d'automate distincts liés
    approximate: bool = False
    subviews: int = 0
    tab_unknown: bool = False  # ligne de résumé d'une page à onglets dont l'onglet par défaut est inconnu

    @property
    def label(self) -> str:
        """``Page``, ``Page/Onglet`` ou ``Page/Onglet/Onglet``."""
        return "/".join([self.page, *self.tabs])


@dataclass
class ProjectStatistics:
    name: str
    folder: str
    kind: str = KIND_PROJECT  # KIND_*
    # --- version
    ide_version: str = ""  # IDEVersion.txt, ex. 1.6.4.11-Stable
    product_version: str = ""  # champ ProductVersion du .optix
    core_version: str = ""
    # --- nœuds
    studio_counts: dict[str, int] = field(default_factory=dict)  # chiffres écrits par Studio dans le .optix
    nodes: int = 0  # nœuds comptés par OptixPlus
    files: int = 0  # fichiers YAML lus
    # --- automates
    stations: list[StationStats] = field(default_factory=list)
    tags_total: int = 0
    structures_total: int = 0
    # --- pages
    pages: list[PageStats] = field(default_factory=list)  # toutes les vues, principales d'abord
    main_pages: int = 0
    average_tags_per_main_page: float = 0.0
    busiest_page: PageStats | None = None  # page principale avec le plus de tags liés
    work_page: PageStats | None = None
    supervision_page: PageStats | None = None
    #: Lignes du tableau : pages principales et feuilles d'onglet (ni sous-vues, ni dialogues, ni popups).
    rows: list[PageRow] = field(default_factory=list)
    #: Ligne de la page « Travail » / « Supervision » à son onglet par défaut (la feuille atteinte en suivant
    #: les onglets par défaut), ou la page entière si elle n'a pas d'onglet ; ``tab_unknown`` si l'onglet
    #: par défaut est inconnu (total de la page). ``None`` si la page est introuvable.
    work_row: PageRow | None = None
    supervision_row: PageRow | None = None
    # --- autres objets
    alarms: int = 0
    netlogic: int = 0
    loggers: int = 0  # DataLogger + EventLogger
    # --- fichiers du projet
    image_files: int = 0
    image_bytes: int = 0
    font_files: int = 0
    font_bytes: int = 0
    project_files_bytes: int = 0
    # --- runtime seulement : ``(nom, octets)`` des bases (SQLite, rétentivité) de ApplicationFiles
    runtime_files: list[tuple[str, int]] = field(default_factory=list)
    #: Remarques à afficher (analyse approximative, fichier relu avec PyYAML, type de pilote inconnu…)
    warnings: list[str] = field(default_factory=list)
