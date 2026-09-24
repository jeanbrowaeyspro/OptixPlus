"""Lecture directe des YAML Optix (``common.optix.tree``) : identique à PyYAML, nœud par nœud.

Les projets réels se vérifient en indiquant leurs dossiers dans ``OPTIXPLUS_OPTIX_SAMPLES``
(séparés par ``;``) ; sans elle, ces tests sont ignorés.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from linkcheck_fixture import make_project
from optix_reference import pyyaml_nodes
from optixplus.common.optix import tree
from optixplus.common.optix.tree import Unsupported, read_nodes
from optixplus.modules.linkcheck.core import project as lc_project

TESTS = Path(__file__).resolve().parents[1]
SAMPLES = [Path(p) for p in os.environ.get("OPTIXPLUS_OPTIX_SAMPLES", "").split(";") if p.strip()]


def _comparable(records):
    """NaN n'est égal à rien, pas même à lui-même : on le remplace par un repère."""
    if not isinstance(records, list):
        return records
    import dataclasses
    import math

    return [
        dataclasses.replace(r, value="<nan>") if isinstance(r.value, float) and math.isnan(r.value) else r
        for r in records
    ]


def _same_as_pyyaml(text: str) -> None:
    assert _comparable(read_nodes(text)) == _comparable(pyyaml_nodes(text))


def _yaml_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.yaml") if p.is_file())


@pytest.mark.parametrize("path", _yaml_files(TESTS / "compare" / "fixtures"), ids=lambda p: p.name)
def test_compare_fixtures_read_like_pyyaml(path: Path) -> None:
    _same_as_pyyaml(path.read_text(encoding="utf-8-sig"))


def test_linkcheck_fixture_read_like_pyyaml(tmp_path: Path) -> None:
    demo = make_project(tmp_path)
    files = _yaml_files(demo)
    assert files
    for path in files:
        with open(path, encoding="utf-8-sig") as fh:  # comme Link Checker : fins de ligne universelles
            _same_as_pyyaml(fh.read())


EDGE_CASES = {
    "valeurs typées et vides": """Name: Racine
Type: FolderType
Children:
- Name: Entier
  Value: 42
- Name: Réel
  Value: 0.0
- Name: Booléen
  Value: true
- Name: Nul
  Value: null
- Name: Vide
  Value:
- Name: Chaîne
  Value: "texte : avec deux-points"
- Name: Apostrophes
  Value: 'l''atelier'
- Name: Échappé
  Value: "ligne\\nsuivante \\u00e9"
- Name: ns=3;Espace
  Value: 2024-01-15
""",
    "JSON en flux sur plusieurs lignes": """Name: Racine
Children:
- Name: Message
  Type: BaseDataVariableType
  Value:
   {
    "Type": 22,
    "Body": {"Text": "a, b [c] {d}", "Id": 0}
   }
  Children:
  - Name: DynamicLink
    Type: DynamicLink
    Value: "../X"
- Name: Tableau
  Value: [1, 2,
    3]
- Name: Suivant
""",
    "inclusions, classes et listes annexes": """Name: Racine
Children:
- File: Sous/Fichier.yaml
- Name: Méthode
  Class: Method
  InputArguments:
  - Name: Arg1
    Type: X
  Children:
  - Name: Dedans
- Name: Objet
  Class: Object
  Children:
  - Name: Ignoré
- Name: Fin
""",
    "liste Children indentée": """Name: Racine
Children:
  - Name: A
    Children:
      - Name: B
        Value: 1
  - Name: C
""",
    "sans saut de ligne final": "Name: Racine\nChildren:\n- Name: A\n  Value: x",
    "lignes vides et espaces de fin": "\n\nName: Racine   \n\nChildren:\n\n- Name: A  \n  Type: T\n\n",
}


@pytest.mark.parametrize("text", EDGE_CASES.values(), ids=EDGE_CASES.keys())
def test_edge_cases_read_like_pyyaml(text: str) -> None:
    _same_as_pyyaml(text)


UNSUPPORTED = {
    "commentaire": "Name: A\n# note\nType: T\n",
    "commentaire en fin de ligne": "Name: A\nType: T # note\n",
    "ancre": "Name: A\nValue: &x 1\n",
    "bloc littéral": "Name: A\nValue: |\n  texte\n",
    "tabulation": "Name: A\n\tType: T\n",
    "texte sur deux lignes": "Name: A\nValue: début\n  suite\n",
    "clé en double": "Name: A\nName: B\n",
    "racine en liste": "- Name: A\n",
    "caractère de contrôle": "Name: A\x07\n",
    "document multiple": "Name: A\n---\nName: B\n",
}


@pytest.mark.parametrize("text", UNSUPPORTED.values(), ids=UNSUPPORTED.keys())
def test_unusual_yaml_is_left_to_pyyaml(text: str) -> None:
    with pytest.raises(Unsupported):
        read_nodes(text)


def _analyse(folder: str, force_pyyaml: bool, monkeypatch):
    if force_pyyaml:
        def refuse(_text):
            raise Unsupported("test")

        monkeypatch.setattr(lc_project, "read_nodes", refuse)
    else:
        monkeypatch.setattr(lc_project, "read_nodes", tree.read_nodes)
    return lc_project.analyse(folder)


