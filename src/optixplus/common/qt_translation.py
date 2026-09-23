"""Traduction des textes standard de Qt (boutons OK/Annuler, menus contextuels…).

Le traducteur est remplacé à chaud lors d'un changement de langue.
"""

from __future__ import annotations

from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
from PySide6.QtWidgets import QApplication

_translator: QTranslator | None = None


def apply(app: QApplication, language: str) -> None:
    """Installe le traducteur de Qt pour ``language`` (aucun pour l'anglais, langue native de Qt)."""
    global _translator
    if _translator is not None:
        app.removeTranslator(_translator)
        _translator = None
    if language != "fr":
        return
    translator = QTranslator(app)
    folder = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if translator.load(QLocale(QLocale.Language.French), "qtbase", "_", folder):
        app.installTranslator(translator)
        _translator = translator
