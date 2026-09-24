"""Fils d'exécution : suivi du log en direct et balayage réseau.

Les accès réseau (SMB, ICMP, NetBIOS) sont bloquants. Câble débranché, une
simple ouverture de fichier sur un chemin UNC peut ne rendre la main qu'au bout
de plusieurs dizaines de secondes, le temps que Windows épuise ses propres
délais. Trois règles en découlent :

* **aucune entrée-sortie réseau sur le fil de l'interface**, jamais, pas même
  un ``os.path.isfile`` ;
* **ne jamais attendre la fin d'un fil bloqué** : on lui demande de s'arrêter
  et on le laisse mourir de son côté, la fenêtre continue sans lui ;
* **ne pas déduire l'état de la liaison du retour de l'appel bloquant** :
  le fil publie l'instant où il entre en lecture, et l'interface constate
  d'elle-même qu'il n'en est pas ressorti, sans rien attendre.

Corrections par rapport à pyFTOLogReader :

* le suivi **dort vraiment** entre deux lectures (attente sur un événement) au lieu de
  se réveiller toutes les 100 ms pour vérifier une demande d'arrêt ;
* une demande d'arrêt **annule la lecture réseau bloquée** (``CancelSynchronousIo``) :
  plus besoin de ``QThread.terminate()``, qui pouvait laisser la session SMB ou une
  poignée de fichier dans un état incertain.
"""

from __future__ import annotations

import ctypes
import ipaddress
import sys
import threading
import time

from PySide6.QtCore import QMutex, QMutexLocker, QThread, Signal

from ...common.i18n import tr
from .core import discovery, export, logreader, netshare
from .core.logreader import LogFollower, PollResult


_THREAD_TERMINATE = 0x0001  # droit requis par CancelSynchronousIo

if sys.platform == "win32":
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.OpenThread.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    _kernel32.OpenThread.restype = ctypes.c_void_p
    _kernel32.CancelSynchronousIo.argtypes = [ctypes.c_void_p]
    _kernel32.CancelSynchronousIo.restype = ctypes.c_int
    _kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    _kernel32.GetCurrentThreadId.restype = ctypes.c_uint32
else:  # pragma: no cover - OptixPlus ne vise que Windows
    _kernel32 = None


