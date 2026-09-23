"""Recherche plein texte dans les deux modèles (phase 4).

On parcourt les fichiers texte de l'inventaire (YAML du modèle, XML, C#…) côté runtime et côté
projet, en binaire, et l'on renvoie les lignes qui contiennent le motif. Long sur 60 Mo :
à lancer dans un thread de travail, avec progression et annulation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .lines import split_lines
from .progress import CancelCheck, ProgressCallback, check_cancel, report
from .scan import Inventory

MAX_HITS = 5000


@dataclass(slots=True)
class SearchHit:
    side: str  # "runtime" | "projet"
    rel: str
    line_no: int  # 1-based
    text: str


def compile_pattern(motif: str, regex: bool = False, casse: bool = False) -> re.Pattern[bytes]:
    """Le motif en expression binaire ; sans ``regex`` le motif est littéral."""
    flags = 0 if casse else re.IGNORECASE
    source = motif if regex else re.escape(motif)
    return re.compile(source.encode("utf-8"), flags)


def search_inventory(
    inventory: Inventory,
    motif: str,
    regex: bool = False,
    casse: bool = False,
    sides: tuple[str, ...] = ("runtime", "projet"),
    only_nodes: bool = True,
    progress: ProgressCallback | None = None,
    cancel: CancelCheck | None = None,
) -> list[SearchHit]:
    """Cherche ``motif`` dans les fichiers texte des deux arbres. ``only_nodes`` limite à ``Nodes/``."""
    if not motif:
        return []
    pattern = compile_pattern(motif, regex, casse)
    targets: list[tuple[str, str, Path]] = []
    for entry in inventory.entries:
        if not entry.is_text and not entry.is_yaml:
            continue
        if only_nodes and not entry.rel.startswith("Nodes/"):
            continue
        if entry.status in ("identique", "different", "runtime_seul") and "runtime" in sides:
            targets.append(("runtime", entry.rel, inventory.runtime_path(entry.rel)))
        if entry.status in ("identique", "different", "projet_seul") and "projet" in sides:
            targets.append(("projet", entry.rel, inventory.projet_path(entry.rel)))
    hits: list[SearchHit] = []
    total = len(targets)
    for index, (side, rel, path) in enumerate(targets):
        check_cancel(cancel)
        report(progress, "recherche", f"{side} : {rel}", index, total)
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if pattern.search(raw) is None:
            continue
        for line_no, line in enumerate(split_lines(raw).lines, start=1):
            if pattern.search(line):
                hits.append(SearchHit(side, rel, line_no, line.decode("utf-8", "replace").strip()[:300]))
                if len(hits) >= MAX_HITS:
                    report(progress, "recherche", "", total, total)
                    return hits
    report(progress, "recherche", "", total, total)
    return hits
