"""Impr. écran dans une fenêtre d'OptixPlus élevé : l'utilisateur est prévenu que la capture est bloquée."""

from __future__ import annotations

import json

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from optixplus.common import i18n
from optixplus.common.settings import Settings
from optixplus.shell.capture_notice import CaptureNotice


def _press_print_screen(widget: QWidget) -> None:
    for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
        QApplication.sendEvent(widget, QKeyEvent(kind, Qt.Key.Key_Print, Qt.KeyboardModifier.NoModifier))
    QCoreApplication.processEvents()


def _boxes() -> list[QMessageBox]:
    return [w for w in QApplication.topLevelWidgets() if isinstance(w, QMessageBox) and w.isVisible()]


@pytest.fixture
def window(qapp, tmp_path):
    i18n.install("fr")
    settings = Settings.load(tmp_path / "s.json")
    widget = QWidget()
    widget.show()
    yield qapp, settings, widget
    for box in _boxes():
        box.close()
    widget.close()
    i18n.install("en")


def test_elevated_print_screen_explains_why_nothing_happens(window):
    app, settings, widget = window
    notice = CaptureNotice(app, settings, elevated=True)
    _press_print_screen(widget)
    _press_print_screen(widget)  # pas de message empilé
    boxes = _boxes()
    assert len(boxes) == 1
    assert boxes[0].text() == "Capture d'écran impossible sur cette fenêtre"
    assert "administrateur" in boxes[0].informativeText()
    app.removeEventFilter(notice)


def test_normal_rights_show_nothing(window):
    app, settings, widget = window
    notice = CaptureNotice(app, settings, elevated=False)
    _press_print_screen(widget)
    assert _boxes() == []
    assert not notice.active


def test_do_not_show_again_is_remembered(window):
    app, settings, widget = window
    notice = CaptureNotice(app, settings, elevated=True)
    _press_print_screen(widget)
    box = _boxes()[0]
    box.checkBox().setChecked(True)
    box.accept()
    QCoreApplication.processEvents()
    assert json.loads(settings.path.read_text(encoding="utf-8"))["general"]["warn_elevated_capture"] is False
    _press_print_screen(widget)
    assert _boxes() == []
    app.removeEventFilter(notice)
