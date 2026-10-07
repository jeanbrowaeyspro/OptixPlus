"""Page de Statistiques : choix du dossier (projet ou runtime), analyse, résultat en cartes.

L'analyse tourne en arrière-plan (``TaskWorker``), annulable. Le calcul est dans
``core.stats`` ; cette page ne fait qu'afficher le ``ProjectStatistics`` obtenu. Le bouton
Analyser est dans la barre d'actions de l'outil (jamais dupliqué dans la page).
"""

from __future__ import annotations

import logging
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ....common import icons, recent
from ....common.i18n import current_language, tr, tr_n
from ....common.progress import Progress
from ....common.widgets import ElidedLabel
from ....common.workers import TaskWorker
from ..core import export
from ..core.config import StatisticsSettings
from ..core.model import (
    KIND_RUNTIME,
    VIEW_DIALOG,
    VIEW_POPUP,
    VIEW_SCREEN,
    VIEW_WINDOW,
    ProjectStatistics,
)
from .table import StatsTable, cell

log = logging.getLogger("optixplus.statistics")

MAX_TABLE_ROWS = 14


def _load_compute():
    """Le calcul, importé à l'usage (le contrat est dans ``core.model``)."""
    from ..core.stats import compute

    return compute


def _num(value: float, decimals: int = 1) -> str:
    text = f"{value:.{decimals}f}"
    return text.replace(".", ",") if current_language() == "fr" else text


def format_size(size: int) -> str:
    if size >= 1024 * 1024:
        return tr("{value} MiB").format(value=_num(size / (1024 * 1024)))
    if size >= 1024:
        return tr("{value} KiB").format(value=_num(size / 1024))
    return tr("{value} B").format(value=size)


def kind_labels() -> dict[str, str]:
    return {VIEW_SCREEN: tr("Screen"), VIEW_DIALOG: tr("Dialog"), VIEW_POPUP: tr("Popup"), VIEW_WINDOW: tr("Window")}


def _yes_no(value: bool) -> str:
    return tr("Yes") if value else tr("No")


def _station_titles() -> list[str]:
    return [tr("Station"), tr("Driver"), tr("Address:port"), tr("Tags"), tr("Of which structures")]


class _Card(QFrame):
    """Une carte : titre et contenu (style ``card`` du thème)."""

    def __init__(self, title: str) -> None:
        super().__init__()
        self.setProperty("card", True)
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(16, 12, 16, 14)
        self.box.setSpacing(8)
        heading = QLabel(title)
        heading.setProperty("heading", True)
        self.box.addWidget(heading)

    def add(self, widget: QWidget) -> None:
        self.box.addWidget(widget)

    def add_text(self, text: str, muted: bool = False) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        if muted:
            label.setProperty("muted", True)
        self.box.addWidget(label)
        return label

    def add_facts(self, facts: list[tuple[str, str, str]]) -> None:
        """Lignes « libellé : valeur » (le troisième élément est une infobulle facultative)."""
        grid = QWidget()
        layout = QGridLayout(grid)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(16)
        layout.setVerticalSpacing(4)
        for row, (name, value, tip) in enumerate(facts):
            key = QLabel(name)
            key.setProperty("muted", True)
            val = QLabel(value)
            val.setWordWrap(True)
            if tip:
                val.setToolTip(tip)
            layout.addWidget(key, row, 0, Qt.AlignmentFlag.AlignTop)
            layout.addWidget(val, row, 1)
        layout.setColumnStretch(1, 1)
        self.add(grid)


