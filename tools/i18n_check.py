"""Vérifie le catalogue français : chaînes non traduites et entrées orphelines.

Les textes sont extraits du code par analyse syntaxique : premier argument littéral des
appels ``tr("…")``, deux premiers de ``tr_n("…", "…", n)``, et les champs ``title`` /
``description`` des ``ModuleSpec`` (traduits à l'affichage).

Usage : ``python tools/i18n_check.py`` (code de sortie 1 s'il manque une traduction).
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "src" / "optixplus"
CATALOG = SOURCE / "i18n" / "fr.json"
SPEC_FIELDS = ("title", "description")


def _literal(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def extract_file(path: Path) -> set[str]:
    keys: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
        if name == "tr" and node.args:
            if (text := _literal(node.args[0])) is not None:
                keys.add(text)
        elif name == "tr_n" and len(node.args) >= 2:
            for arg in node.args[:2]:
                if (text := _literal(arg)) is not None:
                    keys.add(text)
        elif name == "ModuleSpec":
            for kw in node.keywords:
                if kw.arg in SPEC_FIELDS and (text := _literal(kw.value)) is not None:
                    keys.add(text)
    return keys


def extract_keys(source: Path = SOURCE) -> set[str]:
    keys: set[str] = set()
    for path in sorted(source.rglob("*.py")):
        keys |= extract_file(path)
    return keys


def load_catalog(path: Path = CATALOG) -> dict[str, str]:
    return json.loads(path.read_text(encoding="utf-8"))


def check() -> tuple[list[str], list[str]]:
    """Renvoie (clés sans traduction, entrées orphelines)."""
    keys = extract_keys()
    catalog = load_catalog()
    missing = sorted(k for k in keys if not catalog.get(k))
    orphans = sorted(k for k in catalog if k not in keys)
    return missing, orphans


def main() -> int:
    missing, orphans = check()
    for key in missing:
        print(f"NON TRADUIT : {key!r}")
    for key in orphans:
        print(f"ORPHELIN    : {key!r}")
    print(f"{len(missing)} non traduit(s), {len(orphans)} orphelin(s)")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
