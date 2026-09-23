"""Couleurs, pastilles et libellés partagés par les vues."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

# État d'un fichier (inventaire)
COULEUR_ETAT: dict[str, QColor] = {
    "identique": QColor("#9e9e9e"),
    "different": QColor("#f57c00"),
    "runtime_seul": QColor("#1976d2"),
    "projet_seul": QColor("#7b1fa2"),
    "attendu": QColor("#bdbdbd"),
}
LIBELLE_ETAT: dict[str, str] = {
    "identique": "identique",
    "different": "différent",
    "runtime_seul": "runtime seul",
    "projet_seul": "projet seul",
    "attendu": "attendu",
}

# Sens d'un hunk (résumé sémantique)
COULEUR_SENS: dict[str, QColor] = {
    "ajout_runtime": QColor("#2e7d32"),
    "branche_projet": QColor("#c62828"),
    "valeur_modifiee": QColor("#ef6c00"),
    "mixte": QColor("#6a1b9a"),
    "non_significatif": QColor("#9e9e9e"),
    "identique": QColor("#9e9e9e"),
}
SYMBOLE_SENS: dict[str, str] = {
    "ajout_runtime": "➕",
    "branche_projet": "➖",
    "valeur_modifiee": "✏️",
    "mixte": "⇄",
    "non_significatif": "·",
    "identique": "=",
}
LIBELLE_SENS: dict[str, str] = {
    "ajout_runtime": "ajout runtime",
    "branche_projet": "branche projet",
    "valeur_modifiee": "valeur modifiée",
    "mixte": "mixte",
    "non_significatif": "non significatif",
    "identique": "identique",
}
LIBELLE_GENRE: dict[str, str] = {
    "bloc": "bloc",
    "fichier": "référence de fichier",
    "valeur": "valeur",
    "id": "identifiant",
    "dimensions": "compteur dérivé",
    "lignes": "lignes",
    "deplacement": "déplacement",
}

_ICONES: dict[str, QIcon] = {}


def pastille(couleur: QColor, taille: int = 12) -> QIcon:
    """Un disque de couleur, mis en cache."""
    key = f"{couleur.name()}-{taille}"
    icon = _ICONES.get(key)
    if icon is None:
        pixmap = QPixmap(taille, taille)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(couleur)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(1, 1, taille - 2, taille - 2)
        painter.end()
        icon = QIcon(pixmap)
        _ICONES[key] = icon
    return icon


def taille_lisible(octets: int | None) -> str:
    if octets is None:
        return "—"
    if octets < 1024:
        return f"{octets} o"
    if octets < 1024 * 1024:
        return f"{octets / 1024:.1f} Ko"
    return f"{octets / (1024 * 1024):.2f} Mo"
