"""Vue diff côte à côte : numéros de ligne, coloration, repli des zones identiques, navigation par hunk.

Les deux côtés sont alignés dans une seule table (projet à gauche, runtime à droite), ce qui
donne la synchronisation du défilement gratuitement. Les zones identiques plus longues que le
contexte sont repliées en une ligne « … N lignes identiques … » dépliable d'un clic.
"""

from __future__ import annotations

from bisect import bisect_right

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

from ....common import theme
from ....common.i18n import tr
from ..core.diffing import Opcode

CONTEXTE = 3



def fond(kind: str) -> QColor:
    """Fond translucide d'une ligne de diff, dérivé des couleurs du thème (clair ou sombre)."""
    p = theme.current()
    base, alpha = {
        "insert": (p.success, 70),
        "delete": (p.error, 70),
        "replace": (p.warning, 70),
        "vide": (p.text_muted, 40),
        "pli": (p.text_muted, 25),
    }.get(kind, (p.text_muted, 25))
    color = QColor(base)
    color.setAlpha(alpha)
    return color


@dataclass(slots=True)
class _Run:
    """Un bloc de rangées consécutives de même nature (voir ``_Rows``)."""

    start: int  # index de la première rangée
    kind: str
    count: int  # nombre de rangées
    a0: int  # index (0-based) de la première ligne projet
    b0: int
    na: int  # lignes projet présentes dans le bloc (une rangée au-delà n'a pas de côté projet)
    nb: int
    hunk: int
    pli: int = -1
    pli_taille: int = 0


class _Rows(Sequence):
    """Rangées de la vue diff, construites à la demande.

    FTOCompare créait un objet ``DiffRow`` par ligne affichée (~170 000 pour un
    ``Tags.yaml`` déplié). On ne garde ici qu'un ``_Run`` par bloc ; la rangée demandée est
    fabriquée au vol par ``__getitem__`` (recherche dichotomique du bloc).
    """

    def __init__(self, runs: list[_Run], a: Sequence[bytes], b: Sequence[bytes]) -> None:
        self._runs = runs
        self._starts = [r.start for r in runs]
        self._a, self._b = a, b
        self._len = runs[-1].start + runs[-1].count if runs else 0

    def __len__(self) -> int:
        return self._len

    def __getitem__(self, index):  # type: ignore[override]
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(self._len))]
        if index < 0:
            index += self._len
        if not 0 <= index < self._len:
            raise IndexError(index)
        run = self._runs[bisect_right(self._starts, index) - 1]
        d = index - run.start
        if run.kind == "pli":
            return DiffRow("pli", None, None, None, None, -1, pli=run.pli, pli_taille=run.pli_taille)
        a_ok, b_ok = d < run.na, d < run.nb
        return DiffRow(
            run.kind,
            run.a0 + d + 1 if a_ok else None,
            run.b0 + d + 1 if b_ok else None,
            self._a[run.a0 + d] if a_ok else None,
            self._b[run.b0 + d] if b_ok else None,
            run.hunk,
        )

    def row_of_line(self, side: str, line_no: int) -> int:
        """Rangée qui affiche la ligne ``line_no`` (1-based) du côté donné, ou -1."""
        target = line_no - 1
        for run in self._runs:
            if run.kind == "pli":
                continue
            first, count = (run.a0, run.na) if side == "projet" else (run.b0, run.nb)
            if first <= target < first + count:
                return run.start + target - first
        return -1


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
    @staticmethod
    def colonnes() -> tuple[str, ...]:
        return (tr("No."), tr("Project"), tr("No."), tr("Runtime"))

    COL_A_NO, COL_A, COL_B_NO, COL_B = range(4)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.a: Sequence[bytes] = []
        self.b: Sequence[bytes] = []
        self.opcodes: list[Opcode] = []
        self.rows: _Rows = _Rows([], [], [])
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
        runs: list[_Run] = []
        hunk_rows: list[int] = []
        hunk_index = -1
        position = 0

        def add(kind: str, count: int, a0: int, b0: int, na: int, nb: int, hunk: int, **extra) -> None:
            nonlocal position
            if count > 0:
                runs.append(_Run(position, kind, count, a0, b0, na, nb, hunk, **extra))
                position += count

        for k, (tag, i1, i2, j1, j2) in enumerate(self.opcodes):
            if tag == "equal":
                n = i2 - i1
                first = k == 0
                last = k == len(self.opcodes) - 1
                head = 0 if first else CONTEXTE
                tail = 0 if last else CONTEXTE
                if self.fold and k not in self.expanded and n > head + tail + 2:
                    add("equal", head, i1, j1, head, head, -1)
                    add("pli", 1, 0, 0, 0, 0, -1, pli=k, pli_taille=n - head - tail)
                    add("equal", tail, i1 + n - tail, j1 + n - tail, tail, tail, -1)
                else:
                    add("equal", n, i1, j1, n, n, -1)
                continue
            hunk_index += 1
            hunk_rows.append(position)
            na, nb = i2 - i1, j2 - j1
            add(tag, max(na, nb), i1, j1, na, nb, hunk_index)
        self.rows = _Rows(runs, self.a, self.b)
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
            return self.colonnes()[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        r = self.rows[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if r.kind == "pli":
                return "… " + tr("{n} identical lines (click to unfold)").format(n=r.pli_taille) + " …" if col == self.COL_A else ""
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
                return QBrush(fond("pli"))
            if r.kind == "equal":
                return None
            side_a = col in (self.COL_A_NO, self.COL_A)
            if side_a and r.a_text is None or not side_a and r.b_text is None:
                return QBrush(fond("vide"))
            return QBrush(fond(r.kind))
        elif role == Qt.ItemDataRole.FontRole:
            font = QFont(self._mono)
            if r.kind == "pli":
                font.setItalic(True)
            return font
        elif role == Qt.ItemDataRole.TextAlignmentRole and col in (self.COL_A_NO, self.COL_B_NO):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        elif role == Qt.ItemDataRole.ForegroundRole and col in (self.COL_A_NO, self.COL_B_NO):
            return QBrush(QColor(theme.current().text_muted))
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

        self.prev_button = QPushButton("◀ " + tr("Previous difference"))
        self.next_button = QPushButton(tr("Next difference") + " ▶")
        self.prev_button.clicked.connect(self.previous_hunk)
        self.next_button.clicked.connect(self.next_hunk)
        self.position = QLabel("")
        self.fold_box = QCheckBox(tr("Fold identical areas"))
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
        row = self.model.rows.row_of_line(side, line_no)
        if row >= 0:
            index = self.model.index(row, DiffModel.COL_A if side == "projet" else DiffModel.COL_B)
            self.table.setCurrentIndex(index)
            self.table.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)

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
