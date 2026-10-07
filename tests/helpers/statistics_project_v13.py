"""Variante de style 1.3 du projet synthétique de Statistiques (aucun nom réel).

Les pages principales sont des ``Panel`` (pas des ``Screen``) enfants directs de ``UI/Screens`` ; les onglets sont
faits avec des ``PanelLoader`` et des boutons de navigation (``PanelToLoad`` + ``PanelLoader``), sans ``NavigationPanel`` :

- ``SplashPanel`` : page d'attente, ``Panel`` initial du ``PanelLoader`` de la fenêtre, visée par aucun bouton (exclue) ;
- ``IType_00_Alpha`` : page sans onglet (2 tags, 3 liaisons) ;
- ``IType_01_Beta`` : ``PL_Main`` (panneau initial ``IType_TabOne``) et deux boutons « One » / « Two » ; le panneau
  ``IType_TabTwo`` a son propre ``PanelLoader`` (``PL_Sub``) et deux boutons « SubA » / « SubB » (onglets imbriqués) ;
- ``IType_02_Gamma`` : un ``PanelLoader`` sans aucun bouton (une seule ligne ``Gamma/<panneau>``) ;
- ``IType_Confirm`` : boîte de dialogue (exclue) ; ``IType_Gauge`` : sous-vue (exclue, comptée dans l'onglet qui l'instancie).

Le chemin relatif d'un ``PanelLoader`` visé par un bouton part de la variable ``PanelLoader`` du bouton.
"""

from __future__ import annotations

from pathlib import Path

from statistics_project import TAGS_A, TAGS_B, _label, make_project

_PREFIX = "/Objects/Demo/UI"


def _nav_button(name: str, title: str, target: str, loader_path: str) -> str:
    """Bouton de navigation d'onglet (indentation : enfant d'un conteneur à 4 espaces)."""
    return f"""    - Name: {name}
      Type: IType_PanelNavigationButton
      Children:
      - Name: ButtonText
        Type: BaseDataVariableType
        DataType: LocalizedText
        Value: {{"NamespaceIndex":32,"TextId":"{title}"}}
      - Name: PanelToLoad
        Type: BaseDataVariableType
        DataType: NodeId
        Value: "{_PREFIX}/Parts/{target}"
      - Name: PanelLoader
        Type: BaseDataVariableType
        DataType: NodeId
        Children:
        - Name: DynamicLink
          Type: DynamicLink
          DataType: NodePath
          Value: "{loader_path}@NodeId"
"""


def _loader(name: str, initial: str, folder: str = "Parts") -> str:
    return f"""  - Name: {name}
    Type: PanelLoader
    Children:
    - Name: Panel
      Type: NodePointer
      DataType: NodeId
      Value: "{_PREFIX}/{folder}/{initial}"
"""


def _menu_button(name: str, text: str, target: str) -> str:
    return f"""  - Name: {name}
    Type: IType_NavigationButton
    Children:
    - Name: BtText
      Type: BaseDataVariableType
      DataType: LocalizedText
      Value: {{"NamespaceIndex":32,"TextId":"{text}"}}
    - Name: BtPanel
      Type: BaseDataVariableType
      DataType: NodeId
      Value: "{_PREFIX}/Screens/{target}"
"""


UI = f"""Name: UI
Type: FolderType
Children:
- Name: IType_NavigationButton
  Supertype: Rectangle
  Children:
  - Name: BtPanel
    Type: BaseDataVariableType
    DataType: NodeId
- Name: IType_PanelNavigationButton
  Supertype: Rectangle
  Children:
  - Name: PanelToLoad
    Type: BaseDataVariableType
    DataType: NodeId
  - Name: PanelLoader
    Type: BaseDataVariableType
    DataType: NodeId
- Name: IType_MainWindow
  Supertype: Window
  Children:
{_menu_button("BT_Alpha", "Alpha", "IType_00_Alpha")}{_menu_button("BT_Beta", "Beta", "IType_01_Beta")}{_menu_button("BT_Gamma", "Gamma", "IType_02_Gamma")}  - Name: DynamicContent
    Type: PanelLoader
    Children:
    - Name: Panel
      Type: NodePointer
      DataType: NodeId
      Value: "{_PREFIX}/Screens/SplashPanel"
- Name: IType_Confirm
  Supertype: Dialog
  Children:
{_label("LabelPressure", f"{TAGS_A}/Pressure")}- File: Screens/Screens.yaml
- File: Parts/Parts.yaml
"""

SCREENS = (
    """Name: Screens
Type: ScreensCategoryFolder
Children:
- Name: SplashPanel
  Supertype: Panel
- Name: IType_00_Alpha
  Supertype: Panel
  Children:
"""
    + _label("LabelPressure", f"{TAGS_A}/Pressure")
    + _label("LabelLevel", f"{TAGS_A}/Level")
    + _label("LabelPressureCopy", f"{TAGS_A}/Pressure")
    + """- Name: IType_01_Beta
  Supertype: Panel
  Children:
  - Name: Navigation
    Type: RowLayout
    Children:
"""
    + _nav_button("BtOne", "One", "IType_TabOne", "../../../PL_Main")
    + _nav_button("BtTwo", "Two", "IType_TabTwo", "../../../PL_Main")
    + _loader("PL_Main", "IType_TabOne")
    + """- Name: IType_02_Gamma
  Supertype: Panel
  Children:
"""
    + _loader("PL_Fixed", "IType_GammaPanel")
)

PARTS = (
    """Name: Parts
Type: FolderType
Children:
- Name: IType_Gauge
  Supertype: Panel
  Children:
"""
    + _label("LabelLevel", f"{TAGS_A}/Level")
    + _label("LabelSpeed", f"{TAGS_A}/Motor/Speed@Value")
    + """- Name: IType_TabOne
  Supertype: Panel
  Children:
  - Name: Gauge
    Type: IType_Gauge
"""
    + _label("LabelPressure", f"{TAGS_A}/Pressure")
    + """- Name: IType_TabTwo
  Supertype: Panel
  Children:
  - Name: Navigation
    Type: RowLayout
    Children:
"""
    + _nav_button("BtSubA", "SubA", "IType_SubA", "../../../PL_Sub")
    + _nav_button("BtSubB", "SubB", "IType_SubB", "../../../PL_Sub")
    + _loader("PL_Sub", "IType_SubA")
    + """- Name: IType_SubA
  Supertype: Panel
  Children:
"""
    + _label("LabelPressure", f"{TAGS_A}/Pressure")
    + _label("LabelLevel", f"{TAGS_A}/Level")
    + """- Name: IType_SubB
  Supertype: Panel
  Children:
"""
    + _label("LabelTemp", f"{TAGS_B}/Temp")
    + """- Name: IType_GammaPanel
  Supertype: Panel
  DisplayName: {"LocaleId":"fr-FR","Text":"Gamma panel"}
  Children:
"""
    + _label("LabelCount", f"{TAGS_A}/Counters/Count1")
)


def make_project_v13(base: Path, name: str = "Demo13") -> Path:
    """Crée le projet de style 1.3 sous ``base/<name>`` (stations et tags de ``make_project``) et renvoie son dossier."""
    folder = make_project(base, name=name)
    ui = folder / "Nodes" / "UI"
    (ui / "Screens").mkdir()
    (ui / "Parts").mkdir()
    (ui / "UI.yaml").write_text(UI, encoding="utf-8")
    (ui / "Screens" / "Screens.yaml").write_text(SCREENS, encoding="utf-8")
    (ui / "Parts" / "Parts.yaml").write_text(PARTS, encoding="utf-8")
    return folder
