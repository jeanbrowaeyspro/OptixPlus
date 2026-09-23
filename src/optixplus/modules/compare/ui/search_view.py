"""Recherche plein texte dans les deux modèles : saisie, options, résultats, ouverture dans la vue diff."""

from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ....common.i18n import tr
from ....common.progress import Cancelled
from ..core.scan import Inventory
from ..core.search import SearchHit, search_inventory


class SearchWorker(QThread):
    progressed = Signal(str, int, int)
    finished_hits = Signal(object)  # list[SearchHit]
    failed = Signal(str)

    def __init__(self, inventory: Inventory, motif: str, regex: bool, casse: bool, only_nodes: bool, parent=None) -> None:
        super().__init__(parent)
        self.inventory, self.motif, self.regex, self.casse, self.only_nodes = inventory, motif, regex, casse, only_nodes
        self._cancel = False

    def request_cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            hits = search_inventory(
                self.inventory,
                self.motif,
                regex=self.regex,
                casse=self.casse,
                only_nodes=self.only_nodes,
                progress=lambda p: self.progressed.emit(p.current, p.index, p.total),
                cancel=lambda: self._cancel,
            )
        except Cancelled:
            self.finished_hits.emit([])
        except Exception as exc:  # noqa: BLE001 — regex invalide, lecture impossible…
            self.failed.emit(str(exc))
        else:
            self.finished_hits.emit(hits)


class SearchView(QWidget):
    hit_activated = Signal(str, str, int)  # side, rel, line_no

    @staticmethod
    def colonnes() -> list[str]:
        return [tr("Side"), tr("File"), tr("Line"), tr("Text")]


    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.inventory: Inventory | None = None
        self.worker: SearchWorker | None = None
        self.hits: list[SearchHit] = []

        self.input = QLineEdit()
        self.input.setPlaceholderText(tr("Text to search in both models (Enter to start)…"))
        self.input.returnPressed.connect(self.start)
        self.regex = QCheckBox(tr("Regular expression"))
        self.casse = QCheckBox(tr("Match case"))
        self.only_nodes = QCheckBox(tr("Nodes/ only"))
        self.only_nodes.setChecked(True)
        self.button = QPushButton(tr("Find"))
        self.button.clicked.connect(self.start)
        self.status = QLabel("")

        self.model = QStandardItemModel(0, 4, self)
        self.model.setHorizontalHeaderLabels(self.colonnes())
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.doubleClicked.connect(self._on_double_click)

        top = QHBoxLayout()
        top.addWidget(self.input, 1)
        top.addWidget(self.regex)
        top.addWidget(self.casse)
        top.addWidget(self.only_nodes)
        top.addWidget(self.button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(top)
        layout.addWidget(self.status)
        layout.addWidget(self.table, 1)

    def set_inventory(self, inventory: Inventory) -> None:
        self.inventory = inventory
        self.model.removeRows(0, self.model.rowCount())
        self.hits = []
        self.status.setText("")

    def start(self) -> None:
        if self.inventory is None or self.worker is not None and self.worker.isRunning():
            return
        motif = self.input.text()
        if not motif:
            return
        self.button.setEnabled(False)
        self.status.setText(tr("Search in progress…"))
        self.worker = SearchWorker(self.inventory, motif, self.regex.isChecked(), self.casse.isChecked(), self.only_nodes.isChecked(), self)
        self.worker.progressed.connect(lambda current, i, n: self.status.setText(f"{i}/{n}  {current}"))
        self.worker.finished_hits.connect(self._on_hits)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _on_hits(self, hits: list[SearchHit]) -> None:
        self.hits = hits
        self.model.removeRows(0, self.model.rowCount())
        for k, hit in enumerate(hits):
            side = tr("runtime") if hit.side == "runtime" else tr("project")
            items = [QStandardItem(side), QStandardItem(hit.rel), QStandardItem(str(hit.line_no)), QStandardItem(hit.text)]
            items[2].setData(hit.line_no, Qt.ItemDataRole.UserRole)
            for item in items:
                item.setData(k, Qt.ItemDataRole.UserRole + 1)
            self.model.appendRow(items)
        self.table.resizeColumnsToContents()
        n_r = sum(1 for h in hits if h.side == "runtime")
        self.status.setText(
            tr("{n} occurrence(s): {runtime} on the runtime side, {project} on the project side").format(
                n=len(hits), runtime=n_r, project=len(hits) - n_r
            )
        )
        self.button.setEnabled(True)

    def _on_failed(self, message: str) -> None:
        self.status.setText(tr("Search impossible: {error}").format(error=message))
        self.button.setEnabled(True)

    def _on_double_click(self, index) -> None:
        k = index.data(Qt.ItemDataRole.UserRole + 1)
        if k is None:
            return
        hit = self.hits[k]
        self.hit_activated.emit(hit.side, hit.rel, hit.line_no)
