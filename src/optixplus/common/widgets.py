"""Petits widgets réutilisables par tous les outils."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QAbstractScrollArea, QLabel, QLayout, QWidget


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


class FlowLayout(QLayout):
    """Dispose ses éléments de gauche à droite et passe à la ligne quand la place manque.

    La largeur minimale est celle du plus large élément : une barre d'outils étroite
    reste utilisable (onglets côte à côte), sur plusieurs lignes.
    """

    def __init__(self, parent: QWidget | None = None, spacing: int = 8) -> None:
        super().__init__(parent)
        self._items: list = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def addItem(self, item) -> None:  # noqa: N802 (API Qt)
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802 (API Qt)
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):  # noqa: N802 (API Qt)
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:  # noqa: N802 (API Qt)
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 (API Qt)
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 (API Qt)
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802 (API Qt)
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802 (API Qt)
        width = sum(i.sizeHint().width() for i in self._items) + self.spacing() * max(0, len(self._items) - 1)
        height = max((i.sizeHint().height() for i in self._items), default=0)
        margins = self.contentsMargins()
        return QSize(width + margins.left() + margins.right(), height + margins.top() + margins.bottom())

    def minimumSize(self) -> QSize:  # noqa: N802 (API Qt)
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def _arrange(self, rect: QRect, apply: bool) -> int:
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x, y, line_height = area.x(), area.y(), 0
        spacing = self.spacing()
        for item in self._items:
            if item.widget() is not None and not item.widget().isVisibleTo(item.widget().parentWidget()):
                continue
            hint = item.sizeHint()
            if x > area.x() and x + hint.width() > area.right() + 1:
                x, y = area.x(), y + line_height + spacing
                line_height = 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + spacing
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + margins.bottom()


def scrollbar_below_header(view: QAbstractScrollArea) -> None:
    """L'ascenseur vertical d'un tableau ou d'un arbre commence sous l'en-tête des colonnes.

    Qt le fait partir du haut de la vue, à côté des titres. La feuille de style du thème
    décale les ascenseurs marqués ``underHeader`` de la hauteur de l'en-tête (un sélecteur
    « ascenseur dans un tableau » ne les atteint pas). À appeler à la création de la vue.
    """
    bar = view.verticalScrollBar()
    bar.setProperty("underHeader", True)
    # L'ascenseur est déjà préparé par Qt à la création de la vue : style à relire.
    bar.style().unpolish(bar)
    bar.style().polish(bar)
