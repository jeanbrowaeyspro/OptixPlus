"""Projet FT Optix synthétique pour les tests du calcul de Statistiques (format réel, contenu minimal).

Contenu (projet ``Demo``) :

- deux stations CODESYS : ``PlcA`` (5 tags simples + 2 structures) et ``PlcB`` (1 tag) ;
- une fenêtre principale avec un menu (boutons ``BtPanel``) et un ``PanelLoader`` ;
- trois écrans principaux : ``IType_00_Home`` (2 tags), ``IType_01_Work`` (nom affiché « Work
  machine »; liaison absolue, relative, pointeur d'équipement et sous-panneau partagé),
  ``IType_02_Supervision`` (``NavigationPanel`` à deux onglets, chemin dynamique ``{0}`` et
  convertisseur partagé) ; une boîte de dialogue non principale ;
- 2 alarmes, 1 NetLogic, 2 loggers ; quelques fichiers de ``ProjectFiles``.

``runtime=True`` ajoute ``ApplicationFiles`` (bases SQLite) et un fichier ``.source`` ignoré.
"""

from __future__ import annotations

import struct
from pathlib import Path

PROJECT = "Demo"
TAGS_A = "/Objects/Demo/CommDrivers/CODESYSDriver/PlcA/Tags"
TAGS_B = "/Objects/Demo/CommDrivers/CODESYSDriver/PlcB/Tags"

OPTIX = """Project:
 Name: Demo
 GUID: 0123456789abcdef0123456789abcdef
 ProjectNamespaceIndex: 32
 FormatVersion: 1
 ProductVersion: 1.6
 CoreVersion: 4.2
 Dependencies:
  2:
   Uri: 'urn:FTOptix:Core:Net'
   Module: FTOptix.Core.Net
   Version: 2.2
  9:
   Uri: 'urn:FTOptix:UI'
   Module: FTOptix.UI
   Version: 18.1
 Statistics:
  TotalNodeCount: 123
  Objects: 40
  ObjectTypes: 10
  Variables: 70
  Methods: 3
  References: 5
  Files: 9
 Nodes:
 - File: Nodes/Demo.yaml
"""

ROOT = """Name: Demo
Type: ProjectFolder
Children:
- File: CommDrivers/CommDrivers.yaml
- File: UI/UI.yaml
- File: Converters/Converters.yaml
- File: Alarms/Alarms.yaml
- File: Misc/Misc.yaml
"""


def _tag(name: str, indent: str) -> str:
    return (
        f"{indent}- Name: {name}\n{indent}  Type: CODESYSTag\n{indent}  DataType: Int32\n"
        f"{indent}  Children:\n{indent}  - Name: SymbolName\n{indent}    Type: BaseDataVariableType\n"
        f"{indent}    DataType: String\n{indent}    Value: \"{name}\"\n"
    )


def _structure(name: str, members: list[str], indent: str) -> str:
    text = (
        f"{indent}- Name: {name}\n{indent}  Type: TagStructure\n{indent}  DataType: Structure\n"
        f"{indent}  Children:\n{indent}  - Name: SymbolName\n{indent}    Type: BaseDataVariableType\n"
        f"{indent}    DataType: String\n{indent}    Value: \"{name}\"\n"
    )
    return text + "".join(_tag(m, indent + "  ") for m in members)


def _station(name: str, address: str) -> str:
    return f"""  - Name: {name}
    Type: CODESYSStation
    Children:
    - Name: GatewayIP
      Type: BaseDataVariableType
      DataType: String
      Value: "127.0.0.1"
    - Name: Port
      Type: BaseDataVariableType
      DataType: UInt16
      Value: 1217
    - Name: PLCAddress
      Type: BaseDataVariableType
      DataType: String
      Value: "{address}"
    - File: CODESYSDriver/{name}/Tags.yaml
"""


def _tags_file(body: str) -> str:
    return "Name: Tags\nType: FolderType\nChildren:\n" + body


def _link(path: str, indent: str) -> str:
    return (
        f"{indent}- Name: DynamicLink\n{indent}  Type: DynamicLink\n{indent}  DataType: NodePath\n"
        f"{indent}  Value: \"{path}\"\n"
    )


def _label(name: str, path: str) -> str:
    return (
        f"  - Name: {name}\n    Type: Label\n    Children:\n    - Name: Text\n"
        "      Type: BaseDataVariableType\n      DataType: LocalizedText\n      Children:\n"
        + _link(path, "      ")
    )


