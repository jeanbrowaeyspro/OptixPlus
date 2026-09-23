"""Nouveautés : lecture du ``CHANGELOG.md`` embarqué, découpé par version.

Sans Qt. Format « Keep a Changelog » : une section ``## [X.Y.Z] - date`` par version, et
``## [Non publié]`` pour ce qui n'est pas encore sorti.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from ..common import paths
from .github import Version

log = logging.getLogger("optixplus.update")

_HEADING = re.compile(r"^##\s+\[(?P<title>[^\]]+)\](?:\s*[-–—]\s*(?P<date>.+))?\s*$")


@dataclass(frozen=True)
class Section:
    title: str  # « 1.2.0 » ou « Non publié »
    date: str
    body: str

    @property
    def version(self) -> Version | None:
        try:
            return Version.parse(self.title)
        except ValueError:
            return None

    def markdown(self) -> str:
        heading = f"## {self.title}" + (f" — {self.date}" if self.date else "")
        return f"{heading}\n\n{self.body.strip()}\n"


def changelog_path() -> Path | None:
    """Le CHANGELOG embarqué dans l'exécutable, ou celui du dépôt en exécution depuis les sources."""
    for candidate in (paths.resource_path("CHANGELOG.md"), paths.PACKAGE_DIR.parent.parent / "CHANGELOG.md"):
        if candidate.is_file():
            return candidate
    return None


def parse(text: str) -> list[Section]:
    """Sections dans l'ordre du fichier (la plus récente d'abord)."""
    sections: list[Section] = []
    title = date = None
    body: list[str] = []
    for line in text.splitlines():
        match = _HEADING.match(line)
        if match:
            if title is not None:
                sections.append(Section(title, date or "", "\n".join(body)))
            title, date, body = match.group("title").strip(), (match.group("date") or "").strip(), []
        elif title is not None:
            body.append(line)
    if title is not None:
        sections.append(Section(title, date or "", "\n".join(body)))
    return sections


def load() -> list[Section]:
    path = changelog_path()
    if path is None:
        log.warning("CHANGELOG.md introuvable : Nouveautés vides")
        return []
    try:
        return parse(path.read_text(encoding="utf-8"))
    except OSError as exc:
        log.warning("Lecture de %s impossible : %s", path, exc)
        return []


def news_since(sections: list[Section], last_seen: str, current: str) -> list[Section]:
    """Sections publiées après ``last_seen`` et jusqu'à ``current`` incluse.

    Sans version connue (premier lancement), seule la section de la version courante.
    Une version sans section (exécution depuis les sources) donne la section « non publiée ».
    """
    try:
        now = Version.parse(current)
    except ValueError:
        return []
    try:
        seen = Version.parse(last_seen) if last_seen else None
    except ValueError:
        seen = None
    chosen = [
        s for s in sections
        if s.version is not None and s.version <= now and (s.version > seen if seen else s.version == now)
    ]
    if not chosen:
        chosen = [s for s in sections if s.version is None][:1]
    return chosen
