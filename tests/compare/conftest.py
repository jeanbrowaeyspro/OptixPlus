"""Fixtures pytest.

Le couple réel réel (~60 Mo par côté) vit hors dépôt (voir ``DATA_ROOT``).
Le projet ``1.3.2.9`` sur disque a déjà reçu les 4 correctifs décrits dans ``optixplus_expected.json`` ;
pour retrouver son état d'origine, on en construit une copie temporaire (liens physiques quand
c'est possible, copie sinon) dans laquelle on restaure les 4 fichiers de ``_Sauvegarde_AvantMerge``.
Les tests marqués ``couple_reel`` sont ignorés si ces dossiers sont absents.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
EXPECTED = HERE / "expected" / "optixplus_expected.json"
# Emplacement du couple réel : variable d'environnement, sinon le dossier qui contenait
# FTOCompare (les données n'ont pas bougé lors de l'intégration dans OptixPlus).
DATA_ROOT = Path(os.environ.get("OPTIXPLUS_COMPARE_DATA", HERE.parents[2]))
SAUVEGARDE = DATA_ROOT / "_Sauvegarde_AvantMerge"


def _load_expected() -> dict:
    return json.loads(EXPECTED.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def expected() -> dict:
    return _load_expected()


def _copy(src: Path, dst: Path) -> None:
    # Vraie copie, jamais de lien physique : Compare écrit ses fichiers en place, un lien
    # ferait écrire les tests d'application dans le vrai projet du client.
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _mirror(src_root: Path, dst_root: Path) -> None:
    for dirpath, dirnames, filenames in os.walk(src_root):
        dirnames[:] = [d for d in dirnames if not d.startswith("_FTOCompare_Rebut")]
        for name in filenames:
            src = Path(dirpath) / name
            _copy(src, dst_root / src.relative_to(src_root))


def _overlay(src_root: Path, work: Path) -> int:
    """Recopie (vraie copie) les fichiers de ``src_root`` par-dessus la copie de travail."""
    n = 0
    for dirpath, _dirnames, filenames in os.walk(src_root):
        for name in filenames:
            if name == "manifest.json" and Path(dirpath) == src_root:
                continue
            src = Path(dirpath) / name
            dst = work / src.relative_to(src_root)
            if dst.exists():
                dst.unlink()  # ne jamais écrire à travers un lien physique vers le vrai projet
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            n += 1
    return n


def _backups_of(projet: Path) -> list[Path]:
    """Les sauvegardes FTOCompare de ce projet, de la plus récente à la plus ancienne."""
    result: list[Path] = []
    for candidate in sorted(projet.parent.glob("_FTOCompare_Sauvegarde_*"), reverse=True):
        manifest = candidate / "manifest.json"
        if not manifest.is_file():
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if Path(data.get("projet", "")).resolve() == projet.resolve():
            result.append(candidate)
    return result


@pytest.fixture(scope="session")
def couple_reel(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[Path, Path]]:
    """``(runtime, projet_origine)`` : le runtime réel et une copie du projet remise dans son état d'origine."""
    exp = _load_expected()
    runtime = DATA_ROOT / exp["couple"]["runtime"]
    projet = DATA_ROOT / exp["couple"]["projet"]
    if not runtime.is_dir() or not projet.is_dir() or not SAUVEGARDE.is_dir():
        pytest.skip(f"couple réel absent sous {DATA_ROOT}")
    work = tmp_path_factory.mktemp("reel") / projet.name
    _mirror(projet, work)
    # Le projet réel a pu être modifié par l'outil lui-même : on remonte ses sauvegardes,
    # de la plus récente à la plus ancienne (la plus ancienne gagne), puis l'état d'avant merge.
    for backup in _backups_of(projet):
        _overlay(backup, work)
    _overlay(SAUVEGARDE, work)
    yield runtime, work


@pytest.fixture(scope="session")
def comparison(couple_reel: tuple[Path, Path]):
    """La comparaison complète, calculée une fois pour toute la session."""
    from optixplus.modules.compare.core.analysis import compare

    runtime, projet = couple_reel
    return compare(runtime, projet)


@pytest.fixture(autouse=True, scope="package")
def _interface_en_francais():
    """Les tests d'origine vérifient les libellés français : l'interface est mise en français."""
    from optixplus.common import i18n, logging_setup

    logging_setup.configure(to_file=False)
    i18n.install("fr")
    yield
    i18n.install("en")
