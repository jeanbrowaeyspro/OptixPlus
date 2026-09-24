"""Application du plan : sauvegarde, écriture vérifiée, rebut, intégrité, restauration — sur une copie du couple synthétique."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from optixplus.common.optix.text import md5_of_file
from optixplus.common.progress import Progress
from optixplus.modules.compare.core import apply as apply_module
from optixplus.modules.compare.core.analysis import USER_DEFINED_MODULE, compare
from optixplus.modules.compare.core.apply import ApplyError, apply_preview, check_locks, list_backups, read_manifest, restore_backup
from optixplus.modules.compare.core.plan import REBUT_DIR, Plan, build_preview

from .conftest import DIVISION, ORPHELIN, TAGS, TRANSLATIONS


def _snapshot(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): md5_of_file(p) for p in root.rglob("*") if p.is_file()}


def test_plan_vide_rien_a_appliquer(couple: tuple[Path, Path]) -> None:
    runtime, projet = couple
    comparison = compare(runtime, projet)
    plan = Plan()
    assert plan.est_vide()
    preview = build_preview(plan, comparison)
    assert preview.changes == [] and preview.avertissements == []
    rapport = apply_preview(preview, plan, comparison)
    assert rapport.backup_dir is None and rapport.avertissements == ["Rien à appliquer."]
    assert list_backups(projet) == []


def test_recuperer_les_ajouts_puis_restaurer(couple: tuple[Path, Path]) -> None:
    runtime, projet = couple
    avant = _snapshot(projet)
    comparison = compare(runtime, projet)
    plan = Plan()
    plan.recuperer_ajouts(comparison)
    preview = build_preview(plan, comparison)
    steps: list[Progress] = []
    rapport = apply_preview(preview, plan, comparison, progress=steps.append)

    assert rapport.succes and rapport.backup_dir is not None and rapport.backup_dir.name.startswith("_FTOCompare_Sauvegarde_")
    assert {rel for rel, _ in rapport.ecrits} == {TAGS, TRANSLATIONS}
    assert {s.phase for s in steps} == {"sauvegarde", "ecriture", "integrite"}
    for rel, md5 in rapport.ecrits:
        assert md5_of_file(projet / rel) == md5, "relu depuis le disque"
        assert md5_of_file(rapport.backup_dir / rel) == avant[rel], "la sauvegarde est l'original"
    assert (projet / TRANSLATIONS).read_bytes() == (runtime / TRANSLATIONS).read_bytes()
    assert b"Acquit_Z1" in (projet / TAGS).read_bytes() and b"PlanSciage_Manu" in (projet / TAGS).read_bytes()
    assert (projet / TAGS).read_bytes().count(b"\r\n") > 0
    assert rapport.deplaces == [] and rapport.references == []
    assert any("FT Optix" in a for a in rapport.a_faire)
    manifest = read_manifest(rapport.backup_dir)
    assert sorted(manifest["fichiers"]) == sorted([TAGS, TRANSLATIONS]) and manifest["projet"] == str(projet)
    assert list_backups(projet) == [rapport.backup_dir]

    # La comparaison relancée ne voit plus d'ajouts runtime.
    apres = compare(runtime, projet)
    assert apres.synthese().nb_ajouts_runtime == 0

    restaures = restore_backup(rapport.backup_dir)
    assert sorted(restaures) == sorted([TAGS, TRANSLATIONS])
    assert _snapshot(projet) == avant


def test_alignement_complet_avec_rebut_et_integrite(couple: tuple[Path, Path]) -> None:
    runtime, projet = couple
    avant = _snapshot(projet)
    comparison = compare(runtime, projet)
    plan = Plan(deplacer_orphelins=True, copier_statistiques=True)
    plan.aligner_complet(comparison)
    preview = build_preview(plan, comparison)
    assert preview.noms_retires and "Fault_SurchauffeGHDel" in preview.noms_retires
    rapport = apply_preview(preview, plan, comparison)
    assert rapport.succes
    assert not (projet / DIVISION).exists()
    assert len(rapport.deplaces) == 1 and rapport.deplaces[0][0] == DIVISION
    dest = projet / rapport.deplaces[0][1]
    assert dest.exists() and any(part.startswith(REBUT_DIR) for part in dest.parts)
    assert b"IType_Div_BP_Prog" not in (projet / USER_DEFINED_MODULE).read_bytes()
    assert b"IType_Div_BP_Prog" not in (projet / "ProjectFiles/NetSolution/Private/UITypeDefinitions.cs").read_bytes()
    assert ORPHELIN in rapport.orphelins_restants
    assert any("rebut" in a for a in rapport.a_faire) and any(".NET" in a for a in rapport.a_faire)

    apres = compare(runtime, projet)
    assert apres.synthese().nb_divergents == 1, "il ne reste que le YAML orphelin d'origine côté projet"
    assert [e.rel for e in apres.inventory.divergents()] == [ORPHELIN]

    restore_backup(rapport.backup_dir, projet)
    assert (projet / DIVISION).exists()
    assert _snapshot(projet) == avant


def test_echec_d_ecriture_restaure_tout(couple: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, projet = couple
    avant = _snapshot(projet)
    comparison = compare(runtime, projet)
    plan = Plan()
    plan.recuperer_ajouts(comparison)
    preview = build_preview(plan, comparison)

    calls: list[Path] = []
    vrai = apply_module.md5_of_file

    def md5_defaillant(path, *args, **kwargs):
        calls.append(Path(path))
        if len(calls) == 2:
            return "0" * 32  # deuxième fichier : relecture « corrompue »
        return vrai(path, *args, **kwargs)

    monkeypatch.setattr(apply_module, "md5_of_file", md5_defaillant)
    with pytest.raises(ApplyError, match="restaurés"):
        apply_preview(preview, plan, comparison)
    monkeypatch.setattr(apply_module, "md5_of_file", vrai)
    assert _snapshot(projet) == avant, "rien ne reste d'un état partiellement appliqué"


def test_verrous(couple: tuple[Path, Path]) -> None:
    runtime, projet = couple
    cible = projet / TAGS
    cible.chmod(stat.S_IREAD)
    try:
        assert check_locks(projet, [TAGS, "absent.yaml"]) == [TAGS]
        comparison = compare(runtime, projet)
        plan = Plan()
        plan.recuperer_ajouts(comparison)
        with pytest.raises(ApplyError, match="verrouillés"):
            apply_preview(build_preview(plan, comparison), plan, comparison)
        assert list_backups(projet) == [], "aucune sauvegarde créée si un verrou bloque"
    finally:
        os.chmod(cible, stat.S_IWRITE | stat.S_IREAD)
