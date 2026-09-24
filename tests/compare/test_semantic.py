"""Remontée sémantique : des hunks de lignes aux nœuds Optix, sur de petits YAML puis sur le couple synthétique."""

from __future__ import annotations

import pytest

from optixplus.common.optix.scanner import index_nodes
from optixplus.modules.compare.core.analysis import Comparison
from optixplus.modules.compare.core.diffing import Hunk, compute_opcodes, diff_lines, hunks_from_opcodes, sens_global
from optixplus.modules.compare.core.nodes import describe_hunks, sens_semantique

from .conftest import ALARMS, MODEL, PARENTS, SCREENS, TAGS, TRANSLATIONS, tags_file

PROJET = tags_file(["A_Tag", "C_Tag", "Z_Projet"])
RUNTIME = tags_file(["A_Tag", "B_Runtime", "C_Tag"])


# -- Petits YAML ---------------------------------------------------------------------------


def test_index_nodes_chemins_et_bornes() -> None:
    index = index_nodes(PROJET)
    names = [n.path for n in index.nodes if n.kind != "root"]
    assert names[:3] == ["Tags/App", "Tags/App/A_Tag", "Tags/App/A_Tag/SymbolName"]
    root = index.nodes[0]
    assert root.kind == "root" and root.indent == -2 and root.end == len(PROJET)
    app = index.nodes[1]
    assert app.indent == 0 and app.end == len(PROJET)
    a_tag = index.nodes[2]
    assert a_tag.indent == 2 and a_tag.nb_lignes == 9
    assert index.properties(a_tag) == {"Type": "CODESYSTag", "DataType": "Boolean", "Value": "false"}
    assert index.child_value(a_tag, "SymbolName") == "App.IO.A_Tag"
    assert index.enclosing(a_tag.line + 2) is a_tag
    assert [c.name for c in index.children(app)] == ["A_Tag", "C_Tag", "Z_Projet"]


def test_blocs_de_tags() -> None:
    sem = describe_hunks(diff_lines(PROJET, RUNTIME), PROJET, RUNTIME)
    assert [s.genre for s in sem] == ["bloc", "bloc"]
    assert sem[0].sens == "ajout_runtime" and sem[0].noeuds == ["B_Runtime"]
    assert sem[0].chemin == "Tags/App/B_Runtime"
    assert "CODESYSTag Boolean" in sem[0].detail and "App.IO.B_Runtime" in sem[0].detail
    assert sem[1].sens == "branche_projet" and sem[1].noeud == "Z_Projet"
    assert "présent côté projet uniquement" in sem[1].libelle
    assert sens_semantique(sem) == "mixte"


def test_valeur_modifiee_et_id_non_significatif() -> None:
    projet = [
        b"Name: Model",
        b"Type: ModelCategoryFolder",
        b"Children:",
        b"- Name: Enum_X",
        b"  Id: g=fdfba7080932d498240e265326b9b78d",
        b"  Type: BaseObjectType",
        b"- Name: AvecScanner",
        b"  Type: BaseDataVariableType",
        b"  DataType: Boolean",
        b"  Value: false",
    ]
    runtime = [line for line in projet if not line.startswith(b"  Id:")]
    runtime[-1] = b"  Value: true"
    sem = describe_hunks(diff_lines(projet, runtime), projet, runtime)
    assert [s.genre for s in sem] == ["id", "valeur"]
    assert sem[0].significatif is False and sem[0].noeud == "Enum_X"
    assert sem[1].noeud == "AvecScanner" and sem[1].chemin == "Model/AvecScanner"
    assert sem[1].chemin_parent == "Model"
    assert sem[1].detail == "Value: `false` → `true`"
    assert sens_semantique(sem) == "valeur_modifiee"
    assert sens_global(hunks_from_opcodes(compute_opcodes(projet, runtime))) == "mixte"


def test_traduction_virgule_et_dimensions() -> None:
    def dico(rows: list[bytes]) -> list[bytes]:
        body = [b"     " + r + b"," for r in rows[:-1]] + [b"     " + rows[-1]]
        return [
            b"Name: Translations",
            b"Children:",
            b"- Name: TranslationTable",
            b"  Type: LocalizationDictionary",
            b"  Value: ",
            b"   {",
            f'    "Dimensions": [{len(rows)},2],'.encode(),
            b'    "Body": [',
            *body,
            b"    ]",
            b"   }",
        ]

    projet = dico([b'"","en-US"', b'"a","A"'])
    runtime = dico([b'"","en-US"', b'"a","A"', b'"b","B"'])
    sem = describe_hunks(diff_lines(projet, runtime), projet, runtime)
    genres = {s.genre: s for s in sem}
    assert "dimensions" in genres and genres["dimensions"].significatif is False
    assert "[2,2] → [3,2]" in genres["dimensions"].detail
    ajout = [s for s in sem if s.significatif]
    assert len(ajout) == 1 and ajout[0].sens == "ajout_runtime"
    assert '"b","B"' in ajout[0].detail
    assert sens_semantique(sem) == "ajout_runtime"


