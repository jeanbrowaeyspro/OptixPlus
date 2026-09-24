"""Configuration commune des tests : interface hors écran, données dans un dossier temporaire.

Fixtures partagées : ``qapp``, ``make_controller`` / ``controller`` (coquille complète hors
écran), ``message_boxes`` (boîtes de message simulées et relevées). Les aides sans fixture
(``wait_until``, projets et simulations) sont dans ``tests/helpers``, importable directement.
"""

from __future__ import annotations

import os
import shutil
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
# Aides communes (projets synthétiques, simulations, attente) : ``from support import …``.
sys.path.insert(0, str(Path(__file__).resolve().parent / "helpers"))

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from support import MessageBoxes  # noqa: E402


def pytest_collection_modifyitems(config, items) -> None:
    """Tests marqués ``windows_only`` : ignorés hors de Windows (API Windows réelle)."""
    if sys.platform == "win32":
        return
    skip = pytest.mark.skip(reason="API Windows réelle")
    for item in items:
        if "windows_only" in item.keywords:
            item.add_marker(skip)


def pytest_unconfigure(config) -> None:
    """Fin de session : le dossier %APPDATA% temporaire de ce processus est supprimé."""
    shutil.rmtree(_APPDATA, ignore_errors=True)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# --------------------------------------------------------------------------- isolation
@pytest.fixture(autouse=True)
def _never_elevated(monkeypatch):
    """Même lancés depuis un terminal administrateur, les tests se croient en droits normaux.

    Sans cela, chaque contrôleur poserait un vrai crochet clavier (avis Impr. écran) ; les
    tests qui en ont besoin le demandent explicitement (``CaptureNotice(elevated=True)``).
    ``capture_notice`` et ``app`` appellent ``win32.is_elevated`` par le module : c'est ce
    nom-là qui est remplacé.
    """
    from optixplus.common import win32

    monkeypatch.setattr(win32, "is_elevated", lambda: False)


@pytest.fixture(autouse=True)
def _restore_language(qapp):
    """Après chaque test : catalogue de l'application et traducteur de Qt remis à l'état d'avant.

    C'est l'anglais, sauf si une fixture plus large a choisi une langue pour tout un dossier
    (``tests/compare`` travaille en français) : on la rétablit alors, sans la défaire.
    """
    from optixplus.common import i18n, qt_translation

    language = i18n.current_language()
    qt_language = "fr" if qt_translation._translator is not None else "en"
    yield
    if i18n.current_language() != language:
        i18n.install(language)
    if ("fr" if qt_translation._translator is not None else "en") != qt_language:
        qt_translation.apply(qapp, qt_language)


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


# --------------------------------------------------------------------------- boîtes et coquille
@pytest.fixture
def message_boxes(monkeypatch) -> MessageBoxes:
    """Boîtes de message simulées (``question`` → Oui, sinon OK) et relevées."""
    boxes = MessageBoxes()
    boxes.install(monkeypatch)
    return boxes


@pytest.fixture
def make_controller(qapp, tmp_path, message_boxes):
    """Fabrique de contrôleurs : ``make_controller(mode=…, language=…, theme=…)``.

    Réglages dans ``tmp_path/settings.json``, journal sans fichier, boîtes de message
    simulées. La destruction se fait après le test (``_destroy_qt_leftovers``).
    """
    from optixplus.common import i18n, logging_setup
    from optixplus.common.settings import Settings
    from optixplus.common.theme import install_manager
    from optixplus.shell.context import LaunchMode
    from optixplus.shell.controller import AppController

    def make(mode: LaunchMode = LaunchMode.INSTALLED, language: str = "fr", theme: str = "light") -> AppController:
        i18n.install(language)
        logging_setup.configure(to_file=False)
        settings = Settings.load(tmp_path / "settings.json")
        return AppController(qapp, settings, install_manager(qapp, theme), mode)

    return make


@pytest.fixture
def controller(make_controller):
    """Contrôleur installé, en français, thème clair."""
    return make_controller()