def _button(name: str, text_id: str, target: str) -> str:
    return f"""  - Name: {name}
    Type: IType_NavigationButton
    Children:
    - Name: BtText
      Type: BaseDataVariableType
      DataType: LocalizedText
      Value: {{"NamespaceIndex":32,"TextId":"{text_id}"}}
    - Name: BtPanel
      Type: BaseDataVariableType
      DataType: NodeId
      Value: "/Objects/Demo/UI/{target}"
"""


def _tab(name: str, title: str, panel: str) -> str:
    return f"""      - Name: {name}
        Type: NavigationPanelItem
        Children:
        - Name: Title
          Type: BaseDataVariableType
          DataType: LocalizedText
          Value: {{"NamespaceIndex":32,"TextId":"{title}"}}
        - Name: Panel
          Type: NodePointer
          DataType: NodeId
          Value: "/Objects/Demo/UI/{panel}"
"""


def ui_text(current_tab: int | None) -> str:
    tab_value = f"      Value: {current_tab}\n" if current_tab is not None else ""
    return (
        """Name: UI
Type: FolderType
Children:
- Name: PresentationEngine
  Type: NativePresentationEngine
  Children:
  - Name: StartWindow
    Type: NodePointer
    DataType: NodeId
    Value: "/Objects/Demo/UI/IType_MainWindow"
- Name: IType_NavigationButton
  Supertype: Button
  Children:
  - Name: BtPanel
    Type: BaseDataVariableType
    DataType: NodeId
- Name: IType_Menu
  Supertype: Panel
  Children:
"""
        + _button("BT_Home", "Home", "IType_00_Home")
        + _button("BT_Work", "Work", "IType_01_Work")
        + _button("BT_Supervision", "Supervision", "IType_02_Supervision")
        + """- Name: IType_MainWindow
  Supertype: Window
  Children:
  - Name: Menu
    Type: IType_Menu
  - Name: DynamicContent
    Type: PanelLoader
    Children:
    - Name: Panel
      Type: NodePointer
      DataType: NodeId
      Value: "/Objects/Demo/UI/IType_00_Home"
- Name: IType_Gauge
  Supertype: Panel
  Children:
"""
        + _label("LabelLevel", f"{TAGS_A}/Level")
        + _label("LabelSpeed", f"{TAGS_A}/Motor/Speed@Value")
        + """- Name: IType_00_Home
  Supertype: Screen
  Children:
"""
        + _label("LabelPressure", f"{TAGS_A}/Pressure")
        + _label("LabelLevel", f"{TAGS_A}/Level")
        + _label("LabelPressureCopy", f"{TAGS_A}/Pressure")  # même tag, autre objet : 1 tag, 2 liaisons
        + _label("LabelLocal", "/Objects/Demo/Model/Local")
        + """- Name: IType_01_Work
  Supertype: Screen
  DisplayName: {"LocaleId":"fr-FR","Text":"Work machine"}
  Children:
"""
        + _label("LabelPressure", f"{TAGS_A}/Pressure")
        + _label("LabelRelative", "../../../../../CommDrivers/CODESYSDriver/PlcA/Tags/Counters/Count1")
        + """  - Name: Gauge1
    Type: IType_Gauge
  - Name: Gauge2
    Type: IType_Gauge
  - Name: Equipment
    Type: NodePointer
    DataType: NodeId
    Value: "/Objects/Demo/CommDrivers/CODESYSDriver/PlcA/Tags/Motor"
- Name: IType_02_Supervision
  Supertype: Screen
  Children:
  - Name: NavigationPanel
    Type: NavigationPanel
    Children:
    - Name: Panels
      Type: BaseObjectType
      Children:
"""
        + _tab("Axes", "Axes", "IType_TabA")
        + _tab("Alarms", "Alarms", "IType_TabB")
        + "    - Name: CurrentTabIndex\n      Type: BaseDataVariableType\n      DataType: Int32\n"
        + tab_value
        + f"""- Name: IType_TabA
  Supertype: Panel
  Children:
  - Name: Gauge
    Type: IType_Gauge
  - Name: Axis
    Type: BaseDataVariableType
    DataType: NodeId
    Children:
    - Name: DynamicLink
      Type: DynamicLink
      DataType: NodePath
      Children:
      - Name: DynamicLinkFormatter
        Type: StringFormatter
        Children:
        - Name: Format
          Type: BaseDataVariableType
          DataType: LocalizedText
          Value: {{"LocaleId":"fr-FR","Text":"{TAGS_A}/Motor/{{0}}@NodeId"}}
        - Name: ns=7;Source0
          Type: BaseDataVariableType
          DataType: BaseDataType
          Children:
          - Name: DynamicLink
            Type: DynamicLink
            DataType: NodePath
            Value: "../../../../Num"
- Name: IType_TabB
  Supertype: Panel
  Children:
  - Name: Value
    Type: BaseDataVariableType
    DataType: Float
    Children:
"""
        + _link("/Objects/Demo/Converters/Conv1", "    ")
        + """- Name: IType_Dlg
  Supertype: Dialog
  Children:
"""
        + _label("LabelPressure", f"{TAGS_A}/Pressure")
    )


