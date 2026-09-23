"""Opcodes difflib entre deux listes de lignes, et application sélective d'opcodes.

Convention dans tout le moteur : **``a`` est le projet, ``b`` est le runtime**. Ainsi :

- ``insert``  → présent runtime, absent projet → *ajout runtime* ;
- ``delete``  → présent projet, absent runtime → *branche projet* ;
- ``replace`` → *valeur modifiée*.

``autojunk=False`` est indispensable : sans lui difflib ignore les lignes fréquentes
(``Type: CODESYSTag``, ``DataType: Boolean``…) et produit des hunks faux sur ``Tags.yaml``.
Le calcul sur 170 000 lignes prend plusieurs secondes : à lancer dans un thread de travail.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

Opcode = tuple[str, int, int, int, int]
Sens = Literal["ajout_runtime", "branche_projet", "valeur_modifiee"]

SENS_PAR_OPCODE: dict[str, Sens] = {
    "insert": "ajout_runtime",
    "delete": "branche_projet",
    "replace": "valeur_modifiee",
}
LIBELLE_SENS: dict[str, str] = {
    "ajout_runtime": "ajout runtime",
    "branche_projet": "branche projet",
    "valeur_modifiee": "valeur modifiée",
    "mixte": "mixte",
    "non_significatif": "non significatif",
}


@dataclass(frozen=True, slots=True)
class Hunk:
    """Un opcode non ``equal`` : ``a[i1:i2]`` (projet) ⇄ ``b[j1:j2]`` (runtime)."""

    tag: str
    i1: int
    i2: int
    j1: int
    j2: int

    @property
    def sens(self) -> Sens:
        return SENS_PAR_OPCODE[self.tag]

    @property
    def nb_a(self) -> int:
        return self.i2 - self.i1

    @property
    def nb_b(self) -> int:
        return self.j2 - self.j1

    def as_opcode(self) -> Opcode:
        return (self.tag, self.i1, self.i2, self.j1, self.j2)


def _common_prefix(a: Sequence[bytes], b: Sequence[bytes]) -> int:
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


def _common_suffix(a: Sequence[bytes], b: Sequence[bytes], prefix: int) -> int:
    n = min(len(a), len(b)) - prefix
    i = 0
    while i < n and a[len(a) - 1 - i] == b[len(b) - 1 - i]:
        i += 1
    return i


# Au-delà de cette taille (lignes des deux côtés cumulées), on ancre d'abord sur les lignes
# uniques (diff « patience ») avant d'appeler difflib segment par segment.
SEUIL_ANCRAGE = 4000


def _unique_anchors(a: Sequence[bytes], b: Sequence[bytes]) -> list[tuple[int, int]]:
    """Couples (ia, jb) de lignes uniques des deux côtés, dans l'ordre croissant des deux indices.

    C'est le cœur du diff « patience » : les lignes uniques (un ``SymbolName``, un ``Id:``…)
    sont des ancrages sûrs. On garde la plus longue sous-suite croissante de ces couples.
    """
    count_a: dict[bytes, int] = {}
    pos_a: dict[bytes, int] = {}
    for i, line in enumerate(a):
        count_a[line] = count_a.get(line, 0) + 1
        pos_a[line] = i
    count_b: dict[bytes, int] = {}
    pos_b: dict[bytes, int] = {}
    for j, line in enumerate(b):
        count_b[line] = count_b.get(line, 0) + 1
        pos_b[line] = j
    pairs = sorted(
        (pos_a[line], pos_b[line])
        for line, n in count_a.items()
        if n == 1 and count_b.get(line) == 1
    )
    if not pairs:
        return []
    # Plus longue sous-suite croissante sur l'indice b (les indices a sont déjà croissants).
    from bisect import bisect_left

    tails: list[int] = []
    tails_idx: list[int] = []
    prev = [-1] * len(pairs)
    for k, (_, j) in enumerate(pairs):
        pos = bisect_left(tails, j)
        if pos == len(tails):
            tails.append(j)
            tails_idx.append(k)
        else:
            tails[pos] = j
            tails_idx[pos] = k
        prev[k] = tails_idx[pos - 1] if pos > 0 else -1
    chain: list[tuple[int, int]] = []
    k = tails_idx[-1] if tails_idx else -1
    while k >= 0:
        chain.append(pairs[k])
        k = prev[k]
    chain.reverse()
    return chain


def _opcodes_recursive(a: Sequence[bytes], b: Sequence[bytes], ia: int, jb: int) -> list[Opcode]:
    """Opcodes de ``a`` ⇄ ``b`` décalés de ``(ia, jb)``, en ancrant sur les lignes uniques si nécessaire."""
    prefix = _common_prefix(a, b)
    suffix = _common_suffix(a, b, prefix)
    core_a = a[prefix : len(a) - suffix]
    core_b = b[prefix : len(b) - suffix]

    opcodes: list[Opcode] = []
    if prefix:
        opcodes.append(("equal", ia, ia + prefix, jb, jb + prefix))
    oa, ob = ia + prefix, jb + prefix
    if core_a and core_b and len(core_a) + len(core_b) > SEUIL_ANCRAGE:
        anchors = _unique_anchors(core_a, core_b)
    else:
        anchors = []
    if anchors:
        pa = pb = 0
        for i, j in anchors:
            opcodes.extend(_opcodes_recursive(core_a[pa:i], core_b[pb:j], oa + pa, ob + pb))
            opcodes.append(("equal", oa + i, oa + i + 1, ob + j, ob + j + 1))
            pa, pb = i + 1, j + 1
        opcodes.extend(_opcodes_recursive(core_a[pa:], core_b[pb:], oa + pa, ob + pb))
    elif core_a or core_b:
        matcher = SequenceMatcher(None, core_a, core_b, autojunk=False)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            opcodes.append((tag, i1 + oa, i2 + oa, j1 + ob, j2 + ob))
    if suffix:
        opcodes.append(("equal", ia + len(a) - suffix, ia + len(a), jb + len(b) - suffix, jb + len(b)))
    return opcodes


def compute_opcodes(a: Sequence[bytes], b: Sequence[bytes]) -> list[Opcode]:
    """Tous les opcodes (``equal`` compris) entre ``a`` (projet) et ``b`` (runtime).

    Le préfixe et le suffixe communs sont retirés d'abord. Sur les gros fichiers, les lignes
    uniques des deux côtés servent d'ancrages (diff « patience ») et difflib ne travaille
    que segment par segment : ``Tags.yaml`` (170 000 lignes) passe de près d'une minute à
    quelques secondes, avec des hunks au moins aussi justes.
    """
    return _fuse_equals(_opcodes_recursive(a, b, 0, 0))


def _fuse_equals(opcodes: list[Opcode]) -> list[Opcode]:
    fused: list[Opcode] = []
    for op in opcodes:
        if fused and op[0] == "equal" and fused[-1][0] == "equal" and fused[-1][2] == op[1]:
            prev = fused[-1]
            fused[-1] = ("equal", prev[1], op[2], prev[3], op[4])
        else:
            fused.append(op)
    return fused


def hunks_from_opcodes(opcodes: Iterable[Opcode]) -> list[Hunk]:
    """Ne garde que les opcodes qui changent quelque chose."""
    return [Hunk(tag, i1, i2, j1, j2) for tag, i1, i2, j1, j2 in opcodes if tag != "equal"]


def diff_lines(a: Sequence[bytes], b: Sequence[bytes]) -> list[Hunk]:
    """Les hunks entre le projet ``a`` et le runtime ``b``."""
    return hunks_from_opcodes(compute_opcodes(a, b))


def merge_lines(
    a: Sequence[bytes],
    b: Sequence[bytes],
    opcodes: Iterable[Opcode],
    retenus: Iterable[Hunk] | None = None,
    modes: Iterable[str] = (),
) -> list[bytes]:
    """Reconstruit le fichier en partant du projet ``a`` et en y appliquant certains opcodes.

    ``equal`` → côté projet ; opcode retenu → côté runtime ; opcode écarté → côté projet.
    Un opcode est retenu s'il figure dans ``retenus`` (sélection individuelle) ou si son
    tag figure dans ``modes`` (``{"insert"}`` = récupérer les ajouts du runtime,
    ``{"replace"}`` = aligner les valeurs, les trois = alignement complet).
    """
    modes = set(modes)
    retained_keys = {h.as_opcode() for h in retenus} if retenus else set()
    result: list[bytes] = []
    for op in opcodes:
        tag, i1, i2, j1, j2 = op
        if tag == "equal":
            result.extend(a[i1:i2])
        elif tag in modes or op in retained_keys:
            result.extend(b[j1:j2])
        else:
            result.extend(a[i1:i2])
    return result


def sens_global(hunks: Iterable[Hunk]) -> str:
    """Le sens d'ensemble d'un fichier : un seul type d'opcode, ou ``mixte``."""
    kinds = {h.sens for h in hunks}
    if not kinds:
        return "identique"
    if len(kinds) == 1:
        return next(iter(kinds))
    return "mixte"
