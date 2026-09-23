"""Orchestration de la phase 1 : inventaire, hash, diff, remontée sémantique, vues spécialisées.

C'est le point d'entrée du moteur pour l'interface : ``compare(runtime, projet)`` renvoie une
``Comparison`` complète. Tout est calculé ici, rien n'est écrit sur le disque.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from .diffing import Hunk, Opcode, compute_opcodes, hunks_from_opcodes
from .extractors.generated_cs import guid_to_name
from .extractors.module_xml import TypesDelta, compare_type_guids, describe_type_mappings
from .extractors.netlogic import NetLogicDelta, compare_dlls
from .extractors.optix_meta import OptixDelta, compare_optix, versions_compatibles
from .extractors.tags import TagsDelta, compare_tags, is_tags_file
from .extractors.translations import TranslationsDelta, compare_translations, parse_translations
from .lines import TextFile, read_text_file
from .nodes import SemanticHunk, describe_hunks, sens_semantique, slide_opcodes
from .progress import CancelCheck, ProgressCallback, check_cancel, report
from .scan import FileEntry, Inventory, build_inventory, read_ide_version

log = logging.getLogger(__name__)

USER_DEFINED_MODULE = "ProjectFiles/UserDefinedModule.xml"
TYPE_CONSTANTS = "ProjectFiles/NetSolution/Private/TypeConstants.cs"
UI_TYPE_DEFINITIONS = "ProjectFiles/NetSolution/Private/UITypeDefinitions.cs"
NETSOLUTION_BIN = "ProjectFiles/NetSolution/bin/"


@dataclass(slots=True)
class FileDiff:
    """Le diff complet d'un fichier texte présent des deux côtés et différent."""

    entry: FileEntry
    projet: TextFile
    runtime: TextFile
    opcodes: list[Opcode]
    hunks: list[Hunk]
    semantic: list[SemanticHunk]

    @property
    def rel(self) -> str:
        return self.entry.rel

    @property
    def sens(self) -> str:
        return sens_semantique(self.semantic)

    @property
    def significatifs(self) -> list[SemanticHunk]:
        return [s for s in self.semantic if s.significatif]

    def compte(self, sens: str) -> int:
        return sum(1 for s in self.semantic if s.significatif and s.sens == sens)

    @property
    def nb_ajouts_runtime(self) -> int:
        return self.compte("ajout_runtime")

    @property
    def nb_branche_projet(self) -> int:
        return self.compte("branche_projet")

    @property
    def nb_valeurs_modifiees(self) -> int:
        return self.compte("valeur_modifiee")


@dataclass(slots=True)
class Synthese:
    """Le bandeau de synthèse de la fenêtre de résultats."""

    version_runtime: str | None
    version_projet: str | None
    versions_compatibles: bool
    nb_fichiers_compares: int
    nb_yaml_communs: int
    nb_divergents: int
    nb_yaml_divergents: int
    nb_ajouts_runtime: int
    nb_branche_projet: int
    nb_valeurs_modifiees: int
    nb_non_significatifs: int
    nb_runtime_seul: int
    nb_projet_seul: int
    nb_attendus: int
    duree_s: float


