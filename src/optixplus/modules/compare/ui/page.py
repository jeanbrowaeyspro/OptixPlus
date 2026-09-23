"""Page Compare : accueil → analyse en cours → résultats (reprise de la fenêtre de FTOCompare).

Dans OptixPlus, les menus de FTOCompare deviennent la barre d'actions de l'outil ; le
journal, le thème et la barre d'état sont ceux de l'application. Les réglages (historique
des couples, arbitrages mémorisés, dernier export) sont rangés dans ``settings.json``,
section ``compare``.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ....common import icons
from ....common.i18n import tr, tr_n
from ..core.analysis import Comparison
from .results_page import ResultsPage
from .setup_page import SetupPage
from .workers import CompareWorker

log = logging.getLogger(__name__)


def phase_label(phase: str) -> str:
    return {
        "inventaire": tr("Listing files"),
        "hash": tr("Computing fingerprints"),
        "diff": tr("Line-by-line comparison"),
        "analyse": tr("Semantic analysis"),
    }.get(phase, phase)


class ProgressPage(QWidget):
    """Barre de progression avec le fichier en cours, le compteur, et un bouton Annuler."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.phase = QLabel(tr("Preparing…"))
        self.phase.setProperty("heading", True)
        self.current = QLabel("")
        self.current.setWordWrap(True)
        self.current.setProperty("muted", True)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.cancel = QPushButton(tr("Cancel"))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 24, 48, 24)
        layout.addStretch(1)
        layout.addWidget(self.phase)
        layout.addWidget(self.bar)
        layout.addWidget(self.current)
        layout.addWidget(self.cancel, 0, Qt.AlignmentFlag.AlignRight)
        layout.addStretch(2)

    def update(self, phase: str, current: str, index: int, total: int) -> None:  # noqa: A003
        self.phase.setText(phase_label(phase))
        if total > 0:
            self.bar.setRange(0, total)
            self.bar.setValue(min(index, total))
            self.current.setText(f"{index}/{total}  {current}")
        else:
            self.bar.setRange(0, 0)
            self.current.setText(current)


