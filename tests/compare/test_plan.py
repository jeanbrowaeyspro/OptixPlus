"""Plan de décision : actions de masse, actions dérivées, prévisualisation, sérialisation."""

from __future__ import annotations

import json
from pathlib import Path

from optixplus.common.optix.text import split_lines
from optixplus.modules.compare.core.analysis import TYPE_CONSTANTS, UI_TYPE_DEFINITIONS, USER_DEFINED_MODULE, Comparison
from optixplus.modules.compare.core.extractors.translations import parse_translations
from optixplus.modules.compare.core.plan import Plan, build_preview, load_plan, save_plan

from .conftest import DIVISION, MODEL, PARENTS, SCREENS, TAGS, TRANSLATIONS


def test_recuperer_les_ajouts(demo: Comparison) -> None:
    plan = Plan()
    assert plan.recuperer_ajouts(demo) == 3
    preview = build_preview(plan, demo)
    assert {c.rel for c in preview.changes} == {TAGS, TRANSLATIONS}
    assert preview.nb_ajouts == 3 and preview.nb_retraits == 0 and preview.nb_valeurs == 0
    tags = preview.change(TAGS)
    assert tags is not None and b"Acquit_Z1" in tags.new and b"PlanSciage_Manu" in tags.new and b"EnHaut" in tags.new
    assert b"\r\n" in tags.new and tags.new.endswith(b"\r\n")
    trad = preview.change(TRANSLATIONS)
    assert trad is not None and trad.notes == ["Dimensions recalculées : 3 → 4"]
    table = parse_translations(split_lines(trad.new).lines)
    assert table is not None and table.coherent and table.dimensions == (4, 4)
    assert trad.new == demo.diffs[TRANSLATIONS].runtime.to_bytes(), "identique au runtime après ajout + Dimensions"
    assert preview.orphelins == [] and preview.references == []


def test_aligner_les_valeurs(demo: Comparison) -> None:
    plan = Plan()
    assert plan.aligner_valeurs(demo) == 3
    preview = build_preview(plan, demo)
    assert {c.rel for c in preview.changes} == {MODEL, SCREENS}
    assert preview.nb_valeurs == 3
    model = preview.change(MODEL)
    assert model is not None and b"Value: true" in model.new and b"Id: g=fdfba7080932d498240e265326b9b78d" in model.new
    assert preview.change(SCREENS).new == demo.diffs[SCREENS].runtime.to_bytes()


def test_alignement_complet_et_actions_derivees(demo: Comparison) -> None:
    plan = Plan(deplacer_orphelins=True, copier_statistiques=True)
    supprimes = plan.blocs_supprimes(demo)
    assert {s.noeud for _rel, s in supprimes} >= {"Fault_SurchauffeGHDel", "PlanSciage_Manu", "Division/Division.yaml"}
    plan.aligner_complet(demo)
    preview = build_preview(plan, demo)
    rels = {c.rel for c in preview.changes}
    assert {TAGS, MODEL, PARENTS, USER_DEFINED_MODULE, TYPE_CONSTANTS, UI_TYPE_DEFINITIONS, "IHM_Demo.optix"} <= rels
    for rel in demo.diffs:
        change = preview.change(rel)
        assert change is not None and change.new == demo.diffs[rel].runtime.to_bytes(), rel
    assert preview.types_retires == [("bc1cc03e5060e72cb67c1d3cd9d84961", "IType_Div_BP_Prog")]
    tc = preview.change(TYPE_CONSTANTS)
    assert tc is not None and b"IType_Div_BP_Prog" not in tc.new and b"IType_TextErreurDivision" in tc.new
    ui = preview.change(UI_TYPE_DEFINITIONS)
    assert ui is not None and ui.new.count(b"[MapType") == 2 and ui.origine == "dérivé : élagage par GUID"
    assert preview.orphelins == [DIVISION]
    optix = preview.change("IHM_Demo.optix")
    assert optix is not None and b"TotalNodeCount: 100" in optix.new and b"GUID: 0123456789abcdef" in optix.new
    assert any("orphelins" in a for a in preview.avertissements)
    assert not any("Project.Current.Find" in a for a in preview.avertissements), "pas de source NetLogic dans la fixture"
    assert preview.nb_retraits >= 4


def test_decision_individuelle_et_garder_projet(demo: Comparison) -> None:
    plan = Plan()
    fd = demo.diffs[TAGS]
    ajout = next(s for s in fd.semantic if s.noeud == "EnHaut")
    plan.set_decision(TAGS, ajout.hunk.as_opcode(), "prendre_runtime")
    retrait = next(s for s in fd.semantic if s.noeud == "PlanSciage_Manu")
    plan.set_decision(TAGS, retrait.hunk.as_opcode(), "garder_projet")
    assert plan.decision(TAGS, retrait.hunk.as_opcode()) == "garder_projet"
    preview = build_preview(plan, demo)
    assert [c.rel for c in preview.changes] == [TAGS]
    tags = preview.change(TAGS)
    assert b"EnHaut" in tags.new and b"PlanSciage_Manu" in tags.new and b"Acquit_Z1" not in tags.new
    assert tags.nb_ajouts == 1 and tags.nb_retraits == 0
    plan.set_decision(TAGS, ajout.hunk.as_opcode(), "ignorer")
    assert (TAGS, ajout.hunk.as_opcode()) not in plan.decisions


def test_serialisation_et_reappariement(demo: Comparison, tmp_path: Path) -> None:
    plan = Plan(nom="ajouts", copier_statistiques=True)
    plan.recuperer_ajouts(demo)
    path = tmp_path / "plan.json"
    save_plan(plan, path, demo)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == 1 and data["nom"] == "ajouts" and data["options"]["copier_statistiques"] is True
    assert all("noeuds" in e and e["decision"] == "prendre_runtime" for e in data["decisions"])
    charge, perdus = load_plan(path, demo)
    assert perdus == [] and charge.decisions == plan.decisions and charge.copier_statistiques

    # Rejeu avec un hunk décalé : réapparié par (nœuds, sens) ; un hunk inconnu est signalé perdu.
    data["decisions"][0]["hunk"][1] += 1
    data["decisions"].append({"fichier": TAGS, "hunk": [0, 0, 0, 0, 0], "decision": "prendre_runtime", "noeuds": ["Inconnu"], "sens": "ajout_runtime"})
    rejoue, perdus = Plan.from_dict(data, demo)
    assert len(rejoue.decisions) == 3 and len(perdus) == 1 and "Inconnu" in perdus[0]
