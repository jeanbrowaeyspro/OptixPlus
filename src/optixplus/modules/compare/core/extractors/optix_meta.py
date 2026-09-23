"""Métadonnées du projet — ``IHM_<nom>.optix`` et ``IDEVersion.txt``.

Le ``.optix`` porte un bloc ``Statistics:`` (``TotalNodeCount``, ``Objects``, ``ObjectTypes``…)
**purement informatif et recalculé par l'IDE à l'ouverture**. Il ne sert jamais de critère de
comparaison : deux ``.optix`` qui ne diffèrent que par leurs statistiques sont réputés équivalents.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .....common.optix.project import STAT_KEYS, OptixMeta, parse_optix  # noqa: F401

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
