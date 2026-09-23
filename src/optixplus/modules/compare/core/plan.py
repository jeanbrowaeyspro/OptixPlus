"""Phase 2 — le plan de décision : ce que l'utilisateur a arbitré, et ce que cela entraîne.

Chaque hunk porte une décision (*ignorer* par défaut, *prendre le runtime*, *garder le projet*).
Les actions de masse posent une décision sur un ensemble de hunks. ``build_preview`` calcule,
sans rien écrire, les fichiers qui seraient produits, les actions dérivées (``Dimensions``,
élagage par GUID, fichiers orphelins, statistiques) et les avertissements.

Le plan est sérialisable en JSON pour être rejoué sur une autre paire de dossiers.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .analysis import TYPE_CONSTANTS, UI_TYPE_DEFINITIONS, USER_DEFINED_MODULE, Comparison, FileDiff
from .diffing import Opcode, compute_opcodes, merge_lines
from .extractors.generated_cs import prune_type_constants, prune_ui_type_definitions
from .extractors.module_xml import extract_type_guids, guid_of_hunk_lines, merge_type_mappings
from .extractors.optix_meta import copy_statistics
from .extractors.translations import fix_dimensions
from .integrity import Reference, check_braces, find_references
from .lines import TextFile, read_text_file
from .nodes import SemanticHunk

log = logging.getLogger(__name__)

Decision = Literal["ignorer", "prendre_runtime", "garder_projet"]
DECISIONS: tuple[Decision, ...] = ("ignorer", "prendre_runtime", "garder_projet")
LIBELLE_DECISION: dict[str, str] = {
    "ignorer": "Ignorer",
    "prendre_runtime": "Prendre le runtime",
    "garder_projet": "Garder le projet",
}
HunkKey = tuple[str, Opcode]

REBUT_DIR = "_FTOCompare_Rebut"


@dataclass
class Plan:
    """Les décisions par hunk et les options globales."""

    decisions: dict[HunkKey, Decision] = field(default_factory=dict)
    alignement_complet: set[str] = field(default_factory=set)
    copier_statistiques: bool = False
    deplacer_orphelins: bool = True
    nom: str = ""

    # -- Décisions individuelles ----------------------------------------------------

    def decision(self, rel: str, opcode: Opcode) -> Decision:
        if rel in self.alignement_complet:
            return "prendre_runtime"
        return self.decisions.get((rel, tuple(opcode)), "ignorer")  # type: ignore[arg-type]

    def set_decision(self, rel: str, opcode: Opcode, decision: Decision) -> None:
        key = (rel, tuple(opcode))
        if decision == "ignorer":
            self.decisions.pop(key, None)  # type: ignore[arg-type]
        else:
            self.decisions[key] = decision  # type: ignore[index]
        if decision != "prendre_runtime":
            self.alignement_complet.discard(rel)

    def nb_pris(self) -> int:
        return sum(1 for d in self.decisions.values() if d == "prendre_runtime")

    def est_vide(self) -> bool:
        return not self.decisions and not self.alignement_complet and not self.copier_statistiques

    # -- Actions de masse ----------------------------------------------------------------

    def _diffs(self, comparison: Comparison, rels: Iterable[str] | None) -> list[FileDiff]:
        if rels is None:
            return list(comparison.diffs.values())
        return [comparison.diffs[r] for r in rels if r in comparison.diffs]

    def recuperer_ajouts(self, comparison: Comparison, rels: Iterable[str] | None = None) -> int:
        """Retient les ajouts du runtime (``insert``) : le projet gagne ce qui lui manque sans rien perdre."""
        return self._poser(comparison, rels, ("ajout_runtime",))

    def aligner_valeurs(self, comparison: Comparison, rels: Iterable[str] | None = None) -> int:
        """Retient les valeurs modifiées (``replace``)."""
        return self._poser(comparison, rels, ("valeur_modifiee",))

    def _poser(self, comparison: Comparison, rels: Iterable[str] | None, sens: tuple[str, ...]) -> int:
        n = 0
        for fd in self._diffs(comparison, rels):
            for s in fd.semantic:
                if s.significatif and s.sens in sens:
                    self.set_decision(fd.rel, s.hunk.as_opcode(), "prendre_runtime")
                    n += 1
        return n

    def aligner_complet(self, comparison: Comparison, rels: Iterable[str] | None = None) -> int:
        """Le projet devient identique au runtime pour ces fichiers. À confirmer avec la liste des blocs supprimés."""
        n = 0
        for fd in self._diffs(comparison, rels):
            self.alignement_complet.add(fd.rel)
            for sem in fd.semantic:
                self.decisions[(fd.rel, sem.hunk.as_opcode())] = "prendre_runtime"
                n += 1
        return n

    def tout_ignorer(self, comparison: Comparison, rels: Iterable[str] | None = None) -> None:
        for fd in self._diffs(comparison, rels):
            self.alignement_complet.discard(fd.rel)
            for sem in fd.semantic:
                self.decisions.pop((fd.rel, sem.hunk.as_opcode()), None)

    def blocs_supprimes(self, comparison: Comparison, rels: Iterable[str] | None = None) -> list[tuple[str, SemanticHunk]]:
        """Ce que l'alignement complet supprimerait : les hunks « branche projet », nommés."""
        return [
            (fd.rel, s)
            for fd in self._diffs(comparison, rels)
            for s in fd.semantic
            if s.sens == "branche_projet" and s.significatif
        ]

    # -- Sérialisation -----------------------------------------------------------------------

    def to_dict(self, comparison: Comparison | None = None) -> dict:
        entries = []
        for (rel, opcode), decision in sorted(self.decisions.items()):
            entry: dict = {"fichier": rel, "hunk": list(opcode), "decision": decision}
            sem = _semantic_for(comparison, rel, opcode) if comparison else None
            if sem is not None:
                entry.update({"noeuds": sem.noeuds, "sens": sem.sens, "genre": sem.genre})
            entries.append(entry)
        return {
            "version": 1,
            "nom": self.nom,
            "options": {"copier_statistiques": self.copier_statistiques, "deplacer_orphelins": self.deplacer_orphelins},
            "alignement_complet": sorted(self.alignement_complet),
            "decisions": entries,
        }

    def to_json(self, comparison: Comparison | None = None) -> str:
        return json.dumps(self.to_dict(comparison), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, data: dict, comparison: Comparison | None = None) -> tuple[Plan, list[str]]:
        """Reconstruit un plan ; si ``comparison`` est fournie, réapparie les hunks et signale ceux perdus."""
        plan = cls(
            copier_statistiques=bool(data.get("options", {}).get("copier_statistiques", False)),
            deplacer_orphelins=bool(data.get("options", {}).get("deplacer_orphelins", True)),
            nom=str(data.get("nom", "")),
        )
        plan.alignement_complet = set(data.get("alignement_complet", []))
        perdus: list[str] = []
        for entry in data.get("decisions", []):
            rel = entry["fichier"]
            opcode = tuple(entry["hunk"])
            decision = entry.get("decision", "ignorer")
            if decision not in DECISIONS:
                continue
            if comparison is not None:
                matched = _rematch(comparison, rel, opcode, entry)
                if matched is None:
                    perdus.append(f"{rel} : {', '.join(entry.get('noeuds', [])) or opcode} ({entry.get('sens', '?')})")
                    continue
                opcode = matched
            plan.decisions[(rel, opcode)] = decision  # type: ignore[index]
        if comparison is not None:
            plan.alignement_complet &= set(comparison.diffs)
        return plan, perdus

    @classmethod
    def from_json(cls, text: str, comparison: Comparison | None = None) -> tuple[Plan, list[str]]:
        return cls.from_dict(json.loads(text), comparison)


