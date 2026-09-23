r"""Réglages du Lecteur de logs.

Dans OptixPlus, ils sont rangés dans la section ``logreader`` du fichier de réglages
commun (``%APPDATA%\OptixPlus\settings.json``). Les mots de passe y restent chiffrés
par la DPAPI (``common.dpapi``) ; le reste est en clair pour rester lisible.

Corrections par rapport à pyFTOLogReader : chaque valeur lue est validée contre le type
de sa valeur par défaut (une valeur invalide est ignorée et signalée, au lieu d'être
injectée telle quelle).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from ....common import dpapi
from ....common.i18n import tr
from ....common.settings import _coerce, _default_of

log = logging.getLogger("optixplus.logreader")


@dataclass
class Credential:
    """Un jeu d'identifiants essayé lors de la connexion à un IPC."""

    label: str = ""
    username: str = ""
    password: str = ""
    enabled: bool = True


@dataclass
class HighlightRule:
    """Règle de surlignage : une ligne contenant l'un des mots-clés est teintée.

    ``color`` est la teinte choisie par l'utilisateur. Elle est éclaircie sur
    fond clair et assombrie sur fond sombre, de sorte qu'une seule couleur
    suffise pour les deux thèmes.
    """

    name: str = ""
    keywords: list[str] = field(default_factory=list)
    color: str = "#E53935"
    enabled: bool = True
    whole_word: bool = False
    #: ``line`` = toute la ligne brute, ``message`` = colonne message seule.
    scope: str = "line"


def default_rules() -> list[HighlightRule]:
    """Règles livrées par défaut, évaluées dans l'ordre (première atteinte gagne)."""
    return [
        HighlightRule(
            name=tr("Errors"),
            keywords=["erreur", "error", "exception", "échec", "echec", "fail", "failed", "failure"],
            color="#E53935",
        ),
        HighlightRule(
            name=tr("Warnings"),
            keywords=["warning", "avertissement", "warn", "attention"],
            color="#F4B400",
        ),
        HighlightRule(
            name=tr("Communication lost"),
            keywords=["timeout", "disconnect", "déconnex", "deconnex", "lost", "perdu", "unreachable", "refused"],
            color="#FB8C00",
        ),
        HighlightRule(
            name=tr("Success"),
            keywords=["established", "success", "réussi", "reussi", "online", "started", "connected"],
            color="#2E9E5B",
        ),
    ]


def default_hosts() -> list[str]:
    return []


def default_credentials() -> list[Credential]:
    return []


@dataclass
class Settings:
    """Réglages complets de l'application."""

    #: ``system``, ``light`` ou ``dark``.
    theme: str = "system"
    hosts: list[str] = field(default_factory=default_hosts)
    credentials: list[Credential] = field(default_factory=default_credentials)
    highlight_rules: list[HighlightRule] = field(default_factory=default_rules)

    #: Nom du partage Windows et chemin du log à l'intérieur de celui-ci.
    share_name: str = "Optix"
    log_subdir: str = "Log"
    log_filename: str = "FTOptixRuntime.0.log"

    #: Période d'interrogation du fichier pour le suivi en direct, en ms.
    poll_interval_ms: int = 800
    #: Délai d'attente du ping lors de la découverte, en ms.
    ping_timeout_ms: int = 700
    #: Nombre maximal de lignes conservées en mémoire (0 = illimité).
    max_rows: int = 500_000

    autoscroll: bool = True
    show_details_panel: bool = True
    remember_last_host: bool = True
    last_host: str = ""
    #: Colonnes masquées, par identifiant de colonne.
    hidden_columns: list[str] = field(default_factory=list)
    #: Rouvrir à l'ouverture du Lecteur les journaux ouverts lors de la session précédente.
    reopen_logs: bool = True
    #: Automates des onglets ouverts, et disposition des onglets (base64 de QtAds).
    open_hosts: list[str] = field(default_factory=list)
    dock_state: str = ""

    def __post_init__(self) -> None:
        # Hors des champs de la dataclass : non sérialisé. Fonction d'enregistrement
        # fournie par OptixPlus ; absente (tests), ``save`` ne fait rien.
        self._writer: Callable[[dict], None] | None = None

    # --------------------------------------------------------- (dé)sérialisation

    @classmethod
    def bound(cls, store: dict, writer: Callable[[], None]) -> Settings:
        """Réglages lus dans ``store`` (section de settings.json) et enregistrés par ``writer``."""
        settings = cls.from_dict(store) if store else cls()

        def write(data: dict) -> None:
            store.clear()
            store.update(data)
            writer()

        settings._writer = write
        return settings

    @classmethod
    def from_dict(cls, data: dict) -> Settings:
        settings = cls()
        defaults = {f.name: _default_of(f) for f in fields(cls)}
        for key, value in data.items():
            if key not in defaults:
                continue
            if key in ("credentials", "highlight_rules") and not isinstance(value, list):
                log.warning("Réglage logreader.%s invalide, valeur par défaut utilisée", key)
                continue
            if key == "credentials":
                settings.credentials = [
                    Credential(
                        label=item.get("label", ""),
                        username=item.get("username", ""),
                        password=dpapi.unprotect(item.get("password", "")),
                        enabled=item.get("enabled", True),
                    )
                    for item in value
                ]
            elif key == "highlight_rules":
                settings.highlight_rules = [
                    HighlightRule(
                        name=item.get("name", ""),
                        keywords=list(item.get("keywords", [])),
                        color=item.get("color", "#E53935"),
                        enabled=item.get("enabled", True),
                        whole_word=item.get("whole_word", False),
                        scope=item.get("scope", "line"),
                    )
                    for item in value
                ]
            else:
                checked, ok = _coerce(value, defaults[key])
                if not ok:
                    log.warning("Réglage logreader.%s invalide (%r), valeur par défaut utilisée", key, value)
                setattr(settings, key, checked)
        return settings

    def to_dict(self) -> dict:
        data = asdict(self)
        for item in data["credentials"]:
            item["password"] = dpapi.protect(item["password"])
        return data

    def save(self) -> None:
        """Enregistre dans settings.json (écriture atomique assurée par OptixPlus)."""
        writer = getattr(self, "_writer", None)
        if writer is not None:
            writer(self.to_dict())

    def copy_binding_from(self, other: Settings) -> Settings:
        """Reprend la destination d'enregistrement d'un autre objet (boîte Paramètres)."""
        self._writer = getattr(other, "_writer", None)
        return self

    # ------------------------------------------------------------------ utile

    def enabled_credentials(self) -> list[Credential]:
        return [c for c in self.credentials if c.enabled]

    def log_relative_path(self) -> str:
        r"""Chemin du log relatif à la racine du partage, ex. ``Log\FTOptixRuntime.0.log``."""
        return str(Path(self.log_subdir) / self.log_filename)
