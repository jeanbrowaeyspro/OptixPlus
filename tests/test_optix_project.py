"""Reconnaissance d'un dossier de projet ou de runtime FT Optix (``common.optix.project``)."""

from __future__ import annotations

from pathlib import Path

from optixplus.common.optix.project import is_optix_root, read_ide_version, suggest_optix_root


def _optix_folder(root: Path) -> Path:
    (root / "Nodes").mkdir(parents=True)
    (root / "IDEVersion.txt").write_bytes(b"1.3.2.9-Stable")
    return root


def test_detection_dossier_optix(tmp_path: Path) -> None:
    runtime = _optix_folder(tmp_path / "Runtime" / "IHM_X")
    _optix_folder(tmp_path / "Projet" / "IHM_X")
    assert is_optix_root(runtime)
    assert not is_optix_root(tmp_path / "Runtime")
    assert suggest_optix_root(tmp_path / "Runtime") == runtime, "dossier parent : son unique sous-dossier"
    assert suggest_optix_root(tmp_path) is None, "plusieurs sous-dossiers : aucune proposition"
    assert read_ide_version(runtime) == "1.3.2.9-Stable"
    assert read_ide_version(tmp_path) is None
