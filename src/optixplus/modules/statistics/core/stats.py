"""Calcul des statistiques d'un projet ou d'un runtime FT Optix (sans Qt).

Une seule passe sur ``OptixProject.all_nodes`` relève les liaisons (``DynamicLink``), les
pointeurs, les instances de types et les objets à compter ; les résultats sont rangés par
**type du projet** (une « unité » : vue ou panneau). Une page agrège ensuite ses propres
liaisons et celles de toutes les unités qu'elle instancie (sous-vues partagées comptées une
fois). Rien n'est écrit sur le disque.

Règles retenues
---------------
- Un tag d'automate est atteint par un chemin ``/Objects/<Projet>/CommDrivers/<Pilote>/<Station>/Tags/…``
  (absolu, ou relatif résolu par ``OptixProject.resolve``). Les tags **distincts** d'une page sont
  les chemins distincts (suffixe ``@…`` retiré).
- Une liaison peut cibler un convertisseur ou une variable intermédiaire : leurs sources
  (``DynamicLink`` enfants, deux niveaux) sont suivies une seule fois.
- Un chemin dynamique (``{0}`` d'un ``StringFormatter``) compte comme une liaison et comme **un**
  tag (le motif), jamais comme une liste d'indices inventés : la page est alors ``approximate``.
- Les pilotes connus sont décrits dans ``DRIVERS`` (seul CODESYS est vérifié sur de vrais projets).

Tags utilisés
-------------
Un tag d'automate (structure comprise) est « utilisé » s'il est référencé **n'importe où dans le projet**
(vues, types, alarmes, enregistreurs, convertisseurs…, pas seulement les pages principales) : par un
``DynamicLink`` (direct, ou porté par un convertisseur / une variable intermédiaire : leurs liaisons sources
sont des nœuds du projet, donc comptées aussi lorsque personne n'utilise le convertisseur), par un
``NodePointer`` ou par toute autre valeur de nœud qui est un chemin absolu de tag. Un chemin qui descend
sous un tag (propriété, ``@Value``) utilise ce tag.

- Une **structure** ciblée est utilisée, ainsi que tous ses tags descendants. Un tag ciblé n'utilise **pas** sa
  structure parente : elle n'est utilisée que si elle est elle-même référencée.
- Un chemin dynamique (``{0}`` d'un ``StringFormatter``) devient une expression régulière (``{0}`` → chiffres)
  ; tous les tags qu'elle peut viser sont marqués utilisés et le total est signalé approximatif (« ≈ »).
  Choix : mieux vaut un peu trop de tags utilisés qu'un tag réellement lu déclaré inutile.
- Un accès par NetLogic C# (chemin écrit dans le code) n'est pas détecté : un avertissement l'indique si le
  projet contient des NetLogic.
- Inutilisés = synchronisés − utilisés.

"""

from __future__ import annotations

import json
import logging
import os
import re
from bisect import bisect_left
from collections import deque
from dataclasses import dataclass, field

from optixplus.common.i18n import tr
from optixplus.common.optix import project as optix_project
from optixplus.common.optix.model import Node, OptixProject
from optixplus.common.progress import CancelCheck, ProgressCallback, check_cancel, report

from .model import (
    KIND_PROJECT,
    KIND_RUNTIME,
    VIEW_DIALOG,
    VIEW_POPUP,
    VIEW_SCREEN,
    VIEW_WINDOW,
    PageStats,
    ProjectStatistics,
    StationStats,
    StatisticsOptions,
    PageRow,
)

log = logging.getLogger("optixplus.statistics")

CHECK_EVERY = 5000  # éléments entre deux contrôles d'annulation

# --------------------------------------------------------------------------- configuration des pilotes


@dataclass(frozen=True)
class DriverSpec:
    """Ce que l'on sait d'un pilote de communication."""

    station_types: tuple[str, ...]
    tag_types: tuple[str, ...]  # types des nœuds comptés comme tags
    structure_types: tuple[str, ...]  # parmi les tags, ceux qui sont des structures


