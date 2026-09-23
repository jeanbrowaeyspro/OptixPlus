"""Critères d'acceptation sur un couple réel runtime / projet d'un client.

Les données et le résultat attendu (``optixplus_expected.json``) vivent hors dépôt, à
l'emplacement donné par ``OPTIXPLUS_COMPARE_DATA`` ; sans eux, ces tests sont ignorés.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from optixplus.modules.compare.core.analysis import Comparison
from optixplus.modules.compare.core.diffing import merge_lines
from optixplus.modules.compare.core.extractors.generated_cs import (
    braces_balanced,
    parse_ui_type_definitions,
    prune_type_constants,
    prune_ui_type_definitions,
)
from optixplus.common.optix.text import TextFile, md5_of_bytes, read_text_file

pytestmark = pytest.mark.couple_reel

TAGS = "Nodes/CommDrivers/CODESYSDriver/API_CentreDeReprise/Tags/Tags.yaml"
MODEL = "Nodes/Model/Model.yaml"
TRANSLATIONS = "Nodes/Translations/Translations.yaml"
MANU = "Nodes/UI/Screens/04_Manual/Manu_Mechanizations/Manu_Mechanizations.yaml"


# 1. Versions IDE ---------------------------------------------------------------


def test_versions_ide(comparison: Comparison, expected: dict) -> None:
    assert comparison.version_runtime == expected["ide_version"]["runtime"]
    assert comparison.version_projet == expected["ide_version"]["projet"]
    assert comparison.versions_compatibles is expected["ide_version"]["compatible"]


# 2. Inventaire -----------------------------------------------------------------


def test_inventaire(comparison: Comparison, expected: dict) -> None:
    synth = comparison.synthese()
    inv = expected["inventaire"]
    assert synth.nb_yaml_communs == inv["yaml_communs"]
    assert synth.nb_yaml_divergents == inv["yaml_divergents"]
    assert len(comparison.inventory.by_status("projet_seul")) == inv["fichiers_projet_seul"]
    assert len(comparison.inventory.by_status("runtime_seul")) == inv["fichiers_runtime_seul"]
    assert synth.nb_projet_seul == inv["fichiers_projet_seul_significatifs"]
    assert synth.nb_runtime_seul == inv["fichiers_runtime_seul_significatifs"]


def test_fichiers_divergents_et_sens(comparison: Comparison, expected: dict) -> None:
    attendus = {f["chemin"]: f for f in expected["fichiers_divergents"]}
    obtenus = {e.rel: e for e in comparison.yaml_divergents()}
    assert set(obtenus) == set(attendus)
    for rel, exp in attendus.items():
        entry = obtenus[rel]
        assert entry.size_projet == exp["taille_projet"], rel
        assert entry.size_runtime == exp["taille_runtime"], rel
        assert comparison.diffs[rel].sens == exp["sens"], rel


def test_meme_taille_contenu_different(comparison: Comparison) -> None:
    entry = comparison.inventory.get(MANU)
    assert entry is not None
    assert entry.size_projet == entry.size_runtime
    assert entry.status == "different"
    assert entry.md5_projet != entry.md5_runtime


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


# 3. Tags CoDeSys -----------------------------------------------------------------


def test_tags_ajoutes_cote_runtime(comparison: Comparison, expected: dict) -> None:
    delta = comparison.tags[TAGS]
    ajoutes = {t.symbol: t for t in delta.runtime_seul}
    corr = expected["correctifs_ajouts_runtime"]
    for exp in corr["tags_ajoutes"]:
        tag = ajoutes.pop(exp["symbol"], None)
        assert tag is not None, exp["nom"]
        assert tag.name == exp["nom"] and tag.type == exp["type"]
        if "data_type" in exp:
            assert tag.data_type == exp["data_type"]
        if "membres" in exp:
            assert tag.membres == exp["membres"]
    for exp in corr["membres_ajoutes_dans_Statuts_TRSFP2_PinStops"]:
        tag = ajoutes.pop(exp["symbol"], None)
        assert tag is not None, exp["nom"]
        assert tag.name == exp["nom"] and tag.data_type == exp["data_type"]
        assert tag.array == (str(exp["array"]) if "array" in exp else "")
    assert ajoutes == {}, "tags ajoutés non prévus"
    assert delta.modifies == []


def test_structures_branche_projet(comparison: Comparison, expected: dict) -> None:
    delta = comparison.tags[TAGS]
    assert [t.name for t in delta.projet_seul] == expected["branche_projet"]["tags_structures"]
    assert all(t.is_structure for t in delta.projet_seul)


def test_opcodes_insert_dans_tags(comparison: Comparison, expected: dict) -> None:
    fd = comparison.diffs[TAGS]
    assert sum(1 for h in fd.hunks if h.tag == "insert") == expected["correctifs_ajouts_runtime"]["nb_opcodes_insert_dans_Tags_yaml"]
    noms = {n for s in fd.semantic if s.sens == "ajout_runtime" for n in s.noeuds}
    assert {t["nom"] for t in expected["correctifs_ajouts_runtime"]["tags_ajoutes"]} <= noms
    assert all(s.genre == "bloc" for s in fd.semantic)


# 4. Valeur modifiée et identifiants ---------------------------------------------


def test_avec_scanner_et_ids_non_significatifs(comparison: Comparison, expected: dict) -> None:
    fd = comparison.diffs[MODEL]
    valeur = expected["correctifs_ajouts_runtime"]["valeur_modifiee"]
    significatifs = fd.significatifs
    assert len(significatifs) == 1
    s = significatifs[0]
    assert s.genre == "valeur" and s.noeud == valeur["noeud"]
    assert s.chemin.startswith(valeur["chemin_parent"] + "/")
    assert s.detail == f"Value: `{str(valeur['projet']).lower()}` → `{str(valeur['runtime']).lower()}`"

    ids = [s for s in fd.semantic if not s.significatif]
    non_sig = expected["non_significatif"]["model_yaml_lignes_Id"]
    assert len(ids) == non_sig["nombre"]
    assert all(s.genre == "id" and s.sens == "branche_projet" for s in ids)
    assert [s.noeud for s in ids] == non_sig["noeuds"]


# 5. Traductions -------------------------------------------------------------------


def test_traduction_manquante(comparison: Comparison, expected: dict) -> None:
    delta = comparison.translations[TRANSLATIONS]
    trad = expected["correctifs_ajouts_runtime"]["traduction_ajoutee"]
    assert list(delta.dimensions_projet or ()) == trad["dimensions_projet"]
    assert list(delta.dimensions_runtime or ()) == trad["dimensions_runtime"]
    assert delta.runtime_seul == [trad["ligne"]]
    assert delta.projet_seul == [] and delta.modifies == []
    assert delta.projet is not None and delta.projet.coherent
    assert delta.runtime is not None and delta.runtime.coherent

    fd = comparison.diffs[TRANSLATIONS]
    assert fd.sens == "ajout_runtime"
    assert [s.genre for s in fd.semantic if not s.significatif] == ["dimensions"]


# 6. Types utilisateur -------------------------------------------------------------


def test_guids_types_retires(comparison: Comparison, expected: dict) -> None:
    assert comparison.types is not None
    attendus = {g["guid"]: g["nom"] for g in expected["branche_projet"]["guids_types_retires"]}
    assert set(comparison.types.projet_seul) == set(attendus)
    assert comparison.types.runtime_seul == []
    for guid, nom in attendus.items():
        assert comparison.type_names[guid] == nom
        assert nom.startswith("IType_Div_")
    conserves = {g["nom"] for g in expected["branche_projet"]["guids_a_conserver_malgre_le_nom"]}
    noms_retires = {comparison.type_names[g] for g in comparison.types.projet_seul}
    assert conserves.isdisjoint(noms_retires)
    assert conserves <= set(comparison.type_names.values())


def test_elagage_fichiers_generes_par_guid(couple_reel: tuple[Path, Path], comparison: Comparison, expected: dict) -> None:
    _, projet = couple_reel
    guids = comparison.types.projet_seul if comparison.types else []
    exp = expected["branche_projet"]["elagage_fichiers_generes"]

    tc = read_text_file(projet / "ProjectFiles/NetSolution/Private/TypeConstants.cs")
    exp_tc = exp["ProjectFiles/NetSolution/Private/TypeConstants.cs"]
    assert len(tc.lines) == exp_tc["lignes_avant"]
    tc_apres = prune_type_constants(tc.lines, guids)
    assert len(tc_apres) == exp_tc["lignes_apres"]
    assert not any(b"IType_Div_" in line for line in tc_apres)
    assert any(b"IType_TextErreurDivision" in line for line in tc_apres)
    assert any(b"IType_API_Infos_Deligneuse" in line for line in tc_apres)

    ui = read_text_file(projet / "ProjectFiles/NetSolution/Private/UITypeDefinitions.cs")
    exp_ui = exp["ProjectFiles/NetSolution/Private/UITypeDefinitions.cs"]
    assert len(ui.lines) == exp_ui["lignes_avant"]
    assert len(parse_ui_type_definitions(ui.lines)) == exp_ui["classes_avant"]
    ui_apres = prune_ui_type_definitions(ui.lines, guids)
    assert len(ui_apres) == exp_ui["lignes_apres"]
    assert len(parse_ui_type_definitions(ui_apres)) == exp_ui["classes_apres"]
    assert braces_balanced(ui_apres)


# 7. Fichiers structurellement normaux ---------------------------------------------


def test_aucune_divergence_sur_les_fichiers_attendus(comparison: Comparison, expected: dict) -> None:
    divergents = {e.rel for e in comparison.inventory.divergents()}
    cats = expected["categories_attendues"]
    for motif in cats["runtime_seul"] + cats["projet_seul"]:
        for rel in divergents:
            if motif.endswith("/"):
                assert not rel.startswith(motif), rel
            elif "*" in motif:
                prefix, suffix = motif.split("*", 1)
                assert not (rel.startswith(prefix) and rel.endswith(suffix) and rel.count("/") == prefix.count("/")), rel
            else:
                assert rel != motif, rel
    assert not any(rel.endswith(".cs") or rel.endswith(".sln") or "/obj/" in rel for rel in divergents)
    optix = comparison.inventory.get(expected["fichier_optix"])
    assert optix is not None and optix.attendu and optix.status == "different"


def test_statistiques_optix_informatives(comparison: Comparison, expected: dict) -> None:
    assert comparison.optix is not None and comparison.optix.seulement_statistiques
    stats = expected["optix_statistiques"]
    for key, projet_val in stats["projet"].items():
        assert comparison.optix.projet.statistics[key] == projet_val
    for key, runtime_val in stats["runtime"].items():
        assert comparison.optix.runtime.statistics[key] == runtime_val


# 8. Branche projet : blocs nommés -------------------------------------------------


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


def test_marges_modifiees(comparison: Comparison, expected: dict) -> None:
    fd = comparison.diffs[MANU]
    attendu = {c["noeud"]: (c["projet"], c["runtime"]) for c in expected["correctifs_ajouts_runtime"]["marges_modifiees"]["changements"]}
    assert {s.noeud: s.detail for s in fd.semantic} == {
        noeud: f"Value: `{p}` → `{r}`" for noeud, (p, r) in attendu.items()
    }


# 9. NetLogic ------------------------------------------------------------------------


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


# 10. Mode « récupérer les ajouts du runtime » ---------------------------------------


def test_recuperer_les_ajouts_du_runtime(couple_reel: tuple[Path, Path], comparison: Comparison, expected: dict) -> None:
    runtime, _ = couple_reel
    tailles = expected["correctifs_ajouts_runtime"]["tailles_apres_application"]
    for rel, taille in tailles.items():
        fd = comparison.diffs[rel]
        modes = {"insert", "replace"} if rel in (MODEL, MANU) else {"insert"}
        if rel == TRANSLATIONS:
            modes = {"insert", "replace"}  # la virgule de fin de ligne et Dimensions sont des replace
        fusion = TextFile(
            lines=merge_lines(fd.projet.lines, fd.runtime.lines, fd.opcodes, modes=modes),
            eol=fd.projet.eol,
            final_eol=fd.projet.final_eol,
            bom=fd.projet.bom,
        )
        contenu = fusion.to_bytes()
        assert len(contenu) == taille, rel
        if rel in (TRANSLATIONS, MANU):
            assert md5_of_bytes(contenu) == md5_of_bytes((runtime / rel).read_bytes()), rel

    tags = comparison.diffs[TAGS]
    fusion_tags = merge_lines(tags.projet.lines, tags.runtime.lines, tags.opcodes, modes={"insert"})
    from optixplus.modules.compare.core.diffing import diff_lines
    from optixplus.modules.compare.core.nodes import describe_hunks

    reste = describe_hunks(diff_lines(fusion_tags, tags.runtime.lines), fusion_tags, tags.runtime.lines)
    assert [s.sens for s in reste] == ["branche_projet"] * len(reste)
    assert sorted(n for s in reste for n in s.noeuds) == sorted(expected["branche_projet"]["tags_structures"])


# 11. Plan de décision (phase 2) sur le couple réel ------------------------------------


def test_plan_recuperer_ajouts_et_valeurs(couple_reel: tuple[Path, Path], comparison: Comparison, expected: dict) -> None:
    from optixplus.modules.compare.core.plan import Plan, build_preview

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
    from optixplus.modules.compare.core.plan import Plan, build_preview

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
    tc = preview.change("ProjectFiles/NetSolution/Private/TypeConstants.cs")
    ui = preview.change("ProjectFiles/NetSolution/Private/UITypeDefinitions.cs")
    assert tc is not None and len(tc.new.split(b"\r\n")) - 1 == exp["ProjectFiles/NetSolution/Private/TypeConstants.cs"]["lignes_apres"]
    assert ui is not None and ui.new.count(b"[MapType") == exp["ProjectFiles/NetSolution/Private/UITypeDefinitions.cs"]["classes_apres"]
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
