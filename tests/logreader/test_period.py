"""Sélecteur de période : boutons date et heure, calendrier, choix de l'heure, calage sur les événements."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QDate, QTime
from PySide6.QtWidgets import QAbstractSpinBox, QPushButton

from optixplus.common import theme
from optixplus.modules.logreader.ui.datetime_range import DatePickerPopup, TimePickerPopup

from .conftest import line, settle

#: Le 05/09 va de 08:15:10 à 17:40:55, le 07/09 de 06:05:00 à 22:30:00 ; rien le 06/09.
DAYS = [
    ("05-09-2026", ["08:15:10", "11:02:33", "17:40:55"]),
    ("07-09-2026", ["06:05:00", "13:20:41", "22:30:00"]),
]


@pytest.fixture
def log_lines() -> list[str]:
    return [line(n, day=day, hour=hour) for day, hours in DAYS for n, hour in enumerate(hours)]


@pytest.fixture
def period_tab(tab):
    """Onglet avec la barre de période affichée."""
    tab.period_button.setChecked(True)
    settle()
    return tab


def _set_day(field, day: QDate) -> None:
    field.set_date(day)  # comme un choix de l'utilisateur (calage de l'heure compris)


# ------------------------------------------------------------------ boutons date et heure
def test_date_and_time_buttons_fit_their_text_and_share_the_row_height(period_tab):
    field = period_tab.from_edit
    needed = field.date_button.fontMetrics().horizontalAdvance("31/12/2026")
    assert field.date_button.width() >= needed + 30
    assert field.date_button.text() == field.date().toString("dd/MM/yyyy")
    time_needed = field.time_button.fontMetrics().horizontalAdvance("00:00:00")
    assert field.time_button.isVisible()
    assert field.time_button.width() >= time_needed + 20
    assert field.time_button.text() == field.time().toString("HH:mm:ss")
    whole_range = next(b for b in period_tab.period_bar.findChildren(QPushButton) if b.text() == "Toute la plage")
    heights = {field.date_button.height(), field.time_button.height(), whole_range.height()}
    assert len(heights) == 1, heights


def test_date_button_opens_the_calendar(period_tab):
    field = period_tab.from_edit
    field._open_date_picker()
    popups = [p for p in field.findChildren(DatePickerPopup) if p.isVisible()]
    assert len(popups) == 1
    popups[0]._pick(QDate(2026, 9, 7))
    assert field.date() == QDate(2026, 9, 7)
    assert not popups[0].isVisible()


# ------------------------------------------------------------------ choix de l'heure
def test_time_picker_grid_exact_entry_and_confirm(qapp):
    popup = TimePickerPopup(QTime(9, 30, 0), theme.LIGHT)
    popup.show()
    settle()
    assert len(popup._hour_buttons) == 24
    assert len(popup._minute_buttons) == 12  # par pas de 5 minutes
    assert popup._hour_buttons[9].isChecked() and popup._minute_buttons[30].isChecked()

    picked: list[QTime] = []
    popup.timePicked.connect(picked.append)
    popup._hour_buttons[14].click()
    popup._minute_buttons[45].click()
    assert popup._time == QTime(14, 45, 0)

    spins = (popup.hour_spin, popup.minute_spin, popup.second_spin)
    widths = [spin.width() for spin in spins]
    row = sum(widths) + 2 * 6 + 2 * 5  # deux séparateurs et quatre espacements
    assert min(widths) >= 70 and row >= popup.width() - 40  # toute la ligne est partagée
    assert max(widths) - min(widths) <= 2  # à parts égales (au pixel d'arrondi près)
    assert all(spin.buttonSymbols() == QAbstractSpinBox.ButtonSymbols.NoButtons for spin in spins)

    popup.second_spin.setValue(30)
    assert popup._time == QTime(14, 45, 30)
    popup._apply(popup._time)
    assert picked == [QTime(14, 45, 30)]
    popup.deleteLater()


# ------------------------------------------------------------------ calage sur les événements
def test_changing_the_date_snaps_to_the_day_events(period_tab):
    tab = period_tab
    _set_day(tab.from_edit, QDate(2026, 9, 5))
    assert tab.from_edit.time() == QTime(8, 15, 10)  # premier événement du jour
    _set_day(tab.to_edit, QDate(2026, 9, 5))
    assert tab.to_edit.time() == QTime(17, 40, 55)  # dernier événement du jour
    assert tab.proxy.rowCount() == 3

    _set_day(tab.from_edit, QDate(2026, 9, 7))
    _set_day(tab.to_edit, QDate(2026, 9, 7))
    assert (tab.from_edit.time(), tab.to_edit.time()) == (QTime(6, 5, 0), QTime(22, 30, 0))
    assert tab.proxy.rowCount() == 3


def test_day_without_events_spans_the_whole_day(period_tab):
    tab = period_tab
    _set_day(tab.from_edit, QDate(2026, 9, 6))
    _set_day(tab.to_edit, QDate(2026, 9, 6))
    assert tab.from_edit.time() == QTime(0, 0, 0)
    assert tab.to_edit.time() == QTime(23, 59, 59)
    assert tab.proxy.rowCount() == 0


def test_whole_range_then_closing_the_period_removes_the_date_filter(period_tab):
    tab = period_tab
    _set_day(tab.from_edit, QDate(2026, 9, 5))
    _set_day(tab.to_edit, QDate(2026, 9, 5))
    assert tab.proxy.rowCount() == 3
    tab._reset_period_bounds()  # « Toute la plage »
    assert tab.proxy.rowCount() == 6

    _set_day(tab.from_edit, QDate(2026, 9, 7))
    assert tab.proxy.rowCount() == 3
    tab.period_button.setChecked(False)  # période refermée : plus de filtre de date
    assert tab.proxy.rowCount() == 6