class ComparePage(QWidget):
    """Page de l'outil ; ``settings`` offre ``value`` / ``setValue`` (``KeyValueStore`` ou ``QSettings``)."""

    def __init__(self, settings, parent: QWidget | None = None, on_project_used=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self._on_project_used = on_project_used  # projets récents partagés d'OptixPlus
        self.worker: CompareWorker | None = None
        self.comparison: Comparison | None = None
        self.last_backup: Path | None = None
        self._plan_to_replay: dict | None = None

        self.setup_page = SetupPage(self.settings)
        self.progress_page = ProgressPage()
        self.results_page = ResultsPage()
        self.stack = QStackedWidget()
        self.stack.addWidget(self.setup_page)
        self.stack.addWidget(self.progress_page)
        self.stack.addWidget(self.results_page)
        self.status = QLabel()
        self.status.setProperty("muted", True)
        self.status.setContentsMargins(16, 4, 16, 6)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.stack, 1)
        layout.addWidget(self.status)

        self.setup_page.compare_requested.connect(self.start_compare)
        self.progress_page.cancel.clicked.connect(self.cancel_compare)
        self._build_actions()
        self.results_page.applied.connect(self._on_applied)
        self.results_page.semantic.plan_changed.connect(self.remember_plan)
        self.results_page.relaunch_requested.connect(self.relaunch_compare)
        self.show_message(tr("Choose a runtime and a project, then run the comparison."))

    # -- Actions (ex-menus Comparaison et Plan) ------------------------------------------
    def _action(self, text: str, icon: str | None, shortcut: str | None, slot, tooltip: str) -> QAction:
        action = QAction(text, self)
        if icon:
            icons.themed_action(action, icon)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            self.addAction(action)
        action.setToolTip(tooltip)
        action.triggered.connect(lambda _checked=False: slot())
        return action

    def _build_actions(self) -> None:
        self.action_new = self._action(
            tr("New comparison"), "compare", "Ctrl+N", self.show_setup,
            tr("Back to the choice of the runtime and the project to compare."),
        )
        self.action_relaunch = self._action(
            tr("Relaunch"), "refresh", "F5", self.relaunch_compare,
            tr("Compares the same pair again, keeping the decisions already made."),
        )
        self.action_export = self._action(
            tr("Export report…"), "export", "Ctrl+E", self.export_report,
            tr("Writes the whole comparison report (Markdown or HTML)."),
        )
        self.action_preview = self._action(
            tr("Preview / apply…"), "wand", "Ctrl+P", self.results_page.open_plan_dialog,
            tr("Previews then applies the decision plan (all decided differences) to the project."),
        )
        self.action_replay = self._action(
            tr("Replay last decisions"), "history", None, self.replay_last_plan,
            tr("Reapplies the decisions memorised for this runtime / project pair."),
        )
        self.action_restore = self._action(
            tr("Restore a backup…"), "restore", None, self.restore_backup,
            tr("Puts back the files of a backup made before applying a plan."),
        )
        for action in (self.action_relaunch, self.action_export, self.action_preview, self.action_replay):
            action.setEnabled(False)

    def toolbar_actions(self) -> list[QAction | None]:
        return [
            self.action_new,
            self.action_relaunch,
            self.action_export,
            None,
            self.action_preview,
            self.action_replay,
            self.action_restore,
        ]

    def open_project(self, path: str) -> None:
        """Projet choisi ailleurs (accueil) : il devient le projet à corriger."""
        if self.busy:
            return
        self.stack.setCurrentWidget(self.setup_page)
        self.setup_page.projet.set_path(path)

    def show_message(self, text: str) -> None:
        self.status.setText(text)

    # -- Navigation ---------------------------------------------------------------------
    @property
    def busy(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def show_setup(self) -> None:
        if self.busy:
            return
        self.stack.setCurrentWidget(self.setup_page)
        self.show_message(tr("Choose a runtime and a project, then run the comparison."))

    def start_compare(self, runtime: str, projet: str) -> None:
        if self.busy:
            return
        log.info("Comparaison : runtime=%s  projet=%s", runtime, projet)
        if self._on_project_used is not None:
            self._on_project_used(projet)
        self.worker = CompareWorker(runtime, projet, self)
        self.worker.progressed.connect(self.progress_page.update)
        self.worker.succeeded.connect(self._on_success)
        self.worker.failed.connect(self._on_failure)
        self.worker.cancelled.connect(self._on_cancelled)
        self.progress_page.update("inventaire", "", 0, 0)
        self.stack.setCurrentWidget(self.progress_page)
        self.show_message(tr("Analysis in progress…"))
        self.worker.start()

    def cancel_compare(self) -> None:
        if self.worker is not None:
            self.worker.request_cancel()
            self.progress_page.current.setText(tr("Cancelling…"))

    def _on_success(self, comparison: Comparison) -> None:
        self.set_comparison(comparison)
        s = comparison.synthese()
        message = tr("{diverging} differences in {files} compared files, in {seconds:.1f} s.").format(
            diverging=s.nb_divergents, files=s.nb_fichiers_compares, seconds=s.duree_s
        )
        if self._plan_to_replay is not None:
            from ..core.plan import Plan

            plan, perdus = Plan.from_dict(self._plan_to_replay, comparison)
            self._plan_to_replay = None
            self._adopt_plan(plan)
            message += " " + tr("Decisions kept: {n} hunk(s)").format(n=plan.nb_pris())
            message += (", " + tr("{n} not matched again.").format(n=len(perdus))) if perdus else "."
            if perdus:
                log.warning("Décisions non réappariées après relance : %s", "; ".join(perdus))
        self.show_message(message)

    def set_comparison(self, comparison: Comparison) -> None:
        """Affiche une comparaison (après analyse, ou restaurée après reconstruction)."""
        self.comparison = comparison
        self.results_page.set_comparison(comparison)
        self.stack.setCurrentWidget(self.results_page)
        self.action_export.setEnabled(True)
        self.action_relaunch.setEnabled(True)
        self.action_preview.setEnabled(bool(comparison.diffs))
        self.action_replay.setEnabled(self.stored_plan() is not None)

    def _adopt_plan(self, plan) -> None:
        current = self.results_page.plan
        current.decisions = plan.decisions
        current.alignement_complet = plan.alignement_complet
        current.copier_statistiques = plan.copier_statistiques
        current.deplacer_orphelins = plan.deplacer_orphelins
        self.results_page.semantic.model.refresh_decisions()

    def export_report(self, chemin: str | None = None) -> str | None:
        """Écrit le rapport Markdown ou HTML (selon l'extension). Retourne le chemin écrit."""
        if self.comparison is None:
            return None
        if not chemin:
            defaut = str(self.settings.value("dernier_export", str(Path.home() / "FTOCompare_rapport.md")))
            chemin, _filtre = QFileDialog.getSaveFileName(
                self, tr("Export report"), defaut, "Markdown (*.md);;HTML (*.html *.htm)"
            )
        if not chemin:
            return None
        from ..report.html import build_html
        from ..report.markdown import build_markdown

        target = Path(chemin)
        if target.suffix.lower() in (".html", ".htm"):
            contenu = build_html(self.comparison)
        else:
            contenu = build_markdown(self.comparison)
        target.write_text(contenu, encoding="utf-8", newline="\n")
        self.settings.setValue("dernier_export", str(target))
        log.info("Rapport exporté : %s", target)
        self.show_message(tr("Report exported: {path}").format(path=target))
        return str(target)

    def _on_applied(self, rapport) -> None:
        """Après application : proposer de relancer la comparaison sur le projet modifié."""
        if self.comparison is None:
            return
        self.show_message(
            tr("Plan applied: {n} file(s) written, backup in {folder}").format(
                n=len(rapport.ecrits), folder=rapport.backup_dir
            )
        )
        self.last_backup = rapport.backup_dir
        reponse = QMessageBox.question(
            self,
            tr("Plan applied"),
            tr("The plan was applied and verified. Compare the modified project again?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reponse == QMessageBox.StandardButton.Yes:
            self.start_compare(str(self.comparison.runtime_root), str(self.comparison.projet_root))

    # -- Arbitrages mémorisés ----------------------------------------------------------------
    def relaunch_compare(self) -> None:
        """Relance la comparaison sur le même couple en conservant les décisions du plan (réappariées)."""
        if self.comparison is None or self.busy:
            return
        plan = self.results_page.plan
        self._plan_to_replay = None if plan.est_vide() else plan.to_dict(self.comparison)
        self.start_compare(str(self.comparison.runtime_root), str(self.comparison.projet_root))

    def _couple_key(self) -> str | None:
        if self.comparison is None:
            return None
        raw = f"{self.comparison.runtime_root.resolve()}|{self.comparison.projet_root.resolve()}".lower()
        return "plans/" + hashlib.md5(raw.encode("utf-8")).hexdigest()

    def remember_plan(self) -> None:
        """Mémorise le plan courant pour ce couple (arbitrage récurrent), s'il n'est pas vide."""
        key = self._couple_key()
        if key is None:
            return
        plan = self.results_page.plan
        if plan.est_vide():
            return
        self.settings.setValue(key, plan.to_json(self.comparison))
        self.action_replay.setEnabled(True)

    def stored_plan(self) -> str | None:
        key = self._couple_key()
        if key is None:
            return None
        value = self.settings.value(key)
        return value if isinstance(value, str) and value else None

    def replay_last_plan(self) -> list[str] | None:
        """Rejoue le dernier arbitrage mémorisé pour ce couple ; retourne les hunks non réappariés."""
        from ..core.plan import Plan

        text = self.stored_plan()
        if text is None or self.comparison is None:
            return None
        plan, perdus = Plan.from_json(text, self.comparison)
        self._adopt_plan(plan)
        self.show_message(
            tr("Decisions replayed: {taken} hunk(s), {lost} not matched again.").format(
                taken=plan.nb_pris(), lost=len(perdus)
            )
        )
        if perdus:
            QMessageBox.warning(
                self, tr("Decisions partly replayed"), tr("Hunks not found:") + "\n" + "\n".join(perdus)
            )
        return perdus

    def restore_backup(self, chemin: str | None = None) -> list[str] | None:
        """Restaure un dossier de sauvegarde produit par Compare."""
        from ..core.apply import ApplyError, read_manifest, restore_backup

        if not chemin:
            start = str(self.comparison.projet_root.parent) if self.comparison else str(Path.home())
            chemin = QFileDialog.getExistingDirectory(self, tr("Backup folder _FTOCompare_Sauvegarde_…"), start)
        if not chemin:
            return None
        try:
            manifest = read_manifest(chemin)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(
                self, tr("Unreadable backup"), tr("No valid manifest.json in {folder}: {error}").format(folder=chemin, error=exc)
            )
            return None
        reponse = QMessageBox.question(
            self,
            tr("Restore"),
            tr("Restore {files} file(s) and {moves} move(s) in\n{project}?").format(
                files=len(manifest.get("fichiers", [])),
                moves=len(manifest.get("deplaces", [])),
                project=manifest.get("projet"),
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reponse != QMessageBox.StandardButton.Yes:
            return None
        try:
            restaures = restore_backup(chemin)
        except (ApplyError, OSError) as exc:
            QMessageBox.critical(self, tr("Restore failed"), str(exc))
            return None
        self.show_message(
            tr_n("{n} file restored from {folder}", "{n} files restored from {folder}", len(restaures)).format(
                n=len(restaures), folder=chemin
            )
        )
        log.info("Restauration : %d fichier(s) depuis %s", len(restaures), chemin)
        return restaures

    def _on_failure(self, details: str) -> None:
        self.stack.setCurrentWidget(self.setup_page)
        self.show_message(tr("Analysis failed."))
        log.error("Échec de l'analyse :\n%s", details)
        box = QMessageBox(
            QMessageBox.Icon.Critical,
            tr("Analysis failed"),
            tr("The analysis failed. Details are in the log."),
            parent=self,
        )
        box.setDetailedText(details)
        box.exec()

    def _on_cancelled(self) -> None:
        self.stack.setCurrentWidget(self.setup_page)
        self.show_message(tr("Analysis cancelled."))

    def stop(self) -> None:
        """Arrêt coopératif : la comparaison en cours est annulée et attendue."""
        if self.busy:
            self.worker.request_cancel()
            self.worker.wait()

    # -- Reconstruction à l'identique (changement de langue) ------------------------------------
    def snapshot(self) -> dict | None:
        if self.busy:
            return None
        return {
            "setup": self.setup_page.snapshot(),
            "comparison": self.comparison,
            "plan": self.results_page.plan if self.comparison is not None else None,
            "on_results": self.stack.currentWidget() is self.results_page,
            "results": self.results_page.snapshot() if self.comparison is not None else None,
            "last_backup": self.last_backup,
            "status": self.status.text(),
        }

    def restore(self, state: dict) -> None:
        self.setup_page.restore(state.get("setup") or {})
        self.last_backup = state.get("last_backup")
        comparison = state.get("comparison")
        if comparison is not None:
            self.set_comparison(comparison)
            if state.get("plan") is not None:
                self._adopt_plan(state["plan"])
            if state.get("results"):
                self.results_page.restore(state["results"])
        if not state.get("on_results"):
            self.stack.setCurrentWidget(self.setup_page)
        self.show_message(state.get("status", ""))
