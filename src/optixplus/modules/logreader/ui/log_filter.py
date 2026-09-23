"""Filtrage et tri du journal.

Le filtre lit directement les entrées du modèle source plutôt que d'appeler
``data()`` ligne par ligne : sur un journal de plusieurs dizaines de milliers
de lignes, cela fait la différence entre un filtre instantané et un filtre qui
se voit.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QSortFilterProxyModel, Qt

from ....common.i18n import tr
from .log_model import SORT_ROLE

#: Valeurs spéciales du filtre par règle de surlignage.
RULE_ANY = -2
RULE_NONE = -1


class LogFilterProxy(QSortFilterProxyModel):
    """Recherche plein texte, niveaux, règle de surlignage, période et filtres
    de colonnes.

    Le filtrage par source ne figure plus ici : il se fait par l'entonnoir de
    la colonne « Source », comme pour n'importe quelle autre colonne.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSortRole(SORT_ROLE)
        self.setDynamicSortFilter(True)

        self._search = ""
        self._search_terms: list[str] = []
        self._levels: set[str] | None = None      # ``None`` = tous les niveaux
        self._rule = RULE_ANY
        self._from: datetime | None = None
        self._to: datetime | None = None
        #: Filtres posés depuis les en-têtes de colonnes.
        self._column_values: dict[int, set[str]] = {}
        self._column_text: dict[int, str] = {}

    # ----------------------------------------------------------- paramétrage

    def _refilter(self) -> None:
        """Refiltre les lignes (remplace ``invalidateRowsFilter``, déprécié depuis Qt 6.10)."""
        self.beginFilterChange()
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def set_search(self, text: str) -> None:
        text = (text or "").strip().lower()
        if text == self._search:
            return
        self._search = text
        # Les termes séparés par des espaces sont cumulatifs (ET), ce qui rend
        # la recherche « codesys error » utile sans syntaxe à apprendre.
        self._search_terms = text.split()
        self._refilter()

    def set_levels(self, levels) -> None:
        new = None if levels is None else set(levels)
        if new == self._levels:
            return
        self._levels = new
        self._refilter()

    def set_rule(self, rule_index: int) -> None:
        if rule_index == self._rule:
            return
        self._rule = rule_index
        self._refilter()

    def set_period(self, start: datetime | None, end: datetime | None) -> None:
        if (start, end) == (self._from, self._to):
            return
        self._from, self._to = start, end
        self._refilter()

    def set_column_filter(self, column: int, values: set[str] | None, text: str) -> None:
        """Pose ou retire le filtre d'une colonne.

        ``values`` à ``None`` signifie « toutes les valeurs » ; un texte vide
        désactive le filtre « contient ».
        """
        changed = False
        if values is None:
            changed |= self._column_values.pop(column, None) is not None
        elif self._column_values.get(column) != values:
            self._column_values[column] = values
            changed = True

        text = (text or "").strip().lower()
        if not text:
            changed |= self._column_text.pop(column, None) is not None
        elif self._column_text.get(column) != text:
            self._column_text[column] = text
            changed = True

        if changed:
            self._refilter()

    def current_rule(self) -> int:
        """Règle de surlignage actuellement retenue par le filtre."""
        return self._rule

    def column_filter(self, column: int) -> tuple[set[str] | None, str]:
        return self._column_values.get(column), self._column_text.get(column, "")

    def filtered_columns(self) -> set[int]:
        return set(self._column_values) | set(self._column_text)

    def clear_column_filters(self) -> None:
        if self._column_values or self._column_text:
            self._column_values.clear()
            self._column_text.clear()
            self._refilter()

    def reset_filters(self) -> None:
        self._search = ""
        self._search_terms = []
        self._levels = None
        self._rule = RULE_ANY
        self._from = self._to = None
        self._column_values.clear()
        self._column_text.clear()
        self._refilter()

    @property
    def has_active_filters(self) -> bool:
        return bool(
            self._search_terms
            or self._levels is not None
            or self._rule != RULE_ANY
            or self._from
            or self._to
            or self._column_values
            or self._column_text
        )

    # -------------------------------------------------------------- filtrage

    def filterAcceptsRow(self, source_row: int, source_parent) -> bool:
        entry = self.sourceModel().entry_at(source_row)
        if entry is None:
            return False

        if self._levels is not None and entry.level not in self._levels:
            return False

        if self._rule != RULE_ANY:
            if self._rule == RULE_NONE:
                if entry.highlight_index >= 0:
                    return False
            elif entry.highlight_index != self._rule:
                return False

        if self._from or self._to:
            stamp = entry.timestamp
            if stamp is None:
                return False
            if self._from and stamp < self._from:
                return False
            if self._to and stamp > self._to:
                return False

        if self._column_values or self._column_text:
            model = self.sourceModel()
            for column, allowed in self._column_values.items():
                if model.display_text(entry, column) not in allowed:
                    return False
            for column, needle in self._column_text.items():
                if needle not in model.display_text(entry, column).lower():
                    return False

        for term in self._search_terms:
            if term not in entry.search_text:
                return False
        return True

    # ---------------------------------------------------------------- résumé

    def summary(self, rule_names: dict[int, str] | None = None) -> str:
        """Description lisible des filtres actifs, reportée dans l'export."""
        rule_names = rule_names or {}
        parts = []
        if self._levels is not None:
            from .log_model import level_label

            parts.append(tr("Levels: {levels}").format(levels=", ".join(sorted(level_label(l) for l in self._levels))))
        if self._rule == RULE_NONE:
            parts.append(tr("Highlighting: lines not highlighted"))
        elif self._rule != RULE_ANY:
            parts.append(tr("Highlighting: {rule}").format(rule=rule_names.get(self._rule, self._rule)))
        if self._from:
            parts.append(tr("From {date}").format(date=self._from.strftime("%d/%m/%Y %H:%M:%S")))
        if self._to:
            parts.append(tr("Until {date}").format(date=self._to.strftime("%d/%m/%Y %H:%M:%S")))
        if self._search:
            parts.append(tr("Search: “{text}”").format(text=self._search))

        from .log_model import column_titles

        titles = column_titles()
        for column in sorted(set(self._column_values) | set(self._column_text)):
            title = titles[column] if column < len(titles) else str(column)
            values = self._column_values.get(column)
            needle = self._column_text.get(column)
            if values is not None:
                if len(values) <= 4:
                    detail = ", ".join(sorted(v or tr("(empty)") for v in values))
                else:
                    detail = tr("{n} values kept").format(n=len(values))
                parts.append(f"{title} : {detail}")
            if needle:
                parts.append(tr("{column} contains “{text}”").format(column=title, text=needle))
        return " | ".join(parts)

    def sort_summary(self) -> str:
        """Description lisible du tri courant."""
        column = self.sortColumn()
        if column < 0:
            return tr("file order (chronological)")
        from .log_model import column_titles

        direction = tr("ascending") if self.sortOrder() == Qt.SortOrder.AscendingOrder else tr("descending")
        return f"{column_titles()[column]} {direction}"

    def visible_entries(self) -> list:
        """Entrées visibles, dans l'ordre d'affichage (pour l'export)."""
        model = self.sourceModel()
        return [
            model.entry_at(self.mapToSource(self.index(row, 0)).row())
            for row in range(self.rowCount())
        ]
