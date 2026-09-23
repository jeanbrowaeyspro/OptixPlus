"""Mises à jour dans l'interface : vérification automatique ou à la demande, proposition, installation.

La vérification et le téléchargement tournent dans un ``TaskWorker`` ; le moteur
(``optixplus.update``) ne connaît pas Qt.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QByteArray, QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..common import paths, signals, workers
from ..common.i18n import tr
from ..common.progress import Progress
from ..common.workers import TaskWorker
from ..update import installer
from ..update.config import UpdateSettings
from ..update.github import Release, UpdateError, available_update, is_check_due, parse_timestamp
from ..version import APP_NAME, __version__
from .context import LaunchMode

log = logging.getLogger("optixplus.update")

#: Première vérification automatique peu après le démarrage, pour ne pas le ralentir.
STARTUP_DELAY_MS = 20_000
#: Réévaluation périodique de l'échéance (aucune requête si elle n'est pas atteinte).
TICK_MS = 60 * 60 * 1000


class UpdateDialog(QDialog):
    """Une version plus récente est disponible : notes de version et trois choix."""

    install_requested = Signal(object)  # Release
    skip_requested = Signal(object)  # Release

    def __init__(self, release: Release, can_install: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.release = release
        self.setWindowTitle(tr("Update available"))
        self.resize(600, 460)
        layout = QVBoxLayout(self)
        title = QLabel(
            tr("{app} {new} is available (you are using {current}).").format(
                app=APP_NAME, new=release.version, current=__version__
            )
        )
        title.setProperty("heading", True)
        title.setWordWrap(True)
        layout.addWidget(title)
        notes = QTextBrowser()
        notes.setOpenExternalLinks(True)
        notes.setMarkdown(release.notes or tr("No release notes."))
        layout.addWidget(notes, 1)

        buttons = QDialogButtonBox()
        if can_install:
            self.install_button = QPushButton(tr("Install now"))
            self.install_button.setToolTip(
                tr("Downloads the installer, checks its SHA-256 checksum, then closes OptixPlus to update it.")
            )
        else:
            self.install_button = QPushButton(tr("Open the download page"))
            self.install_button.setToolTip(tr("Automatic installation is only available in the installed version."))
        self.install_button.setDefault(True)
        self.install_button.setProperty("accent", True)
        later = QPushButton(tr("Later"))
        self.skip_button = QPushButton(tr("Skip this version"))
        self.skip_button.setToolTip(tr("No more automatic reminder for version {version}.").format(version=release.version))
        buttons.addButton(self.install_button, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(self.skip_button, QDialogButtonBox.ButtonRole.DestructiveRole)
        buttons.addButton(later, QDialogButtonBox.ButtonRole.RejectRole)
        self.install_button.clicked.connect(self._install)
        self.skip_button.clicked.connect(self._skip)
        later.clicked.connect(self.reject)
        layout.addWidget(buttons)

    def _install(self) -> None:
        self.accept()
        self.install_requested.emit(self.release)

    def _skip(self) -> None:
        self.accept()
        self.skip_requested.emit(self.release)

    def snapshot(self) -> dict:
        return {"release": self.release, "geometry": bytes(self.saveGeometry().toBase64().data())}

    def restore(self, state: dict) -> None:
        if state.get("geometry"):
            self.restoreGeometry(QByteArray.fromBase64(state["geometry"]))


class UpdateManager(QObject):
    """Vérifie les releases GitHub selon les réglages et propose l'installation."""

    #: Fin d'une vérification : la release disponible, ou ``None``.
    checked = Signal(object)
    busy_changed = Signal(bool)

    def __init__(self, controller, parent: QObject | None = None) -> None:
        super().__init__(parent or controller)
        self._controller = controller
        self._context = controller.context
        self.settings: UpdateSettings = self._context.settings.section(UpdateSettings)
        self.available: Release | None = None
        self.dialog: UpdateDialog | None = None
        self._worker: TaskWorker | None = None
        self._interactive = False
        self._download: TaskWorker | None = None
        self._progress: QProgressDialog | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(lambda: self._auto_check(at_startup=False))

    # ------------------------------------------------------------------ état
    @property
    def busy(self) -> bool:
        return self._worker is not None or self._download is not None

    @property
    def can_install(self) -> bool:
        """Installation automatique : seulement pour l'exécutable installé."""
        return self._context.mode is LaunchMode.INSTALLED and paths.is_frozen()

    def last_check_text(self) -> str:
        moment = parse_timestamp(self.settings.last_check)
        if moment is None:
            return tr("never")
        return moment.astimezone().strftime("%d/%m/%Y %H:%M")

    # ------------------------------------------------------------------ vérification
    def start(self) -> None:
        """Vérifications automatiques : peu après le démarrage, puis réévaluées chaque heure."""
        QTimer.singleShot(STARTUP_DELAY_MS, lambda: self._auto_check(at_startup=True))
        self._timer.start()

    def _auto_check(self, at_startup: bool) -> None:
        s = self.settings
        if s.auto_check and is_check_due(s.last_check, s.frequency, datetime.now(timezone.utc), at_startup):
            self.check(interactive=False)

    def check(self, interactive: bool = True) -> None:
        """Interroge GitHub ; ``interactive`` : demande explicite, avec réponse même sans nouveauté."""
        if self._worker is not None:
            self._interactive = self._interactive or interactive
            return
        self._interactive = interactive
        include = self.settings.include_prereleases
        # Une demande explicite montre aussi une version ignorée auparavant.
        skipped = "" if interactive else self.settings.skipped_version
        worker = TaskWorker(lambda _progress, _cancel: available_update(__version__, include, skipped), self)
        worker.succeeded.connect(self._on_checked)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(self._on_worker_finished)
        self._worker = worker
        self.busy_changed.emit(True)
        log.info("Recherche de mise à jour (%s)", "à la demande" if interactive else "automatique")
        worker.start()

    def _on_worker_finished(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.deleteLater()
        self.busy_changed.emit(self.busy)

    def _on_checked(self, release: Release | None) -> None:
        self.settings.last_check = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._context.settings.save()
        self.available = release
        interactive = self._interactive
        self.checked.emit(release)
        if release is None:
            log.info("OptixPlus %s est à jour", __version__)
            if interactive:
                QMessageBox.information(
                    self._parent_widget(), tr("Updates"), tr("{app} {version} is up to date.").format(app=APP_NAME, version=__version__)
                )
            return
        log.info("Version %s disponible", release.version)
        tray = self._controller.tray
        if interactive or tray is None:
            self.open_dialog(release)
        else:
            tray.notify(
                tr("{app} {version} is available. Click to see what changed.").format(app=APP_NAME, version=release.version),
                tr("Update available"),
                10_000,
                on_click=lambda: self.open_dialog(release),
            )

    def _on_failed(self, message: str) -> None:
        log.warning("Recherche de mise à jour impossible : %s", message)
        if self._interactive:
            QMessageBox.warning(
                self._parent_widget(), tr("Updates"), tr("The check for updates failed:\n{error}").format(error=message)
            )

    # ------------------------------------------------------------------ proposition
    def _parent_widget(self) -> QWidget | None:
        return self._controller.window

    def open_dialog(self, release: Release | None = None) -> UpdateDialog | None:
        release = release or self.available
        if release is None:
            return None
        if self.dialog is not None and self.dialog.isVisible() and self.dialog.release is release:
            self.dialog.raise_()
            self.dialog.activateWindow()
            return self.dialog
        dialog = UpdateDialog(release, self.can_install and release.installable, self._parent_widget())
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.install_requested.connect(self.install)
        dialog.skip_requested.connect(self.skip)
        signals.track(self, "dialog", dialog)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return dialog

    def skip(self, release: Release) -> None:
        self.settings.skipped_version = str(release.version)
        self._context.settings.save()
        log.info("Version %s ignorée", release.version)

    # ------------------------------------------------------------------ installation
    def install(self, release: Release) -> None:
        if not (self.can_install and release.installable):
            QDesktopServices.openUrl(QUrl(release.page_url))
            return
        if self._download is not None:
            return
        progress = QProgressDialog(tr("Downloading the update…"), tr("Cancel"), 0, 0, self._parent_widget())
        progress.setWindowTitle(tr("Update"))
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        worker = TaskWorker(lambda report, cancel: installer.fetch_installer(release, report, cancel), self)
        worker.progress.connect(self._on_download_progress)
        worker.succeeded.connect(self._on_downloaded)
        worker.failed.connect(self._on_download_failed)
        worker.cancelled.connect(lambda: log.info("Téléchargement de la mise à jour annulé"))
        worker.finished.connect(self._on_download_finished)
        progress.canceled.connect(worker.cancel)
        self._download, self._progress = worker, progress
        self.busy_changed.emit(True)
        worker.start()

    def _on_download_progress(self, step: Progress) -> None:
        if self._progress is None:
            return
        self._progress.setLabelText(step.phase + "…")
        if step.total:
            self._progress.setMaximum(100)
            self._progress.setValue(min(100, step.index * 100 // step.total))
        else:
            self._progress.setMaximum(0)

    def _on_downloaded(self, path: Path) -> None:
        try:
            installer.launch(path)
        except UpdateError as exc:
            self._on_download_failed(str(exc))
            return
        # L'installateur ferme puis relance OptixPlus ; on part proprement tout de suite.
        QTimer.singleShot(0, self._controller.quit)

    def _on_download_failed(self, message: str) -> None:
        log.error("Mise à jour impossible : %s", message)
        QMessageBox.warning(self._parent_widget(), tr("Update"), tr("The update could not be installed:\n{error}").format(error=message))

    def _on_download_finished(self) -> None:
        worker, self._download = self._download, None
        if self._progress is not None:
            self._progress.close()
            self._progress.deleteLater()
            self._progress = None
        if worker is not None:
            worker.deleteLater()
        self.busy_changed.emit(self.busy)

    def shutdown(self) -> None:
        """Arrêt : une requête réseau en cours n'est pas attendue (délai d'attente borné)."""
        self._timer.stop()
        for worker in (self._worker, self._download):
            if worker is not None:
                worker.blockSignals(True)
                worker.cancel()
                worker.setParent(None)
                workers.retire(worker)
        self._worker = self._download = None
