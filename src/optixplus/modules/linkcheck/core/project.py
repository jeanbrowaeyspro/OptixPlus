"""Projet FT Optix chargé depuis ses YAML, et résolution des liens dynamiques (repris de Link Checker).

Un projet Optix est un dossier contenant ``<Nom>.optix`` et un sous-dossier ``Nodes/`` dont
les YAML décrivent l'arbre des nœuds. Chaque nœud a un ``Name``, un ``Type`` (ou
``Supertype`` pour un type du projet), des ``Children`` et parfois une ``Value``. Les
liens dynamiques sont des enfants de type ``DynamicLink`` dont la ``Value`` est un chemin
absolu (``/Objects/<Projet>/…``) ou relatif (``../..``).

Corrections par rapport à l'outil d'origine :
- construction de l'arbre **itérative** (plus de dépassement de la pile de récursion sur
  les projets très profonds) ;
- progression calculée sur les fichiers **réellement inclus** (``File:``), découverts au
  fil du chargement, et non sur tous les ``.yaml`` du dossier ;
- analyse annulable ;
- nom du projet lu dans le bloc ``Project:`` du ``.optix`` (et non la première ligne
  ``Name:`` rencontrée).
"""

from __future__ import annotations

import os
import re
from collections import deque
from dataclasses import dataclass, field

import yaml

from ....common.i18n import tr
from ....common.optix.project import ProjectError, project_folder, read_project_meta  # noqa: F401
from ....common.progress import CancelCheck, ProgressCallback, check_cancel, report

Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)

POINTER_DATATYPES = ("NodeId", "NodePointer", "VariablePointer")
POINTER_TYPES = ("NodePointer", "Alias")
BUILTIN_PROJECT_ROOTS = ("Server", "Users", "RetainedAlarms", "Commands")

# Raisons d'un lien cassé (codes stables ; le libellé est traduit à l'affichage).
REASON_FOREIGN = "foreign"  # vise un autre projet
REASON_MISSING = "missing"  # segment introuvable
REASON_ABOVE_ROOT = "above_root"  # remonte au-dessus de la racine
# Liens non vérifiables, comptés à part.
SKIP_ALIAS = "alias"
SKIP_BUILTIN = "builtin"
SKIP_POINTER = "pointer"

_NS_PREFIX = re.compile(r"^ns=\d+;")
_INDEX_PREFIX = re.compile(r"^\d+:")
_ARRAY = re.compile(r"^(.*?)\[(\d+)\]$")


class Node:
    __slots__ = (
        "name", "type", "supertype", "datatype", "value", "children", "parent",
        "file", "line", "end_line", "value_line", "_path",
    )

    def __init__(self, name: str, parent: Node | None, file: str | None) -> None:
        self.name = name
        self.type: str | None = None
        self.supertype: str | None = None
        self.datatype: str | None = None
        self.value = None
        self.children: dict[str, Node] = {}
        self.parent = parent
        self.file = file  # YAML qui déclare ce nœud
        self.line = 0  # ligne (1-based) du « - Name: »
        self.end_line = 0  # ligne exclusive de fin du bloc
        self.value_line = 0  # ligne (1-based) de la clé Value
        self._path: str | None = None

    def path(self) -> str:
        """Chemin absolu, calculé une fois (utilisé intensivement par les suggestions)."""
        if self._path is None:
            parts = []
            node: Node | None = self
            while node is not None:
                parts.append(node.name)
                node = node.parent
            self._path = "/" + "/".join(reversed(parts))
        return self._path

    def studio_path(self, project_name: str) -> str:
        """Chemin tel qu'on le parcourt dans l'arborescence de Studio (sans /Objects/<Projet>)."""
        p = self.path()
        prefix = "/Objects/" + project_name + "/"
        return p[len(prefix):] if p.startswith(prefix) else p


@dataclass
class BrokenLink:
    file: str  # YAML (chemin absolu)
    line: int  # ligne de la Value du DynamicLink (1-based)
    block_start: int  # ligne du « - Name: DynamicLink » (1-based)
    block_end: int  # ligne exclusive de fin du bloc
    owner_path: str  # chemin Studio de la variable qui porte le lien
    prop: str  # nom de la propriété liée
    target: str  # cible telle qu'écrite
    reason: str  # REASON_*
    detail: str  # segment introuvable, ou nom du projet étranger
    screen: str  # écran ou zone
    suggestions: list[str] = field(default_factory=list)


