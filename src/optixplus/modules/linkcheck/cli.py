"""Mode ligne de commande de Link Checker (repris de l'outil d'origine).

    python -m optixplus linkcheck <dossier du projet> [--fix-prefix]

La sortie console est le résultat attendu de cette commande : ``print`` y est légitime.
"""

from __future__ import annotations

import argparse
import os

from ...common import i18n
from ...common.i18n import tr
from .core import fixer
from .core.project import ProjectError, analyse, reason_label


def main(argv: list[str]) -> int:
    i18n.install(i18n.resolve_language("auto"))
    parser = argparse.ArgumentParser(prog="optixplus linkcheck", description=tr("Lists and fixes broken dynamic links."))
    parser.add_argument("project", help=tr("FT Optix project folder"))
    parser.add_argument(
        "--fix-prefix", action="store_true", help=tr("fix absolute links pointing to another project name")
    )
    args = parser.parse_args(argv)
    try:
        project, broken, stats = analyse(args.project)
    except ProjectError as exc:
        print(exc)
        return 2
    print(
        tr(
            "Project {name}: {files} files, {nodes} nodes, {resolved} links resolved, "
            "{unverifiable} not verifiable (aliases, pointers), {builtin} to internal objects. "
            "Broken links: {broken}."
        ).format(
            name=project.name,
            files=project.files_loaded,
            nodes=len(project.all_nodes),
            resolved=stats.resolved,
            unverifiable=stats.unverifiable,
            builtin=stats.builtin,
            broken=len(broken),
        )
    )
    for link in broken:
        print(f"- {link.screen} | {link.owner_path} | {link.prop}")
        print(f"    {tr('Target')} : {link.target}   ({reason_label(link)})")
        print("    " + tr("File: {file} (line {line})").format(file=os.path.relpath(link.file, project.folder), line=link.line))
        if link.suggestions:
            print(f"    {tr('Suggestion')} : {link.suggestions[0]}")
    if args.fix_prefix:
        fixes, skipped = fixer.propose_prefix_fixes(project, broken)
        for link, target, _code in skipped:
            print("  " + tr("skipped (target absent): {owner} -> {target}").format(owner=link.owner_path, target=target))
        try:
            result = fixer.apply_fixes(project, fixes)
        except fixer.FixError as exc:
            print(exc)
            return 1
        print("\n".join(result.journal))
        print(tr("{files} file(s) modified, backup: {folder}").format(files=result.files, folder=result.backup_dir))
    return 0
