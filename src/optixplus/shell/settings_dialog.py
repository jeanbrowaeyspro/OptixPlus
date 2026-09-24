"""Boîte Paramètres unifiée : une catégorie « Général », puis une par outil qui en propose."""

from __future__ import annotations

import logging

from PySide6.QtCore import QByteArray, Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..common import i18n, signals, startup
from ..common.i18n import tr
from ..common.settings import LANGUAGES
from ..common.theme import THEMES, theme_label
from ..update.github import FREQUENCIES, FREQUENCY_DAILY, FREQUENCY_STARTUP, FREQUENCY_WEEKLY
from .context import AppContext

log = logging.getLogger("optixplus.settings")


def frequency_labels() -> dict[str, str]:
    return {
        FREQUENCY_STARTUP: tr("At startup only"),
        FREQUENCY_DAILY: tr("Every day"),
        FREQUENCY_WEEKLY: tr("Every week"),
    }


class GeneralPage(QWidget):
    """Langue, thème, démarrage avec Windows, mises à jour."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        general = context.settings.general
        form = QFormLayout(self)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setVerticalSpacing(12)

        self.language = QComboBox()
        detected = "Français" if i18n.detect_windows_language() == "fr" else "English"
        labels = {
            "auto": tr("Automatic (Windows: {language})").format(language=detected),
            "fr": "Français",
            "en": "English",
        }
        for code in LANGUAGES:
            self.language.addItem(labels[code], code)
        self.language.setCurrentIndex(max(0, self.language.findData(general.language)))
        form.addRow(tr("Language"), self.language)

        self.theme = QComboBox()
        for code in THEMES:
            self.theme.addItem(theme_label(code), code)
        self.theme.setCurrentIndex(max(0, self.theme.findData(context.theme.theme)))
        form.addRow(tr("Theme"), self.theme)

        self.autostart = QCheckBox(tr("Start OptixPlus with Windows"))
        self.autostart.setChecked(startup.is_enabled())
        if not context.installed:
            self.autostart.setEnabled(False)
            self.autostart.setToolTip(tr("Only available when OptixPlus is installed."))
        form.addRow("", self.autostart)

        heading = QLabel(tr("Updates"))
        heading.setProperty("heading", True)
        form.addRow(heading)
        updates = context.controller.updates
        self._updates = updates
        self.auto_update = QCheckBox(tr("Check for updates automatically"))
        self.auto_update.setChecked(updates.settings.auto_check)
        form.addRow("", self.auto_update)
        self.frequency = QComboBox()
        for code, label in frequency_labels().items():
            self.frequency.addItem(label, code)
        self.frequency.setCurrentIndex(max(0, self.frequency.findData(updates.settings.frequency)))
        self.auto_update.toggled.connect(self.frequency.setEnabled)
        self.frequency.setEnabled(self.auto_update.isChecked())
        form.addRow(tr("Frequency"), self.frequency)
        self.prereleases = QCheckBox(tr("Include pre-releases"))
        self.prereleases.setToolTip(tr("Also offers test versions published before an official release."))
        self.prereleases.setChecked(updates.settings.include_prereleases)
        form.addRow("", self.prereleases)
        self.last_check = QLabel()
        self.last_check.setProperty("muted", True)
        self.check_button = QPushButton(tr("Check now"))
        self.check_button.setToolTip(tr("Asks GitHub whether a newer version of OptixPlus is published."))
        self.check_button.clicked.connect(self._check_now)
        check_row = QHBoxLayout()
        check_row.addWidget(self.last_check, 1)
        check_row.addWidget(self.check_button)
        form.addRow(tr("Last check"), check_row)
        signals.follow(updates.busy_changed, self, self._refresh_update_state)
        self._refresh_update_state()

    def _refresh_update_state(self, *_args) -> None:
        self.last_check.setText(self._updates.last_check_text())
        self.check_button.setEnabled(not self._updates.busy)

    def _check_now(self) -> None:
        self._apply_update_settings()  # la vérification tient compte des préversions cochées
        self._updates.check(interactive=True)

    def _apply_update_settings(self) -> None:
        s = self._updates.settings
        s.auto_check = self.auto_update.isChecked()
        s.frequency = self.frequency.currentData() if self.frequency.currentData() in FREQUENCIES else FREQUENCY_DAILY
        s.include_prereleases = self.prereleases.isChecked()

    def apply(self) -> bool:
        """Applique les choix ; renvoie vrai si la langue effective change."""
        general = self._context.settings.general
        self._apply_update_settings()
        language_changed = False
        language = self.language.currentData()
        if language != general.language:
            general.language = language
            language_changed = i18n.resolve_language(language) != i18n.current_language()
        theme = self.theme.currentData()
        if theme != general.theme:
            general.theme = theme
            self._context.theme.set_theme(theme)
        if self.autostart.isEnabled() and self.autostart.isChecked() != startup.is_enabled():
            try:
                startup.set_enabled(self.autostart.isChecked())
                log.info("Démarrage avec Windows %s", "activé" if self.autostart.isChecked() else "désactivé")
            except OSError as exc:
                log.error("Modification du démarrage automatique impossible : %s", exc)
                QMessageBox.warning(
                    self, "OptixPlus", tr("Unable to change the Windows startup setting:\n{error}").format(error=exc)
                )
        return language_changed


GENERAL = "general"


class SettingsDialog(QDialog):
    """Paramètres de l'application : « Général », puis une catégorie par outil qui en propose.

    La page d'un outil vient de son service (``BackgroundService.settings_page``) : elle
    existe même si l'outil n'a pas encore été ouvert dans la fenêtre.
    """

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self.setWindowTitle(tr("Settings"))
        self.resize(720, 560)

        self._categories = QListWidget()
        self._categories.setFixedWidth(170)
        self._pages = QStackedWidget()
        self._categories.currentRowChanged.connect(self._pages.setCurrentIndex)
        self._category_ids: list[str] = []

        self._general = GeneralPage(context)
        self._add_page(GENERAL, tr("General"), self._general)
        self._tool_pages: dict[str, QWidget] = {}
        for service in context.services.values():
            page = service.settings_page(None)
            if page is not None:
                self._tool_pages[service.spec.id] = page
                self._add_page(service.spec.id, tr(service.spec.title), page)

        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(self._categories)
        body.addWidget(self._pages, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Apply
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._apply)

        layout = QVBoxLayout(self)
        layout.addLayout(body, 1)
        layout.addWidget(buttons)
        self._categories.setCurrentRow(0)

    def select(self, category: str) -> None:
        """Affiche la catégorie ``category`` (« general » ou l'identifiant d'un outil)."""
        if category in self._category_ids:
            self._categories.setCurrentRow(self._category_ids.index(category))

    def tool_page(self, module_id: str) -> QWidget | None:
        return self._tool_pages.get(module_id)

    def snapshot(self) -> dict:
        return {
            "category": self._categories.currentRow(),
            "geometry": bytes(self.saveGeometry().toBase64().data()),
            "pages": {module_id: page.snapshot() for module_id, page in self._tool_pages.items()},
        }

    def restore(self, state: dict) -> None:
        self._categories.setCurrentRow(max(0, state.get("category", 0)))
        if state.get("geometry"):
            self.restoreGeometry(QByteArray.fromBase64(state["geometry"]))
        for module_id, page_state in state.get("pages", {}).items():
            if module_id in self._tool_pages and page_state:
                self._tool_pages[module_id].restore(page_state)

    def _add_page(self, category: str, title: str, page: QWidget) -> None:
        self._category_ids.append(category)
        self._categories.addItem(title)
        self._pages.addWidget(page)

    def _apply(self) -> None:
        for page in self._tool_pages.values():
            page.apply()
        language_changed = self._general.apply()
        self._context.settings.save()
        if language_changed:
            # La fenêtre (parente de cette boîte) va être reconstruite dans la nouvelle
            # langue : la boîte se ferme d'abord, le changement suit hors de ses signaux,
            # puis la boîte est rouverte, traduite, sur la même catégorie.
            controller = self._context.controller
            self.accept()
            dialog_state = self.snapshot()
            QTimer.singleShot(0, lambda: controller.change_language(settings_state=dialog_state))

    def _accept(self) -> None:
        self._apply()
        if self.isVisible():
            self.accept()
