"""Métadonnées du projet — ``IHM_<nom>.optix`` et ``IDEVersion.txt``.

Le ``.optix`` porte un bloc ``Statistics:`` (``TotalNodeCount``, ``Objects``, ``ObjectTypes``…)
**purement informatif et recalculé par l'IDE à l'ouverture**. Il ne sert jamais de critère de
comparaison : deux ``.optix`` qui ne diffèrent que par leurs statistiques sont réputés équivalents.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

_KV_RE = re.compile(rb"^( *)([A-Za-z]+): ?(.*)$")

STAT_KEYS = ("TotalNodeCount", "Objects", "ObjectTypes", "Variables", "Methods", "References", "Files")


@dataclass(slots=True)
class OptixMeta:
    name: str = ""
    guid: str = ""
    product_version: str = ""
    statistics: dict[str, int] = field(default_factory=dict)
    nodes_root: str = ""
    stats_start: int = -1  # ligne ``Statistics:`` (0-based), -1 si absente
    stats_end: int = -1


def parse_optix(lines: Sequence[bytes]) -> OptixMeta:
    """Lit l'en-tête, les statistiques et le pointeur racine d'un ``.optix``."""
    meta = OptixMeta()
    in_stats = False
    stats_indent = -1
    for line_no, line in enumerate(lines):
        match = _KV_RE.match(line)
        if in_stats:
            if match and len(match.group(1)) > stats_indent:
                try:
                    meta.statistics[match.group(2).decode()] = int(match.group(3).strip() or 0)
                except ValueError:
                    pass
                continue
            in_stats = False
            meta.stats_end = line_no
        if match is None:
            if line.lstrip().startswith(b"- File:") and not meta.nodes_root:
                meta.nodes_root = line.split(b"- File:", 1)[1].strip().strip(b"'\"").decode("utf-8", "replace")
            continue
        indent, key, value = len(match.group(1)), match.group(2), match.group(3).strip()
        if key == b"Statistics":
            in_stats = True
            stats_indent = indent
            meta.stats_start = line_no
        elif key == b"Name" and indent == 1 and not meta.name:
            meta.name = value.decode("utf-8", "replace")
        elif key == b"GUID" and not meta.guid:
            meta.guid = value.decode("ascii", "replace")
        elif key == b"ProductVersion":
            meta.product_version = value.decode("ascii", "replace")
    if in_stats:
        meta.stats_end = len(lines)
    return meta


def lines_without_statistics(lines: Sequence[bytes]) -> list[bytes]:
    meta = parse_optix(lines)
    if meta.stats_start < 0:
        return list(lines)
    return list(lines[: meta.stats_start]) + list(lines[meta.stats_end :])


@dataclass(slots=True)
class OptixDelta:
    projet: OptixMeta
    runtime: OptixMeta
    seulement_statistiques: bool

    def stats_rows(self) -> list[tuple[str, int | None, int | None]]:
        """``(clé, projet, runtime)`` pour chaque statistique connue, dans l'ordre canonique."""
        keys = list(STAT_KEYS) + sorted(
            (set(self.projet.statistics) | set(self.runtime.statistics)) - set(STAT_KEYS)
        )
        return [(k, self.projet.statistics.get(k), self.runtime.statistics.get(k)) for k in keys]


def compare_optix(projet_lines: Sequence[bytes], runtime_lines: Sequence[bytes]) -> OptixDelta:
    """Compare deux ``.optix`` en ignorant le bloc ``Statistics``."""
    projet = parse_optix(projet_lines)
    runtime = parse_optix(runtime_lines)
    same_outside = lines_without_statistics(projet_lines) == lines_without_statistics(runtime_lines)
    return OptixDelta(projet=projet, runtime=runtime, seulement_statistiques=same_outside)


def parse_ide_version(raw: bytes | str) -> str:
    """``1.3.2.9-Stable`` → chaîne nettoyée."""
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    return text.strip().lstrip("﻿")


def versions_compatibles(projet: str | None, runtime: str | None) -> bool:
    return bool(projet) and projet == runtime


def copy_statistics(projet_lines: Sequence[bytes], runtime_lines: Sequence[bytes]) -> list[bytes]:
    """Recopie le bloc ``Statistics`` du runtime dans le ``.optix`` du projet (cosmétique, optionnel)."""
    projet = parse_optix(projet_lines)
    runtime = parse_optix(runtime_lines)
    if projet.stats_start < 0 or runtime.stats_start < 0:
        return list(projet_lines)
    return (
        list(projet_lines[: projet.stats_start])
        + list(runtime_lines[runtime.stats_start : runtime.stats_end])
        + list(projet_lines[projet.stats_end :])
    )
