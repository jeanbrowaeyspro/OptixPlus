"""Sélection d'une borne de période : une date et une heure.

Les deux valeurs sont présentées par deux boutons identiques, l'un affichant la
date, l'autre l'heure, chacun ouvrant son propre panneau. Ce choix vient d'une
série de défauts tenaces d'un ``QDateEdit`` habillé par une feuille de style :
son bouton de calendrier recouvrait la bordure arrondie du champ, le texte se
retrouvait rogné dès que la police grandissait — mise à l'échelle de l'écran,
par exemple — et le calendrier finissait par ne plus s'ouvrir selon la façon
dont on habillait le sous-contrôle.

Un bouton, lui, se dimensionne sur son propre texte, s'aligne naturellement
avec les autres boutons de la ligne, et le panneau qu'il ouvre est entièrement
sous notre contrôle.
"""

from __future__ import annotations

from PySide6.QtCore import QDate, QDateTime, QTime, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractSpinBox, QCalendarWidget, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QPushButton, QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
)

from ....common.i18n import tr
from ....common.theme import Palette, popup_stylesheet

#: Pas de la grille des minutes. Cinq minutes suffisent pour cadrer une
#: recherche ; la saisie précise en dessous couvre le reste.
MINUTE_STEP = 5

DATE_FORMAT = "dd/MM/yyyy"
TIME_FORMAT = "HH:mm:ss"