def make_project(base: Path, runtime: bool = False, current_tab: int | None = None, name: str = PROJECT) -> Path:
    """Crée le projet (ou le runtime) sous ``base/<name>`` et renvoie son dossier."""
    folder = base / name
    nodes = folder / "Nodes"
    for sub in ("CommDrivers/CODESYSDriver/PlcA", "CommDrivers/CODESYSDriver/PlcB", "UI", "Converters", "Alarms", "Misc"):
        (nodes / sub).mkdir(parents=True)
    (folder / "Demo.optix").write_text(OPTIX, encoding="utf-8")
    (folder / "IDEVersion.txt").write_text("1.6.4.11-Stable\n", encoding="utf-8")
    (nodes / "Demo.yaml").write_text(ROOT, encoding="utf-8")
    drivers = (
        "Name: CommDrivers\nType: CommDriversCategoryFolder\nChildren:\n- Name: CODESYSDriver\n  Type: CODESYSDriver\n"
        "  Children:\n"
        + _station("PlcA", "10.0.0.1")
        + _station("PlcB", "10.0.0.2")
    )
    (nodes / "CommDrivers" / "CommDrivers.yaml").write_text(drivers, encoding="utf-8")
    tags_a = (
        _tag("Pressure", "")
        + _tag("Level", "")
        + _structure("Motor", ["Speed", "Run"], "")
        + _structure("Counters", ["Count1"], "")
    )
    (nodes / "CommDrivers" / "CODESYSDriver" / "PlcA" / "Tags.yaml").write_text(_tags_file(tags_a), encoding="utf-8")
    (nodes / "CommDrivers" / "CODESYSDriver" / "PlcB" / "Tags.yaml").write_text(_tags_file(_tag("Temp", "")), encoding="utf-8")
    (nodes / "UI" / "UI.yaml").write_text(ui_text(current_tab), encoding="utf-8")
    (nodes / "Converters" / "Converters.yaml").write_text(
        "Name: Converters\nType: FolderType\nChildren:\n- Name: Conv1\n  Type: ExpressionEvaluator\n  Children:\n"
        "  - Name: ns=7;Source0\n    Type: BaseDataVariableType\n    DataType: BaseDataType\n    Children:\n"
        + _link(f"{TAGS_B}/Temp", "    "),
        encoding="utf-8",
    )
    (nodes / "Alarms" / "Alarms.yaml").write_text(
        "Name: Alarms\nType: AlarmsCategoryFolder\nChildren:\n"
        "- Name: Alarm1\n  Type: IType_Alarm\n- Name: Group\n  Type: FolderType\n  Children:\n  - Name: Alarm2\n    Type: IType_Alarm\n",
        encoding="utf-8",
    )
    (nodes / "Misc" / "Misc.yaml").write_text(
        "Name: Misc\nType: FolderType\nChildren:\n"
        "- Name: IType_Alarm\n  Supertype: OffNormalAlarmType\n"
        "- Name: Logic1\n  Type: NetLogic\n"
        "- Name: DataLogger1\n  Type: DataLogger\n"
        "- Name: EventLogger1\n  Type: EventLogger\n",
        encoding="utf-8",
    )
    files = folder / "ProjectFiles"
    (files / "Images").mkdir(parents=True)
    (files / "Fonts").mkdir()
    png = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 100, 50) + b"\x08\x06\x00\x00\x00"
    (files / "Images" / "a.png").write_bytes(png)
    (files / "Images" / "b.svg").write_text("<svg/>", encoding="utf-8")
    (files / "Fonts" / "f.ttf").write_bytes(b"x" * 10)
    (files / "notes.txt").write_text("hello", encoding="utf-8")
    if runtime:
        app = folder / "ApplicationFiles"
        app.mkdir()
        (app / "RetentivityStorage.db").write_bytes(b"r" * 5000)
        (app / "Data.sqlite").write_bytes(b"d" * 20000)
        (app / "log.txt").write_bytes(b"l" * 100)
        (folder / "Demo.source").write_bytes(b"ignored")
    return folder