#: Pilote (type du nœud sous ``CommDrivers``) -> description. Ajouter ici Logix, Modbus, OPC UA.
DRIVERS: dict[str, DriverSpec] = {
    "CODESYSDriver": DriverSpec(("CODESYSStation",), ("CODESYSTag", "TagStructure"), ("TagStructure",)),
}
#: Types qui ne sont jamais des tags (pilote inconnu : on compte les autres nœuds de ``Tags``).
GENERIC_TYPES = frozenset({
    "FolderType", "BaseDataVariableType", "BaseVariableType", "PropertyType", "BaseObjectType",
    "DynamicLink", "NodePointer", "Alias",
})

# --------------------------------------------------------------------------- vues
_VIEW_BASES = {"Screen": VIEW_SCREEN, "Dialog": VIEW_DIALOG, "Window": VIEW_WINDOW, "Popup": VIEW_POPUP}
_PANEL = "panel"
_OTHER = "other"
_MAIN_KINDS = frozenset(_VIEW_BASES.values())
_PREFIX_RE = re.compile(r"^IType_(?:\d+_)?", re.IGNORECASE)
_TAG_RE = re.compile(r"^/Objects/[^/]+/CommDrivers/[^/]+/[^/]+/Tags(?:/|$)")
_ROW_SPLIT = re.compile(r"\r\n|\r|\n")

IMAGE_EXT = frozenset({".png", ".jpg", ".jpeg", ".bmp", ".gif", ".svg"})
FONT_EXT = frozenset({".ttf", ".otf"})


# --------------------------------------------------------------------------- utilitaires
class _Ticker:
    """Contrôle d'annulation et progression tous les ``CHECK_EVERY`` éléments."""

    def __init__(self, progress: ProgressCallback | None, cancel: CancelCheck | None, phase: str, total: int) -> None:
        self.progress, self.cancel, self.phase, self.total = progress, cancel, phase, total
        self.count = 0

    def tick(self) -> None:
        self.count += 1
        if self.count % CHECK_EVERY == 0:
            check_cancel(self.cancel)
            report(self.progress, self.phase, "", self.count, self.total)


class _RawLines:
    """Lignes des YAML, lues à la demande (valeurs sur une ligne que le chargeur ne rend pas)."""

    def __init__(self) -> None:
        self._cache: dict[str, list[str]] = {}

    def lines(self, path: str | None) -> list[str]:
        if not path:
            return []
        if path not in self._cache:
            try:
                with open(path, encoding="utf-8-sig", errors="replace") as fh:
                    self._cache[path] = _ROW_SPLIT.split(fh.read())
            except OSError:
                self._cache[path] = []
        return self._cache[path]

    def value_text(self, node: Node) -> str:
        """Texte brut de la clé ``Value`` d'un nœud (sur sa ligne), vide si introuvable."""
        if isinstance(node.value, str):
            return node.value
        if node.value_line <= 0:
            return ""
        lines = self.lines(node.file)
        if node.value_line > len(lines):
            return ""
        match = re.match(r"^\s*(?:- )?Value:\s*(.*)$", lines[node.value_line - 1])
        return match.group(1).strip() if match else ""

    def key_text(self, node: Node, key: str) -> str:
        """Texte brut d'une clé du nœud lui-même (``DisplayName``…), vide si absente."""
        lines = self.lines(node.file)
        if node.line <= 0 or node.line > len(lines):
            return ""
        head = re.match(r"^(\s*)(- )?", lines[node.line - 1])
        indent = len(head.group(1)) + (2 if head.group(2) else 0)
        pattern = re.compile(r"^ {%d}%s:\s*(.*)$" % (indent, re.escape(key)))
        for text in lines[node.line:min(node.end_line - 1, len(lines))]:
            if text.startswith(" " * indent + "Children:"):
                break
            match = pattern.match(text)
            if match:
                return match.group(1).strip()
        return ""


