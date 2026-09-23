"""Remontée sémantique : d'un hunk de lignes brutes au nœud Optix concerné.

Un hunk « lignes 4123-4180 » est inexploitable. On indexe les lignes ``- Name:`` (début de
nœud, l'indentation donne la profondeur) et ``- File:`` (nœud externalisé), puis on remonte
du hunk au nœud englobant, ou l'on nomme les blocs entiers qu'il ajoute ou retire :
« bloc ``Fault_SurchauffeGHDel`` présent côté projet uniquement ».

L'index des nœuds (``common.optix.scanner``) est commun aux outils ; ce module n'en garde
que la lecture propre à Compare.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from ....common.i18n import tr, tr_n
from ....common.optix.scanner import NODE_RE, PROPERTY_RE, NodeIndex, NodeRef, index_nodes, indent_of, unquote
from .diffing import Hunk, Opcode, Sens

_ID_LINE_RE = re.compile(rb"^ *Id: g=[0-9a-fA-F]{32}\s*$")
_DIMENSIONS_RE = re.compile(rb'^\s*"Dimensions": \[(\d+),(\d+)\],?\s*$')
_SYMBOL_NAME = b"SymbolName"
TAG_TYPES = ("CODESYSTag", "TagStructure")


# ---------------------------------------------------------------------------
# Description sémantique d'un hunk
# ---------------------------------------------------------------------------

Genre = str  # "bloc" | "fichier" | "valeur" | "id" | "dimensions" | "lignes" | "deplacement"


@dataclass(slots=True)
class SemanticHunk:
    """Un hunk expliqué en langage métier."""

    hunk: Hunk
    sens: Sens
    genre: Genre
    noeuds: list[str]
    chemin: str
    detail: str
    significatif: bool = True
    nb_lignes_projet: int = 0
    nb_lignes_runtime: int = 0

    @property
    def noeud(self) -> str:
        return self.noeuds[0] if self.noeuds else ""

    @property
    def chemin_parent(self) -> str:
        return self.chemin.rsplit("/", 1)[0] if "/" in self.chemin else ""

    @property
    def libelle(self) -> str:
        """Une ligne lisible : « bloc `Fault_X` présent côté projet uniquement — 22 lignes »."""
        noms = ", ".join(f"`{n}`" for n in self.noeuds) if self.noeuds else tr("(no node)")
        if self.genre in ("bloc", "fichier"):
            ou = {
                "ajout_runtime": tr("present on the runtime side only"),
                "branche_projet": tr("present on the project side only"),
                "valeur_modifiee": tr("different on both sides"),
            }[self.sens]
            if self.genre == "fichier":
                quoi = tr("file reference")
            else:
                quoi = tr_n("block", "blocks", len(self.noeuds))
            return f"{quoi} {noms} {ou} — {self.detail}"
        if self.genre == "id":
            return tr("identifier of {names}").format(names=noms) + f" — {self.detail}"
        return f"{noms} — {self.detail}"


def _strip_comma(line: bytes) -> bytes:
    return line.rstrip()[:-1] if line.rstrip().endswith(b",") else line.rstrip()


def _is_subsequence(small: Sequence[bytes], big: Sequence[bytes]) -> bool:
    it = iter(big)
    return all(any(x == y for y in it) for x in small)


def _effective_change(hunk: Hunk, a: Sequence[bytes], b: Sequence[bytes]) -> tuple[Sens, list[bytes], list[bytes]]:
    """Ramène un ``replace`` qui n'est qu'une virgule de fin de ligne déplacée à un vrai ajout/retrait.

    Cas typique : ajout d'une ligne en fin de ``Body`` d'un dictionnaire de traductions, où la
    ligne précédente gagne une virgule. difflib voit un ``replace`` de 1 ligne par 2 ; on veut
    voir un ``insert`` d'une ligne.
    """
    la = list(a[hunk.i1 : hunk.i2])
    lb = list(b[hunk.j1 : hunk.j2])
    if hunk.tag != "replace":
        return hunk.sens, la, lb
    sa = [_strip_comma(x) for x in la]
    sb = [_strip_comma(x) for x in lb]
    if len(sa) < len(sb) and _is_subsequence(sa, sb):
        rest = list(lb)
        for x in sa:
            for i, y in enumerate(rest):
                if _strip_comma(y) == x:
                    del rest[i]
                    break
        return "ajout_runtime", [], rest
    if len(sb) < len(sa) and _is_subsequence(sb, sa):
        rest = list(la)
        for x in sb:
            for i, y in enumerate(rest):
                if _strip_comma(y) == x:
                    del rest[i]
                    break
        return "branche_projet", rest, []
    return hunk.sens, la, lb


def _describe_block(index: NodeIndex, node: NodeRef) -> str:
    props = index.properties(node)
    node_type = props.get("Type", "")
    if node_type in TAG_TYPES:
        symbol = index.child_value(node, "SymbolName")
        if symbol is None and node_type == "TagStructure":
            symbol = structure_symbol(index, node)
        dt = props.get("DataType", "")
        dims = props.get("ArrayDimensions", "")
        genre = "structure" if node_type == "TagStructure" else "tag"
        dtype = f" {dt}" if dt and node_type != "TagStructure" else ""
        arr = f"[{dims.strip('[]')}]" if dims else ""
        return f"{genre} {node_type}{dtype}{arr} — {symbol or '?'}"
    what = props.get("Supertype") or node_type or tr("node")
    return tr("block {what}, {n} lines").format(what=what, n=node.nb_lignes)


def structure_symbol(index: NodeIndex, node: NodeRef) -> str | None:
    """Symbole CoDeSys d'une structure, déduit de ses membres (elle n'a pas de ``SymbolName`` propre)."""
    for child in index.children(node):
        symbol = index.child_value(child, "SymbolName")
        if symbol is None and index.properties(child).get("Type") == "TagStructure":
            symbol = structure_symbol(index, child)
        if not symbol:
            continue
        if child.name.isdigit() and symbol.endswith("]") and "[" in symbol:
            return symbol[: symbol.rfind("[")]  # élément « 0 » d'un tableau de structures
        if "." in symbol:
            return symbol.rsplit(".", 1)[0]
    return None


def _top_level_nodes(index: NodeIndex, start: int, end: int) -> list[NodeRef]:
    """Les nœuds qui commencent dans ``[start, end)`` et d'indentation minimale."""
    inside = [n for n in index.nodes if start <= n.line < end]
    if not inside:
        return []
    min_indent = min(n.indent for n in inside)
    return [n for n in inside if n.indent == min_indent]