@dataclass(slots=True)
class Comparison:
    """Résultat complet d'une comparaison runtime ⇄ projet."""

    runtime_root: Path
    projet_root: Path
    version_runtime: str | None
    version_projet: str | None
    inventory: Inventory
    diffs: dict[str, FileDiff] = field(default_factory=dict)
    optix: OptixDelta | None = None
    tags: dict[str, TagsDelta] = field(default_factory=dict)
    translations: dict[str, TranslationsDelta] = field(default_factory=dict)
    types: TypesDelta | None = None
    type_names: dict[str, str] = field(default_factory=dict)
    netlogic: NetLogicDelta | None = None
    orphelins_projet: list[str] = field(default_factory=list)
    orphelins_runtime: list[str] = field(default_factory=list)
    duree_s: float = 0.0

    @property
    def versions_compatibles(self) -> bool:
        return versions_compatibles(self.version_projet, self.version_runtime)

    def diff(self, rel: str) -> FileDiff | None:
        return self.diffs.get(rel)

    def yaml_divergents(self) -> list[FileEntry]:
        return [e for e in self.inventory.divergents() if e.is_yaml and e.status == "different"]

    def synthese(self) -> Synthese:
        inv = self.inventory
        diffs = list(self.diffs.values())
        return Synthese(
            version_runtime=self.version_runtime,
            version_projet=self.version_projet,
            versions_compatibles=self.versions_compatibles,
            nb_fichiers_compares=len(inv.common()),
            nb_yaml_communs=sum(1 for e in inv.common() if e.is_yaml),
            nb_divergents=len(inv.divergents()),
            nb_yaml_divergents=len(self.yaml_divergents()),
            nb_ajouts_runtime=sum(d.nb_ajouts_runtime for d in diffs),
            nb_branche_projet=sum(d.nb_branche_projet for d in diffs),
            nb_valeurs_modifiees=sum(d.nb_valeurs_modifiees for d in diffs),
            nb_non_significatifs=sum(1 for d in diffs for s in d.semantic if not s.significatif),
            nb_runtime_seul=sum(1 for e in inv.by_status("runtime_seul") if not e.attendu),
            nb_projet_seul=sum(1 for e in inv.by_status("projet_seul") if not e.attendu),
            nb_attendus=len(inv.attendus()),
            duree_s=self.duree_s,
        )


# ---------------------------------------------------------------------------


def diff_file(entry: FileEntry, projet_path: Path, runtime_path: Path) -> FileDiff:
    """Diff d'un fichier texte : lecture binaire, opcodes, glissement (YAML), description."""
    projet = read_text_file(projet_path)
    runtime = read_text_file(runtime_path)
    opcodes = compute_opcodes(projet.lines, runtime.lines)
    if entry.is_yaml:
        opcodes = slide_opcodes(opcodes, projet.lines, runtime.lines)
    hunks = hunks_from_opcodes(opcodes)
    semantic = describe_hunks(hunks, projet.lines, runtime.lines)
    return FileDiff(entry=entry, projet=projet, runtime=runtime, opcodes=opcodes, hunks=hunks, semantic=semantic)


def _file_refs_fast(lines: list[bytes]) -> list[str]:
    refs: list[str] = []
    for line in lines:
        stripped = line.lstrip(b" ")
        if stripped.startswith(b"- File:"):
            value = stripped[len(b"- File:") :].strip().strip(b"'\"")
            refs.append(value.decode("utf-8", "replace").replace("\\", "/"))
    return refs


def find_orphans(root: Path, nodes_root: str, yaml_rels: list[str]) -> list[str]:
    """Les YAML sous ``Nodes/`` qu'aucun ``- File:`` ne référence : ignorés par Optix.

    ``nodes_root`` est le pointeur racine du ``.optix`` (``Nodes/IHM_X.yaml``).
    """
    referenced: set[str] = {nodes_root.replace("\\", "/")} if nodes_root else set()
    for rel in yaml_rels:
        try:
            lines = read_text_file(root / rel).lines
        except OSError:
            continue
        base = rel.rsplit("/", 1)[0] if "/" in rel else ""
        for ref in _file_refs_fast(lines):
            full = f"{base}/{ref}" if base else ref
            referenced.add(_normalize(full))
    return sorted(rel for rel in yaml_rels if _normalize(rel) not in referenced)


def _normalize(path: str) -> str:
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


