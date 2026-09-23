"""Fenêtre principale : accueil → analyse en cours → résultats, plus le panneau journal."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.analysis import Comparison
from .log_panel import LogPanel
from .theme import LIBELLE_THEME, THEMES, apply_theme, theme_enregistre
from .results_page import ResultsPage
from .setup_page import SetupPage
from .workers import CompareWorker

log = logging.getLogger(__name__)

LIBELLE_PHASE = {
    "inventaire": "Inventaire des fichiers",
    "hash": "Calcul des empreintes",
    "diff": "Comparaison ligne à ligne",
    "analyse": "Analyse sémantique",
}


class ProgressPage(QWidget):
    """Barre de progression avec le fichier en cours, le compteur, et un bouton Annuler."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.phase = QLabel("<b>Préparation…</b>")
        self.phase.setTextFormat(Qt.TextFormat.RichText)
        self.current = QLabel("")
        self.current.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.cancel = QPushButton("Annuler")
        layout = QVBoxLayout(self)
        layout.addStretch(1)
        layout.addWidget(self.phase)
        layout.addWidget(self.bar)
        layout.addWidget(self.current)
        layout.addWidget(self.cancel, 0, Qt.AlignmentFlag.AlignRight)
        layout.addStretch(2)

    def update(self, phase: str, current: str, index: int, total: int) -> None:  # noqa: A003
        self.phase.setText(f"<b>{LIBELLE_PHASE.get(phase, phase)}</b>")
        if total > 0:
            self.bar.setRange(0, total)
            self.bar.setValue(min(index, total))
            self.current.setText(f"{index}/{total}  {current}")
        else:
            self.bar.setRange(0, 0)
            self.current.setText(current)


