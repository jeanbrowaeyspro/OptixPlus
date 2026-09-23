"""Phase 3 — appliquer et vérifier.

1. contrôle des verrous (le projet doit être fermé dans FT Optix) ;
2. sauvegarde de chaque fichier touché dans ``<parent du projet>/_FTOCompare_Sauvegarde_<horodatage>/`` ;
3. écriture octet pour octet, puis relecture et comparaison de hash ;
4. déplacement des YAML orphelins vers un sous-dossier de rebut (jamais de suppression) ;
5. contrôle d'intégrité : références orphelines, accolades, YAML non référencés ;
6. rapport final et restauration en un appel.

En cas d'échec sur un fichier : arrêt immédiat, restauration de ce qui a déjà été écrit,
message explicite. Jamais d'état partiellement appliqué silencieux.
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ....common.i18n import tr
from .analysis import Comparison, find_orphans
from .integrity import Reference, check_braces, find_references
from ....common.optix.text import md5_of_bytes, md5_of_file
from .plan import REBUT_DIR, Plan, Preview
from ....common.progress import CancelCheck, ProgressCallback, check_cancel, report

log = logging.getLogger(__name__)

BACKUP_PREFIX = "_FTOCompare_Sauvegarde_"
MANIFEST = "manifest.json"


class ApplyError(RuntimeError):
    """Échec d'application ; le projet a été remis dans l'état d'avant."""


@dataclass(slots=True)
class ApplyReport:
    backup_dir: Path | None = None
    ecrits: list[tuple[str, str]] = field(default_factory=list)  # (rel, md5)
    deplaces: list[tuple[str, str]] = field(default_factory=list)  # (rel, destination relative)
    erreurs: list[str] = field(default_factory=list)
    avertissements: list[str] = field(default_factory=list)
    references: list[Reference] = field(default_factory=list)
    orphelins_restants: list[str] = field(default_factory=list)
    a_faire: list[str] = field(default_factory=list)
    restaure: bool = False
    duree_s: float = 0.0

    @property
    def succes(self) -> bool:
        return not self.erreurs and not self.restaure


# ---------------------------------------------------------------------------


def check_locks(projet_root: Path | str, rels: list[str]) -> list[str]:
    """Fichiers qu'on ne peut pas ouvrir en écriture : verrouillés (FT Optix ouvert ?) ou en lecture seule."""
    root = Path(projet_root)
    locked: list[str] = []
    for rel in rels:
        path = root / rel
        if not path.exists():
            continue
        try:
            with open(path, "r+b"):
                pass
        except OSError:
            locked.append(rel)
    return locked


