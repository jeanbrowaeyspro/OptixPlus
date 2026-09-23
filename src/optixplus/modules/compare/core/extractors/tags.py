"""Tags CoDeSys — ``Nodes/CommDrivers/CODESYSDriver/<API>/Tags/Tags.yaml``.

Les tags n'ont pas de ``Id:`` et sont triés alphabétiquement dans leur groupe. La clé métier
est le ``SymbolName`` (chemin de la variable dans l'application CoDeSys, ``App_X.GVL_Y.Var``) :
on indexe par symbole, jamais par position. Une ``TagStructure`` n'a pas de ``SymbolName``
propre : on le déduit de ses membres.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from ..nodes import TAG_TYPES, NodeIndex, NodeRef, index_nodes, structure_symbol


@dataclass(slots=True)
class Tag:
    """Un tag ou une structure CoDeSys, identifié par son symbole."""

    name: str
    path: str
    type: str
    data_type: str
    symbol: str
    array: str = ""
    line: int = 0
    nb_lignes: int = 0
    membres: list[str] = field(default_factory=list)

    @property
    def is_structure(self) -> bool:
        return self.type == "TagStructure"

    @property
    def key(self) -> str:
        return self.symbol

    def signature(self) -> tuple[str, str, str]:
        return (self.type, self.data_type, self.array)


def _tag_from_node(index: NodeIndex, node: NodeRef) -> Tag | None:
    props = index.properties(node)
    node_type = props.get("Type", "")
    if node_type not in TAG_TYPES:
        return None
    symbol = index.child_value(node, "SymbolName")
    if symbol is None and node_type == "TagStructure":
        symbol = structure_symbol(index, node)
    if symbol is None:
        symbol = "chemin:" + node.path
    dims = props.get("ArrayDimensions", "")
    membres = [c.name for c in index.children(node) if c.name != "SymbolName"] if node_type == "TagStructure" else []
    return Tag(
        name=node.name,
        path=node.path,
        type=node_type,
        data_type=props.get("DataType", ""),
        symbol=symbol,
        array=dims.strip("[]") if dims else "",
        line=node.line,
        nb_lignes=node.nb_lignes,
        membres=membres,
    )


def extract_tags(lines: Sequence[bytes]) -> list[Tag]:
    """Tous les tags et structures d'un ``Tags.yaml``, dans l'ordre du fichier."""
    index = index_nodes(lines)
    tags: list[Tag] = []
    for node in index.nodes:
        tag = _tag_from_node(index, node)
        if tag is not None:
            tags.append(tag)
    return tags


def is_tags_file(lines: Sequence[bytes]) -> bool:
    """Vrai si le fichier contient au moins un tag CoDeSys."""
    return any(line.lstrip().startswith(b"Type: CODESYSTag") for line in lines[:5000]) or any(
        line.lstrip().startswith(b"Type: CODESYSTag") for line in lines
    )


@dataclass(slots=True)
class TagRow:
    """Une ligne de la vue « Tags CoDeSys » : les deux côtés confondus, indexés par symbole."""

    symbol: str
    projet: Tag | None
    runtime: Tag | None

    @property
    def etat(self) -> str:
        if self.projet is None:
            return "runtime_seul"
        if self.runtime is None:
            return "projet_seul"
        return "identique" if self.projet.signature() == self.runtime.signature() else "modifie"

    @property
    def ref(self) -> Tag:
        return self.runtime or self.projet  # type: ignore[return-value]

    @property
    def name(self) -> str:
        return self.ref.name


@dataclass(slots=True)
class TagsDelta:
    """Écarts entre les tags du projet et ceux du runtime."""

    rows: list[TagRow]
    runtime_seul: list[Tag]  # blocs de tête seulement (les membres d'une structure ajoutée sont repliés)
    projet_seul: list[Tag]
    modifies: list[TagRow]
    nb_communs: int

    def ecarts(self) -> list[TagRow]:
        return [r for r in self.rows if r.etat != "identique"]


def _parent_symbol(symbol: str) -> str:
    if symbol.endswith("]") and "[" in symbol:
        return symbol[: symbol.rfind("[")]
    return symbol.rsplit(".", 1)[0] if "." in symbol else ""


def _fold(tags: list[Tag]) -> list[Tag]:
    """Ne garde que les tags dont aucun ancêtre n'est lui aussi dans la liste."""
    symbols = {t.symbol for t in tags}
    kept: list[Tag] = []
    for tag in tags:
        parent = _parent_symbol(tag.symbol)
        folded = False
        while parent:
            if parent in symbols:
                folded = True
                break
            parent = _parent_symbol(parent)
        if not folded:
            kept.append(tag)
    return kept


def compare_tags(projet_lines: Sequence[bytes], runtime_lines: Sequence[bytes]) -> TagsDelta:
    """Compare les tags des deux côtés par symbole."""
    projet = {t.symbol: t for t in extract_tags(projet_lines)}
    runtime = {t.symbol: t for t in extract_tags(runtime_lines)}
    order: list[str] = []
    seen: set[str] = set()
    for symbol in list(runtime) + list(projet):
        if symbol not in seen:
            seen.add(symbol)
            order.append(symbol)
    rows = [TagRow(symbol=s, projet=projet.get(s), runtime=runtime.get(s)) for s in order]
    runtime_seul = _fold([r.runtime for r in rows if r.etat == "runtime_seul" and r.runtime])
    projet_seul = _fold([r.projet for r in rows if r.etat == "projet_seul" and r.projet])
    modifies = [r for r in rows if r.etat == "modifie"]
    nb_communs = sum(1 for r in rows if r.projet and r.runtime)
    return TagsDelta(rows=rows, runtime_seul=runtime_seul, projet_seul=projet_seul, modifies=modifies, nb_communs=nb_communs)
