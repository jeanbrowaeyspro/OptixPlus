"""Impr. écran dans une fenêtre d'OptixPlus lancé en administrateur : expliquer pourquoi rien ne se passe.

Quand une fenêtre élevée est au premier plan, Windows (UIPI) empêche les logiciels lancés
normalement (Greenshot…) de recevoir la touche Impr. écran : la capture n'a pas lieu et rien
ne l'indique. OptixPlus prévient l'utilisateur, sans empiler les messages ; « Ne plus
afficher » est mémorisé dans les réglages.

Windows traite Impr. écran comme un raccourci système : une fenêtre ne la reçoit pas comme une
touche ordinaire. Un crochet clavier de bas niveau, installé seulement en administrateur et
limité à cette touche, la voit avant ce traitement ; on ne réagit que si la fenêtre au premier
plan est à OptixPlus. Le filtre d'événements Qt reste en secours.
"""

from __future__ import annotations

import logging
import time

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QApplication, QCheckBox, QMessageBox

from ..common import win32
from ..common.i18n import tr

log = logging.getLogger("optixplus.app")


class CaptureNotice(QObject):
    """Filtre d'événements de l'application, actif seulement si OptixPlus tourne élevé."""

    def __init__(self, app: QApplication, settings, parent: QObject | None = None, elevated: bool | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._box: QMessageBox | None = None
        self._last_key = 0.0
        self.active = win32.is_elevated() if elevated is None else elevated
        self._watcher: win32.PrintScreenWatcher | None = None
        if self.active:
            app.installEventFilter(self)
            self._watcher = win32.PrintScreenWatcher(self._on_key)
            if self._watcher.start():
                log.info("OptixPlus en administrateur : touche Impr. écran surveillée pour prévenir l'utilisateur")
            else:
                log.warning("Surveillance de la touche Impr. écran impossible (crochet clavier refusé)")
            app.aboutToQuit.connect(self._watcher.stop)

    #: Appui et relâchement d'une même frappe (ou seulement l'un des deux, selon la
    #: combinaison) : un seul message.
    SAME_PRESS_S = 1.0

    def _on_key(self, pressed: bool, vk: int = 0, scan: int = 0) -> None:
        """Rappel du crochet : bref, l'affichage est programmé pour la boucle Qt."""
        now = time.monotonic()
        if now - self._last_key < self.SAME_PRESS_S:
            return
        if not win32.foreground_is_own_window():
            return
        self._last_key = now
        log.info("Impr. écran vue (%s, vk=0x%02X, scan=0x%02X)", "appui" if pressed else "relâchement", vk, scan)
        if self._settings.general.warn_elevated_capture:
            QTimer.singleShot(0, self.show_notice)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 (API Qt)
        if (
            event.type() in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease)
            and event.key() == Qt.Key.Key_Print
            and not event.isAutoRepeat()
            and self._settings.general.warn_elevated_capture
        ):
            self.show_notice()
        return False  # la touche poursuit son chemin

    def show_notice(self) -> None:
        if self._box is not None and self._box.isVisible():
            return
        log.info("Impr. écran dans une fenêtre élevée : capture bloquée par Windows, utilisateur prévenu")
        box = QMessageBox(QMessageBox.Icon.Information, "OptixPlus", tr("Screenshot not possible on this window"),
                          QMessageBox.StandardButton.Ok, QApplication.activeWindow())
        box.setInformativeText(
            tr(
                "OptixPlus is running as administrator: Windows prevents screenshot tools started normally "
                "(Greenshot…) from receiving the Print Screen key while an OptixPlus window is active.\n\n"
                "To take the screenshot: click another window first, start OptixPlus normally, or start "
                "your screenshot tool as administrator."
            )
        )
        dont_show = QCheckBox(tr("Do not show this message again"))
        box.setCheckBox(dont_show)
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        box.finished.connect(lambda _result: self._remember(dont_show.isChecked()))
        self._box = box
        box.open()

    def _remember(self, dont_show: bool) -> None:
        self._box = None
        if dont_show:
            self._settings.general.warn_elevated_capture = False
            self._settings.save()
