"""Le couple synthétique versionné ``tests/fixtures`` : un exemplaire de chaque type d'écart.

C'est ce couple qui fait tourner les tests sans dépendre du couple réel réel.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from optixplus.modules.compare.core.analysis import Comparison, compare
from optixplus.modules.compare.core.diffing import merge_lines
from optixplus.modules.compare.core.extractors.translations import parse_translations
from optixplus.common.optix.text import TextFile, split_lines
from optixplus.common.progress import Progress

FIXTURES = Path(__file__).resolve().parent / "fixtures"
RUNTIME = FIXTURES / "runtime" / "IHM_Demo"
PROJET = FIXTURES / "projet" / "IHM_Demo"

TAGS = "Nodes/CommDrivers/CODESYSDriver/API_Demo/Tags/Tags.yaml"
TRANSLATIONS = "Nodes/Translations/Translations.yaml"


@pytest.fixture(scope="module")
def demo() -> Comparison:
    steps: list[Progress] = []
    result = compare(RUNTIME, PROJET, progress=steps.append)
    assert {s.phase for s in steps} == {"inventaire", "hash", "diff", "analyse"}
    return result


def test_versions(demo: Comparison) -> None:
    assert demo.version_runtime == demo.version_projet == "1.3.2.9-Stable"
    assert demo.versions_compatibles


def test_fichiers_crlf_preserves(demo: Comparison) -> None:
    for fd in demo.diffs.values():
        if fd.entry.is_yaml:
            assert fd.projet.eol == b"\r\n" and fd.runtime.eol == b"\r\n"
            assert fd.projet.final_eol and fd.runtime.final_eol


def test_synthese(demo: Comparison) -> None:
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
        "Nodes/UI/Screens/Screens.yaml",
        "Nodes/UI/Parents/Division/Division.yaml",
        "Nodes/UI/Parents/Orphelin/Orphelin.yaml",
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
    entry = demo.inventory.get("Nodes/UI/Screens/Screens.yaml")
    assert entry is not None and entry.size_projet == entry.size_runtime and entry.status == "different"
    fd = demo.diffs[entry.rel]
    assert fd.sens == "valeur_modifiee"
    assert {s.noeud: s.detail for s in fd.semantic} == {
        "TopMargin": "Value: `81.0` → `80.0`",
        "LeftMargin": "Value: `560.0` → `562.0`",
    }
    assert fd.semantic[0].chemin == "Screens/IType_Manual/Panel1/TopMargin"


def test_profondeur_sans_limite(demo: Comparison) -> None:
    assert TAGS in demo.diffs
    assert TAGS.count("/") == 5


def test_tags(demo: Comparison) -> None:
    delta = demo.tags[TAGS]
    assert [(t.name, t.type, t.data_type, t.symbol) for t in delta.runtime_seul] == [
        ("Acquit_Z1", "CODESYSTag", "Boolean", "App_Demo.GVL_IO.Acquit_Z1"),
        ("Acquit_Z2", "CODESYSTag", "Boolean", "App_Demo.GVL_IO.Acquit_Z2"),
        ("EnHaut", "CODESYSTag", "Boolean", "App_Demo.GVL_IO.Statuts.EnHaut"),
    ]
    assert [(t.name, t.membres) for t in delta.projet_seul] == [("PlanSciage_Manu", ["Largeur", "Nombre"])]
    assert delta.modifies == []
    assert {r.symbol for r in delta.rows if r.etat == "identique"} >= {"App_Demo.GVL_IO.Marche", "App_Demo.GVL_IO.Statuts"}

    fd = demo.diffs[TAGS]
    assert fd.sens == "mixte"
    assert [(s.sens, s.noeuds) for s in fd.semantic] == [
        ("ajout_runtime", ["Acquit_Z1", "Acquit_Z2"]),
        ("branche_projet", ["PlanSciage_Manu"]),
        ("ajout_runtime", ["EnHaut"]),
    ]
    assert "App_Demo.GVL_IO.Statuts.EnHaut" in fd.semantic[2].detail


def test_model_valeur_et_id(demo: Comparison) -> None:
    fd = demo.diffs["Nodes/Model/Model.yaml"]
    assert fd.sens == "valeur_modifiee"
    assert [(s.genre, s.noeud, s.significatif) for s in fd.semantic] == [
        ("id", "Enum_Taille", False),
        ("valeur", "AvecScanner", True),
    ]
    assert fd.semantic[1].chemin_parent == "Model"


def test_traductions(demo: Comparison) -> None:
    delta = demo.translations[TRANSLATIONS]
    assert delta.dimensions_projet == (3, 4) and delta.dimensions_runtime == (4, 4)
    assert delta.runtime_seul == [["Créer bois", "Create wood", "Créer bois", "Creare legno"]]
    assert delta.projet is not None and delta.projet.coherent
    assert delta.projet.header == ["", "en-US", "fr-FR", "it-IT"]
    fd = demo.diffs[TRANSLATIONS]
    assert fd.sens == "ajout_runtime"
    assert [s.genre for s in fd.semantic] == ["dimensions", "valeur"]


def test_alarme_branche_projet(demo: Comparison) -> None:
    fd = demo.diffs["Nodes/Alarms/Alarms.yaml"]
    assert fd.sens == "branche_projet"
    assert len(fd.semantic) == 1
    s = fd.semantic[0]
    assert s.genre == "bloc" and s.noeud == "Fault_SurchauffeGHDel"
    assert s.detail == "bloc IType_Demo_Alarm, 11 lignes"
    assert "présent côté projet uniquement" in s.libelle


def test_reference_fichier_et_orphelin(demo: Comparison) -> None:
    fd = demo.diffs["Nodes/UI/Parents/Parents.yaml"]
    assert [(s.genre, s.noeud) for s in fd.semantic] == [("fichier", "Division/Division.yaml")]
    assert demo.orphelins_projet == ["Nodes/UI/Parents/Orphelin/Orphelin.yaml"]
    assert demo.orphelins_runtime == []


def test_types_et_noms(demo: Comparison) -> None:
    assert demo.types is not None
    assert demo.types.projet_seul == ["bc1cc03e5060e72cb67c1d3cd9d84961"]
    assert demo.types.runtime_seul == []
    assert demo.type_names["bc1cc03e5060e72cb67c1d3cd9d84961"] == "IType_Div_BP_Prog"
    assert demo.type_names["8c8a432c986c4c596069cf9ec9a2f980"] == "IType_TextErreurDivision"
    xml = demo.diffs["ProjectFiles/UserDefinedModule.xml"]
    assert [(s.genre, s.sens, s.noeud) for s in xml.semantic] == [("type", "branche_projet", "IType_Div_BP_Prog")]


def test_statistiques_optix(demo: Comparison) -> None:
    assert demo.optix is not None and demo.optix.seulement_statistiques
    rows = {k: (p, r) for k, p, r in demo.optix.stats_rows()}
    assert rows["TotalNodeCount"] == (130, 100)
    assert rows["ObjectTypes"] == (3, 2)
    assert demo.optix.projet.nodes_root == "Nodes/IHM_Demo.yaml"
    assert demo.netlogic is None


def test_recuperer_les_ajouts_du_runtime(demo: Comparison) -> None:
    fd = demo.diffs[TAGS]
    fusion = merge_lines(fd.projet.lines, fd.runtime.lines, fd.opcodes, modes={"insert"})
    texte = TextFile(lines=fusion, eol=fd.projet.eol, final_eol=fd.projet.final_eol).to_bytes()
    assert b"\r\n" in texte and b"Acquit_Z1" in texte and b"PlanSciage_Manu" in texte and b"EnHaut" in texte
    relu = split_lines(texte)
    assert relu.eol == b"\r\n" and relu.lines == fusion

    tr = demo.diffs[TRANSLATIONS]
    fusion_tr = merge_lines(tr.projet.lines, tr.runtime.lines, tr.opcodes, modes={"insert", "replace"})
    table = parse_translations(fusion_tr)
    assert table is not None and table.coherent and table.dimensions == (4, 4)
