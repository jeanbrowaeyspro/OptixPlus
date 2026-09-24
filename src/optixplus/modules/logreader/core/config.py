r"""Réglages du Lecteur de logs.

Dans OptixPlus, ils sont rangés dans la section ``logreader`` du fichier de réglages
commun (``%APPDATA%\OptixPlus\settings.json``). Les mots de passe y restent chiffrés
par la DPAPI (``common.dpapi``) ; le reste est en clair pour rester lisible.

Chaque automate est décrit par l'utilisateur (``Controller``) : nom, adresse, identifiant,
mot de passe et dossier des journaux. Les réglages d'avant (liste d'adresses et liste
d'identifiants communes, partage et sous-dossier communs) sont convertis à la lecture.

Corrections par rapport à pyFTOLogReader : chaque valeur lue est validée contre le type
de sa valeur par défaut (une valeur invalide est ignorée et signalée, au lieu d'être
injectée telle quelle).
"""

from __future__ import annotations

import logging
import ntpath
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, fields, replace

from ....common import dpapi
from ....common.i18n import tr
from ....common.settings import _coerce, _default_of

log = logging.getLogger("optixplus.logreader")


@dataclass
class Credential:
    """Identifiants essayés lors de la connexion au partage d'un automate."""

    label: str = ""
    username: str = ""
    password: str = ""
    enabled: bool = True


#: Dossier des journaux d'un nouvel automate : partage « Optix », sous-dossier « Log ».
DEFAULT_LOG_DIR = "Optix\\Log"
#: Fichier journal d'un nouvel automate (journal du runtime FT Optix).
DEFAULT_LOG_FILENAME = "FTOptixRuntime.0.log"


def _new_id() -> str:
    return uuid.uuid4().hex


@dataclass
class Controller:
    r"""Un automate décrit par l'utilisateur.

    ``log_dir`` est le dossier des journaux :

    * relatif (``Optix\Log``) : sur l'automate, à l'adresse ``host`` ; le premier
      élément est le partage Windows (``\\<host>\Optix\Log``) ;
    * absolu : un dossier local (``C:\...``) ou un chemin réseau complet (``\\...``),
      utilisé tel quel.

    Seul le dossier est obligatoire. L'adresse est facultative, sauf pour un dossier
    relatif, qui se trouve sur l'automate. Sans identifiant, la session Windows courante
    est utilisée.
    """

    id: str = field(default_factory=_new_id)
    name: str = ""
    host: str = ""
    username: str = ""
    password: str = ""
    log_dir: str = DEFAULT_LOG_DIR
    #: Fichier journal lu dans ce dossier (propre à l'automate : un FT Optix de
    #: développement n'écrit pas forcément le même que le runtime d'une machine).
    log_filename: str = DEFAULT_LOG_FILENAME

    @property
    def display_name(self) -> str:
        return self.name.strip() or self.host.strip() or self.log_dir.strip()

    def is_absolute(self) -> bool:
        return ntpath.isabs(self.log_dir.strip()) or self.log_dir.strip().startswith("\\\\")

    def is_local(self) -> bool:
        """Dossier local (lecteur du poste) : aucune connexion réseau."""
        return self.is_absolute() and not self.log_dir.strip().startswith("\\\\")

    def network_share(self) -> tuple[str, str] | None:
        """``(serveur, partage)`` auquel se connecter, ou ``None`` pour un dossier local."""
        path = self.log_dir.strip().replace("/", "\\")
        if self.is_local():
            return None
        if path.startswith("\\\\"):
            parts = [p for p in path[2:].split("\\") if p]
            return (parts[0], parts[1]) if len(parts) >= 2 else None
        parts = [p for p in path.split("\\") if p]
        return (self.host.strip(), parts[0]) if parts and self.host.strip() else None

    def log_folder(self) -> str:
        """Chemin complet du dossier des journaux."""
        from . import netshare

        path = self.log_dir.strip().replace("/", "\\")
        if self.is_absolute():
            return path
        parts = [p for p in path.split("\\") if p]
        if not parts:
            return ""
        return ntpath.join(netshare.unc_path(self.host.strip(), parts[0]), *parts[1:])

    def log_path(self) -> str:
        """Chemin complet du fichier journal."""
        return ntpath.join(self.log_folder(), self.log_filename.strip() or DEFAULT_LOG_FILENAME)

    def credentials(self) -> list[Credential]:
        """Identifiants à essayer après la session Windows (aucun si l'identifiant est vide)."""
        if not self.username.strip():
            return []
        return [Credential(label=self.display_name, username=self.username.strip(), password=self.password)]

    def validation_error(self) -> str:
        """Message si l'automate est incomplet, chaîne vide sinon."""
        if not self.log_dir.strip():
            return tr("The log folder is required.")
        if not self.is_absolute() and not self.host.strip():
            return tr("A relative log folder is on the controller: enter its IP address, or choose a full folder.")
        return ""

    def duplicate(self) -> Controller:
        """Copie à modifier (nouvel identifiant interne, nom marqué « copie »)."""
        name = tr("{name} (copy)").format(name=self.name) if self.name.strip() else ""
        return replace(self, id=_new_id(), name=name)


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
    """Aucune adresse par défaut : chaque utilisateur saisit celles de ses automates."""
    return []