class MainWindow(QMainWindow):
    def __init__(self, settings: QSettings | None = None) -> None:
        super().__init__()
        self.setWindowTitle("FTOCompare — comparaison runtime ⇄ projet FactoryTalk Optix")
        self.resize(1400, 850)
        self.settings = settings or QSettings("FTOCompare", "FTOCompare")
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
        self.setCentralWidget(self.stack)

        self.setup_page.compare_requested.connect(self.start_compare)
        self.progress_page.cancel.clicked.connect(self.cancel_compare)

        self.log_panel = LogPanel()
        dock = QDockWidget("Journal", self)
        dock.setWidget(self.log_panel)
        dock.setObjectName("journal")
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
        dock.hide()
        self.log_dock = dock

        menu = self.menuBar().addMenu("&Comparaison")
        self.action_new = QAction("&Nouvelle comparaison", self)
        self.action_new.setShortcut("Ctrl+N")
        self.action_new.triggered.connect(self.show_setup)
        menu.addAction(self.action_new)
        self.action_relaunch = QAction("&Relancer la comparaison", self)
        self.action_relaunch.setShortcut("F5")
        self.action_relaunch.setEnabled(False)
        self.action_relaunch.triggered.connect(self.relaunch_compare)
        menu.addAction(self.action_relaunch)
        self.action_export = QAction("&Exporter le rapport…", self)
        self.action_export.setShortcut("Ctrl+E")
        self.action_export.setEnabled(False)
        self.action_export.triggered.connect(self.export_report)
        menu.addAction(self.action_export)
        menu.addSeparator()
        quit_action = QAction("&Quitter", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        menu.addAction(quit_action)
        plan_menu = self.menuBar().addMenu("&Plan")
        self.action_preview = QAction("&Prévisualiser / appliquer…", self)
        self.action_preview.setShortcut("Ctrl+P")
        self.action_preview.setEnabled(False)
        self.action_preview.triggered.connect(self.results_page.open_plan_dialog)
        plan_menu.addAction(self.action_preview)
        self.action_replay = QAction("Re&jouer le dernier arbitrage de ce couple", self)
        self.action_replay.setEnabled(False)
        self.action_replay.triggered.connect(self.replay_last_plan)
        plan_menu.addAction(self.action_replay)
        plan_menu.addSeparator()
        self.action_restore = QAction("&Restaurer une sauvegarde…", self)
        self.action_restore.triggered.connect(self.restore_backup)
        plan_menu.addAction(self.action_restore)
        self.results_page.applied.connect(self._on_applied)

        view = self.menuBar().addMenu("&Affichage")
        toggle_log = dock.toggleViewAction()
        toggle_log.setText("&Journal")
        toggle_log.setShortcut("Ctrl+J")
        view.addAction(toggle_log)
        theme_menu = view.addMenu("&Thème")
        self.theme_group = QActionGroup(self)
        self.theme_group.setExclusive(True)
        self.theme_actions: dict[str, QAction] = {}
        current = theme_enregistre(self.settings)
        for theme in THEMES:
            action = QAction(LIBELLE_THEME[theme], self)
            action.setCheckable(True)
            action.setData(theme)
            action.setChecked(theme == current)
            self.theme_group.addAction(action)
            theme_menu.addAction(action)
            self.theme_actions[theme] = action
        self.theme_group.triggered.connect(lambda action: self.set_theme(action.data()))
        self.set_theme(current, persist=False)
        self.results_page.semantic.plan_changed.connect(self.remember_plan)
        self.results_page.relaunch_requested.connect(self.relaunch_compare)

        self.statusBar().showMessage("Choisir un runtime et un projet, puis Comparer.")
        geometry = self.settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)

    # -- Navigation ---------------------------------------------------------------

    def show_setup(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        self.stack.setCurrentWidget(self.setup_page)
        self.statusBar().showMessage("Choisir un runtime et un projet, puis Comparer.")

    def start_compare(self, runtime: str, projet: str) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        log.info("Comparaison : runtime=%s  projet=%s", runtime, projet)
        self.worker = CompareWorker(runtime, projet, self)
        self.worker.progressed.connect(self.progress_page.update)
        self.worker.succeeded.connect(self._on_success)
        self.worker.failed.connect(self._on_failure)
        self.worker.cancelled.connect(self._on_cancelled)
        self.progress_page.update("inventaire", "", 0, 0)
        self.stack.setCurrentWidget(self.progress_page)
        self.statusBar().showMessage("Analyse en cours…")
        self.worker.start()

    def cancel_compare(self) -> None:
        if self.worker is not None:
            self.worker.request_cancel()
            self.progress_page.current.setText("Annulation demandée…")

    def _on_success(self, comparison: Comparison) -> None:
        self.comparison = comparison
        self.results_page.set_comparison(comparison)
        self.stack.setCurrentWidget(self.results_page)
        self.action_export.setEnabled(True)
        self.action_relaunch.setEnabled(True)
        self.action_preview.setEnabled(bool(comparison.diffs))
        self.action_replay.setEnabled(self.stored_plan() is not None)
        s = comparison.synthese()
        message = f"{s.nb_divergents} divergences sur {s.nb_fichiers_compares} fichiers comparés en {s.duree_s:.1f} s."
        if self._plan_to_replay is not None:
            from ..core.plan import Plan

            plan, perdus = Plan.from_dict(self._plan_to_replay, comparison)
            self._plan_to_replay = None
            current = self.results_page.plan
            current.decisions = plan.decisions
            current.alignement_complet = plan.alignement_complet
            current.copier_statistiques = plan.copier_statistiques
            current.deplacer_orphelins = plan.deplacer_orphelins
            self.results_page.semantic.model.refresh_decisions()
            message += f" Décisions conservées : {plan.nb_pris()} hunk(s)"
            message += f", {len(perdus)} non réapparié(s)." if perdus else "."
            if perdus:
                log.warning("Décisions non réappariées après relance : %s", "; ".join(perdus))
        self.statusBar().showMessage(message)

    def export_report(self, chemin: str | None = None) -> str | None:
        """Écrit le rapport Markdown ou HTML (selon l'extension). Retourne le chemin écrit."""
        if self.comparison is None:
            return None
        if not chemin:
            defaut = str(self.settings.value("dernier_export", str(Path.home() / "FTOCompare_rapport.md")))
            chemin, _filtre = QFileDialog.getSaveFileName(
                self, "Exporter le rapport", defaut, "Markdown (*.md);;HTML (*.html *.htm)"
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
        self.statusBar().showMessage(f"Rapport exporté : {target}")
        return str(target)

    def _on_applied(self, rapport) -> None:
        """Après application : proposer de relancer la comparaison sur le projet modifié."""
        if self.comparison is None:
            return
        self.statusBar().showMessage(
            f"Plan appliqué : {len(rapport.ecrits)} fichier(s) écrit(s), sauvegarde dans {rapport.backup_dir}"
        )
        self.last_backup = rapport.backup_dir
        reponse = QMessageBox.question(
            self,
            "Plan appliqué",
            "Le plan a été appliqué et vérifié. Relancer la comparaison sur le projet modifié ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reponse == QMessageBox.StandardButton.Yes:
            self.start_compare(str(self.comparison.runtime_root), str(self.comparison.projet_root))

    # -- Phase 4 : thème et arbitrages mémorisés ---------------------------------------

    def set_theme(self, theme: str, persist: bool = True) -> None:
        if theme not in THEMES:
            theme = "systeme"
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, theme)
        if persist:
            self.settings.setValue("theme", theme)
        action = self.theme_actions.get(theme)
        if action is not None and not action.isChecked():
            action.setChecked(True)

    @property
    def theme(self) -> str:
        checked = self.theme_group.checkedAction()
        return checked.data() if checked is not None else "systeme"

    def relaunch_compare(self) -> None:
        """Relance la comparaison sur le même couple en conservant les décisions du plan (réappariées)."""
        if self.comparison is None or (self.worker is not None and self.worker.isRunning()):
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
        current = self.results_page.plan
        current.decisions = plan.decisions
        current.alignement_complet = plan.alignement_complet
        current.copier_statistiques = plan.copier_statistiques
        current.deplacer_orphelins = plan.deplacer_orphelins
        self.results_page.semantic.model.refresh_decisions()
        self.statusBar().showMessage(f"Arbitrage rejoué : {plan.nb_pris()} hunk(s), {len(perdus)} non réapparié(s).")
        if perdus:
            QMessageBox.warning(self, "Arbitrage partiellement rejoué", "Hunks introuvables :\n" + "\n".join(perdus))
        return perdus

    def restore_backup(self, chemin: str | None = None) -> list[str] | None:
        """Restaure un dossier de sauvegarde produit par FTOCompare (menu Plan)."""
        from ..core.apply import ApplyError, read_manifest, restore_backup

        if not chemin:
            start = str(self.comparison.projet_root.parent) if self.comparison else str(Path.home())
            chemin = QFileDialog.getExistingDirectory(self, "Dossier de sauvegarde _FTOCompare_Sauvegarde_…", start)
        if not chemin:
            return None
        try:
            manifest = read_manifest(chemin)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Sauvegarde illisible", f"Pas de manifest.json valide dans {chemin} : {exc}")
            return None
        reponse = QMessageBox.question(
            self,
            "Restaurer",
            f"Restaurer {len(manifest.get('fichiers', []))} fichier(s) et {len(manifest.get('deplaces', []))} déplacement(s) "
            f"dans\n{manifest.get('projet')} ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reponse != QMessageBox.StandardButton.Yes:
            return None
        try:
            restaures = restore_backup(chemin)
        except (ApplyError, OSError) as exc:
            QMessageBox.critical(self, "Restauration échouée", str(exc))
            return None
        self.statusBar().showMessage(f"{len(restaures)} fichier(s) restauré(s) depuis {chemin}")
        log.info("Restauration : %d fichier(s) depuis %s", len(restaures), chemin)
        return restaures

    def _on_failure(self, details: str) -> None:
        self.stack.setCurrentWidget(self.setup_page)
        self.statusBar().showMessage("Échec de l'analyse.")
        self.log_dock.show()
        box = QMessageBox(QMessageBox.Icon.Critical, "Échec de l'analyse", "L'analyse a échoué. Détails dans le journal.", parent=self)
        box.setDetailedText(details)
        box.exec()

    def _on_cancelled(self) -> None:
        self.stack.setCurrentWidget(self.setup_page)
        self.statusBar().showMessage("Analyse annulée.")

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 — API Qt
        if self.worker is not None and self.worker.isRunning():
            self.worker.request_cancel()
            self.worker.wait(5000)
        self.settings.setValue("geometry", self.saveGeometry())
        self.log_panel.detach()
        super().closeEvent(event)
