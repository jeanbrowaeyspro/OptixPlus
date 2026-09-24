"""État de la connexion et reconnexion automatique ; interface jamais figée par le réseau.

La coupure est simulée en renommant le journal (même symptôme qu'un partage injoignable).
La liaison muette (câble débranché : une ouverture de fichier UNC qui ne rend la main
qu'au bout de dizaines de secondes) est simulée par une ouverture de fichier bloquée sur
un ``threading.Event``, toujours relâchée à la fin du test.
"""

from __future__ import annotations

import threading
import time

import pytest
from PySide6.QtCore import Qt, QTimer

from optixplus.common import theme
from optixplus.modules.logreader.core import logreader
from optixplus.modules.logreader.ui.status_indicator import (
    STATE_CONNECTING,
    STATE_LOST,
    STATE_OFFLINE,
    STATE_ONLINE,
    state_colour,
)

from .conftest import LOG_NAME, line, simulated_ipc, wait_for


@pytest.fixture
def log_lines() -> list[str]:
    return [line(i) for i in range(5)]


class Hang:
    """Ouverture de fichier pilotable : une fois ``start()`` appelé, elle reste bloquée
    jusqu'à ``release()``, comme sur un partage devenu muet."""

    def __init__(self, real_open) -> None:
        self._real_open = real_open
        self._active = threading.Event()
        self._released = threading.Event()
        self._lock = threading.Lock()
        self.waiting = 0  # lectures actuellement bloquées

    def open(self, path):
        if self._active.is_set():
            with self._lock:
                self.waiting += 1
            try:
                self._released.wait(30)  # garde-fou : jamais plus de 30 s
            finally:
                with self._lock:
                    self.waiting -= 1
        return self._real_open(path)

    def start(self) -> None:
        self._released.clear()
        self._active.set()

    def release(self) -> None:
        self._active.clear()
        self._released.set()


@pytest.fixture
def hang(monkeypatch):
    blocker = Hang(logreader.open_shared)
    monkeypatch.setattr(logreader, "open_shared", blocker.open)
    yield blocker
    blocker.release()  # le fil encore bloqué se termine avant le nettoyage commun


class Ticks:
    """Battements d'un minuteur du fil de l'interface : ils s'arrêtent si elle se fige."""

    def __init__(self) -> None:
        self.count = 0
        self.timer = QTimer()
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(20)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    def _tick(self) -> None:
        self.count += 1


# ------------------------------------------------------------------ état de la connexion
def test_state_colour_follows_the_state():
    p = theme.LIGHT
    assert state_colour(STATE_ONLINE, p) == p.success
    assert state_colour(STATE_LOST, p) == p.error
    assert state_colour(STATE_CONNECTING, p) == p.warning
    assert state_colour(STATE_OFFLINE, p) == p.text_muted


def test_offline_until_connected_then_online(make_tab):
    tab = make_tab(connect=False)
    assert tab.connection_state == STATE_OFFLINE
    tab.connect_to(simulated_ipc())
    assert wait_for(lambda: tab.connection_state == STATE_ONLINE)
    assert tab.model.rowCount() == 5


def test_lost_connection_is_announced_then_cleared_on_recovery(tab, log_dir):
    current = log_dir / LOG_NAME
    current.rename(log_dir / "hors-ligne.log")
    assert wait_for(lambda: tab.connection_state == STATE_LOST)
    assert "reconnexion" in tab.status_live.text().lower()
    first_line, _, reason = tab.connection_tooltip.partition("\n")
    assert "perdue" in first_line.lower()
    assert reason  # la raison de la perte accompagne l'état
    # Aucune action de l'utilisateur : le fichier revient, la liaison aussi.
    (log_dir / "hors-ligne.log").rename(current)
    assert wait_for(lambda: tab.connection_state == STATE_ONLINE)
    assert wait_for(lambda: "reconnexion" not in tab.status_live.text().lower())


def test_controller_identity_stays_visible_over_a_temporary_message(tab):
    tab.statusBar().showMessage("Message temporaire quelconque", 0)
    assert tab.status_connection.isVisible()
    assert "BANC-TEST" in tab.status_connection.text()


def test_offline_as_soon_as_following_stops(tab):
    assert wait_for(lambda: tab.connection_state == STATE_ONLINE)
    tab._stop_watcher()
    assert tab.connection_state == STATE_OFFLINE
    assert tab.status_live.text() == ""


# ------------------------------------------------------------------ liaison muette
def _stall(tab, hang) -> None:
    """Bloque la prochaine lecture et attend que la liaison soit déclarée perdue."""
    assert wait_for(lambda: tab.connection_state == STATE_ONLINE)
    hang.start()
    assert wait_for(lambda: tab.connection_state == STATE_LOST, 5)


def test_stalled_read_is_lost_before_it_returns_and_ui_stays_alive(tab, hang):
    ticks = Ticks()
    _stall(tab, hang)
    assert hang.waiting == 1  # déclarée perdue alors que la lecture n'est pas revenue
    assert "reconnexion" in tab.status_live.text().lower()
    assert "aucune réponse" in tab.connection_tooltip
    # Le fil de l'interface continue de traiter ses événements pendant la suspension.
    before = ticks.count
    assert wait_for(lambda: ticks.count >= before + 10, 5)
    assert hang.waiting == 1
    ticks.timer.stop()


def test_stopping_does_not_wait_for_the_stalled_read(tab, hang):
    _stall(tab, hang)
    started = time.monotonic()
    tab._stop_watcher()
    assert time.monotonic() - started < 0.5
    assert tab.connection_state == STATE_OFFLINE
    ticks = Ticks()
    assert wait_for(lambda: ticks.count >= 10, 5)  # l'interface répond, le fil reste bloqué
    assert hang.waiting == 1
    ticks.timer.stop()
    # Reconnexion une fois la liaison rétablie : les lignes sont bien là.
    hang.release()
    tab.connect_to(simulated_ipc())
    assert wait_for(lambda: tab.connection_state == STATE_ONLINE)
    assert tab.model.rowCount() == 5


def test_stalled_link_recovers_by_itself(tab, hang):
    _stall(tab, hang)
    hang.release()
    assert wait_for(lambda: tab.connection_state == STATE_ONLINE)
    assert wait_for(lambda: "reconnexion" not in tab.status_live.text().lower())
    assert tab.model.rowCount() == 5


def test_closing_during_a_stalled_read_is_bounded(tab, hang):
    _stall(tab, hang)
    started = time.monotonic()
    tab.close()
    assert time.monotonic() - started < 2.0