def default_credentials() -> list[Credential]:
    """Aucun identifiant par défaut : la session Windows est tentée, puis ceux saisis."""
    return []


def controllers_from_legacy(data: dict) -> list[Controller]:
    """Automates déduits des anciens réglages : une adresse = un automate.

    Le dossier reprend l'ancien partage et l'ancien sous-dossier ; les identifiants sont
    ceux du premier jeu actif de l'ancienne liste commune.
    """
    hosts = [h for h in data.get("hosts") or [] if isinstance(h, str) and h.strip()]
    share = data.get("share_name") if isinstance(data.get("share_name"), str) else "Optix"
    subdir = data.get("log_subdir") if isinstance(data.get("log_subdir"), str) else "Log"
    log_dir = "\\".join(p for p in (share.strip("\\/ "), subdir.strip("\\/ ")) if p) or DEFAULT_LOG_DIR
    username = password = ""
    for item in data.get("credentials") or []:
        if isinstance(item, dict) and item.get("enabled", True) and item.get("username"):
            username = str(item.get("username", ""))
            password = dpapi.unprotect(item.get("password", ""))
            break
    filename = data.get("log_filename") if isinstance(data.get("log_filename"), str) else ""
    filename = filename.strip() or DEFAULT_LOG_FILENAME
    return [
        Controller(host=h.strip(), username=username, password=password, log_dir=log_dir, log_filename=filename)
        for h in hosts
    ]


@dataclass
class Settings:
    """Réglages complets de l'application."""

    #: ``system``, ``light`` ou ``dark``.
    theme: str = "system"
    controllers: list[Controller] = field(default_factory=list)
    highlight_rules: list[HighlightRule] = field(default_factory=default_rules)

    #: Période d'interrogation du fichier pour le suivi en direct, en ms.
    poll_interval_ms: int = 800
    #: Délai d'attente du ping lors de la découverte, en ms.
    ping_timeout_ms: int = 700
    #: Nombre maximal de lignes conservées en mémoire (0 = illimité).
    max_rows: int = 500_000

    autoscroll: bool = True
    show_details_panel: bool = True
    remember_last_host: bool = True
    #: Dernier automate ouvert : son identifiant (ou une adresse, réglages d'avant).
    last_host: str = ""
    #: Colonnes masquées, par identifiant de colonne.
    hidden_columns: list[str] = field(default_factory=list)
    #: Rouvrir à l'ouverture du Lecteur les journaux ouverts lors de la session précédente.
    reopen_logs: bool = True
    #: Automates des onglets ouverts (identifiant, ou adresse s'il n'est pas décrit),
    #: et disposition des onglets (base64 de QtAds).
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
        legacy_filename = data.get("log_filename") if isinstance(data.get("log_filename"), str) else ""
        legacy_filename = legacy_filename.strip() or DEFAULT_LOG_FILENAME
        if "controllers" not in data and data.get("hosts"):
            settings.controllers = controllers_from_legacy(data)
            log.info("Lecteur de logs : %d automate(s) repris des anciens réglages", len(settings.controllers))
        for key, value in data.items():
            if key not in defaults:
                continue
            if key in ("controllers", "highlight_rules") and not isinstance(value, list):
                log.warning("Réglage logreader.%s invalide, valeur par défaut utilisée", key)
                continue
            if key == "controllers":
                settings.controllers = [
                    Controller(
                        id=str(item.get("id") or _new_id()),
                        name=str(item.get("name", "")),
                        host=str(item.get("host", "")),
                        username=str(item.get("username", "")),
                        password=dpapi.unprotect(item.get("password", "")),
                        log_dir=str(item.get("log_dir", DEFAULT_LOG_DIR)),
                        # Réglages d'avant : nom de fichier commun à tous les automates.
                        log_filename=str(item.get("log_filename") or legacy_filename),
                    )
                    for item in value
                    if isinstance(item, dict)
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
        for item in data["controllers"]:
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

    def find_controller(self, key: str) -> Controller | None:
        """Automate par identifiant, sinon par adresse (casse ignorée)."""
        key = (key or "").strip()
        if not key:
            return None
        for controller in self.controllers:
            if controller.id == key:
                return controller
        return next((c for c in self.controllers if c.host.strip().casefold() == key.casefold()), None)

    def controller_for(self, key: str) -> Controller:
        """Automate décrit, ou automate de passage à cette adresse (dossier par défaut)."""
        return self.find_controller(key) or Controller(host=key)
