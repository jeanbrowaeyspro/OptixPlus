"""Tableaux en lecture seule de la page Statistiques : modèle générique à cellules (texte, clé de tri)."""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableView, QWidget

from ....common.widgets import scrollbar_below_header

#: Une cellule : texte affiché, clé de tri (nombre ou texte), infobulle facultative.
Cell = tuple[str, object, str]


def cell(text: str, key: object = None, tooltip: str = "") -> Cell:
    return (text, text.lower() if key is None else key, tooltip)


class RowsModel(QAbstractTableModel):
    def __init__(self, titles: list[str], rows: list[list[Cell]], parent=None) -> None:
        super().__init__(parent)
        self._titles = titles
        self.rows = rows

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
        text, key, tooltip = self.rows[index.row()][index.column()]
        if role == Qt.ItemDataRole.DisplayRole:
            return text
        if role == Qt.ItemDataRole.UserRole:
            return key
        if role == Qt.ItemDataRole.ToolTipRole:
            return tooltip or text
        if role == Qt.ItemDataRole.TextAlignmentRole and isinstance(key, (int, float)):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None


class _SortProxy(QSortFilterProxyModel):
    """Tri sur la clé de chaque cellule (nombres comparés comme des nombres)."""

    def lessThan(self, left, right) -> bool:  # noqa: N802 (API Qt)
        a, b = left.data(Qt.ItemDataRole.UserRole), right.data(Qt.ItemDataRole.UserRole)
        try:
            return a < b
        except TypeError:
            return str(a) < str(b)


class StatsTable(QTableView):
    """Tableau triable par colonne, à la hauteur de son contenu (au plus ``max_rows`` lignes visibles)."""

    def __init__(self, titles: list[str], rows: list[list[Cell]], *, max_rows: int = 12, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        scrollbar_below_header(self)
        self.rows_model = RowsModel(titles, rows, self)
        self.proxy = _SortProxy(self)
        self.proxy.setSourceModel(self.rows_model)
        self.proxy.setSortRole(Qt.ItemDataRole.UserRole)
        self.setModel(self.proxy)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.verticalHeader().setVisible(False)
        self.setSortingEnabled(True)
        self.sortByColumn(-1, Qt.SortOrder.AscendingOrder)  # ordre du calcul tant qu'on ne trie pas
        header = self.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSortIndicatorShown(True)
        shown = max(1, min(len(rows), max_rows))
        self.setFixedHeight(header.sizeHint().height() + shown * self.verticalHeader().defaultSectionSize() + 4)
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded if len(rows) > max_rows else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

    def sort_state(self) -> tuple[int, int]:
        """(colonne, ordre) du tri courant ; colonne -1 si aucun."""
        header = self.horizontalHeader()
        return (header.sortIndicatorSection() if self.proxy.sortColumn() >= 0 else -1, int(header.sortIndicatorOrder().value))

    def set_sort_state(self, column: int, order: int) -> None:
        if column >= 0:
            self.sortByColumn(column, Qt.SortOrder(order))

    def displayed(self, column: int) -> list[str]:
        """Textes d'une colonne dans l'ordre affiché (utile aux tests)."""
        return [self.proxy.index(r, column).data() for r in range(self.proxy.rowCount())]
