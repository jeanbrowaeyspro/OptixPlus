"""Aides communes aux tests d'interface."""

from __future__ import annotations

import time

from PySide6.QtCore import QCoreApplication


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
