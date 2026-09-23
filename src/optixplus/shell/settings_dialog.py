"""Boîte Paramètres unifiée : une catégorie « Général », puis une par outil qui en propose."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
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
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..common import i18n, startup
from ..common.i18n import tr
from ..common.settings import LANGUAGES
from ..common.theme import THEMES, theme_label
from .context import AppContext

log = logging.getLogger("optixplus.settings")


class GeneralPage(QWidget):
    """Langue, thème, démarrage avec Windows."""

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
        note = QLabel(tr("A language change takes effect the next time OptixPlus starts."))
        note.setProperty("muted", True)
        note.setWordWrap(True)
        form.addRow("", note)

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

    def apply(self) -> bool:
        """Applique les choix ; renvoie vrai si un redémarrage est nécessaire."""
        general = self._context.settings.general
        restart = False
        language = self.language.currentData()
        if language != general.language:
            old_effective = i18n.resolve_language(general.language)
            general.language = language
            restart = i18n.resolve_language(language) != old_effective
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
        return restart


class SettingsDialog(QDialog):
    """Paramètres de l'application."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self.setWindowTitle(tr("Settings"))
        self.resize(680, 440)

        self._categories = QListWidget()
        self._categories.setFixedWidth(170)
        self._pages = QStackedWidget()
        self._categories.currentRowChanged.connect(self._pages.setCurrentIndex)

        self._general = GeneralPage(context)
        self._add_page(tr("General"), self._general)

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

    def _add_page(self, title: str, page: QWidget) -> None:
        self._categories.addItem(title)
        self._pages.addWidget(page)

    def _apply(self) -> None:
        restart = self._general.apply()
        self._context.settings.save()
        if restart:
            QMessageBox.information(
                self, tr("Settings"), tr("The new language will be used the next time OptixPlus starts.")
            )

    def _accept(self) -> None:
        self._apply()
        self.accept()
