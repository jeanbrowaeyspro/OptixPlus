"""Aides communes aux tests d'interface."""

from __future__ import annotations

import time

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QMessageBox


def wait_until(condition, timeout: float = 10.0) -> bool:
    """Fait tourner la boucle d'événements jusqu'à ``condition()`` vraie ou ``timeout`` (s).

    Renvoie la dernière valeur de la condition. PySide6 ne fournit pas ``QTest.qWaitFor`` ;
    ``QTest.qWait`` détruirait en plus les objets en attente de ``deleteLater`` au milieu du test.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return bool(condition())


def settle(seconds: float) -> None:
    """Laisse tourner la boucle d'événements ``seconds`` : pour vérifier que rien ne se passe."""
    wait_until(lambda: False, seconds)


class MessageBoxes:
    """Boîtes de message statiques simulées : hors écran, personne ne peut y répondre.

    ``question`` répond ``answer`` (Oui par défaut) ; ``information`` et ``warning`` répondent
    OK. Chaque boîte est relevée dans ``shown`` sous la forme ``(genre, texte)``. Fixture
    ``message_boxes`` ; ``install`` directement pour une fixture de module.
    """

    def __init__(self) -> None:
        self.shown: list[tuple[str, str]] = []
        self.answer = QMessageBox.StandardButton.Yes

    def of(self, kind: str) -> list[str]:
        """Textes des boîtes d'un genre (``"question"``, ``"information"``, ``"warning"``)."""
        return [text for k, text in self.shown if k == kind]

    def _fake(self, kind: str, answer):
        def show(*args, **kwargs):
            self.shown.append((kind, args[2] if len(args) > 2 else kwargs.get("text", "")))
            return self.answer if answer is None else answer

        return staticmethod(show)

    def install(self, monkeypatch) -> None:
        monkeypatch.setattr(QMessageBox, "question", self._fake("question", None))
        monkeypatch.setattr(QMessageBox, "information", self._fake("information", QMessageBox.StandardButton.Ok))
        monkeypatch.setattr(QMessageBox, "warning", self._fake("warning", QMessageBox.StandardButton.Ok))
