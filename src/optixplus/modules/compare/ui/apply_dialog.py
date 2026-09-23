"""Application du plan : contrôle préalable, progression, rapport final. Restauration d'une sauvegarde."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..core.analysis import Comparison
from ..core.apply import ApplyError, ApplyReport, apply_preview, check_locks
from ..core.plan import Plan, Preview
from ..core.progress import Cancelled, Progress

log = logging.getLogger(__name__)

LIBELLE_PHASE = {"sauvegarde": "Sauvegarde", "ecriture": "Écriture et vérification", "integrite": "Contrôle d'intégrité"}


class ApplyWorker(QThread):
    progressed = Signal(str, str, int, int)
    finished_report = Signal(object)  # ApplyReport
    failed = Signal(str)

    def __init__(self, preview: Preview, plan: Plan, comparison: Comparison, parent=None) -> None:
        super().__init__(parent)
        self.preview, self.plan, self.comparison = preview, plan, comparison
        self._cancel = False

    def request_cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            rapport = apply_preview(
                self.preview,
                self.plan,
                self.comparison,
                progress=lambda p: self.progressed.emit(p.phase, p.current, p.index, p.total),
                cancel=lambda: self._cancel,
            )
        except (ApplyError, Cancelled) as exc:
            self.failed.emit(str(exc) or "Annulé — les fichiers déjà écrits ont été restaurés.")
        except Exception as exc:  # noqa: BLE001
            log.exception("Échec inattendu de l'application")
            self.failed.emit(f"{type(exc).__name__} : {exc}")
        else:
            self.finished_report.emit(rapport)


def format_report(rapport: ApplyReport) -> str:
    lines = [f"Sauvegarde : {rapport.backup_dir}" if rapport.backup_dir else "Aucune sauvegarde (rien à écrire)."]
    lines.append(f"\nFichiers écrits et vérifiés par hash ({len(rapport.ecrits)}) :")
    lines += [f"  ✔ {rel}  md5 {md5}" for rel, md5 in rapport.ecrits]
    if rapport.deplaces:
        lines.append(f"\nFichiers déplacés au rebut ({len(rapport.deplaces)}) :")
        lines += [f"  → {rel}  ⇒  {dest}" for rel, dest in rapport.deplaces]
    if rapport.erreurs:
        lines.append("\nERREURS :")
        lines += [f"  ✖ {e}" for e in rapport.erreurs]
    if rapport.avertissements:
        lines.append("\nAvertissements :")
        lines += [f"  ⚠ {a}" for a in rapport.avertissements]
    if rapport.references:
        lines.append(f"\nRéférences restantes ({len(rapport.references)}) :")
        lines += [f"  {r.rel} l.{r.line_no} — {r.name} : {r.text}" for r in rapport.references[:50]]
    if rapport.orphelins_restants:
        lines.append("\nYAML non référencés :")
        lines += [f"  {rel}" for rel in rapport.orphelins_restants]
    if rapport.a_faire:
        lines.append("\nReste à faire à la main :")
        lines += [f"  • {a}" for a in rapport.a_faire]
    lines.append(f"\nDurée : {rapport.duree_s:.1f} s")
    return "\n".join(lines)


class ApplyDialog(QDialog):
    """Confirmation (projet fermé dans FT Optix), progression, rapport."""

    applied = Signal(object)  # ApplyReport

    def __init__(self, preview: Preview, plan: Plan, comparison: Comparison, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Appliquer le plan")
        self.resize(900, 650)
        self.preview, self.plan, self.comparison = preview, plan, comparison
        self.worker: ApplyWorker | None = None
        self.report: ApplyReport | None = None

        rels = [c.rel for c in preview.changes] + (preview.orphelins if plan.deplacer_orphelins else [])
        locked = check_locks(comparison.projet_root, rels)
        intro = [
            f"<b>{len(preview.changes)}</b> fichier(s) seront écrits dans <code>{comparison.projet_root}</code>, "
            f"après sauvegarde dans un dossier frère horodaté.",
        ]
        if locked:
            intro.append(
                f'<span style="color:#c62828"><b>Fichiers verrouillés</b> ({len(locked)}) — le projet est probablement '
                f"ouvert dans FT Optix : {', '.join(locked[:5])}</span>"
            )
        else:
            intro.append("Aucun verrou détecté sur les fichiers à écrire.")
        self.intro = QLabel("<br>".join(intro))
        self.intro.setTextFormat(Qt.TextFormat.RichText)
        self.intro.setWordWrap(True)
        self.confirm = QCheckBox("Je confirme que le projet est fermé dans FT Optix")
        self.confirm.toggled.connect(self._update_buttons)
        self.phase = QLabel("")
        self.bar = QProgressBar()
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("Le rapport d'application s'affichera ici.")
        self.start_button = QPushButton("Appliquer maintenant")
        self.start_button.clicked.connect(self.start)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.buttons.rejected.connect(self.reject)
        self.buttons.addButton(self.start_button, QDialogButtonBox.ButtonRole.AcceptRole)
        self.locked = locked

        layout = QVBoxLayout(self)
        layout.addWidget(self.intro)
        layout.addWidget(self.confirm)
        layout.addWidget(self.phase)
        layout.addWidget(self.bar)
        layout.addWidget(self.output, 1)
        layout.addWidget(self.buttons)
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.start_button.setEnabled(self.confirm.isChecked() and not self.locked and self.worker is None)

    def start(self) -> None:
        if self.worker is not None:
            return
        self.worker = ApplyWorker(self.preview, self.plan, self.comparison, self)
        self.worker.progressed.connect(self._on_progress)
        self.worker.finished_report.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.start_button.setEnabled(False)
        self.confirm.setEnabled(False)
        self.output.setPlainText("Application en cours…")
        self.worker.start()

    def _on_progress(self, phase: str, current: str, index: int, total: int) -> None:
        self.phase.setText(f"<b>{LIBELLE_PHASE.get(phase, phase)}</b>  {current}")
        self.bar.setRange(0, max(total, 1))
        self.bar.setValue(min(index, max(total, 1)))

    def _on_done(self, rapport: ApplyReport) -> None:
        self.report = rapport
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        self.phase.setText("<b>Terminé</b>" if rapport.succes else "<b>Terminé avec erreurs</b>")
        self.output.setPlainText(format_report(rapport))
        self.applied.emit(rapport)

    def _on_failed(self, message: str) -> None:
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.phase.setText('<b style="color:#c62828">Échec — projet restauré</b>')
        self.output.setPlainText(f"ÉCHEC : {message}\n\nRien n'a été laissé dans un état partiel.")
        log.error("Application échouée : %s", message)
        self.worker = None
        self.confirm.setEnabled(True)
        self._update_buttons()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.worker is not None and self.worker.isRunning():
            self.worker.request_cancel()
            self.worker.wait(10000)
        super().closeEvent(event)
