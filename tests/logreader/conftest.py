"""Outils communs aux tests du Lecteur de logs : attente, partage simulé, onglet connecté.

Le partage réseau est simulé par un dossier temporaire (``netshare.unc_path`` détourné) :
le suivi lit un fichier local, sans jamais toucher au réseau. Les délais de reconnexion,
de détection de liaison muette et d'arrêt sont raccourcis pour que les tests restent
rapides.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication

from optixplus.common import i18n, theme
from optixplus.modules.logreader import session as session_module
from optixplus.modules.logreader.core import netshare
from optixplus.modules.logreader.core.config import Settings as ReaderSettings
from optixplus.modules.logreader.core.discovery import Ipc
from optixplus.modules.logreader.ui import log_tab
from optixplus.modules.logreader.ui.log_tab import LogTab
from optixplus.modules.logreader.workers import LogWatcher

LOG_NAME = "FTOptixRuntime.0.log"


def wait_for(condition, timeout: float = 15.0) -> bool:
    """Traite les événements Qt jusqu'à ce que ``condition()`` soit vraie (ou délai écoulé)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def settle() -> None:
    """Traite les événements en attente (mises en page différées, redimensionnements)."""
    for _ in range(3):
        QCoreApplication.sendPostedEvents()
        QCoreApplication.processEvents()


def line(n: int, level: str = "INFO", message: str = "Evenement", source: str = "FTOptixRuntime",
         day: str = "07-09-2026", hour: str | None = None) -> str:
    """Ligne de journal FT Optix ; par défaut à 09:mm:ss d'après ``n``."""
    stamp = hour or f"09:{n // 60:02d}:{n % 60:02d}"
    return f"{day} {stamp}.000;{level};{source};;{message} {n};;Root/X\r\n"


def write_log(path: Path, lines, mode: str = "a") -> None:
    """Écrit (``w``) ou ajoute (``a``) des lignes au journal, en octets comme le runtime."""
    with open(path, mode + "b") as handle:
        handle.write("".join(lines).encode("utf-8"))


@pytest.fixture(autouse=True)
def fast_timings(monkeypatch):
    """Délais raccourcis et aucun accès réseau réel (session SMB simulée)."""
    monkeypatch.setattr(LogWatcher, "RECONNECT_INTERVAL_MS", 100)
    monkeypatch.setattr(LogWatcher, "STALL_THRESHOLD_MS", 200)
    # Lu à la création de chaque onglet (intervalle de son minuteur).
    monkeypatch.setattr(log_tab, "HEALTH_INTERVAL_MS", 50)
    monkeypatch.setattr(session_module, "SHUTDOWN_GRACE_MS", 100)
    # La reconnexion rouvre la session SMB : ici un partage fictif, rien à ouvrir.
    monkeypatch.setattr(netshare, "connect", lambda *args, **kwargs: netshare.NO_ERROR)
    monkeypatch.setattr(netshare, "disconnect", lambda *args, **kwargs: netshare.NO_ERROR)


@pytest.fixture
def log_dir(tmp_path, monkeypatch) -> Path:
    """Partage simulé : <racine>\\Optix\\Log, lu en local."""
    folder = tmp_path / "share" / "Optix" / "Log"
    folder.mkdir(parents=True)
    monkeypatch.setattr(netshare, "unc_path", lambda host, share: str(tmp_path / "share" / share))
    return folder


@pytest.fixture
def share(log_dir) -> Path:
    """Partage simulé avec un journal de 11 lignes, dont une erreur."""
    write_log(log_dir / LOG_NAME, [line(i) for i in range(1, 11)] + [line(11, "ERROR")], "w")
    return log_dir


@pytest.fixture
def log_lines() -> list[str]:
    """Contenu initial du journal de l'onglet ; redéfini par les modules qui en veulent un autre."""
    return [line(i) for i in range(1, 21)]


def simulated_ipc() -> Ipc:
    """Automate fictif dont le journal est celui du partage simulé."""
    return Ipc(host="local", netbios_name="BANC-TEST", project="ProjetSimule",
               reachable=True, share_accessible=True, log_available=True)


@pytest.fixture
def make_tab(qapp, log_dir, log_lines):
    """Fabrique d'onglets autonomes (hors page), en français, rendus hors écran.

    ``make_tab(settings=None, connect=True)`` : avec ``connect``, l'onglet ouvre le
    journal simulé et attend son chargement complet.
    """
    write_log(log_dir / LOG_NAME, log_lines, "w")
    i18n.install("fr")
    tabs: list[LogTab] = []

    def build(settings: ReaderSettings | None = None, connect: bool = True) -> LogTab:
        settings = settings or ReaderSettings(poll_interval_ms=100, remember_last_host=False)
        tab = LogTab(settings, theme.LIGHT)
        tabs.append(tab)
        tab.resize(1200, 700)
        tab.show()
        if connect:
            tab.connect_to(simulated_ipc())
            assert wait_for(lambda: tab.model.rowCount() == len(log_lines))
        return tab

    yield build
    for tab in tabs:
        tab.close()
    i18n.install("en")


@pytest.fixture
def tab(make_tab) -> LogTab:
    """Onglet connecté au journal simulé, lignes chargées."""
    return make_tab()