def localized_text(raw: str) -> str:
    """Texte (``Text``, sinon ``TextId``) d'un ``LocalizedText`` écrit en JSON sur une ligne."""
    raw = raw.strip()
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
        except ValueError:
            return ""
        return str(data.get("Text") or data.get("TextId") or "") if isinstance(data, dict) else ""
    return raw.strip("\"'")


def short_name(name: str) -> str:
    """Nom technique sans le préfixe ``IType_NN_``."""
    return _PREFIX_RE.sub("", name)


def _tag_key(path: str) -> str:
    return path.split("@", 1)[0].strip()


@dataclass
class _Unit:
    """Un type du projet (vue ou panneau) : ses propres liaisons et ses instances."""

    node: Node
    kind: str
    links: set[int] = field(default_factory=set)  # identifiants des nœuds de liaison
    keys: set[str] = field(default_factory=set)  # chemins de tags distincts
    approximate: bool = False
    edges: dict[str, None] = field(default_factory=dict)  # chemins des unités instanciées


class _Analyzer:
    def __init__(self, project: OptixProject) -> None:
        self.project = project
        self.types = project.types_by_name
        self.raw = _RawLines()
        self._root_cache: dict[str, str] = {}
        self._owner: dict[int, Node | None] = {}
        self.units: dict[str, _Unit] = {}
        self._source_cache: dict[int, list[Node]] = {}
        self.used_refs: set[str] = set()  # chemins de tags référencés (``{0}`` possibles), projet entier

    # ---- types
    def root_type(self, name: str | None) -> str:
        """Nom du type intégré au bout de la chaîne des supertypes."""
        if name is None:
            return ""
        if name in self._root_cache:
            return self._root_cache[name]
        seen: set[str] = set()
        current = name
        while current in self.types and current not in seen:
            seen.add(current)
            current = self.types[current].supertype or ""
        self._root_cache[name] = current
        return current

    def kind_of_base(self, supertype: str | None) -> str:
        root = self.root_type(supertype)
        if root in _VIEW_BASES:
            return _VIEW_BASES[root]
        return _PANEL if root == "Panel" else _OTHER

    # ---- unités
    def unit_node(self, node: Node) -> Node | None:
        """Type du projet qui déclare ce nœud (le nœud lui-même s'il est un type)."""
        if node.supertype is not None:
            return node
        path: list[Node] = []
        current: Node | None = node
        result: Node | None = None
        while current is not None:
            if id(current) in self._owner:
                result = self._owner[id(current)]
                break
            if current.supertype is not None:
                result = current
                break
            path.append(current)
            current = current.parent
        for item in path:
            self._owner[id(item)] = result
        return result

    def unit(self, node: Node) -> _Unit:
        key = node.path()
        found = self.units.get(key)
        if found is None:
            found = _Unit(node, self.kind_of_base(node.supertype))
            self.units[key] = found
        return found

    # ---- tags
    def _tag_path_of(self, value: str, origin: Node) -> tuple[str, bool] | None:
        """(clé de tag, approximatif) pour un chemin de liaison, ``None`` si ce n'est pas un tag."""
        value = value.strip()
        if not value:
            return None
        if value.startswith("/Objects/") and "/CommDrivers/" in value:
            if _TAG_RE.match(value):
                return _tag_key(value), "{" in value
            return None
        if "{" in value:
            return None
        target, code, _ = self.project.resolve(value, origin)
        if target is not None and code == "ok":
            path = target.path()
            if _TAG_RE.match(path):
                return _tag_key(path), False
        return None

    def link_value(self, node: Node) -> str:
        """Chemin d'un ``DynamicLink`` : sa valeur, ou le format de son ``StringFormatter``."""
        if isinstance(node.value, str):
            return node.value
        formatter = node.children.get("DynamicLinkFormatter")
        if formatter is not None:
            fmt = formatter.children.get("Format")
            if fmt is not None:
                return localized_text(self.raw.value_text(fmt))
        return ""

    def sources_of(self, target: Node) -> list[Node]:
        """Liaisons-sources d'un convertisseur ou d'une variable, sur deux niveaux."""
        cached = self._source_cache.get(id(target))
        if cached is not None:
            return cached
        found: list[Node] = []
        for child in target.children.values():
            if child.type == "DynamicLink":
                found.append(child)
            else:
                found.extend(g for g in child.children.values() if g.type == "DynamicLink")
        self._source_cache[id(target)] = found
        return found

    def add_link(self, unit: _Unit | None, node: Node, follow: bool = True) -> None:
        value = self.link_value(node)
        if not value:
            return
        hit = self._tag_path_of(value, node)
        if hit is not None:
            self.used_refs.add(hit[0])
            if unit is not None:
                unit.links.add(id(node))
                unit.keys.add(hit[0])
                unit.approximate = unit.approximate or hit[1]
            return
        if not follow or unit is None or "{" in value or "/CommDrivers/" in value:
            return
        target, code, _ = self.project.resolve(value, node)
        if target is None or code != "ok":
            return
        for source in self.sources_of(target):
            self.add_link(unit, source, follow=False)

    def add_pointer(self, unit: _Unit | None, node: Node, value: str) -> None:
        """Pointeur vers un tag (équipement), ou vers un panneau du projet (sous-vue)."""
        hit = self._tag_path_of(value, node) if value.startswith("/Objects/") else None
        if hit is not None:
            self.used_refs.add(hit[0])
        if unit is None:
            return
        if hit is not None:
            unit.links.add(id(node))
            unit.keys.add(hit[0])
            return
        self.add_edge(unit, value.rsplit("/", 1)[-1])

    def add_edge(self, unit: _Unit, type_name: str) -> None:
        target = self.types.get(type_name)
        if target is None or self.kind_of_base(target.supertype) in _MAIN_KINDS:
            return
        path = target.path()
        if path != unit.node.path():
            unit.edges[path] = None


