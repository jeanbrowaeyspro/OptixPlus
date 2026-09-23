"""Voyant d'état de la connexion, affiché dans la barre du bas."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from ..theme import Palette

STATE_OFFLINE = "offline"      # aucun automate connecté
STATE_CONNECTING = "connecting"  # connexion ou reconnexion en cours
STATE_ONLINE = "online"        # journal lu normalement
STATE_LOST = "lost"            # connexion perdue

_LABELS = {
    STATE_OFFLINE: "Aucun automate connecté",
    STATE_CONNECTING: "Connexion en cours…",
    STATE_ONLINE: "Connexion établie",
    STATE_LOST: "Connexion perdue — reconnexion automatique en cours",
}


class ConnectionIndicator(QWidget):
    """Pastille colorée : verte quand la liaison est bonne, rouge sinon."""

    DIAMETER = 11

    def __init__(self, palette: Palette, parent=None):
        super().__init__(parent)
        self.palette_ = palette
        self._state = STATE_OFFLINE
        self.setFixedSize(QSize(self.DIAMETER + 8, self.DIAMETER + 4))
        self._refresh_tooltip()

    def set_palette_colors(self, palette: Palette) -> None:
        self.palette_ = palette
        self.update()

    @property
    def state(self) -> str:
        return self._state

    def set_state(self, state: str, detail: str = "") -> None:
        self._state = state
        self._refresh_tooltip(detail)
        self.update()

    def _refresh_tooltip(self, detail: str = "") -> None:
        text = _LABELS.get(self._state, self._state)
        self.setToolTip(f"{text}\n{detail}" if detail else text)

    def _colour(self) -> QColor:
        if self._state == STATE_ONLINE:
            return QColor(self.palette_.success)
        if self._state == STATE_LOST:
            return QColor(self.palette_.error)
        if self._state == STATE_CONNECTING:
            return QColor(self.palette_.warning)
        return QColor(self.palette_.border)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        colour = self._colour()
        centre = self.rect().center()
        radius = self.DIAMETER // 2

        # Halo discret : le voyant reste repérable sur un fond clair comme sur
        # un fond sombre, sans avoir à le grossir.
        halo = QColor(colour)
        halo.setAlpha(70)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(halo)
        painter.drawEllipse(centre, radius + 2, radius + 2)

        painter.setBrush(colour)
        painter.drawEllipse(centre, radius, radius)
        painter.end()
