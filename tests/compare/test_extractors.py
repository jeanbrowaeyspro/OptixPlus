"""Extracteurs spécialisés : tags CoDeSys, traductions, types utilisateur, statistiques du ``.optix``."""

from __future__ import annotations

from optixplus.common.optix.text import split_lines
from optixplus.modules.compare.core.analysis import Comparison
from optixplus.modules.compare.core.extractors.module_xml import extract_type_guids, merge_type_mappings
from optixplus.modules.compare.core.extractors.translations import fix_dimensions

from .conftest import RUNTIME, TAGS, TRANSLATIONS


def test_tags(demo: Comparison) -> None:
    delta = demo.tags[TAGS]
    assert [(t.name, t.type, t.data_type, t.symbol) for t in delta.runtime_seul] == [
        ("Acquit_Z1", "CODESYSTag", "Boolean", "App_Demo.GVL_IO.Acquit_Z1"),
        ("Acquit_Z2", "CODESYSTag", "Boolean", "App_Demo.GVL_IO.Acquit_Z2"),
        ("EnHaut", "CODESYSTag", "Boolean", "App_Demo.GVL_IO.Statuts.EnHaut"),
    ]
    assert [(t.name, t.membres, t.is_structure) for t in delta.projet_seul] == [
        ("PlanSciage_Manu", ["Largeur", "Nombre"], True)
    ]
    assert delta.modifies == []
    assert {r.symbol for r in delta.rows if r.etat == "identique"} >= {"App_Demo.GVL_IO.Marche", "App_Demo.GVL_IO.Statuts"}


def test_traductions(demo: Comparison) -> None:
    delta = demo.translations[TRANSLATIONS]
    assert delta.dimensions_projet == (3, 4) and delta.dimensions_runtime == (4, 4)
    assert delta.runtime_seul == [["Créer bois", "Create wood", "Créer bois", "Creare legno"]]
    assert delta.projet_seul == [] and delta.modifies == []
    assert delta.projet is not None and delta.projet.coherent
    assert delta.runtime is not None and delta.runtime.coherent
    assert delta.projet.header == ["", "en-US", "fr-FR", "it-IT"]


def test_fix_dimensions_sans_changement() -> None:
    lines = split_lines((RUNTIME / TRANSLATIONS).read_bytes()).lines
    fixed, delta = fix_dimensions(lines)
    assert delta is None and fixed == list(lines)


def test_types_et_noms(demo: Comparison) -> None:
    assert demo.types is not None
    assert demo.types.projet_seul == ["bc1cc03e5060e72cb67c1d3cd9d84961"]
    assert demo.types.runtime_seul == []
    assert demo.type_names["bc1cc03e5060e72cb67c1d3cd9d84961"] == "IType_Div_BP_Prog"
    assert demo.type_names["8c8a432c986c4c596069cf9ec9a2f980"] == "IType_TextErreurDivision"


def test_fusion_type_mappings_par_guid() -> None:
    def xml(guids: list[str]) -> list[bytes]:
        lines = [b"<TypeMappings>"]
        for g in guids:
            lines += [b"  <TypeMapping>", f'    <NodeId guid="{g}" />'.encode(), b"  </TypeMapping>"]
        return lines + [b"</TypeMappings>"]

    a, b, c, d = ("a" * 32, "b" * 32, "c" * 32, "d" * 32)
    projet, runtime = xml([a, b, c]), xml([b, a, d])
    fusion = merge_type_mappings(projet, runtime, remove=[c], add=[d, a])
    assert [m.guid for m in extract_type_guids(fusion)] == [a, b, d], "c retiré, d ajouté, a jamais dupliqué"
    assert fusion[-1] == b"</TypeMappings>"


def test_statistiques_optix(demo: Comparison) -> None:
    assert demo.optix is not None and demo.optix.seulement_statistiques
    rows = {k: (p, r) for k, p, r in demo.optix.stats_rows()}
    assert rows["TotalNodeCount"] == (130, 100)
    assert rows["ObjectTypes"] == (3, 2)
    assert demo.optix.projet.nodes_root == "Nodes/IHM_Demo.yaml"


def test_pas_de_dll_netlogic(demo: Comparison) -> None:
    """Sans DLL NetLogic des deux côtés, il n'y a rien à comparer (voir le couple réel pour le cas complet)."""
    assert demo.netlogic is None