def backup_dir_for(projet_root: Path | str, when: datetime | None = None) -> Path:
    root = Path(projet_root)
    stamp = (when or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return root.parent / f"{BACKUP_PREFIX}{stamp}"


def _copy_preserving(src: Path, root: Path, dest_root: Path) -> Path:
    dest = dest_root / src.relative_to(root)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return dest


def apply_preview(
    preview: Preview,
    plan: Plan,
    comparison: Comparison,
    progress: ProgressCallback | None = None,
    cancel: CancelCheck | None = None,
) -> ApplyReport:
    """Applique une prévisualisation. Lève ``ApplyError`` après restauration en cas d'échec."""
    started = time.perf_counter()
    root = comparison.projet_root
    reportage = ApplyReport()
    rels = [c.rel for c in preview.changes]
    to_move = list(preview.orphelins) if plan.deplacer_orphelins else []

    locked = check_locks(root, rels + to_move)
    if locked:
        raise ApplyError(tr("Locked files (project open in FT Optix?): {files}").format(files=", ".join(locked)))
    if not preview.changes and not to_move:
        reportage.avertissements.append(tr("Nothing to apply."))
        return reportage

    # 2. Sauvegarde
    backup = backup_dir_for(root)
    backup.mkdir(parents=True, exist_ok=False)
    reportage.backup_dir = backup
    manifest = {
        "projet": str(root),
        "horodatage": datetime.now().isoformat(timespec="seconds"),
        "fichiers": [],
        "deplaces": [],
    }
    total = len(rels) + len(to_move)
    for index, rel in enumerate(rels + to_move):
        check_cancel(cancel)
        report(progress, "sauvegarde", rel, index, total)
        src = root / rel
        if src.exists():
            _copy_preserving(src, root, backup)
            manifest["fichiers"].append(rel)
    _write_manifest(backup, manifest)

    # 3. Écriture vérifiée, avec restauration immédiate en cas d'échec
    written: list[str] = []
    try:
        for index, change in enumerate(preview.changes):
            check_cancel(cancel)
            report(progress, "ecriture", change.rel, index, len(preview.changes))
            target = root / change.rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(change.new)
            written.append(change.rel)
            actual = md5_of_file(target)
            expected = md5_of_bytes(change.new)
            if actual != expected:
                raise ApplyError(
                    tr("{file}: hash read back {actual} ≠ expected {expected}").format(file=change.rel, actual=actual, expected=expected)
                )
            reportage.ecrits.append((change.rel, actual))
            log.info("Écrit et vérifié : %s (%s)", change.rel, actual)
        # 4. Rebut des orphelins
        if to_move:
            rebut = root / f"{REBUT_DIR}_{backup.name[len(BACKUP_PREFIX):]}"
            for rel in to_move:
                check_cancel(cancel)
                src = root / rel
                if not src.exists():
                    continue
                dest = rebut / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dest))
                dest_rel = dest.relative_to(root).as_posix()
                reportage.deplaces.append((rel, dest_rel))
                manifest["deplaces"].append([rel, dest_rel])
                log.info("Déplacé au rebut : %s → %s", rel, dest_rel)
            _write_manifest(backup, manifest)
    except BaseException as exc:
        log.error("Échec pendant l'application : %s — restauration", exc)
        _restore_files(backup, root, written, reportage)
        for rel, dest_rel in reportage.deplaces:
            shutil.move(str(root / dest_rel), str(root / rel))
        reportage.deplaces.clear()
        reportage.restaure = True
        reportage.erreurs.append(str(exc))
        reportage.duree_s = time.perf_counter() - started
        raise ApplyError(
            f"{exc} — " + tr("the files already written were restored from {folder}").format(folder=backup)
        ) from exc

    # 5. Intégrité
    report(progress, "integrite", tr("orphan references"), 0, 3)
    noms = list(preview.noms_retires) + [n for _g, n in preview.types_retires if n != "?"]
    if noms:
        reportage.references = find_references(root, noms)
        if reportage.references:
            reportage.avertissements.append(
                tr("{n} reference(s) to removed nodes or types remain — check them in the IDE.").format(n=len(reportage.references))
            )
    report(progress, "integrite", tr("braces"), 1, 3)
    for change in preview.changes:
        erreur = check_braces(change.rel, change.new)
        if erreur:
            reportage.erreurs.append(erreur)
    report(progress, "integrite", tr("orphan YAML files"), 2, 3)
    nodes_root = comparison.optix.projet.nodes_root if comparison.optix else ""
    yaml_rels = sorted(
        p.relative_to(root).as_posix()
        for p in (root / "Nodes").rglob("*.yaml")
        if REBUT_DIR not in p.parts
    ) if (root / "Nodes").is_dir() else []
    reportage.orphelins_restants = find_orphans(root, nodes_root, yaml_rels)
    if reportage.orphelins_restants:
        reportage.avertissements.append(
            tr("{n} unreferenced YAML file(s) remain under Nodes/ (ignored by Optix).").format(n=len(reportage.orphelins_restants))
        )
    report(progress, "integrite", "", 3, 3)

    # 6. Reste à faire
    if any(rel.endswith(".cs") for rel in rels):
        reportage.a_faire.append(tr("Rebuild the .NET solution (ProjectFiles/NetSolution) or let the IDE regenerate it."))
    reportage.a_faire.append(tr("Open the project in FT Optix: the generated files and the statistics will be regenerated."))
    if reportage.deplaces:
        reportage.a_faire.append(tr("Check, then delete by hand the discard folder ({folder}_…).").format(folder=REBUT_DIR))
    if reportage.orphelins_restants:
        reportage.a_faire.append(tr("Decide what to do with the remaining orphan YAML files."))
    reportage.duree_s = time.perf_counter() - started
    return reportage


def _write_manifest(backup: Path, manifest: dict) -> None:
    (backup / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")


def _restore_files(backup: Path, root: Path, rels: list[str], reportage: ApplyReport | None = None) -> list[str]:
    restored: list[str] = []
    for rel in rels:
        src = backup / rel
        dest = root / rel
        if src.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            if md5_of_file(dest) != md5_of_file(src):
                raise ApplyError(tr("restoring {file}: different hash after copying back").format(file=rel))
            restored.append(rel)
        elif dest.exists():
            dest.unlink()  # fichier créé par l'application : il n'existait pas avant
            restored.append(rel)
    return restored


def read_manifest(backup_dir: Path | str) -> dict:
    return json.loads((Path(backup_dir) / MANIFEST).read_text(encoding="utf-8"))


def restore_backup(backup_dir: Path | str, projet_root: Path | str | None = None) -> list[str]:
    """Remet en place les fichiers d'un dossier de sauvegarde et les YAML déplacés au rebut."""
    backup = Path(backup_dir)
    manifest = read_manifest(backup)
    root = Path(projet_root) if projet_root else Path(manifest["projet"])
    restored = _restore_files(backup, root, list(manifest.get("fichiers", [])))
    for rel, dest_rel in manifest.get("deplaces", []):
        moved = root / dest_rel
        if moved.exists():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(moved), str(root / rel))
            restored.append(rel)
    log.info("Restauration depuis %s : %d fichier(s)", backup, len(restored))
    return restored


def list_backups(projet_root: Path | str) -> list[Path]:
    root = Path(projet_root)
    return sorted((p for p in root.parent.glob(f"{BACKUP_PREFIX}*") if (p / MANIFEST).is_file()), reverse=True)
