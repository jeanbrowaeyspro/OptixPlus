"""Exécution des traitements longs hors du thread de l'interface.

``TaskWorker`` enveloppe une fonction de moteur de la forme
``fn(progress_callback, cancel_check) -> résultat`` : le moteur reste sans Qt, le worker
relaie progression, succès, échec et annulation par signaux.

``retire()`` met de côté un thread qu'on ne veut plus attendre (lecture réseau bloquée par
exemple) : une référence est gardée jusqu'à sa fin, pour que Qt ne détruise pas un
``QThread`` encore actif.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QDeadlineTimer, QObject, QThread, Signal

from .progress import CancelCheck, Cancelled, Progress, ProgressCallback

log = logging.getLogger("optixplus.workers")

TaskFunction = Callable[[ProgressCallback, CancelCheck], Any]


class TaskWorker(QThread):
    """Thread générique pour une fonction de moteur annulable."""

    progress = Signal(object)  # Progress
    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, fn: TaskFunction, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._fn = fn
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def is_cancel_requested(self) -> bool:
        return self._cancel.is_set()

    def _report(self, step: Progress) -> None:
        self.progress.emit(step)

    def run(self) -> None:
        try:
            result = self._fn(self._report, self.is_cancel_requested)
        except Cancelled:
            self.cancelled.emit()
        except Exception as exc:  # le moteur peut lever n'importe quoi : on relaie
            log.exception("Échec du traitement en arrière-plan")
            self.failed.emit(str(exc) or exc.__class__.__name__)
        else:
            if self._cancel.is_set():
                self.cancelled.emit()
            else:
                self.succeeded.emit(result)


_retired: set[QThread] = set()


def retire(thread: QThread) -> None:
    """Abandonne un thread sans l'attendre, en le gardant vivant jusqu'à sa fin."""
    if not thread.isRunning():
        thread.deleteLater()
        return
    _retired.add(thread)

    def _done() -> None:
        _retired.discard(thread)
        thread.deleteLater()

    thread.finished.connect(_done)


def wait_retired(timeout_ms: int = 3000) -> None:
    """À la fermeture : laisse aux threads abandonnés une chance de finir proprement."""
    deadline = QDeadlineTimer(timeout_ms)
    for thread in list(_retired):
        if not thread.wait(deadline):
            log.warning("Un thread d'arrière-plan ne s'est pas terminé à temps")
