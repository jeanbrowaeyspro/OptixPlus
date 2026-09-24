"""Configuration commune des tests : interface hors écran, données dans un dossier temporaire."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Avant tout import de Qt ou d'optixplus : rendu hors écran et %APPDATA% isolé, pour
# ne jamais toucher aux réglages réels de l'utilisateur.
os.environ["QT_QPA_PLATFORM"] = "offscreen"
_APPDATA = tempfile.mkdtemp(prefix="optixplus-tests-")
os.environ["APPDATA"] = _APPDATA

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def appdata() -> Path:
    return Path(_APPDATA)


@pytest.fixture(autouse=True)
def _destroy_qt_leftovers():
    """Après chaque test : détruit les fenêtres, contrôleurs et boîtes laissés en place.

    Sans boucle d'événements, ``close()`` et ``deleteLater()`` ne détruisent rien, et les
    contrôleurs, enfants de l'application, vivent jusqu'à la fin de la session : les fenêtres
    des tests précédents s'accumulaient (près de 9 000 widgets repolis à chaque changement de
    feuille de style, soit des dizaines de secondes par test de la coquille).
    """
    yield
    app = QApplication.instance()
    if app is None:
        return
    from PySide6.QtCore import QCoreApplication, QEvent, QThread

    from optixplus.common import workers
    from optixplus.shell.controller import AppController

    for controller in app.findChildren(AppController):
        controller._rebuilding = True  # fermer sans arrêter l'application
        if controller.window is not None:
            controller.window.close_for_rebuild()
        controller._on_about_to_quit()  # services, mises à jour, threads abandonnés
        controller.deleteLater()
    for widget in app.topLevelWidgets():
        widget.hide()
        widget.deleteLater()
    # Un QThread détruit en cours d'exécution fait planter le processus : on attend la fin
    # des traitements encore lancés avant la destruction.
    for thread in app.findChildren(QThread) + [t for w in app.topLevelWidgets() for t in w.findChildren(QThread)]:
        if thread.isRunning():
            thread.wait(10_000)
    workers.wait_retired(10_000)
    QCoreApplication.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()
