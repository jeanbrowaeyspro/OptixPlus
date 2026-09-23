"""Couleurs et pastilles partagées par les vues ; les libellés sont dans ``core.labels``.

Les couleurs viennent de la palette du thème d'OptixPlus (et non plus de couleurs Material
codées en dur) : elles restent lisibles en clair comme en sombre.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

from ....common import theme
from ....common.i18n import tr


def couleur_etat(status: str) -> QColor:
    """Couleur de l'état d'un fichier (inventaire)."""
    p = theme.current()
    return QColor(
        {
            "identique": p.text_muted,
            "different": p.warning,
            "runtime_seul": p.info,
            "projet_seul": p.accent,
            "attendu": p.text_muted,
        }.get(status, p.text_muted)
    )


def couleur_sens(sens: str) -> QColor:
    """Couleur du sens d'un écart : vert ajout, rouge branche projet, orange valeur."""
    p = theme.current()
    return QColor(
        {
            "ajout_runtime": p.success,
            "branche_projet": p.error,
            "valeur_modifiee": p.warning,
            "mixte": p.accent,
        }.get(sens, p.text_muted)
    )


def couleur_etat_ligne(state: str) -> QColor | None:
    """Couleur d'une ligne des vues spécialisées."""
    return {
        "identique": couleur_etat("identique"),
        "runtime_seul": couleur_sens("ajout_runtime"),
        "projet_seul": couleur_sens("branche_projet"),
        "modifie": couleur_sens("valeur_modifiee"),
    }.get(state)


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
        return tr("{n} B").format(n=octets)
    if octets < 1024 * 1024:
        return tr("{n:.1f} KB").format(n=octets / 1024)
    return tr("{n:.2f} MB").format(n=octets / (1024 * 1024))
