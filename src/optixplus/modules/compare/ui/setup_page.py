"""Écran d'accueil : choix des deux dossiers, détection Optix, versions IDE, bouton Comparer."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ....common import theme
from ....common.i18n import tr
from ....common.optix.project import is_optix_root, read_ide_version, suggest_optix_root

MAX_HISTORIQUE = 10


class FolderPicker(QGroupBox):
    """Un sélecteur de dossier : saisie, historique, parcours, glisser-déposer, détection Optix."""

    changed = Signal()

    def __init__(self, titre: str, parent: QWidget | None = None) -> None:
        super().__init__(titre, parent)
        self.setAcceptDrops(True)
        self._resolved: Path | None = None
        self._version: str | None = None

        self.combo = QComboBox()
        self.combo.setEditable(True)
        self.combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.combo.lineEdit().setPlaceholderText(tr("Drop a folder here, or browse…"))
        self.combo.lineEdit().editingFinished.connect(self._refresh)
        self.combo.activated.connect(self._refresh)

        self.browse = QPushButton(tr("Browse…"))
        self.browse.clicked.connect(self._browse)

        self.status = QLabel(tr("No folder chosen."))
        self.status.setWordWrap(True)
        self.version_label = QLabel("")
        self.version_label.setTextFormat(Qt.TextFormat.RichText)

        self.suggest_button = QPushButton()
        self.suggest_button.setVisible(False)
        self.suggest_button.clicked.connect(self._accept_suggestion)

        row = QHBoxLayout()
        row.addWidget(self.combo, 1)
        row.addWidget(self.browse)
        layout = QVBoxLayout(self)
        layout.addLayout(row)
        layout.addWidget(self.status)
        layout.addWidget(self.version_label)
        layout.addWidget(self.suggest_button)

    # -- API --------------------------------------------------------------

    @property
    def path(self) -> Path | None:
        """Le dossier retenu s'il est un projet/runtime Optix valide, sinon ``None``."""
        return self._resolved

    @property
    def version(self) -> str | None:
        return self._version

    def text(self) -> str:
        return self.combo.currentText().strip().strip('"')

    def set_path(self, path: str | Path) -> None:
        self.combo.setCurrentText(str(path))
        self._refresh()

    def set_history(self, paths: list[str]) -> None:
        current = self.text()
        self.combo.clear()
        self.combo.addItems(paths)
        self.combo.setCurrentText(current)

    # -- Détection ----------------------------------------------------------

    def _refresh(self) -> None:
        text = self.text()
        self._resolved = None
        self._version = None
        self.suggest_button.setVisible(False)
        if not text:
            self.status.setText(tr("No folder chosen."))
            self.version_label.setText("")
        else:
            folder = Path(text)
            if not folder.is_dir():
                self.status.setText("⚠ " + tr("This path is not a folder."))
                self.version_label.setText("")
            elif is_optix_root(folder):
                self._resolved = folder
                self._version = read_ide_version(folder)
                self.status.setText("✔ " + tr("FactoryTalk Optix project / runtime recognised (IDEVersion.txt + Nodes/)."))
                self.version_label.setText(tr("IDE version: <b>{version}</b>").format(version=self._version or tr("unknown")))
            else:
                suggestion = suggest_optix_root(folder)
                if suggestion is not None:
                    self.status.setText(tr("This folder is not an Optix project, but its only subfolder is."))
                    self.suggest_button.setText(tr("Go down into “{name}”").format(name=suggestion.name))
                    self.suggest_button.setProperty("suggestion", str(suggestion))
                    self.suggest_button.setVisible(True)
                else:
                    self.status.setText("⚠ " + tr("No IDEVersion.txt nor Nodes/ folder: this is not an Optix project."))
                self.version_label.setText("")
        self.changed.emit()

    def _accept_suggestion(self) -> None:
        self.set_path(self.suggest_button.property("suggestion"))

    def _browse(self) -> None:
        start = self.text() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, self.title(), start)
        if chosen:
            self.set_path(chosen)

    # -- Glisser-déposer -----------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802 — API Qt
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802 — API Qt
        urls = event.mimeData().urls()
        if not urls:
            return
        local = Path(urls[0].toLocalFile())
        if local.is_file():
            local = local.parent
        self.set_path(local)
        event.acceptProposedAction()


