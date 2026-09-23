r"""Chargement et sauvegarde de la configuration utilisateur.

Le fichier vit dans ``%APPDATA%\pyFTOLogReader\settings.json``. Les mots de
passe y sont chiffrés par la DPAPI (voir :mod:`app.dpapi`) ; le reste est en
clair pour rester lisible et modifiable à la main en cas de besoin.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .. import APP_NAME
from . import dpapi


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
            name="Erreurs",
            keywords=["erreur", "error", "exception", "échec", "echec", "fail", "failed", "failure"],
            color="#E53935",
        ),
        HighlightRule(
            name="Avertissements",
            keywords=["warning", "avertissement", "warn", "attention"],
            color="#F4B400",
        ),
        HighlightRule(
            name="Communication perdue",
            keywords=["timeout", "disconnect", "déconnex", "deconnex", "lost", "perdu", "unreachable", "refused"],
            color="#FB8C00",
        ),
        HighlightRule(
            name="Succès",
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

    # ---------------------------------------------------------------- chemins

    @staticmethod
    def config_dir() -> Path:
        base = os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / APP_NAME

    @classmethod
    def config_path(cls) -> Path:
        return cls.config_dir() / "settings.json"

    # --------------------------------------------------------- (dé)sérialisation

    @classmethod
    def load(cls) -> "Settings":
        path = cls.config_path()
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # Configuration illisible : on repart des valeurs par défaut plutôt
            # que d'empêcher le démarrage.
            return cls()
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        settings = cls()
        for key, value in data.items():
            if not hasattr(settings, key):
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
                setattr(settings, key, value)
        return settings

    def to_dict(self) -> dict:
        data = asdict(self)
        for item in data["credentials"]:
            item["password"] = dpapi.protect(item["password"])
        return data

    def save(self) -> None:
        path = self.config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        # Écriture atomique : on ne veut pas d'un settings.json tronqué si
        # l'application est fermée pendant la sauvegarde.
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        temp.replace(path)

    # ------------------------------------------------------------------ utile

    def enabled_credentials(self) -> list[Credential]:
        return [c for c in self.credentials if c.enabled]

    def log_relative_path(self) -> str:
        r"""Chemin du log relatif à la racine du partage, ex. ``Log\FTOptixRuntime.0.log``."""
        return str(Path(self.log_subdir) / self.log_filename)
