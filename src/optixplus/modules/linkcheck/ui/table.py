"""Tableau des liens cassés (repris de Link Checker)."""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableView, QWidget

from ....common.i18n import tr
from ....common.widgets import scrollbar_below_header
from ..core.project import BrokenLink, reason_label

COLUMN_WIDTHS = [170, 430, 110, 330, 220, 330]


def column_titles() -> list[str]:
    return [
        tr("Screen / area"),
        tr("Path in Studio (object holding the link)"),
        tr("Property"),
        tr("Current target"),
        tr("Reason"),
        tr("Suggestion"),
    ]


class LinksModel(QAbstractTableModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.rows: list[BrokenLink] = []
        self._titles = column_titles()

    def set_rows(self, rows: list[BrokenLink]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802 (API Qt)
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802 (API Qt)
        return len(self._titles)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802 (API Qt)
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self._titles[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        link = self.rows[index.row()]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return [
                link.screen,
                link.owner_path,
                link.prop,
                link.target,
                reason_label(link),
                link.suggestions[0] if link.suggestions else "",
            ][index.column()]
        return None


class LinkTable(QTableView):
    """Dernière colonne collée au bord droit, mais étirable à la main (comportement d'origine)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._last_user = 0
        self._adjusting = False
        scrollbar_below_header(self)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.verticalHeader().setVisible(False)
        header = self.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.sectionResized.connect(self._on_section_resized)

    def setModel(self, model) -> None:  # noqa: N802 (API Qt)
        super().setModel(model)
        for i, width in enumerate(COLUMN_WIDTHS):
            self.setColumnWidth(i, width)
        self._adjust()

    def _on_section_resized(self, index: int, _old: int, new: int) -> None:
        if self._adjusting or self.model() is None:
            return
        if index == self.model().columnCount() - 1:
            self._last_user = new
        self._adjust()

    def resizeEvent(self, event) -> None:  # noqa: N802 (API Qt)
        super().resizeEvent(event)
        self._adjust()

    def _adjust(self) -> None:
        model = self.model()
        if model is None or self._adjusting:
            return
        last = model.columnCount() - 1
        others = sum(self.columnWidth(i) for i in range(last))
        width = max(self._last_user, self.viewport().width() - others, 80)
        if self.columnWidth(last) != width:
            self._adjusting = True
            self.setColumnWidth(last, width)
            self._adjusting = False
