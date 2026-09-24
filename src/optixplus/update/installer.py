"""Installation d'une mise à jour : téléchargement, contrôle SHA-256, lancement de l'installateur.

Sans Qt. L'installateur n'est lancé que si son empreinte correspond à celle publiée avec la
release ; sinon le fichier est supprimé et rien n'est exécuté.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from ..common.i18n import tr
from ..common.progress import CancelCheck, Cancelled, ProgressCallback, check_cancel, report
from ..version import APP_NAME, __version__
from .github import Opener, Release, UpdateError

log = logging.getLogger("optixplus.update")

CHUNK = 256 * 1024
TIMEOUT_S = 30
#: Options de l'installateur Inno Setup : sans questions, en fermant OptixPlus. La relance
#: (avec ``--apres-maj``) est faite par l'installateur lui-même, une seule fois.
INSTALLER_ARGS = ("/SILENT", "/CLOSEAPPLICATIONS")
_HEX = re.compile(r"\b([0-9a-fA-F]{64})\b")


def download_dir() -> Path:
    path = Path(tempfile.gettempdir()) / f"{APP_NAME}-update"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _open(url: str, opener: Opener):
    request = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}/{__version__}"})
    try:
        return opener(request, timeout=TIMEOUT_S)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise UpdateError(tr("Download failed: {error}").format(error=reason)) from exc


def download(
    url: str,
    dest: Path,
    progress: ProgressCallback | None = None,
    cancel: CancelCheck | None = None,
    opener: Opener = urllib.request.urlopen,
    expected_size: int = 0,
) -> Path:
    """Télécharge ``url`` dans ``dest`` (fichier partiel supprimé en cas d'échec ou d'annulation)."""
    partial = dest.with_name(dest.name + ".part")
    phase = tr("Downloading the update")
    try:
        with _open(url, opener) as response, open(partial, "wb") as out:
            total = int(response.headers.get("Content-Length") or expected_size or 0)
            done = 0
            while True:
                check_cancel(cancel)
                chunk = response.read(CHUNK)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                report(progress, phase, dest.name, done, total)
        partial.replace(dest)
    except (Cancelled, UpdateError):
        partial.unlink(missing_ok=True)
        raise
    except OSError as exc:
        partial.unlink(missing_ok=True)
        raise UpdateError(tr("Download failed: {error}").format(error=exc)) from exc
    return dest


def expected_checksum(text: str, filename: str) -> str:
    """Empreinte lue dans un fichier ``.sha256`` (format ``sha256sum`` ou empreinte seule)."""
    lines = [line for line in text.splitlines() if line.strip()]
    for line in lines:
        match = _HEX.search(line)
        if match and filename.lower() in line.lower():
            return match.group(1).lower()
    for line in lines:
        match = _HEX.search(line)
        if match:
            return match.group(1).lower()
    raise UpdateError(tr("The published checksum is unreadable."))


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch_installer(
    release: Release,
    progress: ProgressCallback | None = None,
    cancel: CancelCheck | None = None,
    opener: Opener = urllib.request.urlopen,
    folder: Path | None = None,
) -> Path:
    """Télécharge l'installateur de ``release`` et vérifie son empreinte ; renvoie son chemin."""
    installer, checksum = release.installer, release.checksum
    if installer is None or checksum is None:
        raise UpdateError(tr("This release has no installer to download."))
    folder = folder or download_dir()
    with _open(checksum.url, opener) as response:
        expected = expected_checksum(response.read().decode("utf-8", "replace"), installer.name)
    path = download(installer.url, folder / installer.name, progress, cancel, opener, installer.size)
    report(progress, tr("Checking the download"), installer.name, 0, 0)
    actual = sha256_of(path)
    if actual != expected:
        path.unlink(missing_ok=True)
        log.error("Empreinte de %s incorrecte : %s au lieu de %s", installer.name, actual, expected)
        raise UpdateError(tr("The downloaded file does not match the published checksum. Nothing was installed."))
    log.info("Installateur %s téléchargé et vérifié (SHA-256 %s)", installer.name, actual)
    return path


def _shell_execute(path: str, parameters: str) -> int:
    """``ShellExecuteW`` : un programme qui demande l'élévation déclenche l'invite UAC (valeur > 32 : lancé)."""
    import ctypes

    return int(ctypes.windll.shell32.ShellExecuteW(None, "open", path, parameters, None, 1))


def launch(path: Path) -> None:
    """Lance l'installateur (droits administrateur : invite UAC), puis OptixPlus doit quitter.

    ``CreateProcess`` refuse un programme qui exige l'élévation (erreur 740) : on passe par le
    shell de Windows, qui affiche la demande de confirmation.
    """
    log.info("Lancement de l'installateur %s", path)
    try:
        result = _shell_execute(os.fspath(path), " ".join(INSTALLER_ARGS))
    except (AttributeError, OSError) as exc:
        raise UpdateError(tr("The installer could not be started: {error}").format(error=exc)) from exc
    if result <= 32:
        # 5 : accès refusé, notamment si l'utilisateur a refusé l'élévation.
        raise UpdateError(tr("The installer could not be started: {error}").format(error=f"ShellExecute {result}"))
