"""Threads de travail : l'analyse ne tourne jamais dans le thread de l'interface."""

from __future__ import annotations

import logging
import traceback
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ..core.analysis import compare
from ..core.progress import Cancelled, Progress

log = logging.getLogger(__name__)


class CompareWorker(QThread):
    """Lance ``core.analysis.compare`` et remonte progression, résultat, erreur ou annulation."""

    progressed = Signal(str, str, int, int)  # phase, élément courant, index, total
    succeeded = Signal(object)  # Comparison
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, runtime: Path | str, projet: Path | str, parent=None) -> None:
        super().__init__(parent)
        self._runtime = Path(runtime)
        self._projet = Path(projet)
        self._cancel_requested = False

    def request_cancel(self) -> None:
        self._cancel_requested = True

    def _on_progress(self, step: Progress) -> None:
        self.progressed.emit(step.phase, step.current, step.index, step.total)

    def run(self) -> None:  # exécuté dans le thread de travail
        try:
            result = compare(
                self._runtime,
                self._projet,
                progress=self._on_progress,
                cancel=lambda: self._cancel_requested,
            )
        except Cancelled:
            log.info("Analyse annulée par l'utilisateur")
            self.cancelled.emit()
        except Exception:  # noqa: BLE001 — on veut tout remonter à l'écran
            log.exception("Échec de l'analyse")
            self.failed.emit(traceback.format_exc())
        else:
            self.succeeded.emit(result)
