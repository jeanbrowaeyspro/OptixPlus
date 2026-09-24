"""Versions publiées sur GitHub Releases : lecture de l'API, comparaison, planification.

Sans Qt. Une seule requête HTTPS anonyme par vérification, avec pour seule information
envoyée l'en-tête ``User-Agent: OptixPlus/<version>``.
"""

from __future__ import annotations

import json
import logging
import re
import ssl
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from ..common.i18n import tr
from ..version import APP_NAME, GITHUB_REPO, __version__

log = logging.getLogger("optixplus.update")

API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases"
TIMEOUT_S = 10
INSTALLER_PATTERN = re.compile(r"^OptixPlus-Setup-.+\.exe$", re.IGNORECASE)

FREQUENCY_STARTUP = "startup"
FREQUENCY_DAILY = "daily"
FREQUENCY_WEEKLY = "weekly"
FREQUENCIES = (FREQUENCY_STARTUP, FREQUENCY_DAILY, FREQUENCY_WEEKLY)
_INTERVALS = {FREQUENCY_DAILY: timedelta(days=1), FREQUENCY_WEEKLY: timedelta(days=7)}
#: Délai minimal entre deux vérifications automatiques, quel que soit le réglage :
#: l'API anonyme de GitHub limite le nombre de requêtes par heure.
MIN_INTERVAL = timedelta(hours=1)


class UpdateError(Exception):
    """Vérification ou téléchargement impossible ; le message est prêt à afficher."""


# --------------------------------------------------------------------------- versions
_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")


@dataclass(frozen=True, order=False)
class Version:
    """Version sémantique ``X.Y.Z[-préversion]`` ; une préversion précède la version finale."""

    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...] = ()

    @classmethod
    def parse(cls, text: str) -> Version:
        match = _VERSION.match(text.strip())
        if match is None:
            raise ValueError(f"version invalide : {text!r}")
        pre = tuple(match.group(4).split(".")) if match.group(4) else ()
        return cls(int(match.group(1)), int(match.group(2)), int(match.group(3)), pre)

    @property
    def is_prerelease(self) -> bool:
        return bool(self.prerelease)

    def _key(self) -> tuple:
        # Version finale après toutes ses préversions ; identifiants numériques avant
        # les identifiants textuels, comparés numériquement (règles semver).
        pre = tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in self.prerelease)
        return (self.major, self.minor, self.patch, 0 if self.prerelease else 1, pre)

    def __lt__(self, other: Version) -> bool:
        return self._key() < other._key()

    def __le__(self, other: Version) -> bool:
        return self._key() <= other._key()

    def __gt__(self, other: Version) -> bool:
        return self._key() > other._key()

    def __ge__(self, other: Version) -> bool:
        return self._key() >= other._key()

    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        return f"{base}-{'.'.join(self.prerelease)}" if self.prerelease else base


# --------------------------------------------------------------------------- releases
@dataclass(frozen=True)
class Asset:
    name: str
    url: str
    size: int = 0


@dataclass(frozen=True)
class Release:
    version: Version
    tag: str
    name: str
    notes: str
    page_url: str
    published: str = ""
    assets: tuple[Asset, ...] = field(default_factory=tuple)

    @property
    def installer(self) -> Asset | None:
        return next((a for a in self.assets if INSTALLER_PATTERN.match(a.name)), None)

    @property
    def checksum(self) -> Asset | None:
        installer = self.installer
        if installer is None:
            return None
        wanted = (installer.name + ".sha256").lower()
        return next((a for a in self.assets if a.name.lower() == wanted), None) or next(
            (a for a in self.assets if a.name.lower().endswith(".sha256")), None
        )

    @property
    def installable(self) -> bool:
        return self.installer is not None and self.checksum is not None


