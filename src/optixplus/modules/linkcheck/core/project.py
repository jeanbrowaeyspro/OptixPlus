"""Contrôle de liens : recherche des liens dynamiques cassés d'un projet FT Optix.

Le chargement de l'arbre (``Node``, ``OptixProject``) est dans ``common.optix.model`` ;
ce module y ajoute ce qui est propre aux liens (suggestions, ``find_broken_links``) et
ré-exporte les noms du modèle pour les appelants existants.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from ....common.i18n import tr
from ....common.optix import model
from ....common.optix.model import (  # noqa: F401
    _INDEX_PREFIX,
    POINTER_DATATYPES,
    POINTER_TYPES,
    REASON_ABOVE_ROOT,
    REASON_MISSING,
    SKIP_ALIAS,
    SKIP_BUILTIN,
    SKIP_POINTER,
    Node,
)
from ....common.optix.project import ProjectError, project_folder, read_project_meta  # noqa: F401
from ....common.progress import CancelCheck, ProgressCallback, check_cancel, report

BUILTIN_PROJECT_ROOTS = ("Server", "Users", "RetainedAlarms", "Commands")

# Raison propre au Contrôle de liens (codes stables ; le libellé est traduit à l'affichage).
REASON_FOREIGN = "foreign"  # vise un autre projet


@dataclass
class BrokenLink:
    file: str  # YAML (chemin absolu)
    line: int  # ligne de la Value du DynamicLink (1-based)
    block_start: int  # ligne du « - Name: DynamicLink » (1-based)
    block_end: int  # ligne exclusive de fin du bloc
    owner_path: str  # chemin Studio de la variable qui porte le lien
    prop: str  # nom de la propriété liée
    target: str  # cible telle qu'écrite
    reason: str  # REASON_*
    detail: str  # segment introuvable, ou nom du projet étranger
    screen: str  # écran ou zone
    suggestions: list[str] = field(default_factory=list)


@dataclass
class LinkStats:
    resolved: int = 0
    alias: int = 0
    pointer: int = 0
    builtin: int = 0

    @property
    def unverifiable(self) -> int:
        return self.alias + self.pointer


def reason_label(link: BrokenLink) -> str:
    """Libellé traduit de la raison d'un lien cassé."""
    if link.reason == REASON_FOREIGN:
        return tr("Points to another project: {name}").format(name=link.detail)
    if link.reason == REASON_ABOVE_ROOT:
        return tr("Goes above the root")
    return tr("Segment not found: {segment}").format(segment=link.detail)


class OptixProject(model.OptixProject):
    """Projet Optix avec la recherche de liens cassés (``load()`` vient du modèle commun)."""

    def foreign_project_prefix(self, target: str) -> str | None:
        """Nom du projet étranger si le chemin absolu vise un autre projet, sinon None."""
        match = re.match(r"^/Objects/([^/]+)/", target)
        if match and match.group(1) != self.name and match.group(1) not in BUILTIN_PROJECT_ROOTS:
            return match.group(1)
        return None

    def suggest(self, target: str, origin: Node | None, limit: int = 3) -> list[str]:
        """Candidats portant le même nom que le dernier segment de la cible, du plus au moins probable."""
        last = target.rstrip("/").split("/")[-1].split("@")[0]
        last = re.sub(r"\[\d+\]$", "", _INDEX_PREFIX.sub("", last))
        candidates = self.by_name.get(last, [])
        if not candidates:
            return []
        wanted = [s.split("@")[0] for s in target.strip("/").split("/") if s not in ("..", ".", "")]
        origin_path = origin.path() if origin is not None else ""
        scored = []
        for candidate in candidates:
            path = candidate.path()
            have = path.strip("/").split("/")
            k = 0  # segments communs en partant de la fin
            while k < min(len(wanted), len(have)) and wanted[-1 - k] == have[-1 - k]:
                k += 1
            bonus = os.path.commonprefix([origin_path, path]).count("/") / 100.0 if origin_path else 0.0
            scored.append((k + bonus, path, candidate))
        scored.sort(key=lambda s: -s[0])
        chosen, seen = [], set()
        for _score, path, candidate in scored:
            if path not in seen:
                seen.add(path)
                chosen.append(candidate)
            if len(chosen) >= limit:
                break
        # Même forme que le lien d'origine : relatif s'il l'était, absolu sinon.
        if target.startswith("/") or origin is None:
            return [c.path() for c in chosen]
        return [self.relative_path(origin, c) for c in chosen]

    def find_broken_links(
        self, progress: ProgressCallback | None = None, cancel: CancelCheck | None = None
    ) -> tuple[list[BrokenLink], LinkStats]:
        broken: list[BrokenLink] = []
        stats = LinkStats()
        total = len(self.all_nodes)
        phase = tr("Checking links")
        for i, node in enumerate(self.all_nodes):
            if i % 5000 == 0:
                check_cancel(cancel)
                report(progress, phase, "", i, total)
            if node.type != "DynamicLink" or not isinstance(node.value, str) or node.parent is None:
                continue
            origin = node.parent
            target, code, detail = self.resolve(node.value, origin)
            if target is not None:
                stats.resolved += 1
                continue
            if code == SKIP_ALIAS:
                stats.alias += 1
                continue
            if code == SKIP_POINTER:
                stats.pointer += 1
                continue
            if code == SKIP_BUILTIN:
                stats.builtin += 1
                continue
            foreign = self.foreign_project_prefix(node.value)
            if foreign:
                code, detail = REASON_FOREIGN, foreign
            broken.append(
                BrokenLink(
                    file=node.file or "",
                    line=node.value_line,
                    block_start=node.line,
                    block_end=node.end_line,
                    owner_path=origin.studio_path(self.name),
                    prop=origin.name,
                    target=node.value,
                    reason=code,
                    detail=detail,
                    screen=self.screen_of(origin),
                    suggestions=self.suggest(node.value, origin),
                )
            )
        report(progress, phase, "", total, total)
        broken.sort(key=lambda b: (b.file, b.line))
        return broken, stats


def analyse(folder: str, progress: ProgressCallback | None = None, cancel: CancelCheck | None = None):
    """Charge le projet et cherche les liens cassés : (projet, liens cassés, statistiques)."""
    project = OptixProject(folder).load(progress, cancel)
    broken, stats = project.find_broken_links(progress, cancel)
    return project, broken, stats