# --------------------------------------------------------------------------- lecture du .optix
def _read_optix_header(folder: str) -> tuple[str, str, dict[str, int]]:
    """(version produit, version du noyau, statistiques de Studio)."""
    for name in sorted(os.listdir(folder)):
        if name.lower().endswith(optix_project.OPTIX_SUFFIX) and os.path.isfile(os.path.join(folder, name)):
            with open(os.path.join(folder, name), "rb") as fh:
                lines = fh.read().splitlines()
            meta = optix_project.parse_optix(lines)
            core = ""
            for line in lines:
                text = line.decode("utf-8", "replace")
                if text.startswith(" ") and not text.startswith("  ") and text.strip().startswith("CoreVersion:"):
                    core = text.split(":", 1)[1].strip()
                    break
            return meta.product_version, core, dict(meta.statistics)
    return "", "", {}


# --------------------------------------------------------------------------- images et fichiers
def _scan_files(folder: str, ticker: _Ticker) -> dict:
    """Taille de ProjectFiles, nombre et taille des images et des polices."""
    out = {"bytes": 0, "img_n": 0, "img_b": 0, "font_n": 0, "font_b": 0}
    for root, _dirs, files in os.walk(os.path.join(folder, "ProjectFiles")):
        for name in files:
            ticker.tick()
            try:
                size = os.path.getsize(os.path.join(root, name))
            except OSError:
                continue
            out["bytes"] += size
            ext = os.path.splitext(name)[1].lower()
            if ext in IMAGE_EXT:
                out["img_n"] += 1
                out["img_b"] += size
            elif ext in FONT_EXT:
                out["font_n"] += 1
                out["font_b"] += size
    return out