def release_from_json(data: dict) -> Release | None:
    """Release publiée lue dans la réponse de l'API ; ``None`` si brouillon ou tag illisible."""
    if not isinstance(data, dict) or data.get("draft"):
        return None
    tag = str(data.get("tag_name") or "")
    try:
        version = Version.parse(tag)
    except ValueError:
        log.warning("Release ignorée, tag illisible : %r", tag)
        return None
    assets = tuple(
        Asset(str(a.get("name", "")), str(a.get("browser_download_url", "")), int(a.get("size") or 0))
        for a in data.get("assets") or []
        if isinstance(a, dict) and a.get("browser_download_url")
    )
    return Release(
        version=version,
        tag=tag,
        name=str(data.get("name") or tag),
        notes=str(data.get("body") or ""),
        page_url=str(data.get("html_url") or f"https://github.com/{GITHUB_REPO}/releases"),
        published=str(data.get("published_at") or ""),
        assets=assets,
    )


Opener = Callable[..., object]


def https_context() -> ssl.SSLContext:
    """Contexte TLS vérifié par Windows (magasin de certificats du système).

    L'OpenSSL embarqué ne connaît que les racines déjà présentes dans le magasin ; Windows,
    lui, télécharge au besoin une racine manquante et reconnaît celles d'un antivirus ou d'un
    proxy d'entreprise. Sans ``truststore``, repli sur le contexte par défaut de Python.
    """
    try:
        import truststore
    except ImportError:
        return ssl.create_default_context()
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def urlopen(request, timeout: float = TIMEOUT_S):
    """``urllib.request.urlopen`` avec la vérification TLS de Windows."""
    return urllib.request.urlopen(request, timeout=timeout, context=https_context())


def _get_json(url: str, opener: Opener) -> object:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": f"{APP_NAME}/{__version__}", "Accept": "application/vnd.github+json"},
    )
    try:
        with opener(request, timeout=TIMEOUT_S) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None  # aucune release publiée
        if exc.code in (403, 429):
            raise UpdateError(tr("GitHub limits the number of checks for now. Try again in an hour.")) from exc
        raise UpdateError(tr("GitHub answered with an error ({code}).").format(code=exc.code)) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, ssl.SSLCertVerificationError):
            raise UpdateError(tr("The secure connection to GitHub could not be verified: {error}").format(error=reason)) from exc
        raise UpdateError(tr("GitHub cannot be reached: {error}").format(error=reason)) from exc
    except ValueError as exc:
        raise UpdateError(tr("Unreadable answer from GitHub.")) from exc


def latest_release(include_prereleases: bool = False, opener: Opener = urlopen) -> Release | None:
    """Dernière release publiée (préversions comprises si demandé), ou ``None``."""
    if not include_prereleases:
        data = _get_json(f"{API_URL}/latest", opener)
        return release_from_json(data) if isinstance(data, dict) else None
    data = _get_json(f"{API_URL}?per_page=20", opener)
    releases = [r for r in (release_from_json(d) for d in data or []) if r is not None] if isinstance(data, list) else []
    return max(releases, key=lambda r: r.version._key(), default=None)


def available_update(
    current: str = __version__,
    include_prereleases: bool = False,
    skipped: str = "",
    opener: Opener = urlopen,
) -> Release | None:
    """Release plus récente que ``current`` et différente de la version ignorée, sinon ``None``."""
    release = latest_release(include_prereleases, opener)
    if release is None or release.version <= Version.parse(current):
        return None
    if skipped and str(release.version) == skipped:
        log.info("Version %s disponible mais ignorée à la demande de l'utilisateur", release.version)
        return None
    return release


# --------------------------------------------------------------------------- planification
def parse_timestamp(text: str) -> datetime | None:
    try:
        moment = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def is_check_due(last_check: str, frequency: str, now: datetime, at_startup: bool) -> bool:
    """Faut-il vérifier maintenant ?

    Au démarrage, puis périodiquement selon la fréquence : « au démarrage seulement » ne
    vérifie qu'au lancement ; quotidienne et hebdomadaire dès que l'intervalle est écoulé.
    Jamais deux vérifications automatiques à moins d'une heure d'écart.
    """
    last = parse_timestamp(last_check)
    if last is not None and now - last < MIN_INTERVAL:
        return False
    if frequency == FREQUENCY_STARTUP or frequency not in FREQUENCIES:
        return at_startup
    return last is None or now - last >= _INTERVALS[frequency]
