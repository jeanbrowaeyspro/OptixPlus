"""Prévisualisation du plan : fichiers qui seront écrits, diff exact de chacun, récapitulatif, actions dérivées.

Rien n'est écrit ici. Le bouton « Appliquer… » ouvre la boîte d'application (phase 3).
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..core.analysis import Comparison
from ..core.lines import split_lines
from ..core.plan import Plan, Preview, build_preview, load_plan, save_plan
from .diff_view import DiffView
from .style import taille_lisible

log = logging.getLogger(__name__)


class PlanDialog(QDialog):
    """Liste des fichiers à écrire + diff avant/après + récapitulatif + options."""

    apply_requested = Signal(object)  # Preview
    plan_loaded = Signal()

    def __init__(self, comparison: Comparison, plan: Plan, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Prévisualisation du plan — rien n'est écrit à ce stade")
        self.resize(1300, 800)
        self.comparison = comparison
        self.plan = plan
        self.preview: Preview = build_preview(plan, comparison)

        self.summary = QLabel()
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        self.summary.setWordWrap(True)

        self.files = QListWidget()
        self.files.currentItemChanged.connect(self._show_change)
        self.diff = DiffView()
        self.notes = QTextEdit()
        self.notes.setReadOnly(True)
        self.notes.setMaximumHeight(160)

        self.copy_stats = QCheckBox("Recopier les statistiques du .optix depuis le runtime (cosmétique, régénérées par l'IDE)")
        self.copy_stats.setChecked(plan.copier_statistiques)
        self.copy_stats.toggled.connect(self._option_changed)
        self.move_orphans = QCheckBox("Déplacer les YAML devenus orphelins dans un dossier de rebut (jamais de suppression)")
        self.move_orphans.setChecked(plan.deplacer_orphelins)
        self.move_orphans.toggled.connect(self._option_changed)

        self.save_button = QPushButton("Enregistrer le plan…")
        self.save_button.clicked.connect(self.save_plan_file)
        self.load_button = QPushButton("Charger un plan…")
        self.load_button.clicked.connect(self.load_plan_file)
        self.apply_button = QPushButton("Appliquer…")
        self.apply_button.setDefault(True)
        self.apply_button.clicked.connect(self._apply)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.addButton(self.save_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(self.load_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(self.apply_button, QDialogButtonBox.ButtonRole.AcceptRole)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self.diff, 1)
        right_layout.addWidget(self.notes)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.files)
        splitter.addWidget(right)
        splitter.setSizes([480, 820])

        layout = QVBoxLayout(self)
        layout.addWidget(self.summary)
        layout.addWidget(splitter, 1)
        layout.addWidget(self.copy_stats)
        layout.addWidget(self.move_orphans)
        layout.addWidget(buttons)
        self.refresh()

    # -- Affichage ------------------------------------------------------------------

    def refresh(self) -> None:
        self.preview = build_preview(self.plan, self.comparison)
        p = self.preview
        parts = [
            f"<b>{len(p.changes)}</b> fichier(s) seront écrits",
            f'<span style="color:#2e7d32">➕ <b>{p.nb_ajouts}</b> ajouts</span>',
            f'<span style="color:#c62828">➖ <b>{p.nb_retraits}</b> retraits</span>',
            f'<span style="color:#ef6c00">✏️ <b>{p.nb_valeurs}</b> valeurs</span>',
        ]
        if p.types_retires:
            parts.append(f"{len(p.types_retires)} type(s) élagué(s) par GUID")
        if p.orphelins:
            parts.append(f"{len(p.orphelins)} YAML orphelin(s)")
        text = "  ·  ".join(parts)
        if p.avertissements:
            text += "<br>" + "<br>".join(f'<span style="color:#c62828">⚠ {a}</span>' for a in p.avertissements)
        self.summary.setText(text)
        self.files.clear()
        for change in p.changes:
            item = QListWidgetItem(
                f"{change.rel}\n    {change.origine} — {taille_lisible(change.taille_avant)} → {taille_lisible(change.taille_apres)}"
                f"  (+{change.nb_ajouts} / −{change.nb_retraits} / ✏️{change.nb_valeurs})"
            )
            item.setData(Qt.ItemDataRole.UserRole, change.rel)
            self.files.addItem(item)
        for rel in p.orphelins:
            item = QListWidgetItem(f"{rel}\n    → rebut" if self.plan.deplacer_orphelins else f"{rel}\n    orphelin laissé en place")
            item.setData(Qt.ItemDataRole.UserRole, "")
            item.setForeground(Qt.GlobalColor.gray)
            self.files.addItem(item)
        self.apply_button.setEnabled(bool(p.changes) or bool(p.orphelins and self.plan.deplacer_orphelins))
        if self.files.count():
            self.files.setCurrentRow(0)
        else:
            self.diff.clear()
            self.notes.setPlainText("Aucune décision « prendre le runtime » : rien ne serait écrit.")

    def _show_change(self, current: QListWidgetItem | None, _previous) -> None:
        if current is None:
            return
        rel = current.data(Qt.ItemDataRole.UserRole)
        change = self.preview.change(rel) if rel else None
        if change is None:
            self.diff.clear()
            self.notes.setPlainText("Fichier déplacé au rebut, sans modification de contenu.")
            return
        old_lines = split_lines(change.old).lines
        new_lines = split_lines(change.new).lines
        self.diff.set_content(old_lines, new_lines, change.opcodes(), f"<b>{change.rel}</b> — avant (gauche) → après (droite)")
        lines = [f"Origine : {change.origine}"] + [f"• {n}" for n in change.notes]
        refs = [r for r in self.preview.references if r.rel == change.rel]
        if refs:
            lines.append(f"Références restantes dans ce fichier ({len(refs)}) :")
            lines += [f"  l.{r.line_no} {r.name} : {r.text}" for r in refs[:20]]
        self.notes.setPlainText("\n".join(lines))

    def _option_changed(self) -> None:
        self.plan.copier_statistiques = self.copy_stats.isChecked()
        self.plan.deplacer_orphelins = self.move_orphans.isChecked()
        self.refresh()

    # -- Plan JSON -----------------------------------------------------------------------

    def save_plan_file(self, chemin: str | None = None) -> str | None:
        if not chemin:
            defaut = str(self.comparison.projet_root.parent / "FTOCompare_plan.json")
            chemin, _ = QFileDialog.getSaveFileName(self, "Enregistrer le plan", defaut, "Plan FTOCompare (*.json)")
        if not chemin:
            return None
        save_plan(self.plan, chemin, self.comparison)
        log.info("Plan enregistré : %s", chemin)
        return chemin

    def load_plan_file(self, chemin: str | None = None) -> list[str] | None:
        if not chemin:
            chemin, _ = QFileDialog.getOpenFileName(self, "Charger un plan", str(self.comparison.projet_root.parent), "Plan FTOCompare (*.json)")
        if not chemin:
            return None
        plan, perdus = load_plan(chemin, self.comparison)
        self.plan.decisions = plan.decisions
        self.plan.alignement_complet = plan.alignement_complet
        self.plan.copier_statistiques = plan.copier_statistiques
        self.plan.deplacer_orphelins = plan.deplacer_orphelins
        self.copy_stats.setChecked(plan.copier_statistiques)
        self.move_orphans.setChecked(plan.deplacer_orphelins)
        self.refresh()
        self.plan_loaded.emit()
        if perdus:
            QMessageBox.warning(self, "Plan partiellement rejoué", "Hunks introuvables dans cette comparaison :\n" + "\n".join(perdus))
        log.info("Plan chargé : %s (%d décision(s), %d perdue(s))", chemin, len(plan.decisions), len(perdus))
        return perdus

    def _apply(self) -> None:
        self.apply_requested.emit(self.preview)