# --------------------------------------------------------------------------- calcul principal
def compute(
    folder: str,
    progress: ProgressCallback | None = None,
    cancel: CancelCheck | None = None,
    options: StatisticsOptions | None = None,
) -> ProjectStatistics:
    """Analyse un projet ou un runtime FT Optix. Lève ``Cancelled`` si l'annulation est demandée."""
    options = options or StatisticsOptions()
    project = OptixProject(folder).load(progress, cancel)
    folder = project.folder
    runtime_dir = os.path.join(folder, "ApplicationFiles")
    result = ProjectStatistics(
        name=project.name, folder=folder, kind=KIND_RUNTIME if os.path.isdir(runtime_dir) else KIND_PROJECT
    )
    result.ide_version = optix_project.read_ide_version(folder) or ""
    result.product_version, result.core_version, result.studio_counts = _read_optix_header(folder)
    result.nodes = len(project.all_nodes)
    result.files = project.files_loaded
    if project.pyyaml_files:
        result.warnings.append(
            tr("{count} file(s) outside the usual Optix format were read with PyYAML.").format(count=project.pyyaml_files)
        )

    an = _Analyzer(project)
    root = project.objects.children.get(project.name) or next(iter(project.objects.children.values()), None)

    # --- une passe sur tous les nœuds
    check_cancel(cancel)
    phase = tr("Analysing nodes")
    ticker = _Ticker(progress, cancel, phase, result.nodes)
    report(progress, phase, "", 0, result.nodes)
    nav_titles: dict[str, str] = {}  # nom de type de vue -> texte du bouton de menu qui l'ouvre
    main_names: set[str] = set()  # noms de types ouverts depuis un menu ou au démarrage
    for node in project.all_nodes:
        ticker.tick()
        ntype = node.type
        if node.supertype is not None:
            if node.supertype in an.types:
                an.add_edge(an.unit(node), node.supertype)
            elif an.kind_of_base(node.supertype) != _OTHER:
                an.unit(node)
            continue
        if isinstance(node.value, str) and node.value.startswith("/Objects/") and _TAG_RE.match(node.value):
            an.used_refs.add(_tag_key(node.value))  # tout autre lien vers un tag
        if ntype is None:
            continue
        owner = an.unit_node(node)
        unit = an.unit(owner) if owner is not None else None
        if ntype == "DynamicLink":
            an.add_link(unit, node)
        elif ntype == "NodePointer" and isinstance(node.value, str):
            if node.name == "Panel" and node.parent is not None and node.parent.type == "PanelLoader":
                main_names.add(node.value.rsplit("/", 1)[-1])
            an.add_pointer(unit, node, node.value)
        elif node.name == "BtPanel" and isinstance(node.value, str):
            target = node.value.rsplit("/", 1)[-1]
            main_names.add(target)
            sibling = node.parent.children.get("BtText") if node.parent is not None else None
            if sibling is not None and target not in nav_titles:
                nav_titles[target] = localized_text(an.raw.value_text(sibling))
        if unit is not None and ntype in an.types:
            an.add_edge(unit, ntype)

    # --- automates
    check_cancel(cancel)
    tag_index = _stations(result, root, ticker)

    # --- alarmes, NetLogic, loggers
    for node in project.all_nodes:
        ticker.tick()
        if node.supertype is not None or node.type is None:
            continue
        base = an.root_type(node.type)
        if base in ("NetLogic", "BaseNetLogic"):
            result.netlogic += 1
        elif base in ("DataLogger", "EventLogger"):
            result.loggers += 1
    _mark_used(result, an.used_refs, tag_index)
    if result.netlogic:
        result.warnings.append(tr("Tags used only from NetLogic code are not counted as used."))
    alarms = root.children.get("Alarms") if root is not None else None
    if alarms is not None:
        stack = list(alarms.children.values())
        while stack:
            node = stack.pop()
            ticker.tick()
            base = an.root_type(node.type) if node.supertype is None else ""
            if "Alarm" in base and not base.endswith("Folder"):
                result.alarms += 1
            stack.extend(node.children.values())

    # --- pages
    check_cancel(cancel)
    _pages(result, an, options, nav_titles, main_names)

    # --- fichiers
    check_cancel(cancel)
    phase = tr("Reading project files")
    report(progress, phase, "", 0, 0)
    files = _scan_files(folder, _Ticker(progress, cancel, phase, 0))
    result.project_files_bytes = files["bytes"]
    result.image_files, result.image_bytes = files["img_n"], files["img_b"]
    result.font_files, result.font_bytes = files["font_n"], files["font_b"]
    if result.kind == KIND_RUNTIME:
        entries: list[tuple[str, int]] = []
        for dirpath, _dirs, names in os.walk(runtime_dir):
            for name in names:
                full = os.path.join(dirpath, name)
                try:
                    size = os.path.getsize(full)
                except OSError:
                    continue
                entries.append((os.path.relpath(full, runtime_dir), size))
        result.runtime_files = sorted(entries, key=lambda e: (-e[1], e[0]))
    report(progress, tr("Done"), "", 1, 1)
    return result


