"""Thème système / sombre / clair : style Fusion et palette explicite, persistés dans les réglages.

« Système » rend à Qt son style et sa palette d'origine (qui suivent Windows, sombre ou clair).
« Sombre » et « Clair » imposent une palette explicite avec le style Fusion, quel que soit Windows.
"""

from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

THEMES: tuple[str, ...] = ("systeme", "sombre", "clair")
LIBELLE_THEME: dict[str, str] = {"systeme": "Système", "sombre": "Sombre", "clair": "Clair"}

_DEFAULT: dict[str, object] = {}


def _palette(fond: QColor, base: QColor, alternate: QColor, texte: QColor, mid: QColor, disabled: QColor) -> QPalette:
    p = QPalette()
    accent = QColor(42, 130, 218)
    p.setColor(QPalette.ColorRole.Window, fond)
    p.setColor(QPalette.ColorRole.WindowText, texte)
    p.setColor(QPalette.ColorRole.Base, base)
    p.setColor(QPalette.ColorRole.AlternateBase, alternate)
    p.setColor(QPalette.ColorRole.ToolTipBase, base)
    p.setColor(QPalette.ColorRole.ToolTipText, texte)
    p.setColor(QPalette.ColorRole.Text, texte)
    p.setColor(QPalette.ColorRole.Button, fond)
    p.setColor(QPalette.ColorRole.ButtonText, texte)
    p.setColor(QPalette.ColorRole.BrightText, QColor(255, 80, 80))
    p.setColor(QPalette.ColorRole.Link, accent)
    p.setColor(QPalette.ColorRole.Highlight, accent)
    p.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    p.setColor(QPalette.ColorRole.Mid, mid)
    p.setColor(QPalette.ColorRole.PlaceholderText, disabled)
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        p.setColor(QPalette.ColorGroup.Disabled, role, disabled)
    return p


def dark_palette() -> QPalette:
    return _palette(
        fond=QColor(45, 45, 45),
        base=QColor(30, 30, 30),
        alternate=QColor(38, 38, 38),
        texte=QColor(225, 225, 225),
        mid=QColor(90, 90, 90),
        disabled=QColor(130, 130, 130),
    )


def light_palette() -> QPalette:
    return _palette(
        fond=QColor(240, 240, 240),
        base=QColor(255, 255, 255),
        alternate=QColor(246, 246, 246),
        texte=QColor(30, 30, 30),
        mid=QColor(170, 170, 170),
        disabled=QColor(140, 140, 140),
    )


def apply_theme(app: QApplication, theme: str) -> None:
    """Applique ``systeme``, ``sombre`` ou ``clair`` à toute l'application."""
    if "style" not in _DEFAULT:
        _DEFAULT["style"] = app.style().objectName()
        _DEFAULT["palette"] = QPalette(app.palette())
    if theme == "sombre":
        app.setStyle("Fusion")
        app.setPalette(dark_palette())
    elif theme == "clair":
        app.setStyle("Fusion")
        app.setPalette(light_palette())
    else:
        app.setStyle(str(_DEFAULT["style"]))
        app.setPalette(_DEFAULT["palette"])  # type: ignore[arg-type]


def theme_enregistre(settings: QSettings) -> str:
    """Le thème mémorisé ; l'ancien réglage booléen ``theme_sombre`` est repris."""
    value = settings.value("theme")
    if isinstance(value, str) and value in THEMES:
        return value
    ancien = settings.value("theme_sombre", False)
    return "sombre" if ancien in (True, "true", "True", 1, "1") else "systeme"