def _semantic_for(comparison: Comparison, rel: str, opcode: tuple) -> SemanticHunk | None:
    fd = comparison.diffs.get(rel)
    if fd is None:
        return None
    for s in fd.semantic:
        if s.hunk.as_opcode() == opcode:
            return s
    return None


def _rematch(comparison: Comparison, rel: str, opcode: tuple, entry: dict) -> Opcode | None:
    fd = comparison.diffs.get(rel)
    if fd is None:
        return None
    for s in fd.semantic:
        if s.hunk.as_opcode() == opcode:
            return opcode
    noeuds, sens = entry.get("noeuds"), entry.get("sens")
    if noeuds is None:
        return None
    for s in fd.semantic:
        if s.noeuds == noeuds and s.sens == sens:
            return s.hunk.as_opcode()
    return None


# ---------------------------------------------------------------------------
# Prévisualisation
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class FileChange:
    """Un fichier qui serait écrit : contenu avant/après et le récapitulatif de ce qui change."""

    rel: str
    old: bytes
    new: bytes
    origine: str
    nb_ajouts: int = 0
    nb_retraits: int = 0
    nb_valeurs: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def taille_avant(self) -> int:
        return len(self.old)

    @property
    def taille_apres(self) -> int:
        return len(self.new)

    def opcodes(self) -> list[Opcode]:
        """Le diff exact avant → après, pour la prévisualisation."""
        from .lines import split_lines

        return compute_opcodes(split_lines(self.old).lines, split_lines(self.new).lines)


