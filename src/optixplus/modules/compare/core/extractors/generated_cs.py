"""Fichiers C# auto-générés — ``TypeConstants.cs`` et ``UITypeDefinitions.cs``.

- ``TypeConstants.cs`` : une ligne ``NodeId <Nom> = new NodeId(…, new Guid("<guid>"))`` par type ;
- ``UITypeDefinitions.cs`` : un bloc ``[MapType(… Guid = "<guid>")] public class <Nom> : <Base> { }`` par type.

Ils portent ``WARNING: AUTO-GENERATED CODE, DO NOT EDIT!`` et l'IDE les régénère. On s'en sert
ici pour **résoudre les GUID en noms** (vue « Types utilisateur ») et, en phase 2, pour les élaguer
par GUID afin de garder un état cohérent jusqu'à la prochaine ouverture de l'IDE.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

_CONSTANT_RE = re.compile(rb'NodeId\s+(\w+)\s*=\s*new NodeId\([^)]*new Guid\("([0-9a-fA-F]{32})"\)\)')
_MAPTYPE_RE = re.compile(rb'\[MapType\([^\]]*Guid\s*=\s*"([0-9a-fA-F]{32})"[^\]]*\)\]')
_CLASS_RE = re.compile(rb"^\s*public\s+(?:partial\s+)?class\s+(\w+)\s*(?::\s*([\w.]+))?")


@dataclass(slots=True)
class TypeConstant:
    name: str
    guid: str
    line: int


def parse_type_constants(lines: Sequence[bytes]) -> list[TypeConstant]:
    """Les constantes ``NodeId`` de ``TypeConstants.cs``."""
    result: list[TypeConstant] = []
    for line_no, line in enumerate(lines):
        match = _CONSTANT_RE.search(line)
        if match:
            result.append(TypeConstant(match.group(1).decode(), match.group(2).decode().lower(), line_no))
    return result


def guid_to_name(lines: Sequence[bytes]) -> dict[str, str]:
    """Table GUID → nom de type, à partir de ``TypeConstants.cs``."""
    return {c.guid: c.name for c in parse_type_constants(lines)}


@dataclass(slots=True)
class ClassBlock:
    """Un bloc ``[MapType] public class X : Base { … }`` : lignes ``start`` à ``end`` (exclusive)."""

    name: str
    guid: str
    base: str
    start: int
    end: int


def parse_ui_type_definitions(lines: Sequence[bytes]) -> list[ClassBlock]:
    """Les classes de ``UITypeDefinitions.cs`` avec leurs bornes de lignes (attribut inclus)."""
    blocks: list[ClassBlock] = []
    i = 0
    n = len(lines)
    while i < n:
        attr = _MAPTYPE_RE.search(lines[i])
        if attr is None:
            i += 1
            continue
        start = i
        guid = attr.group(1).decode().lower()
        j = i + 1
        name = base = ""
        while j < n:
            cls = _CLASS_RE.match(lines[j])
            if cls:
                name = cls.group(1).decode()
                base = (cls.group(2) or b"").decode()
                break
            j += 1
        depth = 0
        opened = False
        k = j
        while k < n:
            depth += lines[k].count(b"{") - lines[k].count(b"}")
            if b"{" in lines[k]:
                opened = True
            k += 1
            if opened and depth <= 0:
                break
        blocks.append(ClassBlock(name=name, guid=guid, base=base, start=start, end=k))
        i = k
    return blocks


def braces_balanced(lines: Iterable[bytes]) -> bool:
    depth = 0
    for line in lines:
        depth += line.count(b"{") - line.count(b"}")
        if depth < 0:
            return False
    return depth == 0


def prune_type_constants(lines: Sequence[bytes], guids: Iterable[str]) -> list[bytes]:
    """Retire les lignes ``NodeId`` dont le GUID est dans ``guids``. Jamais par nom."""
    targets = {g.lower() for g in guids}
    doomed = {c.line for c in parse_type_constants(lines) if c.guid in targets}
    return [line for k, line in enumerate(lines) if k not in doomed]


def prune_ui_type_definitions(lines: Sequence[bytes], guids: Iterable[str]) -> list[bytes]:
    """Retire les blocs de classe dont le GUID est dans ``guids``, avec la ligne vide qui les suit."""
    targets = {g.lower() for g in guids}
    doomed: set[int] = set()
    for block in parse_ui_type_definitions(lines):
        if block.guid in targets:
            doomed.update(range(block.start, block.end))
            if block.end < len(lines) and not lines[block.end].strip():
                doomed.add(block.end)
    return [line for k, line in enumerate(lines) if k not in doomed]