def compare(
    runtime_root: Path | str,
    projet_root: Path | str,
    progress: ProgressCallback | None = None,
    cancel: CancelCheck | None = None,
) -> Comparison:
    """Analyse complète (phase 1). Longue : à lancer dans un thread de travail."""
    started = time.perf_counter()
    runtime_root = Path(runtime_root)
    projet_root = Path(projet_root)

    inventory = build_inventory(runtime_root, projet_root, progress=progress, cancel=cancel)
    result = Comparison(
        runtime_root=runtime_root,
        projet_root=projet_root,
        version_runtime=read_ide_version(runtime_root),
        version_projet=read_ide_version(projet_root),
        inventory=inventory,
    )

    # 1. Le .optix : ses statistiques ne sont jamais une divergence.
    optix_entries = [e for e in inventory.common() if e.suffix == ".optix"]
    for entry in optix_entries:
        delta = compare_optix(
            read_text_file(projet_root / entry.rel).lines, read_text_file(runtime_root / entry.rel).lines
        )
        result.optix = delta
        if entry.status == "different" and delta.seulement_statistiques:
            entry.attendu = True
            entry.raison_attendu = "seules les statistiques diffèrent (recalculées par l'IDE à l'ouverture)"
        break

    # 2. Diff de chaque fichier texte différent.
    to_diff = [e for e in inventory.entries if e.status == "different" and e.is_text and not e.attendu]
    total = len(to_diff)
    for index, entry in enumerate(to_diff):
        check_cancel(cancel)
        report(progress, "diff", entry.rel, index, total)
        try:
            result.diffs[entry.rel] = diff_file(entry, projet_root / entry.rel, runtime_root / entry.rel)
        except OSError as exc:
            log.error("Diff impossible pour %s : %s", entry.rel, exc)
    report(progress, "diff", "", total, total)

    # 3. Vues spécialisées.
    check_cancel(cancel)
    report(progress, "analyse", "tags CoDeSys et traductions", 0, 4)
    for rel, fd in result.diffs.items():
        if not fd.entry.is_yaml:
            continue
        if is_tags_file(fd.runtime.lines) or is_tags_file(fd.projet.lines):
            result.tags[rel] = compare_tags(fd.projet.lines, fd.runtime.lines)
        elif parse_translations(fd.runtime.lines) is not None:
            result.translations[rel] = compare_translations(fd.projet.lines, fd.runtime.lines)

    check_cancel(cancel)
    report(progress, "analyse", "types utilisateur", 1, 4)
    module = inventory.get(USER_DEFINED_MODULE)
    if module is not None and module.status in ("identique", "different"):
        result.types = compare_type_guids(
            read_text_file(projet_root / USER_DEFINED_MODULE).lines,
            read_text_file(runtime_root / USER_DEFINED_MODULE).lines,
        )
    constants = projet_root / TYPE_CONSTANTS
    if constants.is_file():
        result.type_names = guid_to_name(read_text_file(constants).lines)
    xml_diff = result.diffs.get(USER_DEFINED_MODULE)
    if xml_diff is not None:
        # L'unité de ce fichier est le TypeMapping, identifié par GUID : un bloc déplacé n'est pas un écart.
        xml_diff.semantic = describe_type_mappings(xml_diff.projet.lines, xml_diff.runtime.lines, result.type_names)

    check_cancel(cancel)
    report(progress, "analyse", "NetLogic", 2, 4)
    dll_name = f"{result.optix.projet.name}.dll" if result.optix and result.optix.projet.name else ""
    dlls = [
        e
        for e in inventory.common()
        if e.rel.startswith(NETSOLUTION_BIN) and e.suffix == ".dll" and (not dll_name or e.name == dll_name)
    ]
    if dlls:
        dll = dlls[0]
        result.netlogic = compare_dlls(projet_root / dll.rel, runtime_root / dll.rel)
        sources = {
            e.name[:-3]: e.rel
            for e in inventory.entries
            if e.suffix == ".cs" and e.rel.startswith("ProjectFiles/NetSolution/") and e.size_projet is not None
        }
        result.netlogic.sources_projet = {c: sources[c] for c in result.netlogic.projet_seul if c in sources}

    check_cancel(cancel)
    report(progress, "analyse", "fichiers orphelins", 3, 4)
    nodes_root = result.optix.projet.nodes_root if result.optix else ""
    projet_yaml = [e.rel for e in inventory.entries if e.is_yaml and e.rel.startswith("Nodes/") and e.size_projet is not None]
    runtime_yaml = [e.rel for e in inventory.entries if e.is_yaml and e.rel.startswith("Nodes/") and e.size_runtime is not None]
    result.orphelins_projet = find_orphans(projet_root, nodes_root, projet_yaml)
    result.orphelins_runtime = find_orphans(runtime_root, nodes_root, runtime_yaml)
    report(progress, "analyse", "", 4, 4)

    result.duree_s = time.perf_counter() - started
    log.info("Comparaison terminée en %.1f s : %d fichiers différents", result.duree_s, len(result.diffs))
    return result