class SetupPage(QWidget):
    """La page d'accueil : deux sélecteurs, l'historique des couples, l'avertissement de version."""

    compare_requested = Signal(str, str)  # runtime, projet

    def __init__(self, settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings  # value / setValue (KeyValueStore, ou QSettings dans les tests)

        heading = QLabel(tr("Compare"))
        heading.setProperty("title", True)
        title = QLabel(tr("Compare a deployed FactoryTalk Optix runtime (or another project) with a development project."))
        title.setProperty("muted", True)
        title.setWordWrap(True)

        self.runtime = FolderPicker(tr("Reference (deployed runtime, or another project)"))
        self.projet = FolderPicker(tr("Project to fix"))
        self.runtime.changed.connect(self._update_state)
        self.projet.changed.connect(self._update_state)

        self.warning = QFrame()
        self.warning.setFrameShape(QFrame.Shape.StyledPanel)
        self.warning.setObjectName("warning")
        self._style_warning()
        theme.follow(self, self._style_warning)
        self.warning_label = QLabel()
        self.warning_label.setWordWrap(True)
        self.warning_label.setTextFormat(Qt.TextFormat.RichText)
        self.override = QCheckBox(tr("Compare anyway — interpret the results with care"))
        self.override.toggled.connect(self._update_state)
        warn_layout = QVBoxLayout(self.warning)
        warn_layout.addWidget(self.warning_label)
        warn_layout.addWidget(self.override)
        self.warning.setVisible(False)

        self.compare_button = QPushButton(tr("Run the comparison"))
        self.compare_button.setProperty("accent", True)
        self.compare_button.setDefault(True)
        self.compare_button.setMinimumHeight(36)
        self.compare_button.setEnabled(False)
        self.compare_button.clicked.connect(self._launch)
        self.hint = QLabel("")
        self.hint.setWordWrap(True)

        self.history = QListWidget()
        self.history.setToolTip(tr("Last compared pairs — double-click to reload"))
        self.history.itemDoubleClicked.connect(self._pick_history)
        history_box = QGroupBox(tr("Last pairs used"))
        history_layout = QVBoxLayout(history_box)
        history_layout.addWidget(self.history)

        left = QVBoxLayout()
        left.addWidget(heading)
        left.addWidget(title)
        left.addWidget(self.runtime)
        left.addWidget(self.projet)
        left.addWidget(self.warning)
        left.addWidget(self.hint)
        left.addStretch(1)
        left.addWidget(self.compare_button)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)
        layout.addLayout(left, 3)
        layout.addWidget(history_box, 2)

        self._load_history()
        self._update_state()

    def _style_warning(self, _palette=None) -> None:
        p = theme.current()
        self.warning.setStyleSheet(
            f"QFrame#warning {{ background: {p.surface_alt}; border: 1px solid {p.warning}; border-radius: 6px; }}"
            f"QFrame#warning QLabel, QFrame#warning QCheckBox {{ color: {p.text}; background: transparent; }}"
        )

    # -- Historique ------------------------------------------------------------

    def couples(self) -> list[tuple[str, str]]:
        raw = self.settings.value("couples", "[]")
        try:
            data = json.loads(raw) if isinstance(raw, str) else []
        except json.JSONDecodeError:
            data = []
        return [(r, p) for r, p in data if isinstance(r, str) and isinstance(p, str)]

    def remember(self, runtime: str, projet: str) -> None:
        couples = [(r, p) for r, p in self.couples() if (r, p) != (runtime, projet)]
        couples.insert(0, (runtime, projet))
        self.settings.setValue("couples", json.dumps(couples[:MAX_HISTORIQUE]))
        self._load_history()

    def _load_history(self) -> None:
        couples = self.couples()
        self.history.clear()
        for runtime, projet in couples:
            item = QListWidgetItem(f"{Path(runtime).name}  ⇄  {Path(projet).name}")
            item.setToolTip(tr("Runtime: {runtime}\nProject: {project}").format(runtime=runtime, project=projet))
            item.setData(Qt.ItemDataRole.UserRole, (runtime, projet))
            self.history.addItem(item)
        self.runtime.set_history(list(dict.fromkeys(r for r, _ in couples)))
        self.projet.set_history(list(dict.fromkeys(p for _, p in couples)))

    def _pick_history(self, item: QListWidgetItem) -> None:
        runtime, projet = item.data(Qt.ItemDataRole.UserRole)
        self.runtime.set_path(runtime)
        self.projet.set_path(projet)

    # -- État ------------------------------------------------------------------

    def versions_differ(self) -> bool:
        return (
            self.runtime.path is not None
            and self.projet.path is not None
            and self.runtime.version != self.projet.version
        )

    def _update_state(self) -> None:
        ready = self.runtime.path is not None and self.projet.path is not None
        differ = self.versions_differ()
        self.warning.setVisible(differ)
        if differ:
            self.warning_label.setText(
                tr(
                    "<b>Different IDE versions</b>: runtime <b>{runtime}</b>, project <b>{project}</b>. "
                    "The comparison is still possible but its results must be interpreted with care."
                ).format(runtime=self.runtime.version or "?", project=self.projet.version or "?")
            )
        else:
            self.override.setChecked(False)
        same = ready and self.runtime.path == self.projet.path
        if same:
            self.hint.setText("⚠ " + tr("Both folders are the same."))
        elif ready and not differ:
            self.hint.setText(tr("Same IDE versions: {version}.").format(version=self.runtime.version))
        else:
            self.hint.setText("")
        self.compare_button.setEnabled(ready and not same and (not differ or self.override.isChecked()))

    # -- Reconstruction à l'identique ------------------------------------------

    def snapshot(self) -> dict:
        return {
            "runtime": str(self.runtime.path) if self.runtime.path else "",
            "projet": str(self.projet.path) if self.projet.path else "",
            "override": self.override.isChecked(),
        }

    def restore(self, state: dict) -> None:
        if state.get("runtime"):
            self.runtime.set_path(state["runtime"])
        if state.get("projet"):
            self.projet.set_path(state["projet"])
        self.override.setChecked(bool(state.get("override")))

    def _launch(self) -> None:
        if self.runtime.path is None or self.projet.path is None:
            return
        runtime, projet = str(self.runtime.path.resolve()), str(self.projet.path.resolve())
        self.remember(runtime, projet)
        self.compare_requested.emit(runtime, projet)
