"""Rapport HTML : le Markdown du rapport, converti par un mini-convertisseur maison.

Le Markdown produit par ``markdown.py`` est contrôlé (titres, tableaux, listes, gras, code) :
un convertisseur de quelques lignes suffit et évite une dépendance.
"""

from __future__ import annotations

import html
import re

from ..core.analysis import Comparison
from .markdown import build_markdown

_STYLE = """
body { font-family: Segoe UI, Arial, sans-serif; margin: 2em auto; max-width: 1200px; color: #212121; }
h1 { border-bottom: 2px solid #1976d2; padding-bottom: .2em; }
h2 { color: #1976d2; margin-top: 1.6em; }
h3 { margin-top: 1.2em; }
table { border-collapse: collapse; margin: .5em 0 1em; font-size: 90%; }
th, td { border: 1px solid #bdbdbd; padding: .25em .6em; vertical-align: top; text-align: left; }
th { background: #eeeeee; }
tr:nth-child(even) td { background: #fafafa; }
code { background: #f1f1f1; padding: 0 .25em; border-radius: 3px; font-family: Consolas, monospace; }
"""

_SEPARATOR = re.compile(r"^\|(\s*-+\s*\|)+\s*$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_CELL_SPLIT = re.compile(r"(?<!\\)\|")


def _inline(text: str) -> str:
    text = html.escape(text, quote=False)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    return text


def _cells(line: str) -> list[str]:
    return [c.strip().replace("\\|", "|") for c in _CELL_SPLIT.split(line.strip().strip("|"))]


def markdown_to_html(md: str, titre: str = "Rapport") -> str:
    out: list[str] = []
    lines = md.splitlines()
    i = 0
    in_list = False
    while i < len(lines):
        line = lines[i]
        if line.startswith("|") and i + 1 < len(lines) and _SEPARATOR.match(lines[i + 1]):
            out.append("<table><thead><tr>" + "".join(f"<th>{_inline(h)}</th>" for h in _cells(line)) + "</tr></thead><tbody>")
            i += 2
            while i < len(lines) and lines[i].startswith("|"):
                out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in _cells(lines[i])) + "</tr>")
                i += 1
            out.append("</tbody></table>")
            continue
        if line.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(line[2:])}</li>")
            i += 1
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        heading = _HEADING.match(line)
        if heading:
            level = len(heading.group(1))
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
        elif line.strip():
            out.append(f"<p>{_inline(line)}</p>")
        i += 1
    if in_list:
        out.append("</ul>")
    body = "\n".join(out)
    return (
        '<!DOCTYPE html>\n<html lang="fr"><head><meta charset="utf-8">'
        f"<title>{html.escape(titre)}</title><style>{_STYLE}</style></head>\n<body>\n{body}\n</body></html>\n"
    )


def build_html(c: Comparison, titre: str = "FTOCompare — rapport de comparaison") -> str:
    return markdown_to_html(build_markdown(c, titre), titre)
