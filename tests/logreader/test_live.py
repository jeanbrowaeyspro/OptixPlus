"""Suivi en direct : ordre d'affichage, ajouts, rotation, historique, reprise après coupure."""

from __future__ import annotations

import os
import shutil

import pytest
from PySide6.QtCore import Qt

from optixplus.modules.logreader.ui.log_model import COLUMN_MESSAGE
from optixplus.modules.logreader.ui.status_indicator import STATE_LOST, STATE_ONLINE

from .conftest import LOG_NAME, line, wait_for, write_log

#: Assez de lignes pour que le tableau défile.
INITIAL = 40


@pytest.fixture
def log_lines() -> list[str]:
    return [line(i) for i in range(1, INITIAL + 1)]


def _message(tab, row: int) -> str:
    return tab.proxy.index(row, COLUMN_MESSAGE).data(Qt.ItemDataRole.DisplayRole)


def _bottom(tab) -> str:
    return _message(tab, tab.proxy.rowCount() - 1)


def _at_bottom(tab) -> bool:
    scrollbar = tab.table.verticalScrollBar()
    return scrollbar.maximum() > 0 and scrollbar.value() == scrollbar.maximum()


def test_chronological_order_with_view_at_the_bottom(tab):
    assert _message(tab, 0) == "Evenement 1"  # plus ancienne en haut
    assert _bottom(tab) == f"Evenement {INITIAL}"  # plus récente en bas
    assert wait_for(lambda: _at_bottom(tab))


def test_appended_lines_arrive_at_the_bottom_and_are_followed(tab, log_dir):
    assert wait_for(lambda: _at_bottom(tab))
    write_log(log_dir / LOG_NAME, [line(i, "ERROR", "Nouvel evenement") for i in range(41, 46)])
    assert wait_for(lambda: tab.model.rowCount() == INITIAL + 5)
    assert _bottom(tab) == "Nouvel evenement 45"
    assert wait_for(lambda: _at_bottom(tab))


def test_rotation_keeps_history_and_is_announced(tab, log_dir):
    current = log_dir / LOG_NAME
    shutil.move(current, log_dir / "FTOptixRuntime.1.log")
    fresh = log_dir / "nouveau.log"
    write_log(fresh, [line(50, message="Apres rotation")], "w")
    os.replace(fresh, current)
    assert wait_for(lambda: tab.model.rowCount() == INITIAL + 1)
    assert _message(tab, 0) == "Evenement 1"  # l'historique n'est pas perdu
    assert _bottom(tab) == "Apres rotation 50"
    assert "Rotation du journal" in tab.status_notice.text()


def test_archives_are_loaded_before_the_live_lines(tab, log_dir):
    write_log(log_dir / "FTOptixRuntime.1.log", [line(i, message="Archive") for i in range(1, 6)], "w")
    tab.load_archives()
    assert wait_for(lambda: tab.model.rowCount() == INITIAL + 5)
    assert tab.session.archives_loaded
    assert _message(tab, 0) == "Archive 1"
    assert _bottom(tab) == f"Evenement {INITIAL}"  # la plus récente reste en bas
    assert "5 lignes d'historique" in tab.status_notice.text()


def test_following_resumes_after_an_outage(tab, log_dir):
    current = log_dir / LOG_NAME
    assert wait_for(lambda: tab.connection_state == STATE_ONLINE)
    current.rename(log_dir / "ecarte.log")
    assert wait_for(lambda: tab.connection_state == STATE_LOST)
    (log_dir / "ecarte.log").rename(current)
    assert wait_for(lambda: tab.connection_state == STATE_ONLINE)
    write_log(current, [line(i) for i in range(41, 45)])
    assert wait_for(lambda: tab.model.rowCount() == INITIAL + 4)
    assert _bottom(tab) == "Evenement 44"