def _stations(result: ProjectStatistics, root: Node | None, ticker: _Ticker) -> dict[str, tuple[StationStats, bool]]:
    """Remplit les stations ; renvoie l'index ``chemin du tag -> (station, est une structure)``."""
    index: dict[str, tuple[StationStats, bool]] = {}
    drivers = root.children.get("CommDrivers") if root is not None else None
    if drivers is None:
        return index
    seen: set[str] = set()
    for driver in drivers.children.values():
        spec = DRIVERS.get(driver.type or "")
        if spec is None and any("Tags" in s.children for s in driver.children.values()):
            result.warnings.append(
                tr("Unknown driver type {type} ({name}): its tags are counted approximately.").format(
                    type=driver.type or "?", name=driver.name
                )
            )
        for station in driver.children.values():
            tags_root = station.children.get("Tags")
            is_station = (station.type in spec.station_types) if spec else tags_root is not None
            path = station.path()
            if not is_station or path in seen:
                continue
            seen.add(path)
            info = StationStats(
                name=station.name, path=path, driver_type=driver.type or "", station_type=station.type or ""
            )
            addr = station.children.get("PLCAddress") or station.children.get("GatewayIP")
            if addr is not None and addr.value is not None:
                info.address = str(addr.value)
            port = station.children.get("Port")
            if port is not None and port.value is not None:
                info.port = str(port.value)
            base = path + "/Tags"
            stack = [(c, f"{base}/{c.name}") for c in tags_root.children.values()] if tags_root is not None else []
            while stack:
                node, node_path = stack.pop()
                ticker.tick()
                ntype = node.type or ""
                if spec is not None:
                    if ntype in spec.tag_types:
                        info.tags += 1
                        index[node_path] = (info, ntype in spec.structure_types)
                    if ntype in spec.structure_types:
                        info.structures += 1
                elif ntype and ntype not in GENERIC_TYPES and node.supertype is None:
                    info.tags += 1
                    index[node_path] = (info, False)
                stack.extend((c, f"{node_path}/{c.name}") for c in node.children.values())
            result.stations.append(info)
    result.tags_total = sum(s.tags for s in result.stations)
    result.structures_total = sum(s.structures for s in result.stations)
    return index


_DYNAMIC_INDEX = re.compile(r"\{\d+\}")


def _mark_used(result: ProjectStatistics, refs: set[str], index: dict[str, tuple[StationStats, bool]]) -> None:
    """Calcule les tags utilisés (voir « Tags utilisés » en tête de module) ; une passe sur les références."""
    if not index:
        return
    ordered = sorted(index)
    used: set[str] = set()
    approximate: set[str] = set()  # tags marqués par un chemin dynamique seulement

    def mark(path: str, target: set[str]) -> None:
        target.add(path)
        if index[path][1]:  # structure : tous ses descendants
            prefix = path + "/"
            i = bisect_left(ordered, prefix)
            while i < len(ordered) and ordered[i].startswith(prefix):
                target.add(ordered[i])
                i += 1

    patterns: set[str] = set()
    for ref in refs:
        if "{" in ref:
            patterns.add(ref)
            continue
        path = ref
        while path and _TAG_RE.match(path):  # un chemin sous un tag (propriété) utilise ce tag
            if path in index:
                mark(path, used)
                break
            path = path.rpartition("/")[0]
    for ref in patterns:
        literal = ref.split("{", 1)[0]
        regex = re.compile("".join(
            r"\d+" if _DYNAMIC_INDEX.fullmatch(part) else re.escape(part)
            for part in re.split(r"(\{\d+\})", ref)
        ))
        i = bisect_left(ordered, literal)
        while i < len(ordered) and ordered[i].startswith(literal):
            if regex.fullmatch(ordered[i]):
                mark(ordered[i], approximate)
            i += 1
    for path in used | approximate:
        station = index[path][0]
        station.tags_used += 1
        if path not in used:
            station.tags_used_approximate = True
    result.tags_used = len(used | approximate)
    result.tags_used_approximate = bool(approximate - used)