@dataclass
class LinkStats:
    resolved: int = 0
    alias: int = 0
    pointer: int = 0
    builtin: int = 0

    @property
    def unverifiable(self) -> int:
        return self.alias + self.pointer


def reason_label(link: BrokenLink) -> str:
    """Libellé traduit de la raison d'un lien cassé."""
    if link.reason == REASON_FOREIGN:
        return tr("Points to another project: {name}").format(name=link.detail)
    if link.reason == REASON_ABOVE_ROOT:
        return tr("Goes above the root")
    return tr("Segment not found: {segment}").format(segment=link.detail)


class OptixProject:
    """Arbre des nœuds d'un projet ; construit par ``load()``."""

    def __init__(self, folder: str) -> None:
        self.folder = project_folder(folder)
        self.name, root = read_project_meta(self.folder)
        self.nodes_dir = os.path.join(self.folder, "Nodes")
        self._root_hint = root
        self.objects = Node("Objects", None, None)
        self.all_nodes: list[Node] = []
        self.types_by_name: dict[str, Node] = {}
        self.by_name: dict[str, list[Node]] = {}
        self.files_loaded = 0

    # ---- chargement ------------------------------------------------------------
    def _root_file(self) -> str:
        if self._root_hint:
            candidate = os.path.normpath(os.path.join(self.folder, self._root_hint))
            if os.path.isfile(candidate):
                return candidate
        candidate = os.path.join(self.nodes_dir, self.name + ".yaml")
        if os.path.isfile(candidate):
            return candidate
        yamls = sorted(f for f in os.listdir(self.nodes_dir) if f.lower().endswith(".yaml"))
        if not yamls:
            raise ProjectError(tr("No root YAML file in {folder}").format(folder=self.nodes_dir))
        return os.path.join(self.nodes_dir, yamls[0])

    def load(self, progress: ProgressCallback | None = None, cancel: CancelCheck | None = None) -> OptixProject:
        """Charge tous les fichiers inclus. Les inclusions (``File:``) sont mises en file et
        chargées ensuite : le total affiché est « chargés + en attente », donc exact."""
        pending: deque[tuple[str, Node]] = deque([(self._root_file(), self.objects)])
        phase = tr("Loading project files")
        while pending:
            check_cancel(cancel)
            path, parent = pending.popleft()
            self.files_loaded += 1
            rel = os.path.relpath(path, self.nodes_dir)
            report(progress, phase, rel, self.files_loaded, self.files_loaded + len(pending))
            node = self._load_file(path, parent, pending)
            if node is not None:
                parent.children[node.name] = node
        return self

    def _load_file(self, path: str, parent: Node, pending: deque) -> Node | None:
        try:
            with open(path, encoding="utf-8-sig") as fh:
                loader = Loader(fh.read())
        except OSError as exc:
            raise ProjectError(tr("Cannot read {file}: {error}").format(file=path, error=exc)) from exc
        try:
            ynode = loader.get_single_node()
            return self._build(ynode, loader, parent, path, pending)
        finally:
            loader.dispose()

    @staticmethod
    def _items(mapping: yaml.MappingNode) -> dict:
        return {k.value: v for k, v in mapping.value}

    @staticmethod
    def _scalar(loader, ynode):
        try:
            return loader.construct_object(ynode, deep=True)
        except Exception:
            return ynode.value

    def _build(self, root_ynode, loader, parent: Node, file: str, pending: deque) -> Node | None:
        """Construit l'arbre d'un fichier sans récursion (pile explicite)."""
        result: Node | None = None
        stack: list[tuple[object, Node, bool]] = [(root_ynode, parent, True)]
        while stack:
            ynode, owner, is_root = stack.pop()
            if not isinstance(ynode, yaml.MappingNode):
                continue
            items = self._items(ynode)
            if "File" in items and "Name" not in items:
                sub = os.path.normpath(os.path.join(os.path.dirname(file), str(items["File"].value)))
                pending.append((sub, owner))
                continue
            if "Class" in items and items["Class"].value != "Method":
                continue
            raw_name = str(items["Name"].value) if "Name" in items else "?"
            name = _NS_PREFIX.sub("", raw_name)
            node = Node(name, owner, file)
            node.line = ynode.start_mark.line + 1
            node.end_line = ynode.end_mark.line + 1
            node.type = items["Type"].value if "Type" in items else None
            node.supertype = items["Supertype"].value if "Supertype" in items else None
            node.datatype = items["DataType"].value if "DataType" in items else None
            if "Value" in items:
                vnode = items["Value"]
                node.value_line = vnode.start_mark.line + 1
                node.value = self._scalar(loader, vnode) if isinstance(vnode, yaml.ScalarNode) else None
            self.all_nodes.append(node)
            self.by_name.setdefault(name, []).append(node)
            if node.supertype is not None:
                self.types_by_name.setdefault(name, node)
            if is_root:
                result = node
            else:
                owner.children[name] = node
            children = items.get("Children")
            if isinstance(children, yaml.SequenceNode):
                # Ordre inverse sur la pile : les enfants sont insérés dans l'ordre du fichier.
                for child in reversed(children.value):
                    stack.append((child, node, False))
        return result

    # ---- résolution --------------------------------------------------------------
    def type_chain(self, node: Node) -> list[Node]:
        chain = []
        type_name = node.type if node.supertype is None else node.supertype
        seen: set[str] = set()
        while type_name in self.types_by_name and type_name not in seen:
            seen.add(type_name)
            type_node = self.types_by_name[type_name]
            chain.append(type_node)
            type_name = type_node.supertype
        return chain

    def child(self, node: Node, segment: str) -> Node | None:
        if segment in node.children:
            return node.children[segment]
        for type_node in self.type_chain(node):
            if segment in type_node.children:
                return type_node.children[segment]
        return None

    def _is_builtin(self, path: str) -> bool:
        if "/Commands/" in path or path.startswith(("/Objects/RetainedAlarms", "/Types/", "/Objects/Server")):
            return True
        # /Objects/Users est interne, sauf si le chemin passe par le projet lui-même. La
        # comparaison porte sur des segments entiers (l'outil d'origine cherchait le nom
        # comme sous-chaîne : un projet « IHM » était trouvé dans « IHM_Ligne2 »).
        return path.startswith("/Objects/Users") and self.name not in path.split("/")

    def resolve(self, path: str, origin: Node) -> tuple[Node | None, str, str]:
        """(nœud ou None, code, détail). Codes : ``ok``, SKIP_*, REASON_MISSING, REASON_ABOVE_ROOT."""
        p = path.strip()
        if "{" in p:
            return None, SKIP_ALIAS, ""
        if self._is_builtin(p):
            return None, SKIP_BUILTIN, ""
        if p.startswith("/"):
            current = self.objects
            segments = p.strip("/").split("/")
            if segments and segments[0] == "Objects":
                segments = segments[1:]
        else:
            current = origin
            segments = p.split("/")
        for raw in segments:
            segment = raw.split("@")[0]
            if segment in ("", "."):
                continue
            if current is not origin and (current.datatype in POINTER_DATATYPES or current.type in POINTER_TYPES):
                if segment != "..":
                    return None, SKIP_POINTER, ""
            if segment == "..":
                if current.parent is None:
                    return None, REASON_ABOVE_ROOT, ""
                current = current.parent
                continue
            segment = _INDEX_PREFIX.sub("", segment)
            index = None
            match = _ARRAY.match(segment)
            if match:
                segment, index = match.group(1), match.group(2)
            nxt = self.child(current, segment)
            if nxt is None:
                return None, REASON_MISSING, segment
            current = nxt
            if index is not None:
                element = self.child(current, index)
                if element is not None:
                    current = element
        return current, "ok", ""

    # ---- analyse -------------------------------------------------------------------
    @staticmethod
    def relative_path(origin: Node, target: Node) -> str:
        """Chemin relatif Optix de ``origin`` vers ``target`` (``..`` = parent de origin)."""
        o = origin.path().strip("/").split("/")
        t = target.path().strip("/").split("/")
        k = 0
        while k < min(len(o), len(t)) and o[k] == t[k]:
            k += 1
        ups = len(o) - k
        rest = t[k:]
        if ups == 0:
            return "/".join(["."] + rest) if rest else "."
        return "/".join([".."] * ups + rest)

    def foreign_project_prefix(self, target: str) -> str | None:
        """Nom du projet étranger si le chemin absolu vise un autre projet, sinon None."""
        match = re.match(r"^/Objects/([^/]+)/", target)
        if match and match.group(1) != self.name and match.group(1) not in BUILTIN_PROJECT_ROOTS:
            return match.group(1)
        return None

    def suggest(self, target: str, origin: Node | None, limit: int = 3) -> list[str]:
        """Candidats portant le même nom que le dernier segment de la cible, du plus au moins probable."""
        last = target.rstrip("/").split("/")[-1].split("@")[0]
        last = re.sub(r"\[\d+\]$", "", _INDEX_PREFIX.sub("", last))
        candidates = self.by_name.get(last, [])
        if not candidates:
            return []
        wanted = [s.split("@")[0] for s in target.strip("/").split("/") if s not in ("..", ".", "")]
        origin_path = origin.path() if origin is not None else ""
        scored = []
        for candidate in candidates:
            path = candidate.path()
            have = path.strip("/").split("/")
            k = 0  # segments communs en partant de la fin
            while k < min(len(wanted), len(have)) and wanted[-1 - k] == have[-1 - k]:
                k += 1
            bonus = os.path.commonprefix([origin_path, path]).count("/") / 100.0 if origin_path else 0.0
            scored.append((k + bonus, path, candidate))
        scored.sort(key=lambda s: -s[0])
        chosen, seen = [], set()
        for _score, path, candidate in scored:
            if path not in seen:
                seen.add(path)
                chosen.append(candidate)
            if len(chosen) >= limit:
                break
        # Même forme que le lien d'origine : relatif s'il l'était, absolu sinon.
        if target.startswith("/") or origin is None:
            return [c.path() for c in chosen]
        return [self.relative_path(origin, c) for c in chosen]

    def screen_of(self, node: Node) -> str:
        segments = node.studio_path(self.name).split("/")
        if len(segments) >= 3 and segments[0] == "UI" and segments[1] in (
            "Screens", "Parents", "Dialogs", "BaseControls", "Menus",
        ):
            return "/".join(segments[:3])
        return "/".join(segments[:2]) if len(segments) >= 2 else node.studio_path(self.name)

    def find_broken_links(
        self, progress: ProgressCallback | None = None, cancel: CancelCheck | None = None
    ) -> tuple[list[BrokenLink], LinkStats]:
        broken: list[BrokenLink] = []
        stats = LinkStats()
        total = len(self.all_nodes)
        phase = tr("Checking links")
        for i, node in enumerate(self.all_nodes):
            if i % 5000 == 0:
                check_cancel(cancel)
                report(progress, phase, "", i, total)
            if node.type != "DynamicLink" or not isinstance(node.value, str) or node.parent is None:
                continue
            origin = node.parent
            target, code, detail = self.resolve(node.value, origin)
            if target is not None:
                stats.resolved += 1
                continue
            if code == SKIP_ALIAS:
                stats.alias += 1
                continue
            if code == SKIP_POINTER:
                stats.pointer += 1
                continue
            if code == SKIP_BUILTIN:
                stats.builtin += 1
                continue
            foreign = self.foreign_project_prefix(node.value)
            if foreign:
                code, detail = REASON_FOREIGN, foreign
            broken.append(
                BrokenLink(
                    file=node.file or "",
                    line=node.value_line,
                    block_start=node.line,
                    block_end=node.end_line,
                    owner_path=origin.studio_path(self.name),
                    prop=origin.name,
                    target=node.value,
                    reason=code,
                    detail=detail,
                    screen=self.screen_of(origin),
                    suggestions=self.suggest(node.value, origin),
                )
            )
        report(progress, phase, "", total, total)
        broken.sort(key=lambda b: (b.file, b.line))
        return broken, stats


def analyse(folder: str, progress: ProgressCallback | None = None, cancel: CancelCheck | None = None):
    """Charge le projet et cherche les liens cassés : (projet, liens cassés, statistiques)."""
    project = OptixProject(folder).load(progress, cancel)
    broken, stats = project.find_broken_links(progress, cancel)
    return project, broken, stats