def describe_hunk(hunk: Hunk, a_index: NodeIndex, b_index: NodeIndex) -> SemanticHunk:
    """Explique un hunk : bloc ajouté/retiré, valeur modifiée, identifiant, compteur dérivé…"""
    a = a_index.lines
    b = b_index.lines
    sens, eff_a, eff_b = _effective_change(hunk, a, b)
    nb_a, nb_b = len(eff_a), len(eff_b)
    changed = eff_a + eff_b

    # 1. Lignes ``Id: g=…`` seules : écart réel mais sans impact, à conserver côté projet.
    if changed and all(_ID_LINE_RE.match(line) for line in changed):
        side_index, line_no = (a_index, hunk.i1) if nb_a else (b_index, hunk.j1)
        node = side_index.enclosing(line_no)
        return SemanticHunk(
            hunk=hunk,
            sens=sens,
            genre="id",
            noeuds=[node.name] if node else [],
            chemin=node.path if node else "",
            detail=tr("identifier present on the project side only, to keep")
            if sens == "branche_projet"
            else tr("identifier present on the runtime side only"),
            significatif=False,
            nb_lignes_projet=nb_a,
            nb_lignes_runtime=nb_b,
        )

    # 2. Compteur ``"Dimensions": [n, m]`` d'un dictionnaire de traductions : dérivé du contenu.
    if hunk.tag == "replace" and nb_a == 1 and nb_b == 1:
        ma, mb = _DIMENSIONS_RE.match(eff_a[0]), _DIMENSIONS_RE.match(eff_b[0])
        if ma and mb:
            node = a_index.enclosing(hunk.i1)
            return SemanticHunk(
                hunk=hunk,
                sens=sens,
                genre="dimensions",
                noeuds=[node.name] if node else [],
                chemin=node.path if node else "",
                detail=f"Dimensions [{ma.group(1).decode()},{ma.group(2).decode()}] → "
                f"[{mb.group(1).decode()},{mb.group(2).decode()}] " + tr("(recomputed from the lines)"),
                significatif=False,
                nb_lignes_projet=nb_a,
                nb_lignes_runtime=nb_b,
            )

    # 3. Blocs entiers : la première ligne changée d'un côté est un début de nœud.
    if sens == "ajout_runtime":
        block_index, start, end = b_index, hunk.j2 - nb_b, hunk.j2
    elif sens == "branche_projet":
        block_index, start, end = a_index, hunk.i1, hunk.i1 + nb_a
    else:
        block_index, start, end = a_index, hunk.i1, hunk.i2
    if block_index.node_at(start) is not None:
        tops = _top_level_nodes(block_index, start, end)
        first = tops[0]
        genre = "fichier" if all(n.kind == "file" for n in tops) else "bloc"
        if len(tops) == 1:
            detail = (
                tr("{name} becomes an orphan").format(name=first.name) if genre == "fichier" else _describe_block(block_index, first)
            )
            if sens == "valeur_modifiee":
                other = b_index.node_at(hunk.j1)
                detail += " ; " + tr("runtime side: {name}").format(name=other.name if other else "?")
        elif len(tops) <= 5:
            detail = " ; ".join(f"{n.name} ({_describe_block(block_index, n)})" for n in tops)
        else:
            detail = tr("{blocks} blocks, {lines} lines").format(blocks=len(tops), lines=end - start)
        return SemanticHunk(
            hunk=hunk,
            sens=sens,
            genre=genre,
            noeuds=[n.name for n in tops],
            chemin=first.path,
            detail=detail,
            nb_lignes_projet=nb_a,
            nb_lignes_runtime=nb_b,
        )

    # 4. Propriété modifiée à l'intérieur d'un nœud.
    if sens == "ajout_runtime":
        node = b_index.enclosing(hunk.j1)
    else:
        node = a_index.enclosing(hunk.i1)
    if node is not None:
        detail = _describe_value_change(eff_a, eff_b, sens)
        return SemanticHunk(
            hunk=hunk,
            sens=sens,
            genre="valeur",
            noeuds=[node.name],
            chemin=node.path,
            detail=detail,
            nb_lignes_projet=nb_a,
            nb_lignes_runtime=nb_b,
        )

    # 5. Fichier sans structure de nœuds (XML, C#…) : on donne les lignes.
    return SemanticHunk(
        hunk=hunk,
        sens=sens,
        genre="lignes",
        noeuds=[],
        chemin="",
        detail=tr("project l.{p1}-{p2} ⇄ runtime l.{r1}-{r2}").format(p1=hunk.i1 + 1, p2=hunk.i2, r1=hunk.j1 + 1, r2=hunk.j2),
        nb_lignes_projet=nb_a,
        nb_lignes_runtime=nb_b,
    )


