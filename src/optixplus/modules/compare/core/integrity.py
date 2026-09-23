"""Contrôle d'intégrité : références orphelines, accolades, YAML non référencés.

Après un retrait de blocs ou de types, une référence restante vers un nœud ou un type disparu
est une régression. On cherche les noms retirés, en mots entiers, dans tout le modèle
(``Nodes/**/*.yaml``), les sources .NET et ``UserDefinedModule.xml``. Le contenu peut être
fourni en mémoire (``overrides``) pour contrôler un état *avant* écriture.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from ....common.i18n import tr
from .extractors.generated_cs import braces_balanced
from .lines import split_lines

MAX_HITS_PAR_NOM = 20


@dataclass(slots=True)
class Reference:
    rel: str
    line_no: int  # 1-based
    name: str
    text: str


def _candidate_files(root: Path) -> list[str]:
    rels: list[str] = []
    for base in ("Nodes", "ProjectFiles/NetSolution", "ProjectFiles"):
        folder = root / base
        if not folder.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(folder):
            dirnames[:] = [d for d in dirnames if d not in ("bin", "obj", ".vs", ".vscode")]
            for name in filenames:
                rel = (Path(dirpath) / name).relative_to(root).as_posix()
                if base == "ProjectFiles" and not rel.endswith("UserDefinedModule.xml"):
                    continue
                if base == "ProjectFiles/NetSolution" and not rel.endswith(".cs"):
                    continue
                if base == "Nodes" and not rel.lower().endswith((".yaml", ".yml")):
                    continue
                rels.append(rel)
    return sorted(set(rels))


def find_references(
    root: Path | str,
    names: Iterable[str],
    overrides: Mapping[str, bytes] | None = None,
    ignore: Mapping[str, Iterable[int]] | None = None,
) -> list[Reference]:
    """Occurrences (mots entiers) de ``names`` dans le modèle du projet.

    ``overrides`` : contenu à utiliser à la place du disque (état prévisualisé).
    ``ignore`` : par fichier, numéros de ligne (1-based) à ne pas signaler.
    """
    root = Path(root)
    targets = sorted({n for n in names if n and len(n) >= 3}, key=len, reverse=True)
    if not targets:
        return []
    pattern = re.compile(rb"(?<![A-Za-z0-9_])(" + b"|".join(re.escape(n.encode()) for n in targets) + rb")(?![A-Za-z0-9_])")
    overrides = dict(overrides or {})
    ignore = {k: set(v) for k, v in (ignore or {}).items()}
    hits: list[Reference] = []
    counts: dict[str, int] = {}
    rels = _candidate_files(root)
    for rel in overrides:
        if rel not in rels:
            rels.append(rel)
    for rel in rels:
        raw = overrides.get(rel)
        if raw is None:
            try:
                raw = (root / rel).read_bytes()
            except OSError:
                continue
        if pattern.search(raw) is None:
            continue
        skip = ignore.get(rel, set())
        for line_no, line in enumerate(split_lines(raw).lines, start=1):
            if line_no in skip:
                continue
            for match in pattern.finditer(line):
                name = match.group(1).decode()
                counts[name] = counts.get(name, 0) + 1
                if counts[name] <= MAX_HITS_PAR_NOM:
                    hits.append(Reference(rel, line_no, name, line.decode("utf-8", "replace").strip()[:200]))
    return hits


def check_braces(rel: str, raw: bytes) -> str | None:
    """Message d'erreur si un fichier C# a des accolades déséquilibrées, sinon ``None``."""
    if not rel.endswith(".cs"):
        return None
    if braces_balanced(split_lines(raw).lines):
        return None
    return tr("{file}: unbalanced braces after pruning").format(file=rel)