@dataclass(slots=True)
class Preview:
    changes: list[FileChange] = field(default_factory=list)
    orphelins: list[str] = field(default_factory=list)  # YAML qui deviendraient orphelins
    types_retires: list[tuple[str, str]] = field(default_factory=list)  # (guid, nom)
    noms_retires: list[str] = field(default_factory=list)  # blocs YAML retirés (pour le contrôle d'intégrité)
    references: list[Reference] = field(default_factory=list)
    avertissements: list[str] = field(default_factory=list)

    @property
    def nb_ajouts(self) -> int:
        return sum(c.nb_ajouts for c in self.changes)

    @property
    def nb_retraits(self) -> int:
        return sum(c.nb_retraits for c in self.changes)

    @property
    def nb_valeurs(self) -> int:
        return sum(c.nb_valeurs for c in self.changes)

    def change(self, rel: str) -> FileChange | None:
        for c in self.changes:
            if c.rel == rel:
                return c
        return None

    def contenus(self) -> dict[str, bytes]:
        return {c.rel: c.new for c in self.changes}


def _file_refs(lines: Iterable[bytes], rel: str) -> set[str]:
    base = rel.rsplit("/", 1)[0] if "/" in rel else ""
    refs: set[str] = set()
    for line in lines:
        stripped = line.lstrip(b" ")
        if stripped.startswith(b"- File:"):
            value = stripped[len(b"- File:") :].strip().strip(b"'\"").decode("utf-8", "replace").replace("\\", "/")
            refs.add(f"{base}/{value}" if base else value)
    return refs


