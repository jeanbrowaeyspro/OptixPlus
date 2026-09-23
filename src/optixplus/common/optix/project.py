"""Dossier d'un projet FactoryTalk Optix : reconnaissance, fichier ``.optix``, références ``- File:``.

Commun à Link Checker (arbre complet du projet) et Compare (projet et runtime déployé).
Sans Qt.

Deux règles de reconnaissance coexistent, chacune pour son usage :

- ``is_optix_root`` (Compare) : ``IDEVersion.txt`` et ``Nodes/``, présents dans un projet
  comme dans un runtime déployé ;
- ``project_folder`` (Link Checker) : ``Nodes/``, ou un chemin vers le fichier ``.optix`` ;
  le ``.optix`` est ensuite exigé par ``read_project_meta``.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..i18n import tr

NODES_DIR = "Nodes"
IDE_VERSION_FILE = "IDEVersion.txt"
OPTIX_SUFFIX = ".optix"

Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


class ProjectError(Exception):
    """Dossier qui n'est pas un projet Optix lisible ; le message est prêt à afficher."""


# --------------------------------------------------------------------------- reconnaissance
def is_optix_root(path: Path | str) -> bool:
    """Un dossier est un projet ou un runtime Optix s'il contient ``IDEVersion.txt`` et ``Nodes/``."""
    root = Path(path)
    return (root / IDE_VERSION_FILE).is_file() and (root / NODES_DIR).is_dir()


def suggest_optix_root(path: Path | str) -> Path | None:
    """Le dossier lui-même s'il est un projet Optix, sinon son unique sous-dossier s'il l'est.

    L'utilisateur a pu choisir le dossier parent d'un export.
    """
    root = Path(path)
    if is_optix_root(root):
        return root
    try:
        subdirs = [p for p in root.iterdir() if p.is_dir()]
    except OSError:
        return None
    if len(subdirs) == 1 and is_optix_root(subdirs[0]):
        return subdirs[0]
    return None


def read_ide_version(root: Path | str) -> str | None:
    """Contenu de ``IDEVersion.txt`` (ex. ``1.3.2.9-Stable``), ou ``None`` s'il est absent."""
    path = Path(root) / IDE_VERSION_FILE
    try:
        return path.read_bytes().decode("utf-8", errors="replace").lstrip("﻿").strip() or None
    except OSError:
        return None


def project_folder(path: str) -> str:
    """Dossier du projet à partir d'un dossier ou d'un fichier ``.optix`` (saisie nettoyée)."""
    path = os.path.abspath(path.strip().strip('"'))
    if path.lower().endswith(OPTIX_SUFFIX) and os.path.isfile(path):
        return os.path.dirname(path)
    if not os.path.isdir(os.path.join(path, NODES_DIR)):
        raise ProjectError(tr("No Nodes folder in {folder}: this is not an FT Optix project.").format(folder=path))
    return path


# --------------------------------------------------------------------------- fichier .optix
def read_project_meta(folder: str) -> tuple[str, str]:
    """(nom du projet, YAML racine relatif) lus dans le ``.optix`` du dossier."""
    optix = [f for f in os.listdir(folder) if f.lower().endswith(OPTIX_SUFFIX) and os.path.isfile(os.path.join(folder, f))]
    if not optix:
        raise ProjectError(tr("No .optix file in {folder}").format(folder=folder))
    path = os.path.join(folder, optix[0])
    name, root = "", ""
    try:
        with open(path, encoding="utf-8-sig") as fh:
            data = yaml.load(fh, Loader=Loader)
        project = data.get("Project", {}) if isinstance(data, dict) else {}
        name = str(project.get("Name") or "")
        nodes = project.get("Nodes") or []
        if nodes and isinstance(nodes[0], dict):
            root = str(nodes[0].get("File") or "")
    except (OSError, yaml.YAMLError, AttributeError):
        pass
    if not name:
        # Repli : ligne « Name: » indentée sous « Project: ».
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            for line in fh:
                match = re.match(r"^\s+Name:\s*(.+?)\s*$", line)
                if match:
                    name = match.group(1).strip("'\"")
                    break
    if not name:
        name = os.path.splitext(optix[0])[0]
    return name, root


_KV_RE = re.compile(rb"^( *)([A-Za-z]+): ?(.*)$")

STAT_KEYS = ("TotalNodeCount", "Objects", "ObjectTypes", "Variables", "Methods", "References", "Files")


@dataclass(slots=True)
class OptixMeta:
    """En-tête d'un ``.optix`` lu octet par octet (ne lève jamais)."""

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


# --------------------------------------------------------------------------- références « - File: »
_FILE_ITEM = b"- File:"


def file_references(lines: Iterable[bytes]) -> list[str]:
    """Cibles des lignes ``- File: …`` d'un YAML, relatives à son dossier, en séparateurs ``/``."""
    refs: list[str] = []
    for line in lines:
        stripped = line.lstrip(b" ")
        if stripped.startswith(_FILE_ITEM):
            value = stripped[len(_FILE_ITEM) :].strip().strip(b"'\"")
            refs.append(value.decode("utf-8", "replace").replace("\\", "/"))
    return refs


def join_reference(rel: str, ref: str) -> str:
    """Chemin (relatif à la racine du projet) d'une référence lue dans le fichier ``rel``."""
    base = rel.rsplit("/", 1)[0] if "/" in rel else ""
    return f"{base}/{ref}" if base else ref


def normalize_rel(path: str) -> str:
    """Chemin relatif normalisé en ``/`` ; un ``..`` au-dessus de la racine est ignoré."""
    parts: list[str] = []
    for part in path.replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)
