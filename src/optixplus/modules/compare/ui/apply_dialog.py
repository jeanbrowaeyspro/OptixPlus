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

from ....common import theme
from ....common.i18n import tr
from ..core.analysis import Comparison
from ..core.apply import ApplyError, ApplyReport, apply_preview, check_locks
from ..core.plan import Plan, Preview
from ..core.progress import Cancelled, Progress

log = logging.getLogger(__name__)



def phase_label(phase: str) -> str:
    return {
        "sauvegarde": tr("Backup"),
        "ecriture": tr("Writing and verification"),
        "integrite": tr("Integrity check"),
    }.get(phase, phase)


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
            self.failed.emit(str(exc) or tr("Cancelled — the files already written were restored."))
        except Exception as exc:  # noqa: BLE001
            log.exception("Échec inattendu de l'application")
            self.failed.emit(f"{type(exc).__name__} : {exc}")
        else:
            self.finished_report.emit(rapport)


def format_report(rapport: ApplyReport) -> str:
    lines = [
        tr("Backup: {folder}").format(folder=rapport.backup_dir) if rapport.backup_dir else tr("No backup (nothing to write).")
    ]
    lines.append("\n" + tr("Files written and verified by hash ({n}):").format(n=len(rapport.ecrits)))
    lines += [f"  ✔ {rel}  md5 {md5}" for rel, md5 in rapport.ecrits]
    if rapport.deplaces:
        lines.append("\n" + tr("Files moved to the discard folder ({n}):").format(n=len(rapport.deplaces)))
        lines += [f"  → {rel}  ⇒  {dest}" for rel, dest in rapport.deplaces]
    if rapport.erreurs:
        lines.append("\n" + tr("ERRORS:"))
        lines += [f"  ✖ {e}" for e in rapport.erreurs]
    if rapport.avertissements:
        lines.append("\n" + tr("Warnings:"))
        lines += [f"  ⚠ {a}" for a in rapport.avertissements]
    if rapport.references:
        lines.append("\n" + tr("Remaining references ({n}):").format(n=len(rapport.references)))
        lines += [f"  {r.rel} l.{r.line_no} — {r.name} : {r.text}" for r in rapport.references[:50]]
    if rapport.orphelins_restants:
        lines.append("\n" + tr("Unreferenced YAML files:"))
        lines += [f"  {rel}" for rel in rapport.orphelins_restants]
    if rapport.a_faire:
        lines.append("\n" + tr("Still to do by hand:"))
        lines += [f"  • {a}" for a in rapport.a_faire]
    lines.append("\n" + tr("Duration: {seconds:.1f} s").format(seconds=rapport.duree_s))
    return "\n".join(lines)


class ApplyDialog(QDialog):
    """Confirmation (projet fermé dans FT Optix), progression, rapport."""

    applied = Signal(object)  # ApplyReport

    def __init__(self, preview: Preview, plan: Plan, comparison: Comparison, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Apply the plan"))
        self.resize(900, 650)
        self.preview, self.plan, self.comparison = preview, plan, comparison
        self.worker: ApplyWorker | None = None
        self.report: ApplyReport | None = None

        rels = [c.rel for c in preview.changes] + (preview.orphelins if plan.deplacer_orphelins else [])
        locked = check_locks(comparison.projet_root, rels)
        intro = [
            tr("<b>{n}</b> file(s) will be written in <code>{folder}</code>, after a backup in a timestamped sibling folder.").format(
                n=len(preview.changes), folder=comparison.projet_root
            ),
        ]
        if locked:
            intro.append(
                f'<span style="color:{theme.current().error}">'
                + tr("<b>Locked files</b> ({n}) — the project is probably open in FT Optix: {files}").format(
                    n=len(locked), files=", ".join(locked[:5])
                )
                + "</span>"
            )
        else:
            intro.append(tr("No lock detected on the files to write."))
        self.intro = QLabel("<br>".join(intro))
        self.intro.setTextFormat(Qt.TextFormat.RichText)
        self.intro.setWordWrap(True)
        self.confirm = QCheckBox(tr("I confirm that the project is closed in FT Optix"))
        self.confirm.toggled.connect(self._update_buttons)
        self.phase = QLabel("")
        self.bar = QProgressBar()
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText(tr("The application report will be shown here."))
        self.start_button = QPushButton(tr("Apply now"))
        self.start_button.setProperty("accent", True)
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
        self.output.setPlainText(tr("Applying…"))
        self.worker.start()

    def _on_progress(self, phase: str, current: str, index: int, total: int) -> None:
        self.phase.setText(f"<b>{phase_label(phase)}</b>  {current}")
        self.bar.setRange(0, max(total, 1))
        self.bar.setValue(min(index, max(total, 1)))

    def _on_done(self, rapport: ApplyReport) -> None:
        self.report = rapport
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        self.phase.setText("<b>" + (tr("Done") if rapport.succes else tr("Done with errors")) + "</b>")
        self.output.setPlainText(format_report(rapport))
        self.applied.emit(rapport)

    def _on_failed(self, message: str) -> None:
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.phase.setText(f'<b style="color:{theme.current().error}">' + tr("Failed — project restored") + "</b>")
        self.output.setPlainText(
            tr("FAILED: {error}").format(error=message) + "\n\n" + tr("Nothing was left in a partial state.")
        )
        log.error("Application échouée : %s", message)
        self.worker = None
        self.confirm.setEnabled(True)
        self._update_buttons()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.worker is not None and self.worker.isRunning():
            self.worker.request_cancel()
            self.worker.wait()  # l'annulation restaure les fichiers déjà écrits : on attend la fin
        super().closeEvent(event)
