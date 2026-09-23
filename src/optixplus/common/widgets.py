"""Petits widgets réutilisables par tous les outils."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QLabel, QWidget


class ElidedLabel(QLabel):
    """Libellé d'une ligne abrégé par « … » quand la place manque, au lieu d'élargir la fenêtre.

    ``text()`` renvoie toujours le texte complet ; l'infobulle reste à la charge de l'appelant.
    """

    def __init__(self, text: str = "", parent: QWidget | None = None,
                 mode: Qt.TextElideMode = Qt.TextElideMode.ElideRight) -> None:
        super().__init__(parent)
        self._full = ""
        self._mode = mode
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 (API Qt)
        self._full = text or ""
        self._elide()
        self.updateGeometry()

    def text(self) -> str:
        return self._full

    def sizeHint(self) -> QSize:  # noqa: N802 (API Qt)
        margins = self.contentsMargins()
        width = self.fontMetrics().horizontalAdvance(self._full) + margins.left() + margins.right() + 2
        return QSize(width, super().sizeHint().height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (API Qt)
        return QSize(min(self.sizeHint().width(), 40), super().minimumSizeHint().height())

    def resizeEvent(self, event) -> None:  # noqa: N802 (API Qt)
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        width = self.contentsRect().width()
        shown = self.fontMetrics().elidedText(self._full, self._mode, width) if width > 0 else self._full
        QLabel.setText(self, shown)
