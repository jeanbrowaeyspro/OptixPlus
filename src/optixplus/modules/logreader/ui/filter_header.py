"""Filtres par colonne, à la manière d'un tableur.

Chaque en-tête porte un entonnoir cliquable qui ouvre un panneau listant les
valeurs présentes dans la colonne, cochables une à une, avec une zone de
recherche et un filtre « contient » qui reste utilisable même quand la colonne
comporte trop de valeurs distinctes pour être listée (le message ou
l'horodatage, typiquement).

Le tri reste accessible par un clic sur le reste de l'en-tête, ainsi que par
deux boutons en haut du panneau. L'indicateur de tri est dessiné ici plutôt que
par Qt, afin qu'il cohabite proprement avec l'entonnoir.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QStyle, QVBoxLayout,
)

from ....common.i18n import tr
from ....common.theme import Palette, popup_stylesheet

#: Largeur réservée à droite de chaque en-tête pour l'entonnoir et la flèche.
INDICATOR_ZONE = 36
FUNNEL_WIDTH = 11
FUNNEL_HEIGHT = 10

#: Marge laissée libre au bord droit de chaque section. La poignée de
#: redimensionnement de Qt se trouve exactement là : sans cette réserve,
#: viser la séparation entre deux colonnes ouvre le filtre au lieu de
#: redimensionner.
GRIP_RESERVE = 9

#: Au-delà de ce nombre de valeurs distinctes, la liste devient inexploitable
#: et le panneau ne propose que le filtre « contient ».
MAX_DISTINCT_VALUES = 1500


class FilterHeaderView(QHeaderView):
    """En-tête horizontal avec entonnoir de filtre et indicateur de tri dessinés."""

    filterRequested = Signal(int, QPoint)

    def __init__(self, palette: Palette, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.palette_ = palette
        self._filtered: set[int] = set()
        self.setSectionsClickable(True)
        self.setHighlightSections(False)
        # Qt dessinerait sa flèche de tri à l'extrême droite, exactement où se
        # trouve l'entonnoir : on la peint nous-mêmes, un peu plus à gauche.
        self.setSortIndicatorShown(False)
        # En dessous, l'entonnoir et la flèche de tri ne laisseraient plus
        # de place au titre de la colonne.
        self.setMinimumSectionSize(78)

    def set_palette_colors(self, palette: Palette) -> None:
        self.palette_ = palette
        self.viewport().update()

    def set_filtered_columns(self, columns) -> None:
        self._filtered = set(columns)
        self.viewport().update()

    # ------------------------------------------------------------- géométrie

    def _grip_margin(self) -> int:
        """Largeur de la poignée de redimensionnement, selon le style en cours."""
        style_margin = self.style().pixelMetric(
            QStyle.PixelMetric.PM_HeaderGripMargin, None, self
        )
        return max(GRIP_RESERVE, style_margin + 4)

    def _funnel_rect(self, rect: QRect) -> QRect:
        return QRect(
            rect.right() - self._grip_margin() - FUNNEL_WIDTH,
            rect.center().y() - FUNNEL_HEIGHT // 2,
            FUNNEL_WIDTH,
            FUNNEL_HEIGHT,
        )

    def _hit_zone(self, rect: QRect) -> QRect:
        """Zone cliquable de l'entonnoir.

        Elle déborde de quelques pixels à gauche de l'icône pour rester facile
        à viser, mais s'arrête avant la poignée de redimensionnement : la
        séparation entre deux colonnes reste donc attrapable.
        """
        funnel = self._funnel_rect(rect)
        return QRect(funnel.left() - 5, rect.top(),
                     funnel.width() + 8, rect.height())

    # ------------------------------------------------------------- rendu

    def paintSection(self, painter: QPainter, rect: QRect, logical_index: int) -> None:
        super().paintSection(painter, rect, logical_index)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        active = logical_index in self._filtered
        colour = QColor(self.palette_.accent if active else self.palette_.text_muted)

        self._paint_funnel(painter, self._funnel_rect(rect), colour, filled=active)

        if self.sortIndicatorSection() == logical_index:
            arrow = QRect(
                self._funnel_rect(rect).left() - 14, rect.center().y() - 3, 9, 6
            )
            self._paint_sort_arrow(
                painter, arrow,
                QColor(self.palette_.text),
                ascending=self.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder,
            )
        painter.restore()

    @staticmethod
    def _paint_funnel(painter: QPainter, rect: QRect, colour: QColor, filled: bool) -> None:
        left, right = float(rect.left()), float(rect.right())
        top, bottom = float(rect.top()), float(rect.bottom())
        middle = (left + right) / 2.0
        neck = top + rect.height() * 0.45

        funnel = QPolygonF([
            QPoint(int(left), int(top)),
            QPoint(int(right), int(top)),
            QPoint(int(middle + 2), int(neck)),
            QPoint(int(middle + 2), int(bottom)),
            QPoint(int(middle - 2), int(bottom - 2)),
            QPoint(int(middle - 2), int(neck)),
        ])
        pen = QPen(colour)
        pen.setWidthF(1.2)
        painter.setPen(pen)
        painter.setBrush(colour if filled else Qt.BrushStyle.NoBrush)
        painter.drawPolygon(funnel)

    @staticmethod
    def _paint_sort_arrow(painter: QPainter, rect: QRect, colour: QColor,
                          ascending: bool) -> None:
        if ascending:
            points = [
                QPoint(rect.left(), rect.bottom()),
                QPoint(rect.right(), rect.bottom()),
                QPoint(rect.center().x(), rect.top()),
            ]
        else:
            points = [
                QPoint(rect.left(), rect.top()),
                QPoint(rect.right(), rect.top()),
                QPoint(rect.center().x(), rect.bottom()),
            ]
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(colour)
        painter.drawPolygon(QPolygonF(points))

    # ------------------------------------------------------------- souris

    def mousePressEvent(self, event) -> None:
        index = self.logicalIndexAt(event.position().toPoint())
        if index >= 0 and not self._near_section_edge(event.position().toPoint()):
            left = self.sectionViewportPosition(index)
            rect = QRect(left, 0, self.sectionSize(index), self.height())
            if self._hit_zone(rect).contains(event.position().toPoint()):
                # Clic sur l'entonnoir : on ouvre le filtre au lieu de trier.
                below = self.mapToGlobal(QPoint(rect.left(), self.height()))
                self.filterRequested.emit(index, below)
                event.accept()
                return
        super().mousePressEvent(event)

    def _near_section_edge(self, position) -> bool:
        """Vrai si le curseur est sur une séparation de colonnes.

        Qt y affiche déjà le curseur de redimensionnement ; on lui laisse la
        main plutôt que d'ouvrir le filtre.
        """
        margin = self._grip_margin()
        for index in range(self.count()):
            if self.isSectionHidden(index):
                continue
            edge = self.sectionViewportPosition(index) + self.sectionSize(index)
            if abs(position.x() - edge) <= margin:
                return True
        return False


class ColumnFilterPopup(QFrame):
    """Panneau de filtre d'une colonne."""

    applied = Signal(int, object, str)   # colonne, valeurs autorisées (ou None), texte
    sortRequested = Signal(int, Qt.SortOrder)

    def __init__(self, column: int, title: str, values: list[tuple[str, int]],
                 selected: set[str] | None, text: str, truncated: bool,
                 palette: Palette, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.column = column
        self.palette_ = palette
        self._all_values = values
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumWidth(320)
        self.setMaximumHeight(500)
        self.setObjectName("columnFilter")
        self.setStyleSheet(popup_stylesheet("columnFilter", palette))
        self._build(title, values, selected, text, truncated)

    def _build(self, title: str, values, selected, text: str, truncated: bool) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        heading = QLabel(title)
        heading.setProperty("heading", True)
        layout.addWidget(heading)

        sort_row = QHBoxLayout()
        sort_row.setSpacing(6)
        ascending = QPushButton(tr("Sort A → Z"))
        ascending.clicked.connect(
            lambda: self._sort(Qt.SortOrder.AscendingOrder)
        )
        descending = QPushButton(tr("Sort Z → A"))
        descending.clicked.connect(
            lambda: self._sort(Qt.SortOrder.DescendingOrder)
        )
        sort_row.addWidget(ascending)
        sort_row.addWidget(descending)
        layout.addLayout(sort_row)

        self.contains_edit = QLineEdit(text)
        self.contains_edit.setPlaceholderText(tr("Contains the text…"))
        self.contains_edit.setClearButtonEnabled(True)
        layout.addWidget(self.contains_edit)

        self.list = QListWidget()
        self.list.setUniformItemSizes(True)

        if truncated:
            notice = QLabel(
                tr("Too many different values in this column to list them. Use the “contains” filter above.")
            )
            notice.setWordWrap(True)
            notice.setProperty("muted", True)
            layout.addWidget(notice)
            self.list.hide()
            self.select_all = None
            self.search_edit = None
        else:
            self.search_edit = QLineEdit()
            self.search_edit.setPlaceholderText(tr("Search for a value…"))
            self.search_edit.setClearButtonEnabled(True)
            self.search_edit.textChanged.connect(self._filter_value_list)
            layout.addWidget(self.search_edit)

            self.select_all = QCheckBox(tr("Select all"))
            self.select_all.setTristate(True)
            self.select_all.clicked.connect(self._toggle_all)
            layout.addWidget(self.select_all)

            for value, count in values:
                item = QListWidgetItem(f"{value or tr('(empty)')}    ·  {count}")
                item.setData(Qt.ItemDataRole.UserRole, value)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                checked = selected is None or value in selected
                item.setCheckState(
                    Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
                )
                self.list.addItem(item)
            self.list.itemChanged.connect(self._refresh_select_all)
            layout.addWidget(self.list, 1)
            self._refresh_select_all()

        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        clear = QPushButton(tr("Clear"))
        clear.setToolTip(tr("Removes the filter of this column."))
        clear.clicked.connect(self._clear)
        buttons.addWidget(clear)
        buttons.addStretch(1)
        cancel = QPushButton(tr("Cancel"))
        cancel.clicked.connect(self.close)
        buttons.addWidget(cancel)
        apply_button = QPushButton(tr("Apply"))
        apply_button.setProperty("accent", True)
        apply_button.setDefault(True)
        apply_button.clicked.connect(self._apply)
        buttons.addWidget(apply_button)
        layout.addLayout(buttons)

    # ------------------------------------------------------------- actions

    def _sort(self, order: Qt.SortOrder) -> None:
        self.sortRequested.emit(self.column, order)
        self.close()

    def _filter_value_list(self, needle: str) -> None:
        needle = needle.strip().lower()
        for row in range(self.list.count()):
            item = self.list.item(row)
            item.setHidden(bool(needle) and needle not in item.text().lower())

    def _toggle_all(self) -> None:
        # Un clic sur une case tristate passerait par l'état partiel : on force
        # un basculement franc entre « tout » et « rien ».
        target = (
            Qt.CheckState.Unchecked
            if self.select_all.checkState() == Qt.CheckState.Checked
            else Qt.CheckState.Checked
        )
        self.list.blockSignals(True)
        for row in range(self.list.count()):
            item = self.list.item(row)
            if not item.isHidden():
                item.setCheckState(target)
        self.list.blockSignals(False)
        self._refresh_select_all()

    def _refresh_select_all(self, *_args) -> None:
        if self.select_all is None:
            return
        total = self.list.count()
        checked = sum(
            1 for row in range(total)
            if self.list.item(row).checkState() == Qt.CheckState.Checked
        )
        self.select_all.blockSignals(True)
        if checked == 0:
            self.select_all.setCheckState(Qt.CheckState.Unchecked)
        elif checked == total:
            self.select_all.setCheckState(Qt.CheckState.Checked)
        else:
            self.select_all.setCheckState(Qt.CheckState.PartiallyChecked)
        self.select_all.blockSignals(False)

    def _clear(self) -> None:
        self.applied.emit(self.column, None, "")
        self.close()

    def _apply(self) -> None:
        text = self.contains_edit.text().strip()
        if self.list.isHidden():
            self.applied.emit(self.column, None, text)
            self.close()
            return

        checked = {
            self.list.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(self.list.count())
            if self.list.item(row).checkState() == Qt.CheckState.Checked
        }
        # Tout coché revient à ne pas filtrer : inutile de faire porter un test
        # à chaque ligne pour un filtre qui ne retire rien.
        values = None if len(checked) == self.list.count() else checked
        self.applied.emit(self.column, values, text)
        self.close()
