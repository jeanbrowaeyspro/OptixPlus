"""Arbre des nœuds d'un fichier YAML FactoryTalk Optix, sans PyYAML, en une passe ligne à ligne.

PyYAML (même avec son chargeur en C) rappelle un résolveur Python pour chaque valeur : sur un
gros projet, la lecture prend une quinzaine de secondes. Les YAML générés par FT Optix sont
très réguliers (blocs indentés de deux espaces, listes ``Children:`` sans retrait, valeurs sur
une ligne ou JSON en flux) : ce module les lit directement et rend, pour chaque nœud, ce que
PyYAML aurait donné — mêmes valeurs typées, mêmes positions (``start_mark`` / ``end_mark``).

Tout ce qui sort de ce sous-ensemble (commentaire, ancre, bloc ``|``, clé inhabituelle, texte sur
plusieurs lignes, caractère non imprimable…) lève ``Unsupported`` : l'appelant relit alors le
fichier avec PyYAML. Les tests comparent les deux lectures nœud par nœud.

Nœuds relevés : la mappe racine du fichier et chaque mappe élément d'une liste ``Children``
d'un nœud relevé. Les autres structures (arguments, valeurs complexes…) sont parcourues pour
suivre l'indentation, sans être relevées.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import yaml

#: Clés d'un nœud dont la valeur est relevée.
FIELDS = ("Name", "Type", "Supertype", "DataType", "Value", "Class", "File")

_KEY = re.compile(r"([A-Za-z_][A-Za-z0-9_]*):(?: (.*))?$")
# Caractères que le lecteur YAML refuse (non imprimables) ou traite comme sauts de ligne.
_UNSUPPORTED_CHARS = re.compile(
    "[^\x0a\x20-\x7e\xa0-\ud7ff\ue000-\ufefe\uff00-\ufffd\U00010000-\U0010ffff]|\u2028|\u2029"
)
_PLAIN_FORBIDDEN_START = set(",[]{}#&*!|>%@`'\"")

_resolver = yaml.resolver.Resolver()
_constructor = yaml.constructor.SafeConstructor()


class Unsupported(Exception):
    """Construction YAML hors du sous-ensemble lu directement : relire avec PyYAML."""


@dataclass(slots=True)
class RawNode:
    """Une mappe relevée (nœud Optix, ou inclusion ``- File:``), dans l'ordre du document."""

    parent: int  # index du RawNode parent (la mappe dont la liste Children le contient), -1 : racine
    line: int  # 1-based, comme ``start_mark.line + 1``
    end_line: int = 0  # comme ``end_mark.line + 1``
    name: str | None = None  # valeur brute de ``Name`` (non construite)
    type: str | None = None
    supertype: str | None = None
    datatype: str | None = None
    klass: str | None = None
    file: str | None = None
    has_value: bool = False
    value: Any = None  # scalaire construit comme PyYAML ; None pour une liste ou une mappe
    value_line: int = 0


@dataclass(slots=True)
class _Scalar:
    text: str  # valeur de ``ScalarNode.value``
    plain: bool


def _scalar(text: str) -> _Scalar:
    """Scalaire tenant sur la ligne (déjà débarrassé des espaces de fin)."""
    first = text[0]
    if first == '"':
        i, n = 1, len(text)
        while i < n:
            ch = text[i]
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                break
            i += 1
        if i != n - 1:
            raise Unsupported("guillemets")
        inner = text[1:-1]
        if "\\" in inner:
            value = yaml.load(text, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))
            if not isinstance(value, str):
                raise Unsupported("guillemets")
            return _Scalar(value, False)
        return _Scalar(inner, False)
    if first == "'":
        if len(text) < 2 or text[-1] != "'" or "'" in text[1:-1].replace("''", ""):
            raise Unsupported("apostrophes")
        return _Scalar(text[1:-1].replace("''", "'"), False)
    if first in _PLAIN_FORBIDDEN_START:
        raise Unsupported("indicateur")
    if first in "-?:" and (len(text) == 1 or text[1] == " "):
        raise Unsupported("indicateur")
    if ": " in text or " #" in text or text.endswith(":"):
        raise Unsupported("scalaire ambigu")
    return _Scalar(text, True)


def construct(scalar: _Scalar | None) -> Any:
    """Valeur construite comme ``SafeConstructor`` (repli sur le texte brut en cas d'erreur)."""
    if scalar is None:
        text, plain = "", True
    else:
        text, plain = scalar.text, scalar.plain
    tag = _resolver.resolve(yaml.ScalarNode, text, (plain, not plain))
    node = yaml.ScalarNode(tag, text)
    try:
        return _constructor.construct_object(node, deep=True)
    except Exception:
        return text
    finally:
        _constructor.constructed_objects.pop(node, None)


