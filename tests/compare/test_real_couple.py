"""Suite d'acceptation, sur demande, sur un couple réel runtime / projet d'un client.

Les données et le résultat attendu (``optixplus_expected.json``) vivent hors dépôt, à
l'emplacement donné par ``OPTIXPLUS_COMPARE_DATA`` ; sans eux, ces tests sont ignorés.

Seuls restent ici les comportements que le couple synthétique ne sait pas reproduire :
DLL NetLogic, élagage des fichiers C# générés, tableaux de tags, types conservés malgré leur
nom, avertissements ``Project.Current.Find`` et tailles réelles après application du plan.
Tout le reste est vérifié sur le couple synthétique.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from optixplus.common.optix.text import read_text_file
from optixplus.modules.compare.core.analysis import Comparison
from optixplus.modules.compare.core.extractors.generated_cs import (
    braces_balanced,
    parse_ui_type_definitions,
    prune_type_constants,
    prune_ui_type_definitions,
)
from optixplus.modules.compare.core.plan import Plan, build_preview

pytestmark = pytest.mark.couple_reel

TAGS = "Nodes/CommDrivers/CODESYSDriver/API_CentreDeReprise/Tags/Tags.yaml"
TRANSLATIONS = "Nodes/Translations/Translations.yaml"
MANU = "Nodes/UI/Screens/04_Manual/Manu_Mechanizations/Manu_Mechanizations.yaml"
TYPE_CONSTANTS = "ProjectFiles/NetSolution/Private/TypeConstants.cs"
UI_TYPES = "ProjectFiles/NetSolution/Private/UITypeDefinitions.cs"


def test_autres_fichiers_divergents(comparison: Comparison, expected: dict) -> None:
    for exp in expected["autres_fichiers_divergents"]:
        entry = comparison.inventory.get(exp["chemin"])
        assert entry is not None and entry.status == "different", exp["chemin"]
        assert entry.size_projet == exp["taille_projet"]
        assert entry.size_runtime == exp["taille_runtime"]
    assert comparison.types is not None
    module = expected["autres_fichiers_divergents"][0]
    assert len(comparison.types.projet) == module["typemappings_projet"]
    assert len(comparison.types.runtime) == module["typemappings_runtime"]


def test_tableaux_de_tags(comparison: Comparison, expected: dict) -> None:
    """Les membres ajoutés dans une structure, dont des tableaux, sont reconnus avec leur dimension."""
    ajoutes = {t.symbol: t for t in comparison.tags[TAGS].runtime_seul}
    membres = expected["correctifs_ajouts_runtime"]["membres_ajoutes_dans_Statuts_TRSFP2_PinStops"]
    assert any("array" in exp for exp in membres), "le résultat attendu doit contenir un tableau"
    for exp in membres:
        tag = ajoutes.get(exp["symbol"])
        assert tag is not None, exp["nom"]
        assert tag.name == exp["nom"] and tag.data_type == exp["data_type"]
        assert tag.array == (str(exp["array"]) if "array" in exp else "")


def test_types_conserves_malgre_le_nom(comparison: Comparison, expected: dict) -> None:
    """Seuls les GUID absents du runtime sont retirés, pas tous les types au nom semblable."""
    assert comparison.types is not None
    attendus = {g["guid"]: g["nom"] for g in expected["branche_projet"]["guids_types_retires"]}
    assert set(comparison.types.projet_seul) == set(attendus)
    conserves = {g["nom"] for g in expected["branche_projet"]["guids_a_conserver_malgre_le_nom"]}
    noms_retires = {comparison.type_names[g] for g in comparison.types.projet_seul}
    assert conserves.isdisjoint(noms_retires)
    assert conserves <= set(comparison.type_names.values())


def test_elagage_fichiers_generes_par_guid(couple_reel: tuple[Path, Path], comparison: Comparison, expected: dict) -> None:
    _, projet = couple_reel
    guids = comparison.types.projet_seul if comparison.types else []
    exp = expected["branche_projet"]["elagage_fichiers_generes"]

    tc = read_text_file(projet / TYPE_CONSTANTS)
    exp_tc = exp[TYPE_CONSTANTS]
    assert len(tc.lines) == exp_tc["lignes_avant"]
    tc_apres = prune_type_constants(tc.lines, guids)
    assert len(tc_apres) == exp_tc["lignes_apres"]
    assert not any(b"IType_Div_" in line for line in tc_apres)
    assert any(b"IType_TextErreurDivision" in line for line in tc_apres)
    assert any(b"IType_API_Infos_Deligneuse" in line for line in tc_apres)

    ui = read_text_file(projet / UI_TYPES)
    exp_ui = exp[UI_TYPES]
    assert len(ui.lines) == exp_ui["lignes_avant"]
    assert len(parse_ui_type_definitions(ui.lines)) == exp_ui["classes_avant"]
    ui_apres = prune_ui_type_definitions(ui.lines, guids)
    assert len(ui_apres) == exp_ui["lignes_apres"]
    assert len(parse_ui_type_definitions(ui_apres)) == exp_ui["classes_apres"]
    assert braces_balanced(ui_apres)


def test_blocs_branche_projet_nommes(comparison: Comparison, expected: dict) -> None:
    def noms(rel: str) -> set[str]:
        return {n for s in comparison.diffs[rel].semantic if s.sens == "branche_projet" for n in s.noeuds}

    bp = expected["branche_projet"]
    assert set(bp["alarmes_faults"]) <= noms("Nodes/Alarms/Faults/Faults.yaml")
    assert set(bp["alarmes_security"]) <= noms("Nodes/Alarms/Security/Security.yaml")
    ecrans = bp["ecrans"]
    assert {"BackgroundDEL", "DEL_ZoneSecurite", "CanterDEL_ZoneSecurite"} <= noms("Nodes/UI/Screens/Screens.yaml")
    assert any(s.chemin.startswith("Screens/IType_03_Work/") for s in comparison.diffs["Nodes/UI/Screens/Screens.yaml"].semantic)
    assert set(ecrans["04_Manual.yaml"]) <= noms("Nodes/UI/Screens/04_Manual/04_Manual.yaml")
    assert "DelManu" in noms("Nodes/UI/Screens/07_Overwatch/07_Overwatch.yaml")
    assert {"ProcedureDEL", "DEL", "DELMANU"} <= noms("Nodes/UI/Screens/09_Settings/09_Settings.yaml")
    assert {"Title_EntryTable", "Title_Guide", "VitDescPressersDEL", "DelManu", "Del"} <= noms(
        "Nodes/UI/Screens/06_Parameters/Machine/Machine.yaml"
    )
    assert set(ecrans["97_PLCs/Machine.yaml"]) <= noms("Nodes/UI/Screens/97_PLCs/Machine/Machine.yaml")

    parents = comparison.diffs["Nodes/UI/Parents/Parents.yaml"].semantic
    assert len(parents) == 1 and parents[0].genre == "fichier"
    assert parents[0].noeud == "Division/Division.yaml"
    assert comparison.orphelins_projet == [] and comparison.orphelins_runtime == []


def test_netlogic_classes_projet_seul(comparison: Comparison, expected: dict) -> None:
    assert comparison.netlogic is not None and not comparison.netlogic.erreur
    attendu = set(expected["branche_projet"]["netlogic_classes_projet_seul"])
    obtenu = set(comparison.netlogic.projet_seul)
    assert comparison.netlogic.runtime_seul == [], "la DLL du projet doit être un sur-ensemble strict"
    assert attendu <= obtenu
    types = {c for c in obtenu if c.startswith("IType_")}
    assert obtenu - types == attendu
    assert types == {g["nom"] for g in expected["branche_projet"]["guids_types_retires"]}
    for classe in attendu:
        assert comparison.netlogic.sources_projet[classe].endswith(f"/{classe}.cs")


def test_plan_recuperer_ajouts_et_valeurs(couple_reel: tuple[Path, Path], comparison: Comparison, expected: dict) -> None:
    runtime, _ = couple_reel
    plan = Plan()
    plan.recuperer_ajouts(comparison)
    plan.aligner_valeurs(comparison)
    preview = build_preview(plan, comparison)
    tailles = expected["correctifs_ajouts_runtime"]["tailles_apres_application"]
    assert {c.rel for c in preview.changes} == set(tailles)
    for rel, taille in tailles.items():
        change = preview.change(rel)
        assert change is not None and change.taille_apres == taille, rel
    trad = preview.change(TRANSLATIONS)
    assert trad is not None and trad.notes == ["Dimensions recalculées : 2146 → 2147"]
    assert trad.new == (runtime / TRANSLATIONS).read_bytes()
    assert preview.change(MANU).new == (runtime / MANU).read_bytes()
    assert preview.orphelins == [] and preview.types_retires == []
    assert preview.nb_ajouts == 10 and preview.nb_valeurs == 3 and preview.nb_retraits == 0  # 9 tags + 1 traduction


def test_plan_alignement_complet(comparison: Comparison, expected: dict) -> None:
    plan = Plan()
    supprimes = plan.blocs_supprimes(comparison)
    noms = {n for _rel, s in supprimes for n in s.noeuds}
    assert set(expected["branche_projet"]["tags_structures"]) <= noms
    assert set(expected["branche_projet"]["alarmes_faults"]) <= noms
    plan.aligner_complet(comparison)
    preview = build_preview(plan, comparison)
    for rel in comparison.diffs:
        assert preview.change(rel).new == comparison.diffs[rel].runtime.to_bytes(), rel
    attendus = {g["guid"]: g["nom"] for g in expected["branche_projet"]["guids_types_retires"]}
    assert dict(preview.types_retires) == attendus
    exp = expected["branche_projet"]["elagage_fichiers_generes"]
    tc = preview.change(TYPE_CONSTANTS)
    ui = preview.change(UI_TYPES)
    assert tc is not None and len(tc.new.split(b"\r\n")) - 1 == exp[TYPE_CONSTANTS]["lignes_apres"]
    assert ui is not None and ui.new.count(b"[MapType") == exp[UI_TYPES]["classes_apres"]
    assert preview.orphelins == [expected["branche_projet"]["fichier_orphelin_apres_retrait"]]
    conserves = {g["nom"] for g in expected["branche_projet"]["guids_a_conserver_malgre_le_nom"]}
    for nom in conserves:
        assert nom.encode() in tc.new
        if nom.encode() in ui.old:
            assert nom.encode() in ui.new
    xml = comparison.diffs["ProjectFiles/UserDefinedModule.xml"]
    assert xml.sens == "branche_projet"
    assert len(xml.semantic) == 21 and all(s.genre == "type" for s in xml.semantic)
    assert {s.noeud for s in xml.semantic} == set(attendus.values())
    # Les références restantes : les Find("IType_Div_…") par chaîne dans un fichier C# du projet
    refs_cs = {r.rel for r in preview.references if r.rel.endswith(".cs")}
    assert any(r.endswith(expected["fichier_cs_references"]) for r in refs_cs)
    assert any("Project.Current.Find" in a for a in preview.avertissements)
