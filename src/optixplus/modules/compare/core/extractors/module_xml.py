"""Types utilisateur — ``ProjectFiles/UserDefinedModule.xml``.

Liste de ``<TypeMapping><TargetType><NodeId … guid="…"/></TargetType></TypeMapping>``.
C'est la **source de vérité du jeu de types** du projet ; le nombre d'entrées correspond à
``ObjectTypes`` du ``.optix``. Le delta de GUID entre les deux fichiers pilote l'élagage des
fichiers C# générés — **toujours par GUID, jamais par nom**.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import TYPE_CHECKING
from dataclasses import dataclass, field

if TYPE_CHECKING:
    from ..nodes import SemanticHunk

_MAPPING_RE = re.compile(rb"<TypeMapping>.*?</TypeMapping>", re.DOTALL)
_GUID_RE = re.compile(rb'guid="([0-9a-fA-F]{32})"')


@dataclass(slots=True)
class TypeMapping:
    guid: str
    line: int  # ligne de la balise <TypeMapping> (0-based)
    end: int = 0  # ligne suivant </TypeMapping> (exclusive)


def extract_type_guids(lines: Sequence[bytes]) -> list[TypeMapping]:
    """Les GUID des ``TypeMapping``, dans l'ordre du fichier."""
    raw = b"\n".join(lines)
    result: list[TypeMapping] = []
    for match in _MAPPING_RE.finditer(raw):
        guid = _GUID_RE.search(match.group(0))
        if guid is None:
            continue
        line = raw.count(b"\n", 0, match.start())
        end = raw.count(b"\n", 0, match.end()) + 1
        result.append(TypeMapping(guid=guid.group(1).decode("ascii").lower(), line=line, end=end))
    return result


@dataclass(slots=True)
class TypesDelta:
    """Écarts de GUID entre les deux ``UserDefinedModule.xml``."""

    projet: list[str]
    runtime: list[str]
    projet_seul: list[str] = field(default_factory=list)
    runtime_seul: list[str] = field(default_factory=list)

    @property
    def nb_communs(self) -> int:
        return len(set(self.projet) & set(self.runtime))


def compare_type_guids(projet_lines: Sequence[bytes], runtime_lines: Sequence[bytes]) -> TypesDelta:
    projet = [m.guid for m in extract_type_guids(projet_lines)]
    runtime = [m.guid for m in extract_type_guids(runtime_lines)]
    runtime_set, projet_set = set(runtime), set(projet)
    return TypesDelta(
        projet=projet,
        runtime=runtime,
        projet_seul=[g for g in projet if g not in runtime_set],
        runtime_seul=[g for g in runtime if g not in projet_set],
    )


def merge_type_mappings(
    projet_lines: Sequence[bytes],
    runtime_lines: Sequence[bytes],
    remove: Iterable[str],
    add: Iterable[str],
) -> list[bytes]:
    """Retire les ``TypeMapping`` de ``remove`` et ajoute ceux de ``add`` (copiés du runtime), par GUID.

    Les blocs ajoutés sont insérés avant ``</TypeMappings>`` ; jamais de doublon.
    """
    remove_set = {g.lower() for g in remove}
    projet_blocks = extract_type_guids(projet_lines)
    present = {b.guid for b in projet_blocks}
    doomed: set[int] = set()
    for block in projet_blocks:
        if block.guid in remove_set:
            doomed.update(range(block.line, block.end))
    result = [line for k, line in enumerate(projet_lines) if k not in doomed]
    runtime_blocks = {b.guid: b for b in extract_type_guids(runtime_lines)}
    kept = present - remove_set
    to_add: list[str] = []
    for guid in add:
        guid = guid.lower()
        if guid in runtime_blocks and guid not in kept and guid not in to_add:
            to_add.append(guid)
    if to_add:
        closing = next((k for k, line in enumerate(result) if b"</TypeMappings>" in line), None)
        if closing is None:
            return result
        added: list[bytes] = []
        for guid in to_add:
            block = runtime_blocks[guid]
            added.extend(runtime_lines[block.line : block.end])
        result[closing:closing] = added
    return result


def describe_type_mappings(
    projet_lines: Sequence[bytes],
    runtime_lines: Sequence[bytes],
    type_names: Mapping[str, str],
) -> list[SemanticHunk]:
    """Un écart sémantique par GUID présent d'un seul côté. Les déplacements de blocs sont invisibles.

    Les hunks sont synthétiques : un retrait porte les lignes exactes du bloc côté projet, un ajout
    celles du bloc côté runtime. ``plan.build_preview`` les applique par GUID, pas par position.
    """
    from ..diffing import Hunk
    from ..nodes import SemanticHunk

    projet = extract_type_guids(projet_lines)
    runtime = extract_type_guids(runtime_lines)
    projet_set = {b.guid for b in projet}
    runtime_set = {b.guid for b in runtime}
    result: list[SemanticHunk] = []
    for block in projet:
        if block.guid in runtime_set:
            continue
        nom = type_names.get(block.guid, "?")
        result.append(
            SemanticHunk(
                hunk=Hunk("delete", block.line, block.end, 0, 0),
                sens="branche_projet",
                genre="type",
                noeuds=[nom],
                chemin=f"TypeMappings/{block.guid}",
                detail=f"TypeMapping guid={block.guid} présent côté projet seulement",
                nb_lignes_projet=block.end - block.line,
            )
        )
    insertion = max((b.end for b in projet), default=0)
    for block in runtime:
        if block.guid in projet_set:
            continue
        nom = type_names.get(block.guid, "?")
        result.append(
            SemanticHunk(
                hunk=Hunk("insert", insertion, insertion, block.line, block.end),
                sens="ajout_runtime",
                genre="type",
                noeuds=[nom],
                chemin=f"TypeMappings/{block.guid}",
                detail=f"TypeMapping guid={block.guid} présent côté runtime seulement (nom inconnu côté projet)",
                nb_lignes_runtime=block.end - block.line,
            )
        )
    return result


def guid_of_hunk_lines(lines: Sequence[bytes]) -> str | None:
    match = _GUID_RE.search(b"\n".join(lines))
    return match.group(1).decode().lower() if match else None