_FIELD_SET = frozenset(FIELDS)
_TRACKED = _FIELD_SET | {"Children"}
_QUICK_FIRST = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_./(")


def _quick_plain(text: str) -> bool:
    """Scalaire simple sans ambiguïté possible (cas courant), sans l'analyse complète."""
    return text[0] in _QUICK_FIRST and ": " not in text and " #" not in text and text[-1] != ":"


class _Flow:
    """Suivi d'une collection en flux (``{…}`` / ``[…]``), éventuellement sur plusieurs lignes."""

    __slots__ = ("depth", "quote", "last")

    def __init__(self) -> None:
        self.depth = 0
        self.quote = ""
        self.last = ""  # dernier caractère significatif hors chaîne (même d'une ligne précédente)

    def feed(self, text: str, start: int = 0) -> int:
        """Avance dans ``text`` ; renvoie l'index qui suit la fermeture, ou -1 si elle continue."""
        i, n = start, len(text)
        while i < n:
            ch = text[i]
            if self.quote == '"':
                if ch == "\\":
                    i += 2
                    continue
                if ch == '"':
                    self.quote = ""
                    self.last = ch
            elif self.quote == "'":
                if ch == "'":
                    if i + 1 < n and text[i + 1] == "'":
                        i += 2
                        continue
                    self.quote = ""
                    self.last = ch
            elif ch == '"' or ch == "'":
                if self.last and self.last not in "[{,:":
                    raise Unsupported("guillemet dans un scalaire en flux")
                self.quote = ch
            elif ch == " ":
                pass
            else:
                if ch in "[{":
                    self.depth += 1
                elif ch in "]}":
                    self.depth -= 1
                    if self.depth == 0:
                        return i + 1
                elif ch == "#" and i > 0 and text[i - 1] == " ":
                    raise Unsupported("commentaire en flux")
                self.last = ch
            i += 1
        if self.quote:
            raise Unsupported("chaîne en flux sur plusieurs lignes")
        return -1


# Cadres de la pile d'indentation.
_MAP, _SEQ = 0, 1


class _Frame:
    __slots__ = ("kind", "indent", "record", "index", "keys", "children_of")

    def __init__(self, kind: int, indent: int, record: RawNode | None = None, index: int = -1, children_of: int = -2) -> None:
        self.kind = kind
        self.indent = indent
        self.record = record  # nœud relevé (mappe), sinon None
        self.index = index  # sa position dans la liste des nœuds relevés
        self.keys: set[str] | None = set() if record is not None else None
        self.children_of = children_of  # liste Children : index du parent ; -2 sinon


def read_nodes(text: str) -> list[RawNode]:
    """Nœuds d'un fichier YAML Optix (texte décodé, fins de ligne ``\\n``), dans l'ordre du document.

    Lève ``Unsupported`` pour toute construction hors du sous-ensemble pris en charge.
    """
    if _UNSUPPORTED_CHARS.search(text) or "\ufeff" in text:
        raise Unsupported("caractères")
    lines = text.split("\n")
    records: list[RawNode] = []
    stack: list[_Frame] = []
    pending: tuple[_Frame, str, int, int] | None = None  # (mappe, clé, colonne, ligne 0-based)
    flow: _Flow | None = None
    flow_target: tuple[RawNode | None, str] | None = None
    started = False

    def close(frame: _Frame, line_no: int) -> None:
        if frame.record is not None:
            frame.record.end_line = line_no + 1

    def set_value(frame: _Frame, key: str, line_no: int, scalar: _Scalar | None, collection: bool) -> None:
        """Valeur d'une clé d'un nœud relevé (``scalar`` None et ``collection`` faux : vide)."""
        record = frame.record
        if record is None or key not in FIELDS:
            return
        if key == "Value":
            record.has_value = True
            record.value_line = line_no + 1
            record.value = None if collection else construct(scalar)
            return
        if collection:
            raise Unsupported(f"{key} n'est pas un scalaire")
        text = scalar.text if scalar is not None else ""
        if key == "Name":
            record.name = text
        elif key == "Type":
            record.type = text
        elif key == "Supertype":
            record.supertype = text
        elif key == "DataType":
            record.datatype = text
        elif key == "Class":
            record.klass = text
        elif key == "File":
            record.file = text

    def open_flow(target_frame: _Frame | None, key: str, body: str, start: int) -> bool:
        """Commence une collection en flux ; vrai si elle se referme sur la même ligne."""
        nonlocal flow, flow_target
        tracker = _Flow()
        end = tracker.feed(body, start)
        if end == -1:
            flow, flow_target = tracker, (target_frame.record if target_frame else None, key)
            return False
        if body[end:].strip():
            raise Unsupported("texte après une collection en flux")
        return True

    def key_line(frame: _Frame, body: str, line_no: int, col: int, match=None) -> None:
        nonlocal pending
        if match is None:
            match = _KEY.fullmatch(body)
            if match is None:
                raise Unsupported("ligne inattendue")
        key, value = match.group(1), match.group(2)
        record = frame.record
        if record is not None and (key in _TRACKED):
            if key in frame.keys:
                raise Unsupported("clé en double")
            frame.keys.add(key)
        if not value:
            pending = (frame, key, col, line_no)
            return
        if value[0] == " ":
            value = value.lstrip(" ")
            if not value:
                pending = (frame, key, col, line_no)
                return
        if value[0] in "[{":
            set_value(frame, key, line_no, None, True)
            open_flow(frame, key, value, 0)
            return
        if record is not None and key in _FIELD_SET:
            set_value(frame, key, line_no, _scalar(value), False)
        elif not _quick_plain(value):
            _scalar(value)  # validation complète : lève Unsupported si besoin

    for line_no, line in enumerate(lines):
        if flow is not None:
            end = flow.feed(line)
            if end != -1:
                if line[end:].strip():
                    raise Unsupported("texte après une collection en flux")
                flow = flow_target = None
            continue
        stripped = line.lstrip(" ")
        if not stripped:
            continue
        body = stripped.rstrip(" ")
        col = len(line) - len(stripped)
        first = body[0]
        if first == "#" or (col == 0 and (body.startswith("---") or body.startswith("...") or first == "%")):
            raise Unsupported("commentaire ou marque de document")
        is_dash = first == "-" and (len(body) == 1 or body[1] == " ")
        is_flow = first in "[{"

        if not started:
            if is_dash or is_flow:
                raise Unsupported("racine non mappe")
            started = True
            root = RawNode(parent=-1, line=line_no + 1)
            records.append(root)
            stack.append(_Frame(_MAP, col, root, 0))
            key_line(stack[-1], body, line_no, col)
            continue

        # Valeur en attente d'une clé « clé: » : liste, mappe ou flux plus loin, sinon vide.
        if pending is not None:
            frame, key, key_col, key_line_no = pending
            pending = None
            if is_dash and col >= key_col:
                set_value(frame, key, line_no, None, True)
                children_of = frame.index if key == "Children" and frame.record is not None else -2
                stack.append(_Frame(_SEQ, col, children_of=children_of))
            elif col > key_col and is_flow:
                set_value(frame, key, line_no, None, True)
                open_flow(frame, key, body, 0)
                continue
            elif col > key_col:
                set_value(frame, key, line_no, None, True)
                stack.append(_Frame(_MAP, col))
                key_line(stack[-1], body, line_no, col)
                continue
            else:
                set_value(frame, key, key_line_no, None, False)

        # Fermeture des blocs que cette ligne quitte.
        while stack:
            top = stack[-1]
            if top.kind == _MAP:
                if col < top.indent:
                    close(stack.pop(), line_no)
                    continue
                if col > top.indent or is_dash or is_flow:
                    raise Unsupported("indentation inattendue")
                break
            if col < top.indent or (col == top.indent and not is_dash):
                stack.pop()
                continue
            if col > top.indent:
                raise Unsupported("indentation inattendue")
            break
        if not stack:
            raise Unsupported("plusieurs documents ou racine refermée")

        top = stack[-1]
        if top.kind == _MAP:
            key_line(top, body, line_no, col)
            continue

        # Élément de liste.
        rest = body[2:].lstrip(" ") if len(body) > 1 else ""
        if not rest:
            raise Unsupported("élément vide ou mappe sur la ligne suivante")
        if rest[0] == "-" and (len(rest) == 1 or rest[1] == " "):
            raise Unsupported("liste imbriquée")
        item_col = col + (len(body) - len(rest))
        if rest[0] in "[{":
            if top.children_of != -2 and rest[0] == "{":
                raise Unsupported("nœud en flux")
            open_flow(None, "", rest, 0)
            continue
        item_match = _KEY.fullmatch(rest)
        if item_match is None:
            _scalar(rest)  # élément scalaire : validé, ignoré (pas une mappe)
            continue
        record, index = None, -1
        if top.children_of != -2:
            record = RawNode(parent=top.children_of, line=line_no + 1)
            index = len(records)
            records.append(record)
        stack.append(_Frame(_MAP, item_col, record, index))
        key_line(stack[-1], rest, line_no, item_col, item_match)

    if flow is not None:
        raise Unsupported("collection en flux non refermée")
    if pending is not None:
        frame, key, _col, key_line_no = pending
        set_value(frame, key, key_line_no, None, False)
    if not started:
        raise Unsupported("fichier vide")
    # Fin du flux : libyaml passe à la ligne suivante si la dernière ligne n'est pas vide.
    end_line = text.count("\n") + (1 if text.rsplit("\n", 1)[-1] else 0)
    while stack:
        close(stack.pop(), end_line)
    return records
