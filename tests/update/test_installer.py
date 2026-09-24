"""Installateur : téléchargement vérifié, lancement silencieux, script Inno Setup."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from fakes import FakeGitHub, release
from optixplus.common.progress import Cancelled
from optixplus.update import installer
from optixplus.update.github import UpdateError

PAYLOAD = b"MZ fake installer"
ISS = Path(__file__).resolve().parents[2] / "installer" / "OptixPlus.iss"


# --------------------------------------------------------------------------- téléchargement vérifié
def _download_routes(checksum: str) -> FakeGitHub:
    return FakeGitHub({
        "https://example.invalid/1.2.0/setup.exe": PAYLOAD,
        "https://example.invalid/1.2.0/setup.sha256": f"{checksum}  OptixPlus-Setup-1.2.0.exe\n".encode(),
    })


GOOD = hashlib.sha256(PAYLOAD).hexdigest()


def test_installer_is_downloaded_and_verified(tmp_path):
    steps = []
    path = installer.fetch_installer(release(), steps.append, None, _download_routes(GOOD), tmp_path)
    assert path.read_bytes() == PAYLOAD
    assert steps and steps[0].total == len(PAYLOAD)


def test_wrong_checksum_removes_the_file(tmp_path):
    with pytest.raises(UpdateError, match="checksum"):
        installer.fetch_installer(release(), None, None, _download_routes("0" * 64), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_cancelled_download_leaves_nothing(tmp_path):
    with pytest.raises(Cancelled):
        installer.fetch_installer(release(), None, lambda: True, _download_routes(GOOD), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_checksum_file_formats():
    digest = "a" * 64
    assert installer.expected_checksum(digest, "x.exe") == digest
    assert installer.expected_checksum(f"{'b' * 64}  other.exe\n{digest} *x.exe", "x.exe") == digest
    with pytest.raises(UpdateError):
        installer.expected_checksum("pas d'empreinte", "x.exe")


# --------------------------------------------------------------------------- lancement
def test_installer_is_launched_silently_through_the_shell(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(installer, "_shell_execute", lambda path, params: calls.append((path, params)) or 42)
    installer.launch(tmp_path / "setup.exe")
    assert calls == [(str(tmp_path / "setup.exe"), "/SILENT /CLOSEAPPLICATIONS")]


def test_refused_elevation_is_reported(monkeypatch, tmp_path):
    monkeypatch.setattr(installer, "_shell_execute", lambda path, params: 5)  # accès refusé (UAC refusé)
    with pytest.raises(UpdateError):
        installer.launch(tmp_path / "setup.exe")


# --------------------------------------------------------------------------- script Inno Setup
# OptixPlus n'est jamais lancé avec les droits administrateur de l'installateur : il
# empêcherait les autres logiciels (Greenshot…) de recevoir leurs raccourcis quand sa fenêtre
# est au premier plan, et écrirait dans le profil de l'administrateur.
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
    assert r"DefaultDirName={autopf}\{#AppName}" in setup