def _summary(result):
    project, broken, stats = result
    nodes = [
        (n.path(), n.name, n.type, n.supertype, n.datatype, repr(n.value), n.file, n.line, n.end_line, n.value_line)
        for n in project.all_nodes
    ]
    return nodes, [vars(b) if hasattr(b, "__dict__") else b for b in broken], stats, project.files_loaded


def test_link_checker_gives_the_same_result_with_both_readers(tmp_path, monkeypatch):
    demo = make_project(tmp_path)
    fast = _analyse(str(demo), False, monkeypatch)
    assert fast[0].pyyaml_files == 0
    assert _summary(fast) == _summary(_analyse(str(demo), True, monkeypatch))


def test_unusual_file_falls_back_to_pyyaml(tmp_path, monkeypatch):
    demo = make_project(tmp_path)
    model = demo / "Nodes" / "Model" / "Model.yaml"
    model.write_text("# Fichier retouché à la main\n" + model.read_text(encoding="utf-8"), encoding="utf-8")
    fast = _analyse(str(demo), False, monkeypatch)
    assert fast[0].pyyaml_files == 1
    assert _summary(fast) == _summary(_analyse(str(demo), True, monkeypatch))


@pytest.mark.skipif(not SAMPLES, reason="OPTIXPLUS_OPTIX_SAMPLES non défini")
@pytest.mark.parametrize("folder", SAMPLES, ids=lambda p: p.name)
def test_real_projects(folder: Path, monkeypatch) -> None:
    if not (folder / "Nodes").is_dir():
        pytest.skip(f"{folder} absent")
    for path in _yaml_files(folder / "Nodes"):
        with open(path, encoding="utf-8-sig") as fh:
            _same_as_pyyaml(fh.read())
    fast = _analyse(str(folder), False, monkeypatch)
    assert _summary(fast) == _summary(_analyse(str(folder), True, monkeypatch))


_TRICKY_VALUES = [
    "0", "-12", "+7", "1_000", "0x1F", "0o17", "017", "1:20", "1.5e3", ".inf", "-.Inf", ".nan", "3.",
    "true", "False", "yes", "No", "on", "OFF", "y", "~", "null", "Null", "2024-01-15", "2024-01-15 10:20:30",
    "abc", "a b c", "chemin/relatif/../X", "../Y@Attr", "{0}", "Tank[3]", "ns=4;Motor", "é à ù", "a:b", "a#b",
    '"quoted"', "'single'", "'l''apostrophe'", '"tab\tnewline\n"', '"a: b # c"', "''", '""', "[]", "{}",
    "[1, 2, 3]", '{"Type": 1, "Body": {"Id": "x, y"}}', "-", "- x", "a: b", "x #c", "&a b", "*b", "!tag x",
    "|", ">", "%x", "@x", "`x", "a:", "? x",
]


def _random_document(rng) -> str:
    lines: list[str] = []

    def node(indent: int, depth: int, first_prefix: str) -> None:
        pad = " " * indent
        keys = [("Name", rng.choice(_TRICKY_VALUES[25:40] + ["Motor", "ns=2;Pump", "0"]))]
        for key in ("Type", "DataType", "Supertype", "Class", "Value", "Id", "Description"):
            if rng.random() < 0.35:
                keys.append((key, rng.choice(_TRICKY_VALUES)))
        rng.shuffle(keys)
        for i, (key, value) in enumerate(keys):
            prefix = first_prefix if i == 0 else pad
            if rng.random() < 0.08:
                lines.append(f"{prefix}{key}:")
                lines.append(f"{pad} {{")
                lines.append(f'{pad}  "Key": [1, "a, b"],')
                lines.append(f'{pad}  "Other": {{"x": "}}"}}')
                lines.append(f"{pad} }}")
            else:
                lines.append(f"{prefix}{key}: {value}".rstrip())
        if rng.random() < 0.2:
            lines.append(f"{pad}InputArguments:")
            lines.append(f"{pad}- Name: Arg")
            lines.append(f"{pad}  Type: X")
        if depth < 3 and rng.random() < 0.7:
            lines.append(f"{pad}Children:")
            child_pad = indent + (2 if rng.random() < 0.2 else 0)
            for _ in range(rng.randint(0, 3)):
                if rng.random() < 0.15:
                    lines.append(" " * child_pad + f"- File: {rng.choice(['A/A.yaml', 'B.yaml'])}")
                else:
                    node(child_pad + 2, depth + 1, " " * child_pad + "- ")

    node(0, 0, "")
    return "\n".join(lines) + ("\n" if rng.random() < 0.8 else "")


def test_random_documents_read_like_pyyaml_or_fall_back() -> None:
    import random

    import yaml

    rng = random.Random(20260923)
    read_directly = 0
    for _ in range(300):
        text = _random_document(rng)
        try:
            expected = pyyaml_nodes(text)
        except yaml.YAMLError:
            expected = "invalide"
        try:
            got = read_nodes(text)
        except Unsupported:
            continue  # relu par PyYAML : même résultat par construction
        assert _comparable(got) == _comparable(expected), text
        read_directly += 1
    assert read_directly > 35  # une bonne part (53 sur 300 avec cette graine) des documents reste lue directement
