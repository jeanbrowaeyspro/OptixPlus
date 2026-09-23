"""Inventaire, hash et classement sur un mini couple construit dans un dossier temporaire."""

from pathlib import Path

import pytest

from optixplus.common.progress import Cancelled, Progress
from optixplus.common.optix.project import is_optix_root, read_ide_version, suggest_optix_root
from optixplus.modules.compare.core.scan import build_inventory


def _make(root: Path, files: dict[str, bytes]) -> Path:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return root


def _couple(tmp_path: Path) -> tuple[Path, Path]:
    runtime = _make(
        tmp_path / "Runtime" / "IHM_X",
        {
            "IDEVersion.txt": b"1.3.2.9-Stable",
            "Nodes/A.yaml": b"- Name: A\r\n  Value: 1\r\n",
            "Nodes/B/C/D/E/F/Profond.yaml": b"- Name: P\r\n  Value: 2\r\n",
            "Nodes/MemeTaille.yaml": b"Value: 80.0\r\n",
            "ApplicationFiles/RetentivityStorage.db": b"\x00\x01",
            "IHM_X.source": b"chiffre",
            "ProjectFiles/NetSolution/bin/IHM_X.dll": b"MZ\x00runtime",
        },
    )
    projet = _make(
        tmp_path / "Projet" / "IHM_X",
        {
            "IDEVersion.txt": b"1.3.2.9-Stable",
            "Nodes/A.yaml": b"- Name: A\r\n  Value: 1\r\n",
            "Nodes/B/C/D/E/F/Profond.yaml": b"- Name: P\r\n  Value: 3\r\n",
            "Nodes/MemeTaille.yaml": b"Value: 81.0\r\n",
            "Nodes/Orphelin.yaml": b"- Name: O\r\n",
            "DesignTimeNodes/X.yaml": b"",
            "IHM_X.optix.design": b"",
            "ProjectFiles/NetSolution/Logic.cs": b"class Logic {}",
            "ProjectFiles/NetSolution/obj/x.cache": b"",
            "ProjectFiles/NetSolution/bin/IHM_X.dll": b"MZ\x00projet",
        },
    )
    return runtime, projet


def test_detection_dossier_optix(tmp_path: Path) -> None:
    runtime, _ = _couple(tmp_path)
    assert is_optix_root(runtime)
    assert not is_optix_root(tmp_path / "Runtime")
    assert suggest_optix_root(tmp_path / "Runtime") == runtime
    assert suggest_optix_root(tmp_path) is None
    assert read_ide_version(runtime) == "1.3.2.9-Stable"
    assert read_ide_version(tmp_path) is None


def test_inventaire_classement(tmp_path: Path) -> None:
    runtime, projet = _couple(tmp_path)
    steps: list[Progress] = []
    inv = build_inventory(runtime, projet, progress=steps.append)

    statuses = {e.rel: e.status for e in inv.entries}
    assert statuses["Nodes/A.yaml"] == "identique"
    assert statuses["Nodes/B/C/D/E/F/Profond.yaml"] == "different", "profondeur sans limite"
    assert statuses["Nodes/MemeTaille.yaml"] == "different", "même taille, contenu différent"
    assert statuses["Nodes/Orphelin.yaml"] == "projet_seul"
    assert statuses["ApplicationFiles/RetentivityStorage.db"] == "runtime_seul"
    assert statuses["ProjectFiles/NetSolution/bin/IHM_X.dll"] == "different"

    attendus = {e.rel for e in inv.attendus()}
    assert attendus == {
        "ApplicationFiles/RetentivityStorage.db",
        "IHM_X.source",
        "DesignTimeNodes/X.yaml",
        "IHM_X.optix.design",
        "ProjectFiles/NetSolution/Logic.cs",
        "ProjectFiles/NetSolution/obj/x.cache",
    }
    divergents = {e.rel for e in inv.divergents()}
    assert divergents == {
        "Nodes/B/C/D/E/F/Profond.yaml",
        "Nodes/MemeTaille.yaml",
        "Nodes/Orphelin.yaml",
        "ProjectFiles/NetSolution/bin/IHM_X.dll",
    }

    meme = inv.get("Nodes/MemeTaille.yaml")
    assert meme is not None
    assert meme.size_runtime == meme.size_projet
    assert meme.md5_runtime != meme.md5_projet
    assert meme.is_text is True
    dll = inv.get("ProjectFiles/NetSolution/bin/IHM_X.dll")
    assert dll is not None and dll.is_text is False

    phases = {s.phase for s in steps}
    assert phases == {"inventaire", "hash"}
    assert any(s.current == "Nodes/A.yaml" for s in steps)


def test_annulation(tmp_path: Path) -> None:
    runtime, projet = _couple(tmp_path)
    try:
        build_inventory(runtime, projet, cancel=lambda: True)
    except Cancelled:
        return
    raise AssertionError("l'annulation aurait dû lever Cancelled")


def test_dossier_introuvable(tmp_path: Path) -> None:
    runtime, projet = _couple(tmp_path)
    with pytest.raises(FileNotFoundError):
        build_inventory(runtime, tmp_path / "absent")
