"""NetLogic — classes d'une DLL .NET, lues dans les métadonnées CLI (ECMA-335).

Le runtime ne contient que la DLL compilée, aucune source. Pour savoir quelles logiques
existent de chaque côté, on lit la table ``TypeDef`` du flux ``#~`` et le heap ``#Strings`` :
PE → CLI header → racine des métadonnées → flux → tables. Un ``strings`` brut dépannerait
mais mélangerait noms de méthodes et noms de classes.
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass, field
from pathlib import Path

from .....common.i18n import tr

log = logging.getLogger(__name__)

_MODULE, _TYPEREF, _TYPEDEF, _FIELD, _METHODDEF = 0x00, 0x01, 0x02, 0x04, 0x06
_MODULEREF, _TYPESPEC, _ASSEMBLYREF = 0x1A, 0x1B, 0x23


class DllError(ValueError):
    """La DLL n'est pas un assembly .NET lisible."""


@dataclass(slots=True)
class TypeDef:
    name: str
    namespace: str
    nested: bool
    base: str = ""

    @property
    def full_name(self) -> str:
        return f"{self.namespace}.{self.name}" if self.namespace else self.name

    @property
    def compiler_generated(self) -> bool:
        return self.name.startswith("<") or self.name == "<Module>"


def _u16(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def _u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def _rva_to_offset(sections: list[tuple[int, int, int]], rva: int) -> int:
    for va, size, raw in sections:
        if va <= rva < va + size:
            return rva - va + raw
    raise DllError(tr("RVA {rva} outside the sections").format(rva=f"{rva:#x}"))


def _read_cstring(data: bytes, off: int) -> str:
    end = data.index(b"\x00", off)
    return data[off:end].decode("utf-8", errors="replace")


def read_typedefs(data: bytes) -> list[TypeDef]:
    """Les ``TypeDef`` d'un assembly .NET, dans l'ordre de la table."""
    if data[:2] != b"MZ":
        raise DllError(tr("not a PE executable"))
    pe = _u32(data, 0x3C)
    if data[pe : pe + 4] != b"PE\x00\x00":
        raise DllError(tr("PE signature missing"))
    coff = pe + 4
    n_sections = _u16(data, coff + 2)
    opt_size = _u16(data, coff + 16)
    opt = coff + 20
    magic = _u16(data, opt)
    dir_off = opt + (96 if magic == 0x10B else 112 if magic == 0x20B else -1)
    if dir_off < 0:
        raise DllError(tr("unknown optional header"))
    cli_rva = _u32(data, dir_off + 14 * 8)
    if cli_rva == 0:
        raise DllError(tr("no CLI header: not a .NET DLL"))
    sec = opt + opt_size
    sections: list[tuple[int, int, int]] = []
    for k in range(n_sections):
        s = sec + 40 * k
        vsize, va, rsize, raw = _u32(data, s + 8), _u32(data, s + 12), _u32(data, s + 16), _u32(data, s + 20)
        sections.append((va, max(vsize, rsize), raw))

    cli = _rva_to_offset(sections, cli_rva)
    meta_rva = _u32(data, cli + 8)
    root = _rva_to_offset(sections, meta_rva)
    if _u32(data, root) != 0x424A5342:
        raise DllError(tr("metadata signature missing"))
    ver_len = _u32(data, root + 12)
    p = root + 16 + ver_len
    n_streams = _u16(data, p + 2)
    p += 4
    streams: dict[str, tuple[int, int]] = {}
    for _ in range(n_streams):
        off, size = _u32(data, p), _u32(data, p + 4)
        name_end = data.index(b"\x00", p + 8)
        name = data[p + 8 : name_end].decode("ascii")
        streams[name] = (root + off, size)
        p = name_end + 1
        p = (p + 3) & ~3
    if "#~" not in streams or "#Strings" not in streams:
        raise DllError(tr("#~ or #Strings stream missing"))
    tables, _ = streams["#~"]
    strings_off, _ = streams["#Strings"]

    heap_sizes = data[tables + 6]
    valid = struct.unpack_from("<Q", data, tables + 8)[0]
    rows: dict[int, int] = {}
    p = tables + 24
    for t in range(64):
        if valid >> t & 1:
            rows[t] = _u32(data, p)
            p += 4
    str_size = 4 if heap_sizes & 1 else 2
    guid_size = 4 if heap_sizes & 2 else 2

    def simple(table: int) -> int:
        return 4 if rows.get(table, 0) > 0xFFFF else 2

    def coded(bits: int, *tabs: int) -> int:
        return 4 if max(rows.get(t, 0) for t in tabs) >= (1 << (16 - bits)) else 2

    module_row = 2 + str_size + 3 * guid_size
    typeref_row = coded(2, _MODULE, _MODULEREF, _ASSEMBLYREF, _TYPEREF) + 2 * str_size
    extends_size = coded(2, _TYPEDEF, _TYPEREF, _TYPESPEC)
    typedef_row = 4 + 2 * str_size + extends_size + simple(_FIELD) + simple(_METHODDEF)

    p += rows.get(_MODULE, 0) * module_row
    typeref_start = p
    p += rows.get(_TYPEREF, 0) * typeref_row
    typedef_start = p

    def read_index(off: int, size: int) -> int:
        return _u32(data, off) if size == 4 else _u16(data, off)

    typerefs: list[str] = []
    for k in range(rows.get(_TYPEREF, 0)):
        r = typeref_start + k * typeref_row
        r += coded(2, _MODULE, _MODULEREF, _ASSEMBLYREF, _TYPEREF)
        name = _read_cstring(data, strings_off + read_index(r, str_size))
        typerefs.append(name)

    result: list[TypeDef] = []
    typedef_names: list[str] = []
    raw_rows: list[tuple[int, str, str, int]] = []
    for k in range(rows.get(_TYPEDEF, 0)):
        r = typedef_start + k * typedef_row
        flags = _u32(data, r)
        name = _read_cstring(data, strings_off + read_index(r + 4, str_size))
        namespace = _read_cstring(data, strings_off + read_index(r + 4 + str_size, str_size))
        extends = read_index(r + 4 + 2 * str_size, extends_size)
        typedef_names.append(name)
        raw_rows.append((flags, name, namespace, extends))
    for flags, name, namespace, extends in raw_rows:
        tag, idx = extends & 3, extends >> 2
        base = ""
        if idx:
            if tag == 0 and idx - 1 < len(typedef_names):
                base = typedef_names[idx - 1]
            elif tag == 1 and idx - 1 < len(typerefs):
                base = typerefs[idx - 1]
        result.append(TypeDef(name=name, namespace=namespace, nested=(flags & 7) >= 2, base=base))
    return result


def read_dll_classes(path: Path | str) -> list[TypeDef]:
    return read_typedefs(Path(path).read_bytes())


def logic_classes(typedefs: list[TypeDef]) -> list[str]:
    """Les classes de premier niveau écrites par l'utilisateur (ni ``<Module>``, ni générées, ni imbriquées)."""
    return [t.name for t in typedefs if not t.nested and not t.compiler_generated]


@dataclass(slots=True)
class NetLogicDelta:
    projet: list[str]
    runtime: list[str]
    projet_seul: list[str] = field(default_factory=list)
    runtime_seul: list[str] = field(default_factory=list)
    erreur: str = ""
    sources_projet: dict[str, str] = field(default_factory=dict)  # classe → chemin relatif du .cs

    @property
    def nb_communs(self) -> int:
        return len(set(self.projet) & set(self.runtime))


def compare_dlls(projet_dll: Path | str, runtime_dll: Path | str) -> NetLogicDelta:
    """Classes présentes dans chaque DLL et de chaque côté seulement."""
    try:
        projet = logic_classes(read_dll_classes(projet_dll))
        runtime = logic_classes(read_dll_classes(runtime_dll))
    except (DllError, OSError, ValueError, struct.error) as exc:
        log.warning("Lecture des DLL NetLogic impossible : %s", exc)
        return NetLogicDelta(projet=[], runtime=[], erreur=str(exc))
    r_set, p_set = set(runtime), set(projet)
    return NetLogicDelta(
        projet=projet,
        runtime=runtime,
        projet_seul=[c for c in projet if c not in r_set],
        runtime_seul=[c for c in runtime if c not in p_set],
    )
