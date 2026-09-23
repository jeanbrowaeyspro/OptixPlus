"""Index des nœuds d'un fichier YAML FactoryTalk Optix, par une passe ligne à ligne sur les octets.

Sans PyYAML ni décodage du fichier : chaque ligne ``- Name:`` ouvre un nœud (l'indentation
donne la profondeur), chaque ``- File:`` un nœud défini dans un autre fichier. Fonctionne
aussi sur un contenu fusionné en mémoire ou un YAML imparfait.

Structure d'un nœud YAML Optix::

    - Name: IType_03_Work            ← début de nœud, indentation k
      Id: g=496e0cee…                ← propriétés à k+2
      Type: BaseDataVariableType
      Children:
      - Name: Enabled                ← enfants à k+2 également
    - File: 03_Work/03_Work.yaml     ← nœud défini dans un autre fichier

Le nœud racine du fichier est ``Name: X`` sans tiret, à l'indentation 0, et ses enfants sont
eux aussi à l'indentation 0 : on lui attribue une indentation effective de −2.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, field

NODE_RE = re.compile(rb"^( *)(- )?(Name|File): ?(.*)$")
PROPERTY_RE = re.compile(rb"^( *)([A-Za-z_][A-Za-z0-9_]*): ?(.*)$")



def indent_of(line: bytes) -> int:
    """Nombre d'espaces de tête. Une ligne vide compte comme infiniment indentée (continuation)."""
    stripped = line.lstrip(b" ")
    if not stripped.strip():
        return 1 << 30
    return len(line) - len(stripped)


def unquote(value: bytes) -> str:
    text = value.strip().decode("utf-8", errors="replace")
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        return text[1:-1]
    return text


@dataclass(slots=True)
class NodeRef:
    """Un nœud repéré dans le fichier : sa ligne de début, sa fin (exclusive), son nom, son chemin."""

    line: int
    end: int
    indent: int
    name: str
    path: str
    kind: str = "node"  # "node" | "file" | "root"

    @property
    def nb_lignes(self) -> int:
        return self.end - self.line

    @property
    def parent_path(self) -> str:
        return self.path.rsplit("/", 1)[0] if "/" in self.path else ""


@dataclass(slots=True)
class NodeIndex:
    """Index des nœuds d'un fichier YAML Optix et, pour chaque ligne, le nœud le plus interne."""

    lines: Sequence[bytes]
    nodes: list[NodeRef] = field(default_factory=list)
    owner: list[int] = field(default_factory=list)  # index dans ``nodes`` ou -1
    indents: list[int] = field(default_factory=list)  # indentation de chaque ligne
    _start_cache: list[int] = field(default_factory=list, repr=False)

    def node_at(self, line_no: int) -> NodeRef | None:
        """Le nœud défini exactement à cette ligne, s'il y en a un."""
        if 0 <= line_no < len(self.owner):
            idx = self.owner[line_no]
            if idx >= 0 and self.nodes[idx].line == line_no:
                return self.nodes[idx]
        return None

    def enclosing(self, line_no: int) -> NodeRef | None:
        """Le nœud le plus interne qui contient cette ligne."""
        if 0 <= line_no < len(self.owner):
            idx = self.owner[line_no]
            if idx >= 0:
                return self.nodes[idx]
        return None

    def properties(self, node: NodeRef) -> dict[str, str]:
        """Les propriétés directes d'un nœud (``Type``, ``DataType``, ``Value``…), sans ses enfants."""
        props: dict[str, str] = {}
        prop_indent = node.indent + 2
        indents = self.indents
        for line_no in range(node.line + 1, node.end):
            if indents[line_no] != prop_indent:
                continue
            line = self.lines[line_no]
            match = PROPERTY_RE.match(line)
            if match is None:
                continue
            if NODE_RE.match(line):
                break  # premier enfant : fin des propriétés directes
            key = match.group(2).decode("ascii")
            if key == "Children":
                continue
            props[key] = unquote(match.group(3))
        return props

    def children(self, node: NodeRef) -> list[NodeRef]:
        """Les nœuds enfants directs. Les nœuds sont triés par ligne : on part du nœud lui-même."""
        child_indent = node.indent + 2
        nodes = self.nodes
        k = bisect_right(self._starts(), node.line)
        result: list[NodeRef] = []
        while k < len(nodes) and nodes[k].line < node.end:
            if nodes[k].indent == child_indent:
                result.append(nodes[k])
            k += 1
        return result

    def _starts(self) -> list[int]:
        if len(self._start_cache) != len(self.nodes):
            self._start_cache = [n.line for n in self.nodes]
        return self._start_cache

    def child_value(self, node: NodeRef, child_name: str) -> str | None:
        """La ``Value`` d'un enfant nommé, ex. le ``SymbolName`` d'un tag CoDeSys."""
        for child in self.children(node):
            if child.name == child_name:
                return self.properties(child).get("Value")
        return None

    def file_refs(self) -> list[NodeRef]:
        return [n for n in self.nodes if n.kind == "file"]


def index_nodes(lines: Sequence[bytes]) -> NodeIndex:
    """Construit l'index des nœuds d'un fichier YAML Optix."""
    index = NodeIndex(lines=lines)
    nodes = index.nodes
    owner = index.owner
    open_stack: list[int] = []  # indices de nœuds encore ouverts
    path_stack: list[str] = []

    indents = index.indents
    for line_no, line in enumerate(lines):
        indent = indent_of(line)
        indents.append(indent)
        match = NODE_RE.match(line)
        if indent != (1 << 30):
            while open_stack and nodes[open_stack[-1]].indent >= indent:
                nodes[open_stack.pop()].end = line_no
                path_stack.pop()
        if match is not None:
            spaces, dash, key, value = match.groups()
            effective = len(spaces) if dash else len(spaces) - 2
            while open_stack and nodes[open_stack[-1]].indent >= effective:
                nodes[open_stack.pop()].end = line_no
                path_stack.pop()
            name = unquote(value)
            kind = "file" if key == b"File" else ("root" if not dash else "node")
            path_stack.append(name)
            node = NodeRef(
                line=line_no,
                end=len(lines),
                indent=effective,
                name=name,
                path="/".join(path_stack),
                kind=kind,
            )
            nodes.append(node)
            open_stack.append(len(nodes) - 1)
        owner.append(open_stack[-1] if open_stack else -1)
    return index
