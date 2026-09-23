"""Diff, fusion sélective et remontée sémantique sur de petits YAML synthétiques."""

from difflib import SequenceMatcher

from optixplus.modules.compare.core.diffing import (
    Hunk,
    compute_opcodes,
    diff_lines,
    hunks_from_opcodes,
    merge_lines,
    sens_global,
)
from optixplus.modules.compare.core.nodes import (
    describe_hunks,
    index_nodes,
    sens_semantique,
    slide_opcodes,
)


def _tag(indent: int, name: str, dtype: str, symbol: str) -> list[bytes]:
    pad = b" " * indent
    return [
        pad + f"- Name: {name}".encode(),
        pad + b"  Type: CODESYSTag",
        pad + f"  DataType: {dtype}".encode(),
        pad + b"  Value: false",
        pad + b"  Children:",
        pad + b"  - Name: SymbolName",
        pad + b"    Type: BaseDataVariableType",
        pad + b"    DataType: String",
        pad + f'    Value: "{symbol}"'.encode(),
    ]


def _tags_file(names: list[str]) -> list[bytes]:
    lines = [b"Name: Tags", b"Type: FolderType", b"Children:", b"- Name: App", b"  Type: TagStructure", b"  Children:"]
    for name in names:
        lines += _tag(2, name, "Boolean", f"App.IO.{name}")
    return lines


PROJET = _tags_file(["A_Tag", "C_Tag", "Z_Projet"])
RUNTIME = _tags_file(["A_Tag", "B_Runtime", "C_Tag"])


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


def test_hunks_et_sens() -> None:
    hunks = diff_lines(PROJET, RUNTIME)
    assert [h.tag for h in hunks] == ["insert", "delete"]
    assert sens_global(hunks) == "mixte"
    assert hunks[0].sens == "ajout_runtime" and hunks[1].sens == "branche_projet"


def test_opcodes_equivalents_a_difflib_sur_petit_fichier() -> None:
    attendu = SequenceMatcher(None, PROJET, RUNTIME, autojunk=False).get_opcodes()
    assert compute_opcodes(PROJET, RUNTIME) == attendu


def test_ancrage_gros_fichier_reconstruit_les_deux_cotes() -> None:
    projet = _tags_file([f"T{i:04d}" for i in range(0, 600)])
    runtime = _tags_file([f"T{i:04d}" for i in range(0, 600) if i % 97 != 0] + ["T9999"])
    ops = compute_opcodes(projet, runtime)
    assert len(projet) + len(runtime) > 4000, "le test doit passer par l'ancrage"
    assert merge_lines(projet, runtime, ops) == projet
    assert merge_lines(projet, runtime, ops, modes={"insert", "delete", "replace"}) == runtime
    hunks = hunks_from_opcodes(ops)
    assert sum(1 for h in hunks if h.tag == "delete") == 7
    assert sum(1 for h in hunks if h.tag == "insert") == 1


def test_fusion_selective() -> None:
    ops = compute_opcodes(PROJET, RUNTIME)
    ajouts = merge_lines(PROJET, RUNTIME, ops, modes={"insert"})
    assert ajouts == _tags_file(["A_Tag", "B_Runtime", "C_Tag", "Z_Projet"])
    complet = merge_lines(PROJET, RUNTIME, ops, modes={"insert", "delete", "replace"})
    assert complet == RUNTIME
    rien = merge_lines(PROJET, RUNTIME, ops)
    assert rien == PROJET
    hunk = hunks_from_opcodes(ops)[1]
    retire = merge_lines(PROJET, RUNTIME, ops, retenus=[hunk])
    assert retire == _tags_file(["A_Tag", "C_Tag"])


def test_remontee_semantique_blocs_tags() -> None:
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
    hunks = diff_lines(projet, runtime)
    sem = describe_hunks(hunks, projet, runtime)
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


def test_glissement_sur_frontiere_de_noeud() -> None:
    """Une insertion que difflib place à cheval sur deux blocs doit glisser jusqu'au ``- Name:``."""
    projet = [b"Name: R", b"Children:", b"- Name: A", b"  Type: T", b"- Name: C", b"  Type: T"]
    runtime = [b"Name: R", b"Children:", b"- Name: A", b"  Type: T", b"- Name: B", b"  Type: T", b"- Name: C", b"  Type: T"]
    # Fenêtre décalée d'une ligne vers le haut : [``  Type: T``, ``- Name: B``], valide mais illisible.
    ops = [("equal", 0, 3, 0, 3), ("insert", 3, 3, 3, 5), ("equal", 3, 6, 5, 8)]
    assert merge_lines(projet, runtime, ops, modes={"insert"}) == runtime, "fenêtre valide"
    glisse = slide_opcodes(ops, projet, runtime)
    assert glisse == [("equal", 0, 4, 0, 4), ("insert", 4, 4, 4, 6), ("equal", 4, 6, 6, 8)]
    assert merge_lines(projet, runtime, glisse, modes={"insert"}) == runtime
    sem = describe_hunks(hunks_from_opcodes(glisse), projet, runtime)
    assert sem[0].noeud == "B" and sem[0].genre == "bloc"


def test_hunk_proprietes() -> None:
    h = Hunk("replace", 3, 5, 3, 4)
    assert h.nb_a == 2 and h.nb_b == 1 and h.sens == "valeur_modifiee"
    assert h.as_opcode() == ("replace", 3, 5, 3, 4)


def test_deplacement_de_bloc_non_significatif() -> None:
    projet = [b"<Mappings>", b"<A/>", b"<B/>", b"</Mappings>"]
    runtime = [b"<Mappings>", b"<B/>", b"<A/>", b"</Mappings>"]
    hunks = [Hunk("delete", 1, 2, 1, 1), Hunk("insert", 3, 3, 2, 3)]  # A retiré ici, réinséré là
    sem = describe_hunks(hunks, projet, runtime)
    assert [(s.genre, s.significatif) for s in sem] == [("deplacement", False), ("deplacement", False)]
    assert sens_semantique(sem) == "non_significatif"