def build_preview(plan: Plan, comparison: Comparison) -> Preview:
    """Calcule, sans rien écrire, tout ce que l'application du plan produirait."""
    preview = Preview()
    projet_root = comparison.projet_root
    removed_names: list[str] = []
    ignore_lines: dict[str, set[int]] = {}

    for rel, fd in comparison.diffs.items():
        complet = rel in plan.alignement_complet
        hunks = fd.hunks if rel != USER_DEFINED_MODULE else [s.hunk for s in fd.semantic]
        retained = [h for h in hunks if complet or plan.decision(rel, h.as_opcode()) == "prendre_runtime"]
        if not retained:
            continue
        if complet:
            new_lines = list(fd.runtime.lines)
        elif rel == USER_DEFINED_MODULE:
            remove = [guid_of_hunk_lines(fd.projet.lines[h.i1 : h.i2]) or "" for h in retained if h.tag == "delete"]
            add = [guid_of_hunk_lines(fd.runtime.lines[h.j1 : h.j2]) or "" for h in retained if h.tag == "insert"]
            new_lines = merge_type_mappings(fd.projet.lines, fd.runtime.lines, remove, add)
        else:
            new_lines = merge_lines(fd.projet.lines, fd.runtime.lines, fd.opcodes, retenus=retained)
        retained_keys = {h.as_opcode() for h in retained}
        change = FileChange(
            rel=rel,
            old=fd.projet.to_bytes(),
            new=b"",
            origine="alignement complet sur le runtime" if complet else "décisions",
        )
        for s in fd.semantic:
            if s.hunk.as_opcode() not in retained_keys:
                continue
            if s.sens == "ajout_runtime":
                change.nb_ajouts += 1
            elif s.sens == "branche_projet":
                change.nb_retraits += 1
                if s.genre == "bloc":
                    removed_names.extend(s.noeuds)
            elif s.significatif:
                change.nb_valeurs += 1
        if rel in comparison.translations:
            new_lines, fixed = fix_dimensions(new_lines)
            if fixed:
                change.notes.append(f"Dimensions recalculées : {fixed[0]} → {fixed[1]}")
        change.new = TextFile(lines=new_lines, eol=fd.projet.eol, final_eol=fd.projet.final_eol, bom=fd.projet.bom).to_bytes()
        if fd.entry.is_yaml:
            avant = _file_refs(fd.projet.lines, rel)
            apres = _file_refs(new_lines, rel)
            for ref in sorted(avant - apres):
                if (projet_root / ref).is_file():
                    preview.orphelins.append(ref)
                    change.notes.append(f"{ref} devient orphelin")
        if change.new != change.old:
            preview.changes.append(change)

    # Élagage des fichiers générés, piloté par le delta de GUID (jamais par nom).
    xml_change = preview.change(USER_DEFINED_MODULE)
    if xml_change is not None:
        from .lines import split_lines

        before = {m.guid for m in extract_type_guids(split_lines(xml_change.old).lines)}
        after_list = [m.guid for m in extract_type_guids(split_lines(xml_change.new).lines)]
        after = set(after_list)
        if len(after_list) != len(after):
            doublons = sorted({g for g in after_list if after_list.count(g) > 1})
            preview.avertissements.append(
                f"{USER_DEFINED_MODULE} : {len(doublons)} GUID en double après fusion — ne pas appliquer en l'état "
                "(un TypeMapping déplacé a été pris pour un ajout)."
            )
        removed = sorted(before - after)
        if removed:
            preview.types_retires = [(g, comparison.type_names.get(g, "?")) for g in removed]
            removed_names.extend(n for _g, n in preview.types_retires if n != "?")
            for rel, prune in ((TYPE_CONSTANTS, prune_type_constants), (UI_TYPE_DEFINITIONS, prune_ui_type_definitions)):
                path = projet_root / rel
                if not path.is_file():
                    continue
                tf = read_text_file(path)
                pruned = prune(tf.lines, removed)
                new = TextFile(lines=pruned, eol=tf.eol, final_eol=tf.final_eol, bom=tf.bom).to_bytes()
                old = tf.to_bytes()
                if new != old:
                    change = FileChange(rel=rel, old=old, new=new, origine="dérivé : élagage par GUID", nb_retraits=len(removed))
                    change.notes.append(f"{len(removed)} type(s) retiré(s) : " + ", ".join(n for _g, n in preview.types_retires))
                    erreur = check_braces(rel, new)
                    if erreur:
                        preview.avertissements.append(erreur)
                    preview.changes.append(change)
            if comparison.netlogic is not None and comparison.netlogic.sources_projet:
                preview.avertissements.append(
                    "Des types sont retirés : les logiques qui les cherchent par chaîne "
                    "(Project.Current.Find(\"…\")) renverront null à l'exécution. Compilation intacte."
                )

    if plan.copier_statistiques and comparison.optix is not None:
        for entry in comparison.inventory.common():
            if entry.suffix == ".optix":
                p = read_text_file(projet_root / entry.rel)
                r = read_text_file(comparison.runtime_root / entry.rel)
                new = TextFile(lines=copy_statistics(p.lines, r.lines), eol=p.eol, final_eol=p.final_eol, bom=p.bom).to_bytes()
                if new != p.to_bytes():
                    preview.changes.append(FileChange(entry.rel, p.to_bytes(), new, "statistiques .optix (cosmétique)"))
                break

    preview.noms_retires = sorted({n for n in removed_names if n not in {nm for _g, nm in preview.types_retires}})
    if removed_names:
        overrides = preview.contenus()
        preview.references = find_references(projet_root, set(removed_names), overrides=overrides, ignore=ignore_lines)
        preview.references = [r for r in preview.references if r.rel not in plan.alignement_complet or r.rel not in overrides]
        if preview.references:
            preview.avertissements.append(
                f"{len(preview.references)} référence(s) restante(s) à des nœuds ou types retirés — à vérifier avant d'appliquer."
            )
    if preview.orphelins:
        action = "déplacés dans " + REBUT_DIR if plan.deplacer_orphelins else "laissés en place (ignorés par Optix)"
        preview.avertissements.append(f"{len(preview.orphelins)} fichier(s) YAML deviennent orphelins : {action}.")
    return preview


def save_plan(plan: Plan, path: Path | str, comparison: Comparison | None = None) -> None:
    Path(path).write_text(plan.to_json(comparison), encoding="utf-8", newline="\n")


def load_plan(path: Path | str, comparison: Comparison | None = None) -> tuple[Plan, list[str]]:
    return Plan.from_json(Path(path).read_text(encoding="utf-8"), comparison)
