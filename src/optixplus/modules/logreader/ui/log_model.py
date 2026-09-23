"""Modèle de tableau et filtre pour le journal.

Le tableau est virtualisé par Qt : seules les lignes visibles sont peintes,
ce qui permet d'afficher plusieurs centaines de milliers d'entrées sans
ralentissement. Le filtre travaille directement sur la liste d'entrées du
modèle source plutôt qu'en passant par ``data()``, ce qui rend le
rafraîchissement d'un filtre quasi instantané.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor

from ..core.highlight import Highlighter
from ..core.logparser import KNOWN_LEVELS

#: Rôle utilisé pour le tri : il expose la valeur brute (datetime, entier)
#: plutôt que le texte affiché, pour que le tri par date soit chronologique.
SORT_ROLE = Qt.ItemDataRole.UserRole + 1
#: Rôle exposant l'objet :class:`~app.logparser.LogEntry` complet.
ENTRY_ROLE = Qt.ItemDataRole.UserRole + 2

COLUMN_LINE = 0
COLUMN_TIMESTAMP = 1
COLUMN_LEVEL = 2
COLUMN_SOURCE = 3
COLUMN_CODE = 4
COLUMN_MESSAGE = 5
COLUMN_NODE = 6

#: Largeurs par défaut. Elles tiennent compte des 34 pixels réservés à droite
#: de chaque en-tête pour l'entonnoir de filtre et l'indicateur de tri.
COLUMNS = (
    ("line", "N°", 96),
    ("timestamp", "Date / heure", 190),
    ("level", "Niveau", 130),
    ("source", "Source", 210),
    ("code", "Code", 104),
    ("message", "Message", 560),
    ("node_path", "Chemin du nœud", 320),
)

LEVEL_LABELS = {
    "ERROR": "Erreur",
    "WARNING": "Avertissement",
    "INFO": "Information",
}


def level_label(level: str) -> str:
    return LEVEL_LABELS.get(level, level or "—")


class LogTableModel(QAbstractTableModel):
    """Expose une liste de :class:`~app.logparser.LogEntry` sous forme de tableau."""

    countChanged = Signal()

    def __init__(self, highlighter: Highlighter, max_rows: int = 0, parent=None):
        super().__init__(parent)
        self._entries: list = []
        self._highlighter = highlighter
        self._max_rows = max_rows
        self._background_cache: dict[int, QColor] = {}
        self._foreground_cache: dict[int, QColor] = {}
        #: Numéro attribué à la prochaine entrée. Il ne redescend jamais : une
        #: ligne élaguée ne libère pas son numéro, sinon deux lignes
        #: différentes porteraient le même numéro au fil de la session.
        self._next_number = 0
        self._counts: dict[str, int] = {}

    # ------------------------------------------------------------ interface Qt

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._entries)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section: int, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole or orientation != Qt.Orientation.Horizontal:
            return None
        return COLUMNS[section][1]

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        entry = self._entries[index.row()]
        column = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            return self._display(entry, column)
        if role == SORT_ROLE:
            return self._sort_value(entry, column)
        if role == ENTRY_ROLE:
            return entry
        if role == Qt.ItemDataRole.BackgroundRole:
            return self._background(entry.highlight_index)
        if role == Qt.ItemDataRole.ForegroundRole:
            return self._foreground(entry.highlight_index)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if column in (COLUMN_LINE, COLUMN_CODE):
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltip(entry)
        return None

    @staticmethod
    def _display(entry, column: int):
        if column == COLUMN_LINE:
            return entry.index + 1
        if column == COLUMN_TIMESTAMP:
            return entry.timestamp_text or "—"
        if column == COLUMN_LEVEL:
            return level_label(entry.level)
        if column == COLUMN_SOURCE:
            return entry.source
        if column == COLUMN_CODE:
            return entry.code
        if column == COLUMN_MESSAGE:
            # Une ligne de tableau ne peut afficher qu'une ligne de texte : les
            # tabulations (qui figurent des retours à la ligne) deviennent des
            # séparateurs visibles, le détail complet restant dans le panneau.
            return entry.message.replace("\t", " ⏎ ").strip()
        if column == COLUMN_NODE:
            return entry.node_path
        return ""

    @staticmethod
    def _sort_value(entry, column: int):
        if column == COLUMN_LINE:
            return entry.index
        if column == COLUMN_TIMESTAMP:
            # Les entrées sans horodatage lisible sont regroupées au début.
            return entry.timestamp or datetime.min
        if column == COLUMN_LEVEL:
            # Tri par gravité décroissante plutôt qu'alphabétique.
            try:
                return KNOWN_LEVELS.index(entry.level)
            except ValueError:
                return len(KNOWN_LEVELS)
        if column == COLUMN_CODE:
            return entry.code.lower()
        if column == COLUMN_SOURCE:
            return entry.source.lower()
        if column == COLUMN_MESSAGE:
            return entry.message.lower()
        if column == COLUMN_NODE:
            return entry.node_path.lower()
        return ""

    def _tooltip(self, entry) -> str:
        parts = [entry.message_multiline]
        if entry.details:
            parts.append("— Détails —\n" + entry.details_multiline)
        if entry.node_path:
            parts.append("— Nœud —\n" + entry.node_path)
        text = "\n\n".join(p for p in parts if p)
        return text[:2000] + ("…" if len(text) > 2000 else "")

    # ------------------------------------------------------------- couleurs

    def _background(self, rule_index: int):
        if rule_index < 0:
            return None
        if rule_index not in self._background_cache:
            style = self._highlighter.style_at(rule_index)
            if style is None:
                return None
            self._background_cache[rule_index] = QColor(style.background)
        return self._background_cache[rule_index]

    def _foreground(self, rule_index: int):
        if rule_index < 0:
            return None
        if rule_index not in self._foreground_cache:
            style = self._highlighter.style_at(rule_index)
            if style is None:
                return None
            self._foreground_cache[rule_index] = QColor(style.foreground)
        return self._foreground_cache[rule_index]

    def refresh_highlighting(self) -> None:
        """Recalcule le surlignage de toutes les lignes après un changement
        de règles ou de thème."""
        self._background_cache.clear()
        self._foreground_cache.clear()
        self._highlighter.apply(self._entries)
        if self._entries:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._entries) - 1, len(COLUMNS) - 1),
                [Qt.ItemDataRole.BackgroundRole, Qt.ItemDataRole.ForegroundRole],
            )

    # ------------------------------------------------------------- contenu

    @property
    def entries(self) -> list:
        return self._entries

    def entry_at(self, row: int):
        if 0 <= row < len(self._entries):
            return self._entries[row]
        return None

    def set_max_rows(self, max_rows: int) -> None:
        self._max_rows = max_rows
        self._trim()

    # Compteurs par niveau tenus à jour au fil des ajouts et des élagages. pyFTOLogReader
    # les recalculait en parcourant toutes les lignes (jusqu'à 500 000) à chaque lot reçu.
    def _count(self, entries, sign: int) -> None:
        counts = self._counts
        for entry in entries:
            counts[entry.level] = counts.get(entry.level, 0) + sign

    def clear(self) -> None:
        self.beginResetModel()
        self._entries = []
        self._next_number = 0
        self._counts = {}
        self.endResetModel()
        self.countChanged.emit()

    def set_entries(self, entries: list) -> None:
        self.beginResetModel()
        entries = list(entries)
        for number, entry in enumerate(entries):
            entry.index = number
        self._next_number = len(entries)
        self._highlighter.apply(entries)
        self._entries = entries
        self._counts = {}
        self._count(entries, 1)
        self.endResetModel()
        self._trim()
        self.countChanged.emit()

    def append_entries(self, entries: list) -> None:
        if not entries:
            return
        for entry in entries:
            entry.index = self._next_number
            self._next_number += 1
        self._highlighter.apply(entries)
        first = len(self._entries)
        self.beginInsertRows(QModelIndex(), first, first + len(entries) - 1)
        self._entries.extend(entries)
        self._count(entries, 1)
        self.endInsertRows()
        self._trim()
        self.countChanged.emit()

    def _trim(self) -> None:
        """Élague les lignes les plus anciennes au-delà de la limite configurée."""
        if not self._max_rows or len(self._entries) <= self._max_rows:
            return
        excess = len(self._entries) - self._max_rows
        self.beginRemoveRows(QModelIndex(), 0, excess - 1)
        self._count(self._entries[:excess], -1)
        del self._entries[:excess]
        self.endRemoveRows()

    def level_counts(self) -> dict[str, int]:
        counts = {level: 0 for level in KNOWN_LEVELS}
        counts.update(self._counts)
        return counts

    def display_text(self, entry, column: int) -> str:
        """Valeur affichée d'une cellule, sous forme de texte.

        Sert de référence commune aux filtres par colonne : ce que l'on filtre
        est exactement ce que l'utilisateur lit dans le tableau.
        """
        value = self._display(entry, column)
        return "" if value is None else str(value)

    def distinct_values(self, column: int, limit: int) -> tuple[list[tuple[str, int]], bool]:
        """Valeurs distinctes d'une colonne, avec leur nombre d'occurrences.

        Renvoie ``(valeurs, tronqué)``. Le drapeau passe à vrai dès que *limit*
        est dépassé : la colonne est alors trop variée pour être présentée sous
        forme de liste à cocher.
        """
        counts: dict[str, int] = {}
        for entry in self._entries:
            value = self.display_text(entry, column)
            counts[value] = counts.get(value, 0) + 1
            if len(counts) > limit:
                return [], True

        def sort_key(item: tuple[str, int]):
            # Les colonnes numériques se trient comme des nombres, pas comme du
            # texte, sans quoi « 10 » précèderait « 9 ».
            text = item[0]
            return (0, int(text)) if text.isdigit() else (1, text.lower())

        return sorted(counts.items(), key=sort_key), False
