"""Session de lecture : un automate, son suivi en direct, ses lignes, ses filtres.

pyFTOLogReader mêlait tout cela à sa fenêtre. OptixPlus le sépare de l'onglet qui
l'affiche (``ui.log_tab.LogTab``) :

* plusieurs journaux s'ouvrent côte à côte, chacun dans sa session ;
* au changement de langue, la fenêtre est reconstruite mais les sessions **survivent** :
  le nouvel onglet reprend la même session — pas de reconnexion, pas de ligne perdue,
  historique chargé conservé.

La session ne contient aucun widget : modèle et filtre (``QAbstractTableModel`` et
proxy) sont des objets de données Qt, pas des éléments d'affichage.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

from PySide6.QtCore import QObject, Signal

from ...common import workers as common_workers
from ...common.i18n import tr
from .core import netshare
from .core.config import Settings
from .core.discovery import Ipc
from .core.highlight import Highlighter
from .ui.log_filter import LogFilterProxy
from .ui.log_model import LogTableModel
from .ui.status_indicator import STATE_CONNECTING, STATE_LOST, STATE_OFFLINE, STATE_ONLINE
from .workers import ArchiveLoader, DiscoveryWorker, LogWatcher, retire

log = logging.getLogger("optixplus.logreader")

# Délai laissé aux fils de lecture pour s'arrêter à la fermeture, une fois leur lecture
# réseau annulée. Au-delà, ils sont abandonnés (jamais tués).
SHUTDOWN_GRACE_MS = 1500


class LogSession(QObject):
    """Données et fils d'un journal ouvert ; indépendante de tout widget."""

    #: Première lecture terminée (``PollResult``).
    loaded = Signal(object)
    #: Nouvelles lignes reçues.
    entriesAdded = Signal(list)
    #: Mention passagère à afficher : ``(texte, durée en ms)``.
    notice = Signal(str, int)
    #: L'état de la liaison ou le libellé « en direct » a changé.
    liveChanged = Signal()
    #: Automate, nom ou chemin a changé (titre de l'onglet).
    identityChanged = Signal()
    #: Journal d'un automate ouvert (liste des automates récents).
    opened = Signal()
    #: Historique chargé : ``(lignes ajoutées, message d'erreur)``.
    archivesFinished = Signal(list, str)
    #: Recherche du dernier automate : ``True`` si la connexion a abouti.
    probeFinished = Signal(bool)

    def __init__(self, settings: Settings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.highlighter = Highlighter(settings.highlight_rules)
        self.model = LogTableModel(self.highlighter, settings.max_rows, self)
        self.proxy = LogFilterProxy(self)
        self.proxy.setSourceModel(self.model)

        self.watcher: LogWatcher | None = None
        self.archive_loader: ArchiveLoader | None = None
        self.probe_worker: DiscoveryWorker | None = None
        self.ipc: Ipc | None = None
        self.path = ""
        self.archives_loaded = False
        self.paused = False
        self.link_detail = ""
        self.probing_host = ""
        #: Erreurs reçues pendant que l'onglet n'était pas affiché (pastille de l'onglet).
        self.unseen_errors = 0
        self.visible = True
        #: Fils dont on a demandé l'arrêt et qu'on ne veut surtout pas attendre.
        self._retiring: list = []

    # ------------------------------------------------------------------ identité
    @property
    def display_name(self) -> str:
        if self.ipc is not None:
            return self.ipc.display_name
        return self.probing_host or tr("New log")

    # ------------------------------------------------------------------ connexion
    def connect_to(self, ipc: Ipc) -> None:
        """Ouvre le journal de l'IPC choisi et démarre le suivi."""
        self.stop_watcher()
        self.ipc = ipc
        self.probing_host = ""
        self.path = os.path.join(
            netshare.unc_path(ipc.host, self.settings.share_name), self.settings.log_relative_path()
        )
        self.archives_loaded = False
        self.unseen_errors = 0
        self.model.clear()
        if self.settings.remember_last_host:
            self.settings.last_host = ipc.host
            self.settings.save()
        log.info("Lecteur de logs : ouverture de %s (%s)", ipc.display_name, self.path)

        watcher = LogWatcher(
            self.path,
            self.settings.poll_interval_ms,
            self,
            host=ipc.host,
            share=self.settings.share_name,
            credentials=self.settings.enabled_credentials(),
        )
        watcher.initialLoaded.connect(self._on_initial_loaded)
        watcher.entriesAdded.connect(self._on_entries_added)
        watcher.fileRotated.connect(self._on_file_rotated)
        watcher.errorChanged.connect(self._on_watcher_error)
        watcher.connectionChanged.connect(self._on_connection_changed)
        watcher.set_paused(self.paused)
        self.watcher = watcher
        watcher.start()
        self.identityChanged.emit()
        self.liveChanged.emit()
        self.opened.emit()

    def probe_host(self, host: str) -> None:
        """Retente un automate connu sans bloquer (ping, NetBIOS, partage : plusieurs secondes éteint)."""
        self.probing_host = host
        self.identityChanged.emit()
        worker = DiscoveryWorker(
            [host],
            self.settings.share_name,
            self.settings.log_relative_path(),
            self.settings.enabled_credentials(),
            self.settings.ping_timeout_ms,
            parent=self,
        )
        worker.finishedScan.connect(self._on_probed)
        self.probe_worker = worker
        worker.start()

    def _on_probed(self, results: list) -> None:
        retire(self.probe_worker, self._retiring)
        self.probe_worker = None
        usable = [ipc for ipc in results if ipc.log_available]
        if usable:
            self.connect_to(usable[0])
            self.probeFinished.emit(True)
        else:
            self.probeFinished.emit(False)
            self.liveChanged.emit()

    def stop_watcher(self) -> None:
        # Pas d'attente : un fil coincé dans une lecture réseau ne rendrait la main que
        # dans plusieurs dizaines de secondes, et la fenêtre resterait figée d'autant.
        retire(self.watcher, self._retiring)
        self.watcher = None
        self.link_detail = ""
        self.liveChanged.emit()

    def set_paused(self, paused: bool) -> None:
        self.paused = paused
        if self.watcher is not None:
            self.watcher.set_paused(paused)
        self.liveChanged.emit()

    # ------------------------------------------------------------------ réception
    def _on_initial_loaded(self, result) -> None:
        self.model.set_entries(result.entries)
        self.loaded.emit(result)
        self.liveChanged.emit()

    def _on_entries_added(self, entries: list) -> None:
        self.model.append_entries(entries)
        if not self.visible:
            self.unseen_errors += sum(1 for e in entries if e.level == "ERROR")
            self.identityChanged.emit()
        self.entriesAdded.emit(entries)
        self.liveChanged.emit()

    def _on_file_rotated(self, entries: list) -> None:
        # Le runtime a basculé sur un nouveau fichier : les lignes déjà affichées
        # viennent de l'ancien, on enchaîne donc sans les perdre.
        self.model.append_entries(entries)
        self.notice.emit(tr("Log rotation detected: following continues on the new file."), 8000)
        self.entriesAdded.emit(entries)
        self.liveChanged.emit()

    def _on_watcher_error(self, error: str) -> None:
        if error:
            self.notice.emit(tr("Cannot read: {error}").format(error=error), 10000)
        self.liveChanged.emit()

    def _on_connection_changed(self, connected: bool, detail: str) -> None:
        self.link_detail = "" if connected else detail
        self.liveChanged.emit()

    def connection_state(self) -> tuple[str, str]:
        """(état du voyant, motif), d'après l'état réel de la liaison.

        Une lecture qui s'éternise suffit à déclarer la liaison perdue, sans attendre
        l'échec formel de l'appel bloquant.
        """
        if self.watcher is None:
            if self.probe_worker is not None:
                return STATE_CONNECTING, self.probing_host
            return STATE_OFFLINE, ""
        if not self.watcher.has_verdict() and not self.watcher.is_stalled():
            return STATE_CONNECTING, self.path
        stalled = self.watcher.is_stalled()
        if self.watcher.is_connected() and not stalled:
            return STATE_ONLINE, self.path
        if stalled and not self.link_detail:
            silence = self.watcher.io_stalled_ms() / 1000.0
            return STATE_LOST, tr("no answer for {seconds:.0f} s").format(seconds=silence)
        return STATE_LOST, self.link_detail or tr("link interrupted")

    def live_label(self) -> str:
        if self.watcher is None:
            return ""
        if not self.watcher.has_verdict():
            return tr("Loading…")
        if not self.watcher.is_connected() or self.watcher.is_stalled():
            return tr("Connection lost  ·  reconnecting…")
        if self.paused:
            return tr("Following suspended")
        return tr("Live  ·  {time}").format(time=datetime.now().strftime("%H:%M:%S"))

    # ------------------------------------------------------------------ historique
    def load_archives(self) -> bool:
        """Lance le chargement des fichiers de rotation ; faux s'il n'y a rien à faire."""
        if self.ipc is None or self.archives_loaded or self.archive_loader is not None:
            return False
        log_dir = os.path.join(netshare.unc_path(self.ipc.host, self.settings.share_name), self.settings.log_subdir)
        # La recherche des fichiers est elle-même une entrée-sortie réseau : elle se
        # fait dans le fil, pas ici.
        loader = ArchiveLoader(log_dir, self.settings.log_filename, self)
        loader.loaded.connect(self._on_archives_loaded)
        self.archive_loader = loader
        loader.start()
        return True

    def _on_archives_loaded(self, entries: list, error: str) -> None:
        self.archive_loader = None
        if entries:
            # Les archives précèdent chronologiquement les lignes déjà affichées.
            self.model.set_entries(entries + list(self.model.entries))
            self.archives_loaded = True
        self.archivesFinished.emit(entries, error)

    # ------------------------------------------------------------------ réglages
    def apply_settings(self, settings: Settings) -> None:
        """Nouveaux réglages (boîte Paramètres du lecteur)."""
        previous_path = self.settings.log_relative_path()
        self.settings = settings
        self.highlighter.set_rules(settings.highlight_rules)
        self.model.refresh_highlighting()
        self.model.set_max_rows(settings.max_rows)
        if self.watcher is not None:
            self.watcher.set_interval(settings.poll_interval_ms)
        if settings.log_relative_path() != previous_path and self.ipc is not None:
            self.connect_to(self.ipc)  # le chemin du journal a changé : relecture

    # ------------------------------------------------------------------ arrêt
    @property
    def busy(self) -> bool:
        """Vrai si une opération à ne pas interrompre est en cours (historique)."""
        return self.archive_loader is not None

    def shutdown(self) -> None:
        """Arrêt coopératif de tous les fils, sans ``terminate()``.

        La lecture réseau en cours est annulée (``CancelSynchronousIo``) ; chaque fil a
        ensuite un court délai pour s'arrêter. Un fil qui ne s'arrête pas est abandonné
        à ``common.workers.retire`` : gardé en vie jusqu'à sa fin, jamais tué.
        """
        self.stop_watcher()
        threads = [t for t in (self.archive_loader, self.probe_worker, *self._retiring) if t is not None]
        self.archive_loader = self.probe_worker = None
        for thread in threads:
            thread.blockSignals(True)
            thread.requestInterruption()
        for thread in threads:
            if thread.isRunning() and not thread.wait(SHUTDOWN_GRACE_MS):
                log.warning("Un fil du lecteur de logs ne s'est pas arrêté à temps : abandonné")
                thread.setParent(None)
                common_workers.retire(thread)
        self._retiring.clear()
