"""Icônes vectorielles de l'interface, recolorées selon le thème.

Les SVG de ``resources/icons`` utilisent ``currentColor`` ; l'icône est rendue avec la
couleur demandée. Les rendus sont mis en cache par (nom, couleurs, taille) ; le cache est
vidé à chaque changement de thème.
"""

from __future__ import annotations

from functools import cache

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from . import paths, theme

RENDER_SIZES = (16, 20, 24, 32, 48)


@cache
def _svg_source(name: str) -> str:
    return paths.resource_path("icons", f"{name}.svg").read_text(encoding="utf-8")


def render_svg(svg: str, size: int, device_ratio: float = 1.0) -> QPixmap:
    """Rend un SVG dans un pixmap carré transparent."""
    px = max(1, round(size * device_ratio))
    pixmap = QPixmap(px, px)
    pixmap.fill(Qt.GlobalColor.transparent)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, px, px))
    painter.end()
    pixmap.setDevicePixelRatio(device_ratio)
    return pixmap


@cache
def _themed(name: str, normal: str, active: str | None) -> QIcon:
    icon = QIcon()
    source = _svg_source(name)
    for size in RENDER_SIZES:
        for ratio in (1.0, 2.0):
            icon.addPixmap(
                render_svg(source.replace("currentColor", normal), size, ratio), QIcon.Mode.Normal, QIcon.State.Off
            )
            if active:
                on = render_svg(source.replace("currentColor", active), size, ratio)
                icon.addPixmap(on, QIcon.Mode.Normal, QIcon.State.On)
                icon.addPixmap(on, QIcon.Mode.Active, QIcon.State.Off)
    return icon


def themed_icon(name: str, *, highlight_when_checked: bool = False) -> QIcon:
    """Icône de l'interface aux couleurs du thème courant.

    ``highlight_when_checked`` : l'état coché (barre latérale) prend la couleur d'accent.
    """
    p = theme.current()
    return _themed(name, p.text_muted if highlight_when_checked else p.text, p.accent if highlight_when_checked else None)


def themed_action(action, name: str):
    """Pose une icône d'interface sur une action et la marque pour la recoloration au changement
    de thème (la fenêtre recolore les actions portant la propriété ``themedIcon``)."""
    action.setIcon(themed_icon(name))
    action.setProperty("themedIcon", name)
    return action


_PASTILLES: dict[str, QIcon] = {}


def pastille(couleur, taille: int = 12) -> QIcon:
    """Un disque de couleur (état, voyant), mis en cache par couleur et taille."""
    from PySide6.QtGui import QColor

    couleur = QColor(couleur)
    key = f"{couleur.name()}-{taille}"
    icon = _PASTILLES.get(key)
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
        _PASTILLES[key] = icon
    return icon


def app_icon(suspended: bool = False) -> QIcon:
    """Icône de l'application (fenêtres, tray)."""
    name = "app_suspended" if suspended else "app"
    ico = paths.resource_path("icons", f"{name}.ico")
    if ico.exists():
        return QIcon(str(ico))
    return QIcon(paths.resource_path("icons", f"{name}.svg").as_posix())


def clear_cache() -> None:
    _themed.cache_clear()


def icon_size(px: int) -> QSize:
    return QSize(px, px)
