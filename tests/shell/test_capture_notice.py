"""Impr. écran dans une fenêtre d'OptixPlus élevé : l'utilisateur est prévenu que la capture est bloquée.

Le crochet clavier est remplacé par une simulation : son décodage et sa pose réelle sont
vérifiés dans ``tests/common/test_win32_hooks.py``.
"""

from __future__ import annotations

import json

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from optixplus.common import i18n, win32
from optixplus.common.settings import Settings
from optixplus.shell.capture_notice import CaptureNotice


class _FakeWatcher:
    """Crochet clavier simulé : rien n'est posé dans Windows."""

    def __init__(self, on_press) -> None:
        self.on_press = on_press
        self.started = False

    def start(self) -> bool:
        self.started = True
        return True

    def stop(self) -> None:
        self.started = False


def _press_print_screen(widget: QWidget) -> None:
    for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
        QApplication.sendEvent(widget, QKeyEvent(kind, Qt.Key.Key_Print, Qt.KeyboardModifier.NoModifier))
    QCoreApplication.processEvents()


def _boxes() -> list[QMessageBox]:
    return [w for w in QApplication.topLevelWidgets() if isinstance(w, QMessageBox) and w.isVisible()]


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(win32, "PrintScreenWatcher", _FakeWatcher)
    i18n.install("fr")
    settings = Settings.load(tmp_path / "s.json")
    widget = QWidget()
    widget.show()
    notices: list[CaptureNotice] = []

    def notice(elevated: bool) -> CaptureNotice:
        created = CaptureNotice(qapp, settings, elevated=elevated)
        notices.append(created)
        return created

    yield notice, settings, widget
    for created in notices:
        qapp.removeEventFilter(created)


def test_elevated_print_screen_explains_why_nothing_happens(window):
    notice, _settings, widget = window
    assert notice(elevated=True)._watcher.started
    _press_print_screen(widget)
    _press_print_screen(widget)  # pas de message empilé
    boxes = _boxes()
    assert len(boxes) == 1
    assert boxes[0].text() == "Capture d'écran impossible sur cette fenêtre"
    assert "administrateur" in boxes[0].informativeText()


def test_normal_rights_show_nothing(window):
    notice, _settings, widget = window
    created = notice(elevated=False)
    _press_print_screen(widget)
    assert _boxes() == []
    assert not created.active
    assert created._watcher is None  # aucun crochet clavier


def test_do_not_show_again_is_remembered(window):
    notice, settings, widget = window
    notice(elevated=True)
    _press_print_screen(widget)
    box = _boxes()[0]
    box.checkBox().setChecked(True)
    box.accept()
    QCoreApplication.processEvents()
    assert json.loads(settings.path.read_text(encoding="utf-8"))["general"]["warn_elevated_capture"] is False
    _press_print_screen(widget)
    assert _boxes() == []


@pytest.mark.parametrize(
    ("own_window", "alone", "expected"),
    [
        (False, True, 0),  # fenêtre d'un autre logiciel au premier plan : rien
        (True, False, 0),  # combinaison (Alt+Impr. écran…) : Greenshot la reçoit, pas de message
        (True, True, 1),  # Impr. écran seule sur notre fenêtre : un message
    ],
)
def test_key_from_the_hook_shows_one_message_only_when_it_matters(window, monkeypatch, own_window, alone, expected):
    notice, _settings, _widget = window
    created = notice(elevated=False)  # sans crochet : on appelle le rappel directement
    monkeypatch.setattr(win32, "foreground_is_own_window", lambda: own_window)
    created._on_key(True, 0x2C, 0x37, alone=alone)  # appui…
    created._on_key(False, 0x2C, 0x37, alone=alone)  # … et relâchement de la même frappe
    QCoreApplication.processEvents()
    assert len(_boxes()) == expected