class DatePickerPopup(QFrame):
    """Panneau de choix d'une date : un calendrier et deux raccourcis."""

    datePicked = Signal(QDate)

    def __init__(self, current: QDate, palette: Palette, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("datePicker")
        self.setStyleSheet(popup_stylesheet("datePicker", palette))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        self.calendar = QCalendarWidget()
        self.calendar.setGridVisible(False)
        self.calendar.setVerticalHeaderFormat(
            QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader
        )
        if current.isValid():
            self.calendar.setSelectedDate(current)
        self.calendar.clicked.connect(self._pick)
        layout.addWidget(self.calendar)

        shortcuts = QHBoxLayout()
        shortcuts.setSpacing(5)
        today = QPushButton(tr("Today"))
        today.clicked.connect(lambda: self._pick(QDate.currentDate()))
        shortcuts.addWidget(today)
        yesterday = QPushButton("Hier")
        yesterday.clicked.connect(lambda: self._pick(QDate.currentDate().addDays(-1)))
        shortcuts.addWidget(yesterday)
        shortcuts.addStretch(1)
        layout.addLayout(shortcuts)

    def _pick(self, date: QDate) -> None:
        self.datePicked.emit(QDate(date))
        self.close()


class TimePickerPopup(QFrame):
    """Panneau de choix d'une heure : grilles d'heures et de minutes."""

    timePicked = Signal(QTime)

    def __init__(self, current: QTime, palette: Palette, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self._time = QTime(current)
        self.palette_ = palette
        self._hour_buttons: dict[int, QPushButton] = {}
        self._minute_buttons: dict[int, QPushButton] = {}

        self.setObjectName("timePicker")
        self.setStyleSheet(popup_stylesheet("timePicker", palette))
        self._build()
        self._refresh()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(9)

        self.preview = QLabel()
        self.preview.setProperty("heading", True)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.preview)

        layout.addWidget(self._section_label(tr("Hour")))
        hours = QGridLayout()
        hours.setSpacing(3)
        for hour in range(24):
            button = self._grid_button(f"{hour:02d}")
            button.clicked.connect(lambda _=False, h=hour: self._set_hour(h))
            self._hour_buttons[hour] = button
            hours.addWidget(button, hour // 6, hour % 6)
        layout.addLayout(hours)

        layout.addWidget(self._section_label(tr("Minute")))
        minutes = QGridLayout()
        minutes.setSpacing(3)
        for position, minute in enumerate(range(0, 60, MINUTE_STEP)):
            button = self._grid_button(f"{minute:02d}")
            button.clicked.connect(lambda _=False, m=minute: self._set_minute(m))
            self._minute_buttons[minute] = button
            minutes.addWidget(button, position // 6, position % 6)
        layout.addLayout(minutes)

        layout.addWidget(self._section_label(tr("Exact entry")))
        precise = QHBoxLayout()
        precise.setSpacing(5)
        self.hour_spin = self._spin(23)
        self.minute_spin = self._spin(59)
        self.second_spin = self._spin(59)
        for index, spin in enumerate((self.hour_spin, self.minute_spin, self.second_spin)):
            spin.valueChanged.connect(self._spins_changed)
            precise.addWidget(spin, 1)
            if index < 2:
                separator = QLabel(":")
                separator.setAlignment(Qt.AlignmentFlag.AlignCenter)
                separator.setFixedWidth(6)
                precise.addWidget(separator)
        layout.addLayout(precise)

        shortcuts = QHBoxLayout()
        shortcuts.setSpacing(4)
        for label, value in (
            ("00:00", QTime(0, 0, 0)),
            ("12:00", QTime(12, 0, 0)),
            ("23:59", QTime(23, 59, 59)),
        ):
            button = QPushButton(label)
            button.clicked.connect(lambda _=False, t=value: self._apply(t))
            shortcuts.addWidget(button)
        now = QPushButton("Maintenant")
        now.clicked.connect(lambda: self._apply(QTime.currentTime()))
        shortcuts.addWidget(now)
        layout.addLayout(shortcuts)

        validate = QPushButton("Valider")
        validate.setProperty("accent", True)
        validate.setDefault(True)
        validate.clicked.connect(lambda: self._apply(self._time))
        layout.addWidget(validate)

    @staticmethod
    def _section_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("muted", True)
        return label

    @staticmethod
    def _grid_button(text: str) -> QPushButton:
        button = QPushButton(text)
        button.setFixedSize(42, 28)
        button.setCheckable(True)
        button.setProperty("grid", True)
        return button

    @staticmethod
    def _spin(maximum: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(0, maximum)
        spin.setWrapping(True)
        # Sans les flèches, tout le champ revient à son texte. Les touches Haut
        # et Bas continuent d'incrémenter la valeur.
        spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        # Minimum volontairement bas : c'est la grille des heures qui fixe la
        # largeur du panneau, pas cette ligne.
        spin.setMinimumWidth(52)
        spin.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return spin

    # ------------------------------------------------------------- état

    def _set_hour(self, hour: int) -> None:
        self._time = QTime(hour, self._time.minute(), self._time.second())
        self._refresh()

    def _set_minute(self, minute: int) -> None:
        self._time = QTime(self._time.hour(), minute, self._time.second())
        self._refresh()

    def _spins_changed(self) -> None:
        self._time = QTime(
            self.hour_spin.value(), self.minute_spin.value(), self.second_spin.value()
        )
        self._refresh(update_spins=False)

    def _refresh(self, update_spins: bool = True) -> None:
        self.preview.setText(self._time.toString(TIME_FORMAT))

        for hour, button in self._hour_buttons.items():
            button.setChecked(hour == self._time.hour())
        # La minute courante n'est pas forcément un multiple du pas : on met en
        # évidence la case la plus proche en dessous, pour situer la sélection.
        nearest = (self._time.minute() // MINUTE_STEP) * MINUTE_STEP
        for minute, button in self._minute_buttons.items():
            button.setChecked(minute == nearest)

        if update_spins:
            for spin, value in (
                (self.hour_spin, self._time.hour()),
                (self.minute_spin, self._time.minute()),
                (self.second_spin, self._time.second()),
            ):
                spin.blockSignals(True)
                spin.setValue(value)
                spin.blockSignals(False)

    def _apply(self, value: QTime) -> None:
        self._time = QTime(value)
        self.timePicked.emit(self._time)
        self.close()


class DateTimeField(QWidget):
    """Une borne de période : bouton date et bouton heure, côte à côte."""

    #: La valeur a changé, quelle qu'en soit la cause.
    valueChanged = Signal()
    #: Seule la date a changé, du fait de l'utilisateur.
    dateEdited = Signal(QDate)

    def __init__(self, palette: Palette, parent=None):
        super().__init__(parent)
        self.palette_ = palette
        self._date = QDate.currentDate()
        self._time = QTime(0, 0, 0)
        self._silent = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.date_button = QPushButton()
        self.date_button.setToolTip(tr("Choose the date"))
        self.date_button.clicked.connect(self._open_date_picker)
        layout.addWidget(self.date_button)

        self.time_button = QPushButton()
        self.time_button.setToolTip(tr("Choose the time"))
        self.time_button.clicked.connect(self._open_time_picker)
        layout.addWidget(self.time_button)

        self._refresh_labels()

    def set_palette_colors(self, palette: Palette) -> None:
        self.palette_ = palette

    def _refresh_labels(self) -> None:
        """Réaffiche les libellés et réserve la place du texte le plus long.

        La largeur découle de la police effective : une mise à l'échelle de
        l'écran ou un changement de police ne peut donc pas rogner le texte.
        """
        self.date_button.setText(self._date.toString(DATE_FORMAT))
        self.time_button.setText(self._time.toString(TIME_FORMAT))

        margin = 32  # bordures et remplissage horizontal du bouton
        self.date_button.setMinimumWidth(
            self.date_button.fontMetrics().horizontalAdvance("30/12/2026") + margin
        )
        self.time_button.setMinimumWidth(
            self.time_button.fontMetrics().horizontalAdvance("00:00:00") + margin
        )

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == event.Type.FontChange:
            self._refresh_labels()

    # ------------------------------------------------------------- valeur

    def dateTime(self) -> QDateTime:
        return QDateTime(self._date, self._time)

    def setDateTime(self, value: QDateTime, silent: bool = False) -> None:
        previous = self._silent
        self._silent = True
        self.set_date(value.date(), silent=True)
        self._silent = previous
        self.set_time(value.time(), silent=silent)

    def date(self) -> QDate:
        return QDate(self._date)

    def set_date(self, value: QDate, silent: bool = False) -> None:
        """Change la date. Sans ``silent``, prévient comme le ferait un clic."""
        if not value.isValid():
            return
        self._date = QDate(value)
        self._refresh_labels()
        if silent or self._silent:
            return
        # L'écouteur cale d'abord l'heure sur les événements du jour choisi ;
        # la valeur complète n'est signalée qu'ensuite, une seule fois.
        self.dateEdited.emit(QDate(self._date))
        self.valueChanged.emit()

    def time(self) -> QTime:
        return QTime(self._time)

    def set_time(self, value: QTime, silent: bool = False) -> None:
        self._time = QTime(value)
        self._refresh_labels()
        if not silent and not self._silent:
            self.valueChanged.emit()

    # ------------------------------------------------------------- panneaux

    def _open_date_picker(self) -> None:
        popup = DatePickerPopup(self._date, self.palette_, self)
        popup.datePicked.connect(self.set_date)
        self._show_under(popup, self.date_button)

    def _open_time_picker(self) -> None:
        popup = TimePickerPopup(self._time, self.palette_, self)
        popup.timePicked.connect(self.set_time)
        self._show_under(popup, self.time_button)

    def _show_under(self, popup: QFrame, anchor: QPushButton) -> None:
        popup.adjustSize()
        below = anchor.mapToGlobal(anchor.rect().bottomLeft())
        screen = self.screen().availableGeometry()

        x = min(below.x(), screen.right() - popup.width() - 8)
        y = below.y() + 4
        if y + popup.height() > screen.bottom():
            # Pas la place en dessous : on ouvre au-dessus du bouton.
            y = anchor.mapToGlobal(anchor.rect().topLeft()).y() - popup.height() - 4
        popup.move(max(screen.left() + 8, x), max(screen.top() + 8, y))
        popup.show()