def _closure(an: _Analyzer, start: _Unit, skip: frozenset[str] = frozenset()) -> tuple[set[int], set[str], bool, int]:
    """Liaisons, tags distincts, approximation et nombre de panneaux d'une unité et de ses sous-vues
    (sans entrer dans les unités de ``skip``)."""
    seen = {start.node.path()}
    queue = deque([start])
    links: set[int] = set()
    keys: set[str] = set()
    approx = False
    panels = 0
    while queue:
        unit = queue.popleft()
        links |= unit.links
        keys |= unit.keys
        approx = approx or unit.approximate
        for path in unit.edges:
            if path not in seen and path not in skip:
                seen.add(path)
                target = an.units.get(path)
                if target is not None:
                    queue.append(target)
                    panels += target.kind == _PANEL
    return links, keys, approx, panels


def _pages(result: ProjectStatistics, an: _Analyzer, options: StatisticsOptions, nav_titles: dict[str, str],
           main_names: set[str]) -> None:
    views = [u for u in an.units.values() if u.kind in _MAIN_KINDS]

    main = {u.node.path() for u in views if u.kind == VIEW_SCREEN and u.node.name in main_names}
    if not main:
        main = {u.node.path() for u in views if u.kind == VIEW_SCREEN}
        if main:
            result.warnings.append(tr("No menu or start-up link found: every screen is counted as a main page."))
    pages: list[PageStats] = []
    for unit in views:
        node = unit.node
        links, keys, approx, panels = _closure(an, unit)
        title = localized_text(an.raw.key_text(node, "DisplayName")) or nav_titles.get(node.name, "") or node.name
        pages.append(PageStats(
            name=node.name, title=title, kind=unit.kind, path=node.path(),
            is_main=node.path() in main, links=len(links), tags=len(keys), approximate=approx, subviews=panels,
        ))
        if approx and node.path() in main:
            result.warnings.append(
                tr("Page {name}: dynamic paths cannot be resolved, tag count is approximate.").format(name=title)
            )
    pages.sort(key=lambda p: (not p.is_main, p.path))
    result.pages = pages
    mains = [p for p in pages if p.is_main]
    result.main_pages = len(mains)
    result.work_page = _find(pages, options.work_names)
    result.supervision_page = _find(pages, options.supervision_names)
    cache: dict[str, tuple[list[PageRow], PageRow]] = {}

    def rows_of(page: PageStats | None) -> tuple[list[PageRow], PageRow] | None:
        unit = an.units.get(page.path) if page is not None else None
        if unit is None:
            return None
        if page.path not in cache:
            rows, default, _unknown = _tab_rows(an, unit, page.title, [], frozenset({page.path}))
            cache[page.path] = (rows, default or PageRow(
                page.title, page.path, [], page.links, page.tags, page.approximate, page.subviews, tab_unknown=True
            ))
        return cache[page.path]

    for page in mains:
        found = rows_of(page)
        if found is not None:
            result.rows.extend(found[0])
    if result.rows:
        result.average_tags_per_view = sum(r.tags for r in result.rows) / len(result.rows)
        result.busiest_row = max(result.rows, key=lambda r: r.tags)
    for page, attr in ((result.work_page, "work_row"), (result.supervision_page, "supervision_row")):
        found = rows_of(page)
        if found is not None:
            setattr(result, attr, found[1])


