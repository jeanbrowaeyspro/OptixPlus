"""Petit projet FT Optix synthétique pour les tests de Link Checker.

Généré dans un dossier temporaire : chaque test part d'un projet intact. ``UI.yaml`` est
écrit en CRLF avec BOM pour vérifier que les corrections conservent le format.
"""

from __future__ import annotations

from pathlib import Path

OPTIX = """Project:
 Name: Demo
 GUID: 0123456789abcdef0123456789abcdef
 ProductVersion: 1.6
 Nodes:
 - File: Nodes/Demo.yaml
"""

ROOT = """Name: Demo
Type: ProjectFolder
Children:
- File: Model/Model.yaml
- File: UI/UI.yaml
"""

MODEL = """Name: Model
Type: FolderType
Children:
- Name: Speed
  Type: BaseDataVariableType
  DataType: Float
  Value: 0.0
- Name: Motors
  Type: FolderType
  Children:
  - Name: Motor1
    Type: MotorType
- Name: MotorType
  Supertype: BaseObjectType
  Children:
  - Name: Current
    Type: BaseDataVariableType
    DataType: Float
    Value: 0.0
- Name: Levels
  Type: BaseDataVariableType
  DataType: Float
  Children:
  - Name: "0"
    Type: BaseDataVariableType
    DataType: Float
- Name: Ptr
  Type: BaseDataVariableType
  DataType: NodeId
  Value: "/Objects/Demo/Model/Speed"
"""

# (nom du label, valeur écrite dans le YAML) — la valeur est recopiée telle quelle.
LABELS = [
    ("LabelOk", '"/Objects/Demo/Model/Speed"'),
    ("LabelForeign", '"/Objects/OldProject/Model/Speed"'),
    ("LabelMissing", '"../../../../../Model/Old/Speed"'),
    ("LabelType", '"/Objects/Demo/Model/Motors/Motor1/Current@Value"'),
    ("LabelArray", '"/Objects/Demo/Model/Levels[0]"'),
    ("LabelRelOk", '"../../../../../Model/Speed"'),
    ("LabelAlias", '"{Alias1}/Speed"'),
    ("LabelPointer", '"/Objects/Demo/Model/Ptr/Something"'),
    ("LabelBuiltin", '"/Objects/Server/ServerStatus"'),
    ("LabelAbove", '"../../../../../../../../Foo"'),
    ("LabelForeignBare", "/Objects/OldProject/Model/Speed"),
    ("LabelForeignMissing", '"/Objects/OldProject/Model/Nowhere"'),
]


def _label(name: str, value: str) -> str:
    return f"""    - Name: {name}
      Type: Label
      Children:
      - Name: Text
        Type: BaseDataVariableType
        DataType: LocalizedText
        Children:
        - Name: DynamicLink
          Type: DynamicLink
          DataType: NodePath
          Value: {value}
"""


def ui_text() -> str:
    body = """Name: UI
Type: FolderType
Children:
- Name: Screens
  Type: FolderType
  Children:
  - Name: Main
    Supertype: Screen
    Children:
"""
    return body + "".join(_label(n, v) for n, v in LABELS)


def make_project(base: Path) -> Path:
    folder = base / "Demo"
    (folder / "Nodes" / "Model").mkdir(parents=True)
    (folder / "Nodes" / "UI").mkdir(parents=True)
    (folder / "Demo.optix").write_text(OPTIX, encoding="utf-8")
    (folder / "Nodes" / "Demo.yaml").write_text(ROOT, encoding="utf-8")
    (folder / "Nodes" / "Model" / "Model.yaml").write_text(MODEL, encoding="utf-8")
    ui = ui_text().replace("\n", "\r\n").encode("utf-8")
    (folder / "Nodes" / "UI" / "UI.yaml").write_bytes(b"\xef\xbb\xbf" + ui)
    return folder