def test_reference_fichier_retiree() -> None:
    projet = [b"Name: Parents", b"Children:", b"- File: Division/Division.yaml", b"- File: IO/IO.yaml"]
    runtime = [b"Name: Parents", b"Children:", b"- File: IO/IO.yaml"]
    sem = describe_hunks(diff_lines(projet, runtime), projet, runtime)
    assert len(sem) == 1
    assert sem[0].genre == "fichier" and sem[0].noeud == "Division/Division.yaml"
    assert "orphelin" in sem[0].detail
    assert index_nodes(projet).file_refs()[0].name == "Division/Division.yaml"


def test_deplacement_de_bloc_non_significatif() -> None:
    projet = [b"<Mappings>", b"<A/>", b"<B/>", b"</Mappings>"]
    runtime = [b"<Mappings>", b"<B/>", b"<A/>", b"</Mappings>"]
    hunks = [Hunk("delete", 1, 2, 1, 1), Hunk("insert", 3, 3, 2, 3)]  # A retiré ici, réinséré là
    sem = describe_hunks(hunks, projet, runtime)
    assert [(s.genre, s.significatif) for s in sem] == [("deplacement", False), ("deplacement", False)]
    assert sens_semantique(sem) == "non_significatif"


# -- Couple synthétique : une ligne par écart, (genre, sens, nœuds, significatif) --------------


@pytest.mark.parametrize(
    ("rel", "sens", "attendu"),
    [
        (
            TAGS,
            "mixte",
            [
                ("bloc", "ajout_runtime", ["Acquit_Z1", "Acquit_Z2"], True),
                ("bloc", "branche_projet", ["PlanSciage_Manu"], True),
                ("bloc", "ajout_runtime", ["EnHaut"], True),
            ],
        ),
        (
            MODEL,
            "valeur_modifiee",
            [("id", "branche_projet", ["Enum_Taille"], False), ("valeur", "valeur_modifiee", ["AvecScanner"], True)],
        ),
        (
            TRANSLATIONS,
            "ajout_runtime",
            [
                ("dimensions", "valeur_modifiee", ["TranslationTable"], False),
                ("valeur", "ajout_runtime", ["TranslationTable"], True),
            ],
        ),
        (ALARMS, "branche_projet", [("bloc", "branche_projet", ["Fault_SurchauffeGHDel"], True)]),
        (PARENTS, "branche_projet", [("fichier", "branche_projet", ["Division/Division.yaml"], True)]),
        (
            SCREENS,
            "valeur_modifiee",
            [("valeur", "valeur_modifiee", ["TopMargin"], True), ("valeur", "valeur_modifiee", ["LeftMargin"], True)],
        ),
        ("ProjectFiles/UserDefinedModule.xml", "branche_projet", [("type", "branche_projet", ["IType_Div_BP_Prog"], True)]),
    ],
    ids=["tags", "model", "traductions", "alarmes", "parents", "ecrans", "module_xml"],
)
def test_semantique_par_fichier(demo: Comparison, rel: str, sens: str, attendu: list[tuple]) -> None:
    fd = demo.diffs[rel]
    assert fd.sens == sens
    assert [(s.genre, s.sens, s.noeuds, s.significatif) for s in fd.semantic] == attendu


def test_details_semantiques(demo: Comparison) -> None:
    """Chemins, détails et libellés affichés pour les écarts du couple synthétique."""
    assert "App_Demo.GVL_IO.Statuts.EnHaut" in demo.diffs[TAGS].semantic[2].detail
    assert demo.diffs[MODEL].semantic[1].chemin_parent == "Model"
    alarme = demo.diffs[ALARMS].semantic[0]
    assert alarme.detail == "bloc IType_Demo_Alarm, 11 lignes"
    assert "présent côté projet uniquement" in alarme.libelle
    ecrans = demo.diffs[SCREENS].semantic
    assert {s.noeud: s.detail for s in ecrans} == {
        "TopMargin": "Value: `81.0` → `80.0`",
        "LeftMargin": "Value: `560.0` → `562.0`",
    }
    assert ecrans[0].chemin == "Screens/IType_Manual/Panel1/TopMargin"
