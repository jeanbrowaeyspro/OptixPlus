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


def _hook_call(watcher, vk: int, message: int) -> None:
    import ctypes

    from optixplus.common import win32

    info = win32._KbdLLHookStruct(vkCode=vk)
    watcher._callback(0, message, ctypes.addressof(info))


def test_keyboard_hook_sees_print_screen_only_on_our_window(window, monkeypatch):
    from optixplus.common import win32

    app, settings, widget = window
    notice = CaptureNotice(app, settings, elevated=False)  # sans crochet réel : on appelle le rappel
    seen = []
    watcher = win32.PrintScreenWatcher(lambda pressed: seen.append(pressed))
    monkeypatch.setattr(win32.user32, "CallNextHookEx", lambda *a: 0)
    _hook_call(watcher, win32.VK_SNAPSHOT, 0x0100)
    _hook_call(watcher, win32.VK_SNAPSHOT, 0x0101)
    _hook_call(watcher, 0x41, 0x0101)  # une autre touche : ignorée
    assert seen == [True, False]

    monkeypatch.setattr(win32, "foreground_is_own_window", lambda: False)
    notice._on_key(False)
    QCoreApplication.processEvents()
    assert _boxes() == []  # fenêtre d'un autre logiciel au premier plan : rien
    monkeypatch.setattr(win32, "foreground_is_own_window", lambda: True)
    notice._on_key(False)
    QCoreApplication.processEvents()
    assert len(_boxes()) == 1


def test_keyboard_hook_can_be_installed_and_removed():
    from optixplus.common import win32

    watcher = win32.PrintScreenWatcher(lambda pressed: None)
    try:
        assert watcher.start()
    finally:
        watcher.stop()
