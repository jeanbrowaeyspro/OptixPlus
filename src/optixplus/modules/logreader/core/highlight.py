"""Moteur de surlignage par mots-clés.

Chaque règle est compilée en une expression régulière unique (alternance de ses
mots-clés) : une ligne coûte une recherche par règle plutôt qu'une par mot-clé,
ce qui permet de recolorer un journal de plusieurs centaines de milliers de
lignes sans latence perceptible.

Les couleurs stockées dans la configuration sont des teintes vives. Elles sont
éclaircies sur fond clair et assombries sur fond sombre : une seule couleur par
règle suffit donc pour les deux thèmes, et l'utilisateur n'a qu'un choix à
faire.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .colors import blend, readable_text_color
from .config import HighlightRule

#: Fond de référence utilisé pour dériver les teintes de chaque thème.
LIGHT_BASE = "#FFFFFF"
DARK_BASE = "#1E2127"

#: Opacité de la teinte sur le fond. Assez marquée pour repérer une ligne d'un
#: coup d'œil, assez discrète pour que le texte reste parfaitement lisible.
LIGHT_ALPHA = 0.22
DARK_ALPHA = 0.34


@dataclass(frozen=True)
class RuleStyle:
    """Couleurs effectives d'une règle pour un thème donné."""

    background: str
    foreground: str


def rule_style(color: str, dark: bool) -> RuleStyle:
    """Décline une teinte en couleurs de fond et de texte pour un thème."""
    base = DARK_BASE if dark else LIGHT_BASE
    alpha = DARK_ALPHA if dark else LIGHT_ALPHA
    try:
        background = blend(color, base, alpha)
    except ValueError:
        background = base
    return RuleStyle(background=background, foreground=readable_text_color(background))


class _CompiledRule:
    __slots__ = ("rule", "pattern", "use_message_only")

    def __init__(self, rule: HighlightRule):
        self.rule = rule
        self.use_message_only = rule.scope == "message"
        keywords = [k.strip().lower() for k in rule.keywords if k and k.strip()]
        if not keywords:
            self.pattern = None
            return
        alternation = "|".join(re.escape(k) for k in keywords)
        if rule.whole_word:
            alternation = rf"\b(?:{alternation})\b"
        self.pattern = re.compile(alternation)


class Highlighter:
    """Applique un jeu de règles à des entrées de log."""

    def __init__(self, rules: list[HighlightRule] | None = None, dark: bool = False):
        self._rules: list[HighlightRule] = []
        self._compiled: list[_CompiledRule] = []
        self._dark = dark
        self._styles: list[RuleStyle] = []
        self.set_rules(rules or [])

    # ------------------------------------------------------------ paramétrage

    def set_rules(self, rules: list[HighlightRule]) -> None:
        self._rules = list(rules)
        self._compiled = [_CompiledRule(r) for r in self._rules if r.enabled]
        self._refresh_styles()

    def set_dark(self, dark: bool) -> None:
        if dark != self._dark:
            self._dark = dark
            self._refresh_styles()

    def _refresh_styles(self) -> None:
        self._styles = [rule_style(c.rule.color, self._dark) for c in self._compiled]

    @property
    def is_dark(self) -> bool:
        return self._dark

    @property
    def active_rules(self) -> list[HighlightRule]:
        return [c.rule for c in self._compiled]

    # ---------------------------------------------------------------- calcul

    def match_index(self, entry) -> int:
        """Indice de la première règle active qui s'applique, ``-1`` sinon.

        L'ordre des règles fait foi : la première qui correspond l'emporte, ce
        qui permet à l'utilisateur de placer « Erreurs » avant « Succès » pour
        qu'une ligne contenant les deux soit signalée comme une erreur.
        """
        message = None
        for index, compiled in enumerate(self._compiled):
            if compiled.pattern is None:
                continue
            if compiled.use_message_only:
                if message is None:
                    message = entry.message.lower()
                haystack = message
            else:
                haystack = entry.search_text
            if compiled.pattern.search(haystack):
                return index
        return -1

    def style_at(self, index: int) -> RuleStyle | None:
        """Style correspondant à un indice renvoyé par :meth:`match_index`."""
        if 0 <= index < len(self._styles):
            return self._styles[index]
        return None

    def rule_at(self, index: int) -> HighlightRule | None:
        if 0 <= index < len(self._compiled):
            return self._compiled[index].rule
        return None

    def apply(self, entries) -> None:
        """Recalcule l'indice de règle de chaque entrée, sur place."""
        for entry in entries:
            entry.highlight_index = self.match_index(entry)
