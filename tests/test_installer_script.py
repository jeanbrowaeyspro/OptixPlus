"""Script Inno Setup : OptixPlus n'est jamais lancé avec les droits administrateur de l'installateur.

Lancé en administrateur, OptixPlus empêcherait les autres logiciels (Greenshot…) de recevoir
leurs raccourcis quand sa fenêtre est au premier plan, et écrirait dans le profil de l'administrateur.
"""

from __future__ import annotations

import re
from pathlib import Path

ISS = Path(__file__).resolve().parent.parent / "installer" / "OptixPlus.iss"


def _section(name: str) -> list[str]:
    lines, inside = [], False
    for line in ISS.read_text(encoding="utf-8-sig").splitlines():
        if line.startswith("["):
            inside = line.strip() == f"[{name}]"
            continue
        if inside and line.strip() and not line.lstrip().startswith(";"):
            lines.append(line)
    return lines


def test_every_launch_of_optixplus_runs_as_the_original_user():
    runs = [line for line in _section("Run") if "{#AppExe}" in line]
    assert runs, "aucun lancement d'OptixPlus dans [Run]"
    for line in runs:
        flags = re.search(r"Flags:\s*([^;]+)", line)
        assert flags and "runasoriginaluser" in flags.group(1).split(), line


def test_installs_in_program_files():
    setup = "\n".join(_section("Setup"))
    assert "PrivilegesRequired=admin" in setup
    assert "DefaultDirName={autopf}\{#AppName}" in setup