class _IoCanceller:
    """Poignée du fil de lecture, pour annuler depuis un autre fil une entrée-sortie bloquée."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._handle = None

    def attach(self) -> None:
        """À appeler depuis le fil de lecture lui-même, au début de ``run``."""
        if _kernel32 is None:
            return
        handle = _kernel32.OpenThread(_THREAD_TERMINATE, 0, _kernel32.GetCurrentThreadId())
        with self._lock:
            self._handle = handle

    def detach(self) -> None:
        with self._lock:
            handle, self._handle = self._handle, None
        if handle and _kernel32 is not None:
            _kernel32.CloseHandle(handle)

    def cancel(self) -> None:
        """Interrompt la lecture réseau en cours du fil (sans effet s'il n'en fait aucune)."""
        with self._lock:
            if self._handle and _kernel32 is not None:
                _kernel32.CancelSynchronousIo(self._handle)


def retire(thread: QThread, registry: list) -> None:
    """Met un fil à la retraite sans jamais l'attendre.

    Un fil coincé dans une lecture réseau ne répond pas à une demande d'arrêt
    avant d'en être sorti. L'attendre reviendrait à figer la fenêtre pendant
    tout ce temps. On coupe donc ses signaux, on lui demande de s'arrêter, et
    on le garde dans *registry* le temps qu'il se termine : sans cette
    référence, Qt détruirait un fil encore en cours d'exécution.
    """
    if thread is None:
        return
    thread.blockSignals(True)
    thread.requestInterruption()
    if not thread.isRunning():
        thread.deleteLater()
        return
    registry.append(thread)
    thread.finished.connect(thread.deleteLater)
    thread.finished.connect(lambda: registry.remove(thread) if thread in registry else None)


class LogWatcher(QThread):
    """Lit le fichier une première fois puis surveille ses ajouts."""

    #: Chargement initial terminé (``PollResult``).
    initialLoaded = Signal(object)
    #: Nouvelles entrées à ajouter en bas du tableau (``list[LogEntry]``).
    entriesAdded = Signal(list)
    #: Le fichier a été remplacé : ``list[LogEntry]`` du nouveau contenu.
    fileRotated = Signal(list)
    #: Message d'erreur courant, chaîne vide quand tout va bien.
    errorChanged = Signal(str)
    #: État de la liaison : ``(connectée, message)``. Émis à chaque changement.
    connectionChanged = Signal(bool, str)

    #: Attente minimale entre deux tentatives de reconnexion. Inutile de
    #: harceler un automate éteint à la cadence de lecture du journal.
    RECONNECT_INTERVAL_MS = 3000

    #: Au-delà de ce silence, la liaison est déclarée perdue sans attendre que
    #: l'appel bloquant rende la main.
    STALL_THRESHOLD_MS = 1200

    def __init__(self, path: str, interval_ms: int = 800, parent=None,
                 host: str = "", share: str = "", credentials=None):
        super().__init__(parent)
        self._follower = LogFollower(path)
        self._interval_ms = max(100, interval_ms)
        self._paused = False
        self._mutex = QMutex()
        self._last_error = ""
        # Nécessaires pour rouvrir la session SMB si elle tombe : une simple
        # relecture du fichier ne suffit pas quand c'est le partage qui a été
        # perdu, par exemple après un redémarrage de l'automate.
        self._host = host
        self._share = share
        self._credentials = list(credentials or [])
        #: ``None`` tant que la première lecture n'a pas tranché. Sans cet état
        #: intermédiaire, la surveillance déclarerait la liaison bonne avant
        #: même d'avoir lu quoi que ce soit.
        self._connected: bool | None = None
        #: Vrai lorsque la machine a déjà répondu au ping ou au port 445. Tant
        #: qu'elle ne l'a jamais fait, ces sondes ne disent rien d'utile — un
        #: chemin local, ou un hôte qui filtre tout — et ne doivent donc pas
        #: servir à décider s'il vaut la peine de lire le journal.
        self._probes_are_meaningful = False
        #: Instant d'entrée dans la lecture en cours, en millisecondes
        #: monotones. Zéro quand le fil ne lit rien. L'interface s'en sert pour
        #: constater une liaison muette sans attendre le retour de l'appel.
        self._io_started_ms = 0.0
        #: Réveil immédiat du fil (arrêt demandé, reprise, nouvel intervalle).
        self._wake = threading.Event()
        self._canceller = _IoCanceller()

    def requestInterruption(self) -> None:  # noqa: N802 (API Qt)
        """Demande d'arrêt : réveille le fil et annule sa lecture réseau éventuelle."""
        super().requestInterruption()
        self._wake.set()
        self._canceller.cancel()

    # ------------------------------------------------------------- pilotage

    @property
    def path(self) -> str:
        return self._follower.path

    def set_interval(self, interval_ms: int) -> None:
        with QMutexLocker(self._mutex):
            self._interval_ms = max(100, interval_ms)
        self._wake.set()

    def set_paused(self, paused: bool) -> None:
        with QMutexLocker(self._mutex):
            self._paused = paused
        self._wake.set()

    def is_paused(self) -> bool:
        with QMutexLocker(self._mutex):
            return self._paused

    def _begin_io(self) -> None:
        with QMutexLocker(self._mutex):
            self._io_started_ms = time.monotonic() * 1000.0

    def _end_io(self) -> None:
        with QMutexLocker(self._mutex):
            self._io_started_ms = 0.0

    def io_stalled_ms(self) -> float:
        """Durée de la lecture en cours, ou zéro si le fil n'en fait aucune.

        Appelable depuis l'interface : ne prend qu'un verrou et lit un flottant.
        """
        with QMutexLocker(self._mutex):
            started = self._io_started_ms
        if not started:
            return 0.0
        return time.monotonic() * 1000.0 - started

    def is_stalled(self) -> bool:
        return self.io_stalled_ms() > self.STALL_THRESHOLD_MS

    # ------------------------------------------------------------ exécution

    def run(self) -> None:
        self._canceller.attach()
        try:
            self._run()
        finally:
            self._canceller.detach()

    def _run(self) -> None:
        self._begin_io()
        try:
            result = self._follower.read_all()
        finally:
            self._end_io()
        self._report_error(result.error)
        self._connected = not result.error
        self.connectionChanged.emit(
            self._connected, result.error or tr("log read")
        )
        self.initialLoaded.emit(result)

        if self._connected:
            # Une fois la liaison établie, on note si le ping et le port 445
            # renseignent sur cette machine. Les sondes sont immédiates quand
            # elle répond, et le résultat évite plus tard des lectures vouées
            # à rester suspendues.
            self._host_reachable()

        while not self.isInterruptionRequested():
            with QMutexLocker(self._mutex):
                interval, paused = self._interval_ms, self._paused
            if not self._connected:
                interval = max(interval, self.RECONNECT_INTERVAL_MS)

            # Sommeil réel jusqu'à la prochaine lecture ; une demande d'arrêt, une
            # reprise ou un changement d'intervalle réveille le fil aussitôt.
            self._wake.wait(interval / 1000.0)
            self._wake.clear()
            if self.isInterruptionRequested():
                break
            if paused:
                continue

            if self._should_skip_read():
                # Machine connue joignable mais muette à l'instant : ouvrir le
                # fichier ne ferait que bloquer de longues secondes pour un
                # échec certain. On repasse au tour suivant, à moindres frais.
                continue

            self._begin_io()
            try:
                result = self._follower.poll()
            finally:
                self._end_io()

            self._report_error(result.error)
            if result.error:
                self._set_connected(False, result.error)
                self._try_reconnect()
                continue

            self._set_connected(True, "")
            if result.rotated:
                self.fileRotated.emit(result.entries)
            elif result.entries:
                self.entriesAdded.emit(result.entries)

    def _report_error(self, error: str) -> None:
        """N'émet que les changements d'état, pour ne pas inonder l'interface
        de messages identiques quand le réseau tombe."""
        if error != self._last_error:
            self._last_error = error
            self.errorChanged.emit(error)

    def _set_connected(self, connected: bool, detail: str) -> None:
        if connected != self._connected:
            self._connected = connected
            self.connectionChanged.emit(connected, detail)

    def _host_reachable(self) -> bool:
        """Test de joignabilité rapide et borné, sans toucher au partage.

        Le ping et l'ouverture TCP échouent en quelques millisecondes quand le
        câble est débranché, là où une tentative SMB resterait suspendue
        plusieurs dizaines de secondes.

        Deux garde-fous encadrent ce test :

        * il ne s'applique qu'à une adresse IP littérale. Sonder un nom
          d'hôte imposerait une résolution DNS, dont la durée n'est bornée par
          aucun de nos délais et qui, sur un nom inconnu, immobilise le fil
          plusieurs secondes avant même la première lecture ;
        * un « non » n'est retenu que si la machine a déjà répondu au moins une
          fois. Sinon c'est que ces sondes ne la concernent pas — hôte filtrant
          à la fois l'ICMP et le port 445 — et s'en servir pour renoncer à lire
          empêcherait tout retour en ligne.
        """
        if not self._host_is_address():
            return True
        if discovery.ping(self._host, 700)[0] or discovery.tcp_probe(self._host, 445, 0.7):
            self._probes_are_meaningful = True
            return True
        return not self._probes_are_meaningful

    def _should_skip_read(self) -> bool:
        """Vrai s'il est inutile de tenter la lecture ce tour-ci.

        On ne consulte les sondes que pour une machine qui y a déjà répondu :
        c'est le cas du câble débranché, où une ouverture SMB reste suspendue
        des dizaines de secondes. Pour une adresse qui n'a jamais répondu à ces
        sondes, mesures à l'appui, l'ouverture échoue en moins d'une
        milliseconde là où la sonde coûterait près d'une seconde : on tente
        alors directement la lecture.
        """
        if self._connected or not self._probes_are_meaningful:
            return False
        return not self._host_reachable()

    def _host_is_address(self) -> bool:
        """Vrai si l'hôte est une adresse IP, donc sondable sans résolution."""
        if not self._host:
            return False
        try:
            ipaddress.ip_address(self._host)
        except ValueError:
            return False
        return True

    def _try_reconnect(self) -> None:
        """Rouvre la session SMB avant la prochaine lecture.

        Le fichier peut redevenir lisible sans rien faire — coupure réseau
        brève — mais si c'est la session vers le partage qui est tombée, seule
        une reconnexion la rétablit. On ferme donc l'ancienne avant d'en
        rouvrir une, sans quoi Windows refuse tout nouvel identifiant.

        On ne s'y risque que si la machine répond : sinon l'appel resterait
        suspendu bien plus longtemps que l'intervalle de reconnexion.
        """
        if not self._host or not self._share:
            return
        if self._probes_are_meaningful and not self._host_reachable():
            return
        self._begin_io()
        try:
            netshare.disconnect(self._host, self._share)
            netshare.connect_with_fallback(self._host, self._share, self._credentials)
        finally:
            self._end_io()

    def is_connected(self) -> bool:
        return self._connected is True

    def has_verdict(self) -> bool:
        """Vrai dès que la première lecture a tranché sur l'état de la liaison."""
        return self._connected is not None


