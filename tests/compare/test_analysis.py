"""Comparaison complète du couple synthétique : progression, synthèse, classement, orphelins."""

from __future__ import annotations

from optixplus.common.progress import Progress
from optixplus.modules.compare.core.analysis import Comparison, compare

from .conftest import ORPHELIN, PROJET, RUNTIME, SCREENS, TAGS, TRANSLATIONS


def test_progression_par_phase() -> None:
    steps: list[Progress] = []
    compare(RUNTIME, PROJET, progress=steps.append)
    assert {s.phase for s in steps} == {"inventaire", "hash", "diff", "analyse"}


def test_synthese(demo: Comparison) -> None:
    assert demo.version_runtime == demo.version_projet == "1.3.2.9-Stable"
    assert demo.versions_compatibles
    s = demo.synthese()
    assert s.nb_yaml_communs == 10
    assert s.nb_yaml_divergents == 6
    assert s.nb_ajouts_runtime == 3  # Acquit_Z1+Z2 (1 hunk), EnHaut, traduction
    assert s.nb_branche_projet == 4  # Fault_SurchauffeGHDel, PlanSciage_Manu, Division/Division.yaml, TypeMapping XML
    assert s.nb_valeurs_modifiees == 3  # AvecScanner, TopMargin, LeftMargin
    assert s.nb_non_significatifs == 2  # Id d'Enum_Taille, Dimensions
    assert s.nb_projet_seul == 2  # Division.yaml (branche projet) et Orphelin.yaml
    assert s.nb_runtime_seul == 0


def test_classement_et_categories_attendues(demo: Comparison) -> None:
    inv = demo.inventory
    divergents = {e.rel for e in inv.divergents()}
    assert divergents == {
        "Nodes/Alarms/Alarms.yaml",
        TAGS,
        "Nodes/Model/Model.yaml",
        TRANSLATIONS,
        "Nodes/UI/Parents/Parents.yaml",
        SCREENS,
        "Nodes/UI/Parents/Division/Division.yaml",
        ORPHELIN,
        "ProjectFiles/UserDefinedModule.xml",
    }
    attendus = {e.rel: e.raison_attendu for e in inv.attendus()}
    assert "IHM_Demo.optix" in attendus and "statistiques" in attendus["IHM_Demo.optix"]
    assert "ApplicationFiles/RetentivityStorage.db" in attendus
    assert "IHM_Demo.source.password" in attendus
    assert "ProjectFiles/NetSolution/Private/TypeConstants.cs" in attendus
    assert "ProjectFiles/NetSolution/obj/project.assets.json" in attendus
    assert "DesignTimeNodes/CommDrivers/TagImporter.yaml" in attendus
    assert "IHM_Demo.optix.design" in attendus
    assert inv.get("ProjectFiles/Images/logo.svg").status == "identique"


def test_meme_taille_contenu_different(demo: Comparison) -> None:
    entry = demo.inventory.get(SCREENS)
    assert entry is not None and entry.size_projet == entry.size_runtime and entry.status == "different"
    assert demo.diffs[entry.rel].sens == "valeur_modifiee"


def test_fichiers_crlf_preserves(demo: Comparison) -> None:
    for fd in demo.diffs.values():
        if fd.entry.is_yaml:
            assert fd.projet.eol == b"\r\n" and fd.runtime.eol == b"\r\n"
            assert fd.projet.final_eol and fd.runtime.final_eol


def test_orphelins(demo: Comparison) -> None:
    """Le YAML du projet qu'aucun ``- File:`` ne référence est signalé orphelin."""
    assert demo.orphelins_projet == [ORPHELIN]
    assert demo.orphelins_runtime == []
