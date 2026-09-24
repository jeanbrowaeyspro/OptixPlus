"""Intégrité : références restantes vers des nœuds ou des types retirés."""

from __future__ import annotations

from pathlib import Path

from optixplus.modules.compare.core.integrity import find_references


def test_references_orphelines(tmp_path: Path) -> None:
    root = tmp_path / "P"
    (root / "Nodes").mkdir(parents=True)
    (root / "ProjectFiles" / "NetSolution").mkdir(parents=True)
    (root / "Nodes" / "A.yaml").write_bytes(b"- Name: X\r\n  Value: {NodePath: Parents/Division/Lame}\r\n- Name: Division2\r\n")
    (root / "ProjectFiles" / "NetSolution" / "L.cs").write_bytes(b'var t = Project.Current.Find("IType_Div_BP_Prog");\r\n')
    hits = find_references(root, ["Division", "IType_Div_BP_Prog"])
    assert [(h.rel, h.line_no, h.name) for h in hits] == [
        ("Nodes/A.yaml", 2, "Division"),
        ("ProjectFiles/NetSolution/L.cs", 1, "IType_Div_BP_Prog"),
    ]
    assert find_references(root, ["Division"], overrides={"Nodes/A.yaml": b"rien\r\n"}) == []