class ArchiveLoader(QThread):
    """Charge les fichiers de log archivés (``.1``, ``.2``, ``.3``).

    La recherche des fichiers existants se fait ici, et non dans l'appelant :
    un ``os.path.isfile`` sur un chemin UNC est une entrée-sortie réseau comme
    une autre, et n'a donc rien à faire sur le fil de l'interface.
    """

    loaded = Signal(list, str)  # entrées, message d'erreur éventuel

    def __init__(self, log_dir: str, filename: str, parent=None):
        super().__init__(parent)
        self._log_dir = log_dir
        self._filename = filename

    def run(self) -> None:
        paths = logreader.archive_paths(self._log_dir, self._filename)
        if not paths:
            self.loaded.emit([], "")
            return

        entries: list = []
        errors: list[str] = []
        # Du plus ancien au plus récent : « .3 » précède « .1 » dans le temps.
        for path in sorted(paths, reverse=True):
            found, error = logreader.read_file(path, start_index=len(entries))
            if error:
                errors.append(error)
            entries.extend(found)
        self.loaded.emit(entries, " ; ".join(errors))


class DiscoveryWorker(QThread):
    """Sonde les automates configurés et remonte les résultats au fil de l'eau."""

    hostProbed = Signal(object)   # discovery.Ipc
    finishedScan = Signal(list)   # list[discovery.Ipc]

    def __init__(self, controllers, log_filename: str, ping_timeout_ms: int = 700, parent=None):
        super().__init__(parent)
        self._controllers = list(controllers)
        self._log_filename = log_filename
        self._ping_timeout_ms = ping_timeout_ms

    def run(self) -> None:
        results = discovery.discover(
            self._controllers,
            self._log_filename,
            self._ping_timeout_ms,
            on_result=self.hostProbed.emit,
        )
        self.finishedScan.emit(results)


class ExportWorker(QThread):
    """Écrit le fichier exporté sans figer la fenêtre."""

    progressed = Signal(int, int)     # lignes écrites, total
    finishedExport = Signal(str, str)  # chemin produit, message d'erreur

    def __init__(self, path: str, entries, highlighter, context, as_csv: bool = False, parent=None):
        super().__init__(parent)
        self._path = path
        self._entries = entries
        self._highlighter = highlighter
        self._context = context
        self._as_csv = as_csv

    def run(self) -> None:
        try:
            if self._as_csv:
                export.export_csv(self._path, self._entries, on_progress=self.progressed.emit)
            else:
                export.export_xlsx(
                    self._path, self._entries, self._highlighter, self._context,
                    on_progress=self.progressed.emit,
                )
        except Exception as exc:  # l'écriture peut échouer (fichier ouvert, disque plein)
            self.finishedExport.emit("", str(exc))
            return
        self.finishedExport.emit(self._path, "")