def _describe_value_change(eff_a: list[bytes], eff_b: list[bytes], sens: Sens) -> str:
    """« Value: `81.0` → `80.0` » quand les lignes se correspondent une à une, sinon un décompte."""
    if sens == "valeur_modifiee" and len(eff_a) == len(eff_b):
        parts: list[str] = []
        for la, lb in zip(eff_a, eff_b):
            ma, mb = PROPERTY_RE.match(la), PROPERTY_RE.match(lb)
            if ma and mb and ma.group(2) == mb.group(2):
                key = ma.group(2).decode("ascii")
                parts.append(f"{key}: `{unquote(ma.group(3))}` → `{unquote(mb.group(3))}`")
            else:
                parts.append(f"`{la.strip().decode('utf-8', 'replace')}` → `{lb.strip().decode('utf-8', 'replace')}`")
        return " ; ".join(parts)
    if sens == "ajout_runtime":
        lines = eff_b
        if len(lines) == 1:
            return tr("line added on the runtime side: {line}").format(line=f"`{lines[0].strip().decode('utf-8', 'replace')}`")
        return tr("{n} lines added on the runtime side").format(n=len(lines))
    if sens == "branche_projet":
        lines = eff_a
        if len(lines) == 1:
            return tr("line present on the project side only: {line}").format(
                line=f"`{lines[0].strip().decode('utf-8', 'replace')}`"
            )
        return tr("{n} lines present on the project side only").format(n=len(lines))
    return tr("{project} project line(s) ⇄ {runtime} runtime line(s)").format(project=len(eff_a), runtime=len(eff_b))


# ---------------------------------------------------------------------------
# Glissement des hunks sur les frontières de nœuds
# ---------------------------------------------------------------------------


def _window_score(lines: Sequence[bytes], start: int, end: int) -> int:
    """Note une fenêtre d'insertion/suppression : 2 si elle commence sur un nœud de tête, +1 si elle se referme proprement."""
    node_indents = [indent_of(lines[k]) for k in range(start, end) if NODE_RE.match(lines[k])]
    if not node_indents:
        return 0
    min_indent = min(node_indents)
    score = 0
    if NODE_RE.match(lines[start]) and indent_of(lines[start]) == min_indent:
        score += 2
    if end >= len(lines) or indent_of(lines[end]) <= min_indent:
        score += 1
    return score


