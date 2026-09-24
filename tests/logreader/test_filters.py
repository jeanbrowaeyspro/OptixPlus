"""Filtres de l'onglet : niveaux, tri, filtres par colonne, surlignage, réinitialisation."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QDate, Qt

from optixplus.modules.logreader.core.config import default_rules
from optixplus.modules.logreader.core.highlight import Highlighter
from optixplus.modules.logreader.core.logparser import parse_line
from optixplus.modules.logreader.ui.filter_header import MAX_DISTINCT_VALUES, ColumnFilterPopup, FilterHeaderView
from optixplus.modules.logreader.ui.log_filter import RULE_ANY, RULE_NONE
from optixplus.modules.logreader.ui.log_model import (
    COLUMN_LEVEL,
    COLUMN_MESSAGE,
    COLUMN_SOURCE,
    COLUMN_TIMESTAMP,
    LogTableModel,
    level_label,
)

from .conftest import line

LEVELS = ["INFO", "ERROR", "WARNING"]
SOURCES = ["urn:FTOptix:CODESYS", "FTOptixRuntime", "urn:FTOptix:WebUI"]
MESSAGES = ["Communication error", "Communication established", "Store online"]
TOTAL = 30


def _lines() -> list[str]:
    """30 lignes : 3 niveaux, 3 sources, 3 messages, 10 lignes de chaque."""
    return [line(i, LEVELS[i % 3], MESSAGES[i % 3], SOURCES[i % 3]) for i in range(TOTAL)]


@pytest.fixture
def log_lines() -> list[str]:
    return _lines()


# ------------------------------------------------------------------ modèle seul
def test_distinct_values_are_counted_and_truncated_when_too_varied():
    model = LogTableModel(Highlighter(default_rules()))
    model.set_entries([parse_line(text.rstrip("\r\n"), i) for i, text in enumerate(_lines())])
    values, truncated = model.distinct_values(COLUMN_LEVEL, MAX_DISTINCT_VALUES)
    assert not truncated
    assert {value for value, _ in values} == {level_label(level) for level in LEVELS}
    assert all(count == 10 for _, count in values)
    # Une colonne trop variée n'est pas listée : seul le filtre « contient » reste.
    assert model.distinct_values(COLUMN_TIMESTAMP, 5) == ([], True)


# ------------------------------------------------------------------ onglet
def test_level_filter(tab):
    tab._filter_on_level("ERROR")
    assert tab.proxy.rowCount() == 10
    assert not tab.level_checks["INFO"].isChecked()


def test_sort_by_severity_puts_errors_first(tab):
    tab.table.sortByColumn(COLUMN_LEVEL, Qt.SortOrder.AscendingOrder)
    first = tab.model.entry_at(tab.proxy.mapToSource(tab.proxy.index(0, 0)).row())
    assert first.level == "ERROR"
    assert "Niveau" in tab.proxy.sort_summary()


def test_column_filters_combine_and_are_summarised(tab):
    assert isinstance(tab.table.horizontalHeader(), FilterHeaderView)
    tab._apply_column_filter(COLUMN_LEVEL, {"Erreur"}, "")
    assert tab.proxy.rowCount() == 10
    assert COLUMN_LEVEL in tab.proxy.filtered_columns()
    assert COLUMN_LEVEL in tab.header._filtered  # entonnoir marqué actif
    tab._apply_column_filter(COLUMN_SOURCE, None, "webui")  # « contient », combiné au précédent
    assert tab.proxy.rowCount() == 0
    tab._apply_column_filter(COLUMN_LEVEL, None, "")  # retiré : l'autre reste
    assert tab.proxy.rowCount() == 10
    assert tab.proxy.filtered_columns() == {COLUMN_SOURCE}
    tab._apply_column_filter(COLUMN_MESSAGE, None, "established")
    assert tab.proxy.rowCount() == 0
    summary = tab.proxy.summary()
    assert "Source" in summary and "Message" in summary


def test_filter_popup_lists_values_and_shows_a_partial_selection(tab):
    values, truncated = tab.model.distinct_values(COLUMN_LEVEL, MAX_DISTINCT_VALUES)
    popup = ColumnFilterPopup(
        column=COLUMN_LEVEL, title="Niveau", values=values, selected=None, text="",
        truncated=truncated, palette=tab.palette_, parent=tab,
    )
    popup.show()
    assert popup.list.count() == 3
    popup.list.item(0).setCheckState(Qt.CheckState.Unchecked)
    assert popup.select_all.checkState() == Qt.CheckState.PartiallyChecked
    popup.close()


def test_show_only_this_source_uses_the_column_filter(tab):
    tab._filter_on_source("urn:FTOptix:WebUI")
    assert COLUMN_SOURCE in tab.proxy.filtered_columns()
    assert tab.proxy.rowCount() == 10


def test_highlight_menu_and_rule_filters(tab):
    labels = [action.text() for action in tab._highlight_menu().actions()]
    assert labels[0] == "Tous les surlignages"
    assert labels[-1] == "Lignes non surlignées"
    assert len(labels) == len(tab.highlighter.active_rules) + 2

    tab._apply_rule_filter(0)  # première règle : Erreurs
    expected = sum(1 for e in tab.model.entries if e.highlight_index == 0)
    assert expected > 0 and tab.proxy.rowCount() == expected
    checked = [a.text() for a in tab._highlight_menu().actions() if a.isChecked()]
    assert checked == [labels[1]]  # le menu montre la règle retenue

    tab._apply_rule_filter(RULE_NONE)
    assert tab.proxy.rowCount() == sum(1 for e in tab.model.entries if e.highlight_index < 0)


def test_reset_clears_every_filter(tab):
    tab.search_edit.setText("Communication")
    tab._filter_on_level("ERROR")
    tab.period_button.setChecked(True)
    tab.from_edit.set_date(QDate(2026, 9, 7))
    tab._apply_column_filter(COLUMN_SOURCE, None, "codesys")
    tab._apply_rule_filter(0)
    assert tab.proxy.rowCount() < TOTAL
    assert "partir du" in tab.proxy.summary()  # période active

    tab.reset_filters()
    assert tab.proxy.rowCount() == TOTAL
    assert tab.search_edit.text() == ""
    assert all(check.isChecked() for check in tab.level_checks.values())
    assert not tab.period_button.isChecked()
    assert not tab.proxy.filtered_columns() and not tab.header._filtered
    assert tab.proxy.current_rule() == RULE_ANY
    assert tab.proxy.summary() == ""  # plus aucun filtre, période comprise
