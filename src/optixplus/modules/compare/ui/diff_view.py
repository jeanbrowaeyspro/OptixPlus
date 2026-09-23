"""Vue diff côte à côte : numéros de ligne, coloration, repli des zones identiques, navigation par hunk.

Les deux côtés sont alignés dans une seule table (projet à gauche, runtime à droite), ce qui
donne la synchronisation du défilement gratuitement. Les zones identiques plus longues que le
contexte sont repliées en une ligne « … N lignes identiques … » dépliable d'un clic.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..core.diffing import Opcode

CONTEXTE = 3

FOND: dict[str, QColor] = {
    "insert": QColor(46, 125, 50, 70),
    "delete": QColor(198, 40, 40, 70),
    "replace": QColor(239, 108, 0, 70),
    "vide": QColor(128, 128, 128, 40),
    "pli": QColor(128, 128, 128, 25),
}


@dataclass(slots=True)
class DiffRow:
    kind: str  # "equal" | "insert" | "delete" | "replace" | "pli"
    a_no: int | None  # numéro de ligne projet (1-based) ou None
    b_no: int | None
    a_text: bytes | None
    b_text: bytes | None
    hunk: int  # index du hunk (opcodes non equal) ou -1
    pli: int = -1  # identifiant du pli pour une ligne "pli"
    pli_taille: int = 0


class DiffModel(QAbstractTableModel):
    COLONNES = ("N°", "Projet", "N°", "Runtime")
    COL_A_NO, COL_A, COL_B_NO, COL_B = range(4)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.a: Sequence[bytes] = []
        self.b: Sequence[bytes] = []
        self.opcodes: list[Opcode] = []
        self.rows: list[DiffRow] = []
        self.hunk_rows: list[int] = []  # ligne de début de chaque hunk
        self.expanded: set[int] = set()
        self.fold = True
        self._mono = QFont("Consolas", 9)

    # -- Construction ----------------------------------------------------------

    def set_content(self, a: Sequence[bytes], b: Sequence[bytes], opcodes: Sequence[Opcode]) -> None:
        self.a, self.b, self.opcodes = a, b, list(opcodes)
        self.expanded = set()
        self.rebuild()

    def rebuild(self) -> None:
        self.beginResetModel()
        rows: list[DiffRow] = []
        hunk_rows: list[int] = []
        hunk_index = -1
        for k, (tag, i1, i2, j1, j2) in enumerate(self.opcodes):
            if tag == "equal":
                n = i2 - i1
                first = k == 0
                last = k == len(self.opcodes) - 1
                head = 0 if first else CONTEXTE
                tail = 0 if last else CONTEXTE
                if self.fold and k not in self.expanded and n > head + tail + 2:
                    for d in range(head):
                        rows.append(DiffRow("equal", i1 + d + 1, j1 + d + 1, self.a[i1 + d], self.b[j1 + d], -1))
                    hidden = n - head - tail
                    rows.append(DiffRow("pli", None, None, None, None, -1, pli=k, pli_taille=hidden))
                    for d in range(n - tail, n):
                        rows.append(DiffRow("equal", i1 + d + 1, j1 + d + 1, self.a[i1 + d], self.b[j1 + d], -1))
                else:
                    for d in range(n):
                        rows.append(DiffRow("equal", i1 + d + 1, j1 + d + 1, self.a[i1 + d], self.b[j1 + d], -1))
                continue
            hunk_index += 1
            hunk_rows.append(len(rows))
            na, nb = i2 - i1, j2 - j1
            for d in range(max(na, nb)):
                a_ok, b_ok = d < na, d < nb
                rows.append(
                    DiffRow(
                        tag,
                        i1 + d + 1 if a_ok else None,
                        j1 + d + 1 if b_ok else None,
                        self.a[i1 + d] if a_ok else None,
                        self.b[j1 + d] if b_ok else None,
                        hunk_index,
                    )
                )
        self.rows = rows
        self.hunk_rows = hunk_rows
        self.endResetModel()

    def toggle_fold(self, row: int) -> None:
        r = self.rows[row]
        if r.kind == "pli":
            self.expanded.add(r.pli)
            self.rebuild()

    def set_folding(self, fold: bool) -> None:
        self.fold = fold
        self.rebuild()

    def row_of_hunk(self, hunk_index: int) -> int:
        if 0 <= hunk_index < len(self.hunk_rows):
            return self.hunk_rows[hunk_index]
        return -1

    def hunk_at(self, row: int) -> int:
        return self.rows[row].hunk if 0 <= row < len(self.rows) else -1

    # -- Modèle ------------------------------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 4

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.COLONNES[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        r = self.rows[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if r.kind == "pli":
                return f"… {r.pli_taille} lignes identiques (cliquer pour déplier) …" if col == self.COL_A else ""
            if col == self.COL_A_NO:
                return str(r.a_no) if r.a_no else ""
            if col == self.COL_B_NO:
                return str(r.b_no) if r.b_no else ""
            if col == self.COL_A:
                return r.a_text.decode("utf-8", "replace").replace("\t", "    ") if r.a_text is not None else ""
            if col == self.COL_B:
                return r.b_text.decode("utf-8", "replace").replace("\t", "    ") if r.b_text is not None else ""
        elif role == Qt.ItemDataRole.BackgroundRole:
            if r.kind == "pli":
                return QBrush(FOND["pli"])
            if r.kind == "equal":
                return None
            side_a = col in (self.COL_A_NO, self.COL_A)
            if side_a and r.a_text is None or not side_a and r.b_text is None:
                return QBrush(FOND["vide"])
            return QBrush(FOND[r.kind])
        elif role == Qt.ItemDataRole.FontRole:
            font = QFont(self._mono)
            if r.kind == "pli":
                font.setItalic(True)
            return font
        elif role == Qt.ItemDataRole.TextAlignmentRole and col in (self.COL_A_NO, self.COL_B_NO):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        elif role == Qt.ItemDataRole.ForegroundRole and col in (self.COL_A_NO, self.COL_B_NO):
            return QBrush(QColor(128, 128, 128))
        return None


class DiffView(QWidget):
    """La table alignée, la barre de navigation et le repli des zones identiques."""

    hunk_changed = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.model = DiffModel(self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setWordWrap(False)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(18)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(DiffModel.COL_A_NO, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(DiffModel.COL_B_NO, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(DiffModel.COL_A, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(DiffModel.COL_B, QHeaderView.ResizeMode.Stretch)
        header.resizeSection(DiffModel.COL_A_NO, 60)
        header.resizeSection(DiffModel.COL_B_NO, 60)
        self.table.clicked.connect(self._on_click)
        self.table.selectionModel().currentRowChanged.connect(self._on_current)

        self.prev_button = QPushButton("◀ Hunk précédent")
        self.next_button = QPushButton("Hunk suivant ▶")
        self.prev_button.clicked.connect(self.previous_hunk)
        self.next_button.clicked.connect(self.next_hunk)
        self.position = QLabel("")
        self.fold_box = QCheckBox("Replier les zones identiques")
        self.fold_box.setChecked(True)
        self.fold_box.toggled.connect(self._toggle_fold)
        self.title = QLabel("")
        self.title.setTextFormat(Qt.TextFormat.RichText)

        bar = QHBoxLayout()
        bar.addWidget(self.title, 1)
        bar.addWidget(self.prev_button)
        bar.addWidget(self.position)
        bar.addWidget(self.next_button)
        bar.addWidget(self.fold_box)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(bar)
        layout.addWidget(self.table, 1)
        self._current_hunk = -1

    # -- API ----------------------------------------------------------------------

    def set_content(self, a: Sequence[bytes], b: Sequence[bytes], opcodes: Sequence[Opcode], titre: str = "") -> None:
        self.model.set_content(a, b, opcodes)
        self.title.setText(titre)
        self._current_hunk = -1
        self._update_position()
        if self.model.hunk_rows:
            self.go_to_hunk(0)

    def clear(self) -> None:
        self.model.set_content([], [], [])
        self.title.setText("")
        self._update_position()

    def nb_hunks(self) -> int:
        return len(self.model.hunk_rows)

    def current_hunk(self) -> int:
        return self._current_hunk

    def go_to_hunk(self, hunk_index: int) -> None:
        row = self.model.row_of_hunk(hunk_index)
        if row < 0:
            return
        self._current_hunk = hunk_index
        index = self.model.index(row, DiffModel.COL_A)
        self.table.setCurrentIndex(index)
        self.table.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)
        self._update_position()
        self.hunk_changed.emit(hunk_index)

    def go_to_opcode(self, opcode: Opcode) -> None:
        """Positionne la vue sur le hunk correspondant à cet opcode (venant du résumé sémantique)."""
        non_equal = [op for op in self.model.opcodes if op[0] != "equal"]
        if opcode in non_equal:
            self.go_to_hunk(non_equal.index(opcode))
            return
        if not non_equal:
            return
        # Hunk synthétique (ex. TypeMapping par GUID) : aller au hunk réel le plus proche.
        side = 3 if opcode[0] == "insert" else 1
        target = opcode[side]
        distances = [abs(op[side] - target) for op in non_equal]
        self.go_to_hunk(distances.index(min(distances)))

    def go_to_line(self, side: str, line_no: int) -> None:
        """Positionne la vue sur une ligne (1-based) du projet ou du runtime, en dépliant si besoin."""
        self.model.set_folding(False)
        self.fold_box.blockSignals(True)
        self.fold_box.setChecked(False)
        self.fold_box.blockSignals(False)
        attr = "a_no" if side == "projet" else "b_no"
        for row, r in enumerate(self.model.rows):
            if getattr(r, attr) == line_no:
                index = self.model.index(row, DiffModel.COL_A if side == "projet" else DiffModel.COL_B)
                self.table.setCurrentIndex(index)
                self.table.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)
                return

    def next_hunk(self) -> None:
        if self.nb_hunks():
            self.go_to_hunk(min(self._current_hunk + 1, self.nb_hunks() - 1))

    def previous_hunk(self) -> None:
        if self.nb_hunks():
            self.go_to_hunk(max(self._current_hunk - 1, 0))

    # -- Interne --------------------------------------------------------------------

    def _update_position(self) -> None:
        n = self.nb_hunks()
        self.position.setText(f"{self._current_hunk + 1} / {n}" if n else "—")
        self.prev_button.setEnabled(n > 0 and self._current_hunk > 0)
        self.next_button.setEnabled(n > 0 and self._current_hunk < n - 1)

    def _toggle_fold(self, checked: bool) -> None:
        self.model.set_folding(checked)
        if self._current_hunk >= 0:
            self.go_to_hunk(self._current_hunk)

    def _on_click(self, index: QModelIndex) -> None:
        if self.model.rows[index.row()].kind == "pli":
            self.model.toggle_fold(index.row())
            if self._current_hunk >= 0:
                row = self.model.row_of_hunk(self._current_hunk)
                self.table.setCurrentIndex(self.model.index(row, DiffModel.COL_A))

    def _on_current(self, current: QModelIndex, _previous: QModelIndex) -> None:
        hunk = self.model.hunk_at(current.row()) if current.isValid() else -1
        if hunk >= 0 and hunk != self._current_hunk:
            self._current_hunk = hunk
            self._update_position()
            self.hunk_changed.emit(hunk)
