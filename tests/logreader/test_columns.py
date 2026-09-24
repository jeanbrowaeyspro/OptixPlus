"""Colonnes du tableau : poignée et entonnoir, masquage mémorisé, ancrage au bord droit."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QRect

from optixplus.modules.logreader.core.config import Settings as ReaderSettings
from optixplus.modules.logreader.ui.log_model import COLUMN_LEVEL, COLUMN_MESSAGE, COLUMN_SOURCE, COLUMNS

from .conftest import line, settle


@pytest.fixture
def log_lines() -> list[str]:
    levels = ["INFO", "ERROR", "WARNING"]
    return [line(i, levels[i % 3]) for i in range(12)]


def _level_rect(tab) -> QRect:
    header = tab.header
    return QRect(header.sectionViewportPosition(COLUMN_LEVEL), 0, header.sectionSize(COLUMN_LEVEL), header.height())


def _right_gap(tab) -> int:
    """Vide entre la fin de la dernière colonne et le bord du tableau (négatif : débordement)."""
    header = tab.header
    used = sum(header.sectionSize(i) for i in range(header.count()) if not header.isSectionHidden(i))
    return tab.table.viewport().width() - used


# ------------------------------------------------------------------ poignée et entonnoir
@pytest.mark.parametrize("offset", [0, 1, 2, 4, 6])
def test_column_edge_resizes_instead_of_opening_the_filter(tab, offset):
    rect = _level_rect(tab)
    assert tab.header._near_section_edge(QPoint(rect.right() - offset, rect.height() // 2))


def test_funnel_opens_the_filter_without_biting_the_grip(tab):
    header = tab.header
    rect = _level_rect(tab)
    funnel = header._funnel_rect(rect)
    centre = QPoint(funnel.center().x(), rect.height() // 2)
    assert header._hit_zone(rect).contains(centre)
    assert not header._near_section_edge(centre)
    assert funnel.right() < rect.right() - header._grip_margin() + 1


# ------------------------------------------------------------------ masquage
def test_hiding_a_column_is_saved_and_drops_its_filter(tab):
    assert tab._visible_column_count() == len(COLUMNS)
    tab._set_column_visible(COLUMN_SOURCE, False)
    assert tab.header.isSectionHidden(COLUMN_SOURCE)
    assert tab.settings.hidden_columns == [COLUMNS[COLUMN_SOURCE][0]]
    # Un filtre posé sur une colonne masquée serait invisible : il part avec elle.
    tab._apply_column_filter(COLUMN_LEVEL, {"Erreur"}, "")
    assert tab.proxy.rowCount() == 4
    tab._set_column_visible(COLUMN_LEVEL, False)
    assert COLUMN_LEVEL not in tab.proxy.filtered_columns()
    assert tab.proxy.rowCount() == 12


def test_hidden_columns_survive_a_new_tab(make_tab):
    store: dict = {}
    settings = ReaderSettings.bound(store, lambda: None)
    settings.poll_interval_ms, settings.remember_last_host = 100, False
    first = make_tab(settings)
    first._set_column_visible(COLUMN_SOURCE, False)
    first._set_column_visible(COLUMN_LEVEL, False)
    first.close()

    reread = ReaderSettings.bound(store, lambda: None)
    assert set(reread.hidden_columns) == {COLUMNS[COLUMN_SOURCE][0], COLUMNS[COLUMN_LEVEL][0]}
    second = make_tab(reread, connect=False)
    assert second.header.isSectionHidden(COLUMN_SOURCE) and second.header.isSectionHidden(COLUMN_LEVEL)


def test_at_least_one_column_stays_visible_and_show_all_restores(tab):
    for index in range(len(COLUMNS)):
        tab._set_column_visible(index, False)
    assert tab._visible_column_count() == 1
    tab._show_all_columns()
    assert tab._visible_column_count() == len(COLUMNS)
    assert tab.settings.hidden_columns == []


# ------------------------------------------------------------------ géométrie
@pytest.mark.parametrize("width, height", [(1100, 700), (1500, 820), (1920, 1080), (2560, 1400)])
def test_last_column_is_anchored_to_the_right_edge(tab, width, height):
    tab.resize(width, height)
    settle()
    assert _right_gap(tab) <= 0  # jamais de vide à droite (un débordement fait défiler)


def test_last_column_fills_a_wide_table_exactly(tab):
    tab.resize(2400, 1000)
    settle()
    assert _right_gap(tab) == 0


def test_resizing_a_middle_column_keeps_the_last_one_anchored(tab):
    header = tab.header
    tab.resize(1900, 900)
    settle()
    last = header.count() - 1
    before = header.sectionSize(last)
    header.resizeSection(COLUMN_MESSAGE, 300)
    settle()
    assert _right_gap(tab) == 0
    assert header.sectionSize(last) > before  # l'espace libéré va à la dernière colonne
    header.resizeSection(COLUMN_MESSAGE, 900)
    settle()
    assert _right_gap(tab) <= 0


def test_table_absorbs_the_extra_height(tab):
    settle()
    table_before, detail_before = tab.table.height(), tab.splitter.widget(1).height()
    tab.resize(1600, 1100)
    settle()
    assert tab.table.height() - table_before > 300
    assert tab.splitter.widget(1).height() - detail_before <= 2  # le détail garde sa hauteur