class StatisticsPage(QWidget):
    def __init__(self, context, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self.result: ProjectStatistics | None = None
        self.tables: dict[str, StatsTable] = {}
        self._worker: TaskWorker | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 16, 24, 16)
        outer.setSpacing(10)

        # ---- dossier -----------------------------------------------------------------
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("Project or runtime")))
        self.path = QComboBox()
        self.path.setEditable(True)
        self.path.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.path.lineEdit().setPlaceholderText(tr("Project or runtime folder"))
        self.path.lineEdit().returnPressed.connect(self.analyse)
        self._fill_recent()
        if self.path.count():
            self.path.setEditText(self.path.itemText(0))
        row.addWidget(self.path, 1)
        browse = QPushButton(tr("Browse…"))
        browse.clicked.connect(self.browse)
        row.addWidget(browse)
        outer.addLayout(row)

        # ---- synthèse, remplacée par la progression pendant l'analyse -------------------
        row = QHBoxLayout()
        self.summary = QLabel(tr("Choose a project or a runtime, then Analyse."))
        self.summary.setProperty("muted", True)
        self.summary.setWordWrap(True)
        row.addWidget(self.summary, 1)
        self.progress_row = QWidget()
        progress_layout = QHBoxLayout(self.progress_row)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(240)
        self.progress.setTextVisible(False)
        self.progress_label = ElidedLabel(mode=Qt.TextElideMode.ElideMiddle)
        self.progress_label.setProperty("muted", True)
        self.cancel_button = QPushButton(tr("Cancel"))
        self.cancel_button.clicked.connect(self.cancel)
        progress_layout.addWidget(self.progress)
        progress_layout.addWidget(self.progress_label, 1)
        progress_layout.addWidget(self.cancel_button)
        self.progress_row.hide()
        row.addWidget(self.progress_row, 1)
        outer.addLayout(row)

        # ---- résultat : cartes dans une zone défilante (taille fixe pendant l'analyse) -------
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.cards = QWidget()
        self.cards_layout = QVBoxLayout(self.cards)
        self.cards_layout.setContentsMargins(0, 0, 8, 0)
        self.cards_layout.setSpacing(12)
        self.scroll.setWidget(self.cards)
        outer.addWidget(self.scroll, 1)

        self._build_actions()
        self._update_actions()

    # ---- actions ---------------------------------------------------------------------------
    def _build_actions(self) -> None:
        self.act_analyse = icons.themed_action(QAction(tr("Analyse"), self), "statistics")
        self.act_analyse.setShortcut(QKeySequence("F5"))
        self.act_analyse.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.act_analyse.triggered.connect(self.analyse)
        self.addAction(self.act_analyse)
        self.act_export = icons.themed_action(QAction(tr("Export to CSV…"), self), "export")
        self.act_export.triggered.connect(self.export_csv)
        self.act_analyse.setToolTip(tr("Analyse the whole project or runtime folder (F5)"))
        self.act_export.setToolTip(tr("Exports the station and page tables of the current analysis to a CSV file."))

    def toolbar_actions(self) -> list[QAction | None]:
        return [self.act_analyse, None, self.act_export]

    def _update_actions(self) -> None:
        busy = self._worker is not None
        self.act_analyse.setEnabled(not busy)
        self.act_export.setEnabled(not busy and self.result is not None)

    # ---- dossier ---------------------------------------------------------------------------
    def _fill_recent(self) -> None:
        current = self.path.currentText()
        self.path.blockSignals(True)
        self.path.clear()
        self.path.addItems(recent.recent_projects(self._context.settings))
        self.path.setEditText(current)
        self.path.blockSignals(False)

    def browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("Project or runtime folder"), self.path.currentText() or "")
        if folder:
            self.path.setEditText(os.path.normpath(folder))
            self.analyse()

    def open_project(self, path: str) -> None:
        self.path.setEditText(path)
        self.analyse()

    # ---- analyse ---------------------------------------------------------------------------
    @property
    def busy(self) -> bool:
        return self._worker is not None

    def analyse(self) -> None:
        if self._worker is not None:
            return
        folder = self.path.currentText().strip().strip('"')
        if not folder:
            QMessageBox.warning(self, tr("Statistics"), tr("Enter the project or runtime folder."))
            return
        options = self._context.settings.section(StatisticsSettings).options()
        compute = _load_compute()
        worker = TaskWorker(lambda progress, cancel: compute(folder, progress, cancel, options), self)
        worker.progress.connect(self._on_progress)
        worker.succeeded.connect(self._on_analysed)
        worker.failed.connect(self._on_failed)
        worker.cancelled.connect(self._on_cancelled)
        worker.finished.connect(self._on_finished)
        self._worker = worker
        self.progress.setRange(0, 0)
        self.progress_label.setText("")
        self.summary.hide()
        self.progress_row.show()
        self._update_actions()
        worker.start()

    def cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.progress_label.setText(tr("Cancelling…"))

    def stop(self) -> None:
        """Arrêt coopératif : l'analyse est annulée et attendue."""
        worker = self._worker
        if worker is not None:
            worker.cancel()
            worker.wait()

    def _on_progress(self, step: Progress) -> None:
        if step.total > 0:
            self.progress.setRange(0, step.total)
            self.progress.setValue(step.index)
            text = f"{step.phase} ({step.index}/{step.total})"
        else:
            text = step.phase
        if step.current:
            text += f" — {step.current}"
        self.progress_label.setText(text)
        self.progress_label.setToolTip(text)

    def _on_finished(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.deleteLater()
        self.progress_row.hide()
        self.summary.show()
        self._update_actions()

    def _on_failed(self, message: str) -> None:
        self.summary.setText(tr("Analysis failed."))
        QMessageBox.critical(self, tr("Analysis"), message)

    def _on_cancelled(self) -> None:
        self.summary.setText(tr("Analysis cancelled."))

    def _on_analysed(self, result: ProjectStatistics) -> None:
        recent.add_recent_project(self._context.settings, result.folder)
        self._fill_recent()
        self.path.setEditText(result.folder)
        log.info("Statistiques de %s : %d tag(s), %d page(s)", result.name, result.tags_total, len(result.pages))
        self.show_result(result)

    # ---- résultat ----------------------------------------------------------------------------
    def _summary_text(self) -> str:
        r = self.result
        if r is None:
            return tr("Choose a project or a runtime, then Analyse.")
        return tr("{name}: {tags} synchronised tags, {pages} pages.").format(name=r.name, tags=r.tags_total, pages=len(r.pages))

    def show_result(self, result: ProjectStatistics) -> None:
        self.result = result
        self.summary.setText(self._summary_text())
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.tables.clear()
        self.cards_layout.addWidget(self._header_card(result))
        self.cards_layout.addWidget(self._stations_card(result))
        self.cards_layout.addWidget(self._pages_card(result))
        self.cards_layout.addWidget(self._project_card(result))
        if result.kind == KIND_RUNTIME:
            self.cards_layout.addWidget(self._runtime_files_card(result))
        self.cards_layout.addWidget(self._memory_card(result))
        if result.warnings:
            self.cards_layout.addWidget(self._warnings_card(result))
        self.cards_layout.addStretch(1)
        self._update_actions()

    def _header_card(self, r: ProjectStatistics) -> QWidget:
        card = _Card(r.name)
        version = r.ide_version or tr("unknown")
        if r.product_version:
            version += f" ({r.product_version})"
        modules = ", ".join(f"{name} {ver}".strip() for name, ver in r.modules) or "—"
        card.add_facts(
            [
                (tr("Type"), tr("Runtime") if r.kind == KIND_RUNTIME else tr("Project"), ""),
                (tr("FT Optix version"), version, ""),
                (tr("Folder"), r.folder, ""),
                (tr("Modules"), modules, ""),
            ]
        )
        return card

    def _stations_card(self, r: ProjectStatistics) -> QWidget:
        card = _Card(tr("Controllers"))
        if not r.stations:
            card.add_text(tr("No controller station found."), muted=True)
            return card
        rows = [
            [
                cell(s.name),
                cell(s.driver_type),
                cell(export.station_address(s.address, s.port)),
                cell(str(s.tags), s.tags),
                cell(str(s.structures), s.structures),
            ]
            for s in r.stations
        ]
        table = StatsTable(_station_titles(), rows, max_rows=8)
        self.tables["stations"] = table
        card.add(table)
        card.add_text(
            tr("Synchronised tags: {tags} (including {structures} structures).").format(
                tags=r.tags_total, structures=r.structures_total
            )
        )
        return card

    def _pages_card(self, r: ProjectStatistics) -> QWidget:
        card = _Card(tr("Pages"))
        not_found = tr("not found")
        busiest = (
            tr("{title} ({tags} tags)").format(title=r.busiest_page.title, tags=r.busiest_page.tags)
            if r.busiest_page
            else not_found
        )
        facts = [
            (tr("Main pages"), str(r.main_pages), ""),
            (tr("Average tags per main page"), _num(r.average_tags_per_main_page), ""),
            (tr("Busiest page"), busiest, ""),
            (tr("Work page"), r.work_page.title if r.work_page else not_found, ""),
            (tr("Supervision page"), r.supervision_page.title if r.supervision_page else not_found, ""),
        ]
        if r.supervision_page is not None:
            facts.append((tr("Supervision default tab"), r.supervision_default_tab or tr("unknown"), ""))
        card.add_facts(facts)
        if not r.pages:
            card.add_text(tr("No page found."), muted=True)
            return card
        kinds = kind_labels()
        rows = []
        for p in r.pages:
            approx = tr("Approximate: some dynamic paths could not be resolved.") if p.approximate else ""
            rows.append(
                [
                    cell(p.title, tooltip=p.path),
                    cell(kinds.get(p.kind, p.kind)),
                    cell(_yes_no(p.is_main), int(p.is_main)),
                    cell(f"≈ {p.tags}" if p.approximate else str(p.tags), p.tags, approx),
                    cell(f"≈ {p.links}" if p.approximate else str(p.links), p.links, approx),
                    cell(str(p.subviews), p.subviews),
                ]
            )
        titles = [tr("Page"), tr("Type"), tr("Main"), tr("Linked tags"), tr("Links"), tr("Subviews")]
        table = StatsTable(titles, rows, max_rows=MAX_TABLE_ROWS)
        self.tables["pages"] = table
        card.add(table)
        return card

    def _project_card(self, r: ProjectStatistics) -> QWidget:
        card = _Card(tr("Content"))
        studio = sum(r.studio_counts.values())
        studio_tip = "\n".join(f"{name}: {count}" for name, count in sorted(r.studio_counts.items()))
        nodes = tr("Studio: {studio} · OptixPlus: {ours}").format(studio=studio if r.studio_counts else "—", ours=r.nodes)
        facts = [
            (tr("Nodes"), nodes, studio_tip),
            (tr("YAML files read"), str(r.files), ""),
            (tr("Alarms"), str(r.alarms), ""),
            (tr("NetLogic"), str(r.netlogic), ""),
            (tr("Data and event loggers"), str(r.loggers), ""),
        ]
        if r.kind != KIND_RUNTIME:
            images = tr_n("{n} file, {size}", "{n} files, {size}", r.image_files)
            fonts = tr_n("{n} file, {size}", "{n} files, {size}", r.font_files)
            facts += [
                (tr("Images"), images.format(n=r.image_files, size=format_size(r.image_bytes)), ""),
                (tr("Fonts"), fonts.format(n=r.font_files, size=format_size(r.font_bytes)), ""),
                (tr("ProjectFiles folder"), format_size(r.project_files_bytes), ""),
            ]
        card.add_facts(facts)
        return card

    def _runtime_files_card(self, r: ProjectStatistics) -> QWidget:
        card = _Card(tr("ApplicationFiles"))
        if not r.runtime_files:
            card.add_text(tr("No database file found."), muted=True)
            return card
        rows = [[cell(name), cell(format_size(size), size)] for name, size in r.runtime_files]
        table = StatsTable([tr("File"), tr("Size")], rows, max_rows=8)
        self.tables["runtime_files"] = table
        card.add(table)
        return card

    def _memory_card(self, r: ProjectStatistics) -> QWidget:
        card = _Card(tr("Estimated memory"))
        m = r.memory
        label = card.add_text(tr("{low}–{high} MiB (estimate)").format(low=_num(m.low_mib, 0), high=_num(m.high_mib, 0)))
        font = label.font()
        font.setBold(True)
        label.setFont(font)
        if m.detail:
            label.setToolTip("\n".join(f"{tr(name)}: {_num(mib)} {tr('MiB')}" for name, mib in m.detail))
            rows = [[cell(tr(name)), cell(_num(mib), mib)] for name, mib in m.detail]
            table = StatsTable([tr("Item"), tr("MiB")], rows, max_rows=8)
            self.tables["memory"] = table
            card.add(table)
        card.add_text(tr("Rough estimate, to be read as an order of magnitude."), muted=True)
        return card

    def _warnings_card(self, r: ProjectStatistics) -> QWidget:
        card = _Card(tr("Warnings"))
        for warning in r.warnings:
            card.add_text("• " + tr(warning))
        return card

    # ---- export ----------------------------------------------------------------------------
    def export_csv(self) -> None:
        if self.result is None:
            return
        default = f"{self.result.name}-statistics.csv"
        path, _filter = QFileDialog.getSaveFileName(self, tr("Export to CSV…"), default, tr("CSV files (*.csv)"))
        if not path:
            return
        page_titles = [
            tr("Page"), tr("Name"), tr("Type"), tr("Main"), tr("Linked tags"), tr("Links"), tr("Subviews"), tr("Approximate"),
        ]
        try:
            export.write_csv(
                path,
                self.result,
                station_titles=_station_titles(),
                page_titles=page_titles,
                section_titles=(tr("Controllers"), tr("Pages")),
                kind_labels=kind_labels(),
            )
        except OSError as exc:
            QMessageBox.critical(self, tr("Export to CSV…"), str(exc))
            return
        log.info("Export CSV : %s", path)

    # ---- reconstruction en l'état --------------------------------------------------------------
    def snapshot(self) -> dict | None:
        if self.busy:
            return None
        return {
            "path": self.path.currentText(),
            "result": self.result,
            "sorts": {name: table.sort_state() for name, table in self.tables.items()},
            "scroll": self.scroll.verticalScrollBar().value(),
        }

    def restore(self, state: dict) -> None:
        self.path.setEditText(state.get("path", ""))
        if state.get("result") is not None:
            self.show_result(state["result"])
            for name, (column, order) in state.get("sorts", {}).items():
                if name in self.tables:
                    self.tables[name].set_sort_state(column, order)
            self.scroll.verticalScrollBar().setValue(state.get("scroll", 0))
