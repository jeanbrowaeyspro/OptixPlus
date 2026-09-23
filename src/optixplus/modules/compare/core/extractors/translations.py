"""Traductions — ``Nodes/Translations/Translations.yaml``.

Le nœud ``TranslationTable`` (``LocalizationDictionary``) porte une ``Value`` JSON :
``"Dimensions": [<nb_lignes>, <nb_colonnes>]`` puis un ``Body`` plat de
``nb_lignes × nb_colonnes`` chaînes. La première ligne est l'en-tête (``"", "en-US", …``),
la première colonne de chaque ligne est la clé. Ajouter une ligne impose d'incrémenter
``Dimensions[0]`` : un décompte faux casse le chargement.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from ..nodes import NodeIndex, NodeRef, index_nodes, indent_of

log = logging.getLogger(__name__)


@dataclass(slots=True)
class TranslationTable:
    """Le dictionnaire de localisation décodé."""

    node: str
    dimensions: tuple[int, int]
    header: list[str]
    rows: list[list[str]]
    value_start: int  # première ligne du bloc JSON (0-based)
    value_end: int  # ligne suivant le bloc (exclusive)

    @property
    def coherent(self) -> bool:
        """Vrai si ``Dimensions`` correspond au contenu réel du ``Body``."""
        return self.dimensions[0] == len(self.rows) + 1 and all(len(r) == self.dimensions[1] for r in self.rows)

    def by_key(self) -> dict[str, list[str]]:
        return {row[0]: row for row in self.rows if row}


def _value_block(index: NodeIndex, node: NodeRef) -> tuple[int, int] | None:
    prop_indent = node.indent + 2
    for line_no in range(node.line + 1, node.end):
        line = index.lines[line_no]
        if indent_of(line) == prop_indent and line.lstrip().startswith(b"Value:"):
            end = line_no + 1
            while end < node.end and indent_of(index.lines[end]) > prop_indent:
                end += 1
            return line_no + 1, end
    return None


def parse_translations(lines: Sequence[bytes]) -> TranslationTable | None:
    """Décode le premier ``LocalizationDictionary`` du fichier, ou ``None`` s'il n'y en a pas."""
    index = index_nodes(lines)
    for node in index.nodes:
        if index.properties(node).get("Type") != "LocalizationDictionary":
            continue
        block = _value_block(index, node)
        if block is None:
            continue
        start, end = block
        raw = b"\n".join(lines[start:end]).decode("utf-8", errors="replace")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            log.warning("Dictionnaire de traductions illisible dans %s : %s", node.path, exc)
            return None
        dims = value.get("Dimensions", [0, 0])
        body: list[str] = value.get("Body", [])
        n_rows, n_cols = int(dims[0]), int(dims[1])
        if n_cols <= 0:
            return None
        grid = [body[i : i + n_cols] for i in range(0, len(body), n_cols)]
        header = grid[0] if grid else []
        return TranslationTable(
            node=node.path,
            dimensions=(n_rows, n_cols),
            header=header,
            rows=grid[1:],
            value_start=start,
            value_end=end,
        )
    return None


@dataclass(slots=True)
class TranslationsDelta:
    """Écarts entre les deux dictionnaires."""

    projet: TranslationTable | None
    runtime: TranslationTable | None
    runtime_seul: list[list[str]] = field(default_factory=list)
    projet_seul: list[list[str]] = field(default_factory=list)
    modifies: list[tuple[list[str], list[str]]] = field(default_factory=list)  # (projet, runtime)
    nb_communs: int = 0

    @property
    def dimensions_projet(self) -> tuple[int, int] | None:
        return self.projet.dimensions if self.projet else None

    @property
    def dimensions_runtime(self) -> tuple[int, int] | None:
        return self.runtime.dimensions if self.runtime else None


def compare_translations(projet_lines: Sequence[bytes], runtime_lines: Sequence[bytes]) -> TranslationsDelta:
    """Compare les lignes des deux dictionnaires par clé (première colonne)."""
    projet = parse_translations(projet_lines)
    runtime = parse_translations(runtime_lines)
    delta = TranslationsDelta(projet=projet, runtime=runtime)
    if projet is None or runtime is None:
        return delta
    p_rows = projet.by_key()
    r_rows = runtime.by_key()
    for key, row in r_rows.items():
        if key not in p_rows:
            delta.runtime_seul.append(row)
        elif p_rows[key] != row:
            delta.modifies.append((p_rows[key], row))
        else:
            delta.nb_communs += 1
    for key, row in p_rows.items():
        if key not in r_rows:
            delta.projet_seul.append(row)
    return delta


_DIMENSIONS_LINE = re.compile(rb'^(\s*"Dimensions": \[)(\d+)(,\s*\d+\],?\s*)$')


def fix_dimensions(lines: Sequence[bytes]) -> tuple[list[bytes], tuple[int, int] | None]:
    """Recalcule ``Dimensions[0]`` à partir du ``Body`` réel. Retourne les lignes et ``(avant, après)`` si changé.

    Action dérivée obligatoire après tout ajout ou retrait de ligne de traduction : un décompte
    faux casse le chargement du dictionnaire.
    """
    result = list(lines)
    table = parse_translations(result)
    if table is None:
        return result, None
    attendu = len(table.rows) + 1
    if table.dimensions[0] == attendu:
        return result, None
    for line_no in range(table.value_start, table.value_end):
        match = _DIMENSIONS_LINE.match(result[line_no])
        if match:
            avant = int(match.group(2))
            result[line_no] = match.group(1) + str(attendu).encode() + match.group(3)
            return result, (avant, attendu)
    return result, None
