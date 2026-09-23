"""Page de Link Checker : choix du projet, analyse, tableau des liens cassés, corrections.

Reprend l'interface d'origine. Analyse **et corrections** tournent en arrière-plan
(``TaskWorker``) ; l'analyse est annulable. Les actions sont dans la barre d'actions de
l'outil.
"""

from __future__ import annotations

import logging
import os

from PySide6.QtCore import QByteArray, QItemSelectionModel, Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ....common import icons, recent, win32
from ....common.i18n import tr, tr_n
from ....common.progress import Progress
from ....common.workers import TaskWorker
from ..core import fixer
from ..core.project import REASON_ABOVE_ROOT, REASON_FOREIGN, REASON_MISSING, BrokenLink, analyse, reason_label
from .table import LinksModel, LinkTable

log = logging.getLogger("optixplus.linkcheck")

STUDIO_PROCESS = "FTOptixStudio.exe"
FILTERS = (None, REASON_FOREIGN, REASON_MISSING, REASON_ABOVE_ROOT)


def filter_labels() -> list[str]:
    return [tr("All broken links"), tr("Pointing to another project"), tr("Segment not found"), tr("Going above the root")]


class LinkCheckPage(QWidget):
    def __init__(self, context, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self.project = None
        self.broken: list[BrokenLink] = []
        self.stats = None
        self._worker: TaskWorker | None = None
        self._worker_kind = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 16, 24, 16)
        outer.setSpacing(10)

        # ---- projet ------------------------------------------------------------------
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("FT Optix project")))
        self.path = QComboBox()
        self.path.setEditable(True)
        self.path.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.path.lineEdit().setPlaceholderText(tr("Folder containing the .optix file and the Nodes folder"))
        self.path.lineEdit().returnPressed.connect(self.analyse)
        self._fill_recent()
        if self.path.count():
            self.path.setEditText(self.path.itemText(0))  # dernier projet, comme l'outil d'origine
        row.addWidget(self.path, 1)
        browse = QPushButton(tr("Browse…"))
        browse.clicked.connect(self.browse)
        row.addWidget(browse)
        self.analyse_button = QPushButton(tr("Analyse"))
        self.analyse_button.setProperty("accent", True)
        self.analyse_button.clicked.connect(self.analyse)
        row.addWidget(self.analyse_button)
        outer.addLayout(row)

        # ---- filtre et synthèse -----------------------------------------------------------
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("Show")))
        self.filter = QComboBox()
        self.filter.addItems(filter_labels())
        self.filter.currentIndexChanged.connect(self.fill)
        row.addWidget(self.filter)
        row.addSpacing(16)
        self.summary = QLabel(tr("Choose a project, then Analyse. Close FT Optix Studio before any fix."))
        self.summary.setProperty("muted", True)
        self.summary.setWordWrap(True)
        row.addWidget(self.summary, 1)
        outer.addLayout(row)

        # ---- progression ---------------------------------------------------------------------
        self.progress_row = QWidget()
        progress_layout = QHBoxLayout(self.progress_row)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(360)
        self.progress.setTextVisible(False)
        self.progress_label = QLabel()
        self.progress_label.setProperty("muted", True)
        self.cancel_button = QPushButton(tr("Cancel"))
        self.cancel_button.clicked.connect(self.cancel)
        progress_layout.addWidget(self.progress)
        progress_layout.addWidget(self.progress_label, 1)
        progress_layout.addWidget(self.cancel_button)
        self.progress_row.hide()
        outer.addWidget(self.progress_row)

        # ---- tableau et détail ---------------------------------------------------------------
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.model = LinksModel(self)
        self.table = LinkTable()
        self.table.setModel(self.model)
        self.table.selectionModel().selectionChanged.connect(self.show_detail)
        self.table.doubleClicked.connect(lambda _i: self.fix_manual())
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMaximumBlockCount(200)
        self.splitter.addWidget(self.table)
        self.splitter.addWidget(self.detail)
        self.splitter.setSizes([560, 150])
        outer.addWidget(self.splitter, 1)

        self._build_actions()
        self._update_actions()

    # ---- actions ---------------------------------------------------------------------------
    def _build_actions(self) -> None:
        self.act_analyse = icons.themed_action(QAction(tr("Analyse"), self), "linkcheck")
        self.act_analyse.setShortcut(QKeySequence("F5"))
        self.act_analyse.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.act_analyse.triggered.connect(self.analyse)
        self.addAction(self.act_analyse)
        self.act_prefix = icons.themed_action(QAction(tr("Fix links to another project"), self), "link-fix")
        self.act_prefix.triggered.connect(self.fix_prefix)
        self.act_suggestion = icons.themed_action(QAction(tr("Apply suggestion"), self), "wand")
        self.act_suggestion.triggered.connect(self.fix_suggestion)
        self.act_manual = icons.themed_action(QAction(tr("Replace target…"), self), "edit")
        self.act_manual.triggered.connect(self.fix_manual)
        self.act_remove = icons.themed_action(QAction(tr("Remove link"), self), "trash")
        self.act_remove.triggered.connect(self.fix_remove)
        self.act_folder = icons.themed_action(QAction(tr("Open project folder"), self), "window")
        self.act_folder.triggered.connect(self.open_folder)

    def toolbar_actions(self) -> list[QAction | None]:
        return [
            self.act_analyse,
            None,
            self.act_prefix,
            self.act_suggestion,
            self.act_manual,
            self.act_remove,
            None,
            self.act_folder,
        ]

    def _update_actions(self) -> None:
        busy = self._worker is not None
        has_project = self.project is not None
        selected = bool(self.selected()) and not busy
        self.act_analyse.setEnabled(not busy)
        self.analyse_button.setEnabled(not busy)
        self.act_prefix.setEnabled(
            has_project and not busy and any(self.project.foreign_project_prefix(b.target) for b in self.broken)
        )
        self.act_suggestion.setEnabled(selected and any(b.suggestions for b in self.selected()))
        self.act_manual.setEnabled(selected)
        self.act_remove.setEnabled(selected)
        self.act_folder.setEnabled(has_project)

    # ---- projet -----------------------------------------------------------------------------
    def _fill_recent(self) -> None:
        """Liste déroulante des projets récents, sans toucher au texte saisi."""
        current = self.path.currentText()
        self.path.blockSignals(True)
        self.path.clear()
        self.path.addItems(recent.recent_projects(self._context.settings))
        self.path.setEditText(current)
        self.path.blockSignals(False)

    def browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("FT Optix project folder"), self.path.currentText() or "")
        if folder:
            self.path.setEditText(os.path.normpath(folder))
            self.analyse()

    def open_project(self, path: str) -> None:
        self.path.setEditText(path)
        self.analyse()

    def open_folder(self) -> None:
        if self.project is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.project.folder))

    # ---- analyse --------------------------------------------------------------------------------
    def analyse(self) -> None:
        if self._worker is not None:
            return
        path = self.path.currentText().strip().strip('"')
        if not path:
            QMessageBox.warning(self, tr("Link Checker"), tr("Enter the project folder."))
            return
        self._start(lambda progress, cancel: analyse(path, progress, cancel), "analyse", self._on_analysed)
        self._analysed_path = path
        self.summary.setText(tr("Analysis in progress…"))

    def _start(self, fn, kind: str, on_success) -> None:
        worker = TaskWorker(fn, self)
        worker.progress.connect(self._on_progress)
        worker.succeeded.connect(on_success)
        worker.failed.connect(self._on_failed)
        worker.cancelled.connect(self._on_cancelled)
        worker.finished.connect(self._on_finished)
        self._worker = worker
        self._worker_kind = kind
        self.progress.setRange(0, 0)
        self.progress_label.setText("")
        self.cancel_button.setVisible(kind == "analyse")  # une écriture ne s'interrompt pas
        self.progress_row.show()
        self._update_actions()
        worker.start()

    def cancel(self) -> None:
        if self._worker is not None and self._worker_kind == "analyse":
            self._worker.cancel()
            self.progress_label.setText(tr("Cancelling…"))

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

    def _on_finished(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.deleteLater()
        self.progress_row.hide()
        self._update_actions()
        if getattr(self, "_reanalyse", False):
            self._reanalyse = False
            self.analyse()

    def _on_failed(self, message: str) -> None:
        title = tr("Analysis") if self._worker_kind == "analyse" else tr("Fix")
        self.summary.setText(tr("Analysis failed.") if self._worker_kind == "analyse" else tr("Fix failed."))
        QMessageBox.critical(self, title, message)

    def _on_cancelled(self) -> None:
        self.summary.setText(tr("Analysis cancelled."))

    def _on_analysed(self, result) -> None:
        self.project, self.broken, self.stats = result
        recent.add_recent_project(self._context.settings, self.project.folder)
        self._fill_recent()
        self.path.setEditText(self.project.folder)
        log.info("Analyse de %s : %d lien(s) cassé(s)", self.project.name, len(self.broken))
        self._show_summary()
        self.fill()

    def _show_summary(self) -> None:
        project, stats = self.project, self.stats
        if project is None or stats is None:
            return
        self.summary.setText(
            tr(
                "Project {name}: {files} files, {nodes} nodes, {resolved} links resolved, "
                "{unverifiable} not verifiable (aliases, pointers), {builtin} to internal objects. "
                "Broken links: {broken}."
            ).format(
                name=project.name,
                files=project.files_loaded,
                nodes=len(project.all_nodes),
                resolved=stats.resolved,
                unverifiable=stats.unverifiable,
                builtin=stats.builtin,
                broken=len(self.broken),
            )
        )

    def fill(self) -> None:
        reason = FILTERS[self.filter.currentIndex()]
        rows = [b for b in self.broken if reason is None or b.reason == reason]
        self.model.set_rows(rows)
        self.detail.clear()
        self._update_actions()

    # ---- sélection et détail -------------------------------------------------------------------
    def selected(self) -> list[BrokenLink]:
        model = self.table.selectionModel()
        if model is None:
            return []
        return [self.model.rows[i.row()] for i in model.selectedRows() if i.row() < len(self.model.rows)]

    def show_detail(self, *_args) -> None:
        selection = self.selected()
        self.detail.clear()
        self._update_actions()
        if len(selection) == 1 and self.project is not None:
            link = selection[0]
            rel = os.path.relpath(link.file, self.project.folder)
            lines = [
                f"{tr('Object')} : {link.owner_path}",
                f"{tr('Property')} : {link.prop}",
                f"{tr('Target')} : {link.target}",
                f"{tr('Reason')} : {reason_label(link)}",
                tr("File: {file} (line {line})").format(file=rel, line=link.line),
            ]
            if link.suggestions:
                lines.append(tr("Suggestions:"))
                lines += [f"   {s}" for s in link.suggestions]
            else:
                lines.append(tr("No suggestion: no node of the project has this name."))
            self.detail.setPlainText("\n".join(lines))
        elif selection:
            self.detail.setPlainText(tr_n("{n} link selected.", "{n} links selected.", len(selection)).format(n=len(selection)))

    # ---- corrections -------------------------------------------------------------------------------
    def _confirm_and_apply(self, fixes: list[fixer.Fix], title: str) -> None:
        if not fixes:
            QMessageBox.information(self, title, tr("Nothing to fix."))
            return
        text = tr_n(
            "{n} fix will be written to the project YAML files.",
            "{n} fixes will be written to the project YAML files.",
            len(fixes),
        ).format(n=len(fixes))
        text += "\n" + tr("A backup of the modified files will be made next to the project.")
        default = QMessageBox.StandardButton.Yes
        if win32.process_running(STUDIO_PROCESS):
            text += "\n\n" + tr("FT Optix Studio is open: close it before continuing, or it may overwrite the fixes.")
            default = QMessageBox.StandardButton.No
        text += "\n\n" + tr("Continue?")
        answer = QMessageBox.question(
            self, title, text, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, default
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        project = self.project
        self._fix_title = title
        self._start(lambda progress, _cancel: fixer.apply_fixes(project, fixes, progress=progress), "fix", self._on_fixed)

    def _on_fixed(self, result: fixer.FixResult) -> None:
        log.info("%d fichier(s) corrigé(s) ; sauvegarde : %s", result.files, result.backup_dir)
        for line in result.journal:
            log.info("  %s", line)
        shown = "\n".join(result.journal[:15]) + ("\n…" if len(result.journal) > 15 else "")
        QMessageBox.information(
            self,
            self._fix_title,
            tr_n("{n} file modified.", "{n} files modified.", result.files).format(n=result.files)
            + "\n"
            + tr("Backup: {folder}").format(folder=result.backup_dir)
            + "\n\n"
            + shown,
        )
        # Nouvelle analyse une fois la tâche de correction terminée (voir _on_finished).
        self._reanalyse = True

    def fix_prefix(self) -> None:
        fixes, skipped = fixer.propose_prefix_fixes(self.project, self.broken)
        title = tr("Links to another project")
        if skipped:
            listed = "\n".join(f"{s[0].owner_path}\n   → {s[1]}" for s in skipped[:10])
            QMessageBox.warning(
                self,
                title,
                tr_n(
                    "{n} link will not be fixed automatically, its target does not exist in this project:",
                    "{n} links will not be fixed automatically, their target does not exist in this project:",
                    len(skipped),
                ).format(n=len(skipped))
                + "\n\n"
                + listed,
            )
        self._confirm_and_apply(fixes, title)

    def fix_suggestion(self) -> None:
        selection = self.selected()
        fixes = [fixer.Fix(b, fixer.ACTION_REPLACE, b.suggestions[0]) for b in selection if b.suggestions]
        title = tr("Apply suggestion")
        if len(fixes) < len(selection):
            missing = len(selection) - len(fixes)
            QMessageBox.warning(
                self,
                title,
                tr_n(
                    "{n} selected link has no suggestion and is skipped.",
                    "{n} selected links have no suggestion and are skipped.",
                    missing,
                ).format(n=missing),
            )
        self._confirm_and_apply(fixes, title)

    def fix_manual(self) -> None:
        selection = self.selected()
        if not selection or self._worker is not None:
            return
        default = selection[0].suggestions[0] if selection[0].suggestions else selection[0].target
        title = tr("New target")
        target, ok = QInputDialog.getText(
            self,
            title,
            tr_n(
                "New target for {n} link (absolute /Objects/… or relative ../…):",
                "New target for {n} links (absolute /Objects/… or relative ../…):",
                len(selection),
            ).format(n=len(selection)),
            QLineEdit.EchoMode.Normal,
            default,
        )
        target = target.strip()
        if not ok or not target:
            return
        if target.startswith("/"):
            node, code, detail = self.project.resolve(target, self.project.objects)
            if node is None and code not in ("pointer", "alias", "builtin"):
                answer = QMessageBox.question(
                    self,
                    tr("Target not found"),
                    tr("The target {target} is not found in the project ({reason}). Apply anyway?").format(
                        target=target, reason=detail or code
                    ),
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
        self._confirm_and_apply([fixer.Fix(b, fixer.ACTION_REPLACE, target) for b in selection], tr("Replace target"))

    def fix_remove(self) -> None:
        selection = self.selected()
        if not selection:
            return
        title = tr("Remove link")
        answer = QMessageBox.question(
            self,
            title,
            tr_n(
                "Remove the dynamic link of {n} property? It will keep its current static value.",
                "Remove the dynamic link of {n} properties? They will keep their current static value.",
                len(selection),
            ).format(n=len(selection)),
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._confirm_and_apply([fixer.Fix(b, fixer.ACTION_REMOVE) for b in selection], title)

    # ---- cycle de vie ------------------------------------------------------------------------------
    @property
    def busy(self) -> bool:
        return self._worker is not None

    def stop(self) -> None:
        """Arrêt coopératif : l'analyse est annulée et attendue ; une écriture va à son terme."""
        worker = self._worker
        if worker is None:
            return
        if self._worker_kind == "analyse":
            worker.cancel()
        worker.wait()

    def snapshot(self) -> dict | None:
        if self.busy:
            return None
        selection_model = self.table.selectionModel()
        return {
            "path": self.path.currentText(),
            "filter": self.filter.currentIndex(),
            "result": (self.project, self.broken, self.stats) if self.project is not None else None,
            "selected": sorted(i.row() for i in selection_model.selectedRows()) if selection_model else [],
            "scroll": self.table.verticalScrollBar().value(),
            "splitter": bytes(self.splitter.saveState().toBase64().data()),
        }

    def restore(self, state: dict) -> None:
        self.path.setEditText(state.get("path", ""))
        self.filter.blockSignals(True)
        self.filter.setCurrentIndex(state.get("filter", 0))
        self.filter.blockSignals(False)
        if state.get("result"):
            self.project, self.broken, self.stats = state["result"]
            self._show_summary()
            self.fill()
        selection_model = self.table.selectionModel()
        flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
        for row in state.get("selected", []):
            if row < self.model.rowCount():
                selection_model.select(self.model.index(row, 0), flags)
        self.table.verticalScrollBar().setValue(state.get("scroll", 0))
        if state.get("splitter"):
            self.splitter.restoreState(QByteArray.fromBase64(state["splitter"]))
        self._update_actions()