def slide_opcodes(opcodes: Sequence[Opcode], a: Sequence[bytes], b: Sequence[bytes]) -> list[Opcode]:
    """Fait glisser chaque ``insert``/``delete`` dans sa marge de lignes égales pour qu'il commence sur un ``- Name:``.

    difflib place arbitrairement une insertion dans une zone de lignes répétées (``Children:``,
    ``- Name: SymbolName``…). Le contenu reconstruit est identique quelle que soit la position,
    mais la lecture sémantique, elle, exige que le hunk épouse le bloc.
    """
    ops = list(opcodes)
    for k, op in enumerate(ops):
        tag, i1, i2, j1, j2 = op
        if tag not in ("insert", "delete"):
            continue
        lines, s, e = (b, j1, j2) if tag == "insert" else (a, i1, i2)
        if e <= s:
            continue
        prev_eq = ops[k - 1] if k > 0 and ops[k - 1][0] == "equal" else None
        next_eq = ops[k + 1] if k + 1 < len(ops) and ops[k + 1][0] == "equal" else None
        max_up = prev_eq[2] - prev_eq[1] if prev_eq else 0
        max_down = next_eq[2] - next_eq[1] if next_eq else 0
        up = 0
        while up < max_up and lines[s - 1 - up] == lines[e - 1 - up]:
            up += 1
        down = 0
        while down < max_down and lines[s + down] == lines[e + down]:
            down += 1
        if up == 0 and down == 0:
            continue
        best_shift, best_key = 0, (_window_score(lines, s, e), 0, 0)
        for shift in range(-up, down + 1):
            key = (_window_score(lines, s + shift, e + shift), -abs(shift), -shift)
            if key > best_key:
                best_shift, best_key = shift, key
        if best_shift == 0:
            continue
        d = best_shift
        ops[k] = (tag, i1 + d, i2 + d, j1 + d, j2 + d)  # le côté vide glisse avec l'autre
        if prev_eq:
            ops[k - 1] = ("equal", prev_eq[1], prev_eq[2] + d, prev_eq[3], prev_eq[4] + d)
        if next_eq:
            ops[k + 1] = ("equal", next_eq[1] + d, next_eq[2], next_eq[3] + d, next_eq[4])
    return [op for op in ops if op[0] != "equal" or op[2] > op[1]]


_GUID_ATTR_RE = re.compile(rb'guid="([0-9a-fA-F]{32})"')


def _mark_moves(semantic: list[SemanticHunk], a: Sequence[bytes], b: Sequence[bytes]) -> None:
    """Un bloc retiré ici et réinséré ailleurs à l'identique est un déplacement, pas un écart.

    Cas réel : les ``TypeMapping`` de ``UserDefinedModule.xml`` ne sont pas dans le même ordre
    des deux côtés. Sans cette passe, « récupérer les ajouts du runtime » dupliquerait le bloc.
    """
    deletes = [s for s in semantic if s.hunk.tag == "delete" and s.genre == "lignes"]
    inserts = [s for s in semantic if s.hunk.tag == "insert" and s.genre == "lignes"]
    if not deletes or not inserts:
        return
    by_content: dict[tuple[bytes, ...], list[SemanticHunk]] = {}
    for s in inserts:
        key = tuple(line.strip() for line in b[s.hunk.j1 : s.hunk.j2])
        by_content.setdefault(key, []).append(s)
    for s in deletes:
        key = tuple(line.strip() for line in a[s.hunk.i1 : s.hunk.i2])
        candidates = by_content.get(key)
        if not candidates:
            continue
        other = candidates.pop(0)
        for hunk, where in ((s, "projet"), (other, "runtime")):
            hunk.genre = "deplacement"
            hunk.significatif = False
            hunk.detail = (
                tr("block moved without change ({n} lines)").format(n=hunk.nb_lignes_projet or hunk.nb_lignes_runtime)
                + f" — {hunk.detail}"
            )


def _guid_detail(lines: Sequence[bytes]) -> str:
    guids = [m.group(1).decode().lower() for line in lines for m in _GUID_ATTR_RE.finditer(line)]
    if not guids:
        return ""
    shown = ", ".join(guids[:3]) + (f" … (+{len(guids) - 3})" if len(guids) > 3 else "")
    return f" — {len(guids)} GUID : {shown}"


def describe_hunks(hunks: Sequence[Hunk], a_lines: Sequence[bytes], b_lines: Sequence[bytes]) -> list[SemanticHunk]:
    """Indexe les deux côtés puis décrit chaque hunk."""
    a_index = index_nodes(a_lines)
    b_index = index_nodes(b_lines)
    semantic = [describe_hunk(h, a_index, b_index) for h in hunks]
    for s in semantic:
        if s.genre == "lignes":
            s.detail += _guid_detail(list(a_lines[s.hunk.i1 : s.hunk.i2]) + list(b_lines[s.hunk.j1 : s.hunk.j2]))
    _mark_moves(semantic, a_lines, b_lines)
    return semantic


def sens_semantique(semantic: Sequence[SemanticHunk]) -> str:
    """Sens d'ensemble calculé sur les seuls hunks significatifs."""
    kinds = {s.sens for s in semantic if s.significatif}
    if not kinds:
        return "non_significatif" if semantic else "identique"
    if len(kinds) == 1:
        return next(iter(kinds))
    return "mixte"