def _find(pages: list[PageStats], names: tuple[str, ...]) -> PageStats | None:
    """Page dont le nom affiché ou technique (sans ``IType_NN_``) est l'un des noms, sans tenir compte de la casse."""
    wanted = {n.strip().lower() for n in names if n.strip()}

    def candidates(page: PageStats) -> set[str]:
        return {page.title.lower(), page.name.lower(), short_name(page.name).lower()}

    screens = [p for p in pages if p.kind == VIEW_SCREEN]
    for pool in ([p for p in screens if p.is_main], screens, pages):
        for page in pool:
            if candidates(page) & wanted:
                return page
    for page in pages:
        if page.is_main and any(w in c for w in wanted for c in candidates(page)):
            return page
    return None


def _find_nav(an: _Analyzer, start: _Unit) -> Node | None:
    """Premier ``NavigationPanel`` de l'unité, sinon de ses sous-vues."""
    seen = {start.node.path()}
    queue = deque([start])
    while queue:
        unit = queue.popleft()
        nodes = deque(unit.node.children.values())
        while nodes:
            node = nodes.popleft()
            if node.type == "NavigationPanel":
                return node
            nodes.extend(node.children.values())
        for path in unit.edges:
            if path not in seen and path in an.units:
                seen.add(path)
                queue.append(an.units[path])
    return None


def _tab_rows(an: _Analyzer, unit: _Unit, title: str, tabs: list[str], visited: frozenset[str]
              ) -> tuple[list[PageRow], PageRow | None, bool]:
    """Lignes (page ou feuilles d'onglet) d'une unité, ligne de l'onglet par défaut, onglet inconnu ?

    Sans ``NavigationPanel`` : une seule ligne. Avec : une ligne par feuille d'onglet (onglets imbriqués
    suivis), plus une ligne pour le contenu hors onglets seulement s'il a ses propres liaisons.
    L'onglet par défaut est ``CurrentTabIndex`` s'il a une valeur scalaire, sinon le premier ; hors limites,
    il est inconnu (``None``).
    """
    path = unit.node.path()

    def row(source: _Unit, labels: list[str], skip: frozenset[str] = frozenset()) -> PageRow:
        links, keys, approx, panels = _closure(an, source, skip)
        return PageRow(title, path, list(labels), len(links), len(keys), approx, panels)

    nav = _find_nav(an, unit)
    panels_node = nav.children.get("Panels") if nav is not None else None
    items = [c for c in panels_node.children.values() if c.type == "NavigationPanelItem"] if panels_node is not None else []
    if not items:
        single = row(unit, tabs)
        return [single], single, False
    index: int | None = 0
    current = nav.children.get("CurrentTabIndex")
    if current is not None and isinstance(current.value, int) and not isinstance(current.value, bool):
        index = current.value
    if not 0 <= index < len(items):
        index = None
    targets: list[_Unit | None] = []
    for item in items:
        pointer = item.children.get("Panel")
        name = pointer.value.rsplit("/", 1)[-1] if pointer is not None and isinstance(pointer.value, str) else ""
        node = an.types.get(name)
        targets.append(an.units.get(node.path()) if node is not None else None)
    skip = frozenset(u.node.path() for u in targets if u is not None)
    rows: list[PageRow] = []
    own = row(unit, tabs, skip)
    if own.links:
        rows.append(own)
    default: PageRow | None = None
    unknown = index is None
    for i, item in enumerate(items):
        label = item.children.get("Title")
        text = localized_text(an.raw.value_text(label)) if label is not None else ""
        sub_tabs = [*tabs, text or item.name]
        target = targets[i]
        if target is None or target.node.path() in visited:
            leaf = PageRow(title, path, sub_tabs)
            sub_rows, sub_default, sub_unknown = [leaf], leaf, False
        else:
            sub_rows, sub_default, sub_unknown = _tab_rows(an, target, title, sub_tabs, visited | {target.node.path()})
        rows.extend(sub_rows)
        if i == index:
            default, unknown = sub_default, sub_unknown
    return rows, default, unknown
