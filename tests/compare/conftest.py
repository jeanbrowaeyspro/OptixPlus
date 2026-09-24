"""Fixtures et outils communs des tests de Compare.

Le couple synthétique versionné (``fixtures/``) contient un exemplaire de chaque type d'écart :
c'est lui qui fait tourner la suite sans dépendre d'un projet de client.

Le couple réel d'un client (~60 Mo par côté) et son résultat attendu vivent hors dépôt (voir
``DATA_ROOT`` et ``EXPECTED``) : les tests marqués ``couple_reel`` sont ignorés s'ils sont absents.
Le projet sur disque a déjà reçu les 4 correctifs décrits dans le résultat attendu ; pour retrouver
son état d'origine, on en construit une copie temporaire (vraie copie, jamais de lien physique)
dans laquelle on restaure les 4 fichiers de ``_Sauvegarde_AvantMerge``.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
RUNTIME = FIXTURES / "runtime" / "IHM_Demo"
PROJET = FIXTURES / "projet" / "IHM_Demo"

TAGS = "Nodes/CommDrivers/CODESYSDriver/API_Demo/Tags/Tags.yaml"
TRANSLATIONS = "Nodes/Translations/Translations.yaml"
MODEL = "Nodes/Model/Model.yaml"
PARENTS = "Nodes/UI/Parents/Parents.yaml"
SCREENS = "Nodes/UI/Screens/Screens.yaml"
ALARMS = "Nodes/Alarms/Alarms.yaml"
DIVISION = "Nodes/UI/Parents/Division/Division.yaml"
ORPHELIN = "Nodes/UI/Parents/Orphelin/Orphelin.yaml"

# Emplacement du couple réel : variable d'environnement, sinon le dossier qui contenait
# FTOCompare (les données n'ont pas bougé lors de l'intégration dans OptixPlus).
DATA_ROOT = Path(os.environ.get("OPTIXPLUS_COMPARE_DATA", HERE.parents[2]))
SAUVEGARDE = DATA_ROOT / "_Sauvegarde_AvantMerge"
EXPECTED = Path(os.environ.get("OPTIXPLUS_COMPARE_EXPECTED", DATA_ROOT / "optixplus_expected.json"))


# -- Outils ------------------------------------------------------------------------------


def wait_until(condition: Callable[[], object], timeout: float = 30.0) -> bool:
    """Traite les événements Qt jusqu'à ce que ``condition()`` soit vraie ; ``False`` à l'expiration.

    L'appelant fait ``assert wait_until(...)`` : une attente expirée fait échouer le test au lieu
    de le laisser continuer sur un état incomplet.
    """
    from PySide6.QtCore import QCoreApplication

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    QCoreApplication.processEvents()
    return bool(condition())


def find_item(item, name: str):
    """Le premier élément de l'arbre (``item`` compris) dont la première colonne vaut ``name``."""
    if item.text(0) == name:
        return item
    for k in range(item.childCount()):
        found = find_item(item.child(k), name)
        if found is not None:
            return found
    return None


def compared_page(settings, runtime: Path = RUNTIME, projet: Path = PROJET):
    """Une page Compare dont la comparaison ``runtime`` / ``projet`` est terminée."""
    from optixplus.modules.compare.ui.page import ComparePage

    page = ComparePage(settings)
    page.setup_page.runtime.set_path(runtime)
    page.setup_page.projet.set_path(projet)
    page.setup_page.compare_button.click()
    assert wait_until(lambda: page.comparison is not None and not page.busy)
    return page


def ini_settings(path: Path):
    """Des ``QSettings`` isolés dans un fichier INI temporaire."""
    from PySide6.QtCore import QSettings

    return QSettings(str(path), QSettings.Format.IniFormat)


# -- Fixtures ----------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="package")
def _interface_en_francais():
    """Les tests d'origine vérifient les libellés français : l'interface est mise en français."""
    from optixplus.common import i18n, logging_setup

    logging_setup.configure(to_file=False)
    i18n.install("fr")
    yield
    i18n.install("en")


@pytest.fixture(scope="package")
def demo(_interface_en_francais):
    """La comparaison du couple synthétique, calculée une seule fois pour tous les tests de Compare.

    Portée « paquet » plutôt que « session » : la comparaison produit des libellés traduits,
    elle doit donc être calculée après la mise en français de l'interface.
    """
    from optixplus.modules.compare.core.analysis import compare

    return compare(RUNTIME, PROJET)


@pytest.fixture
def couple(tmp_path: Path) -> tuple[Path, Path]:
    """``(runtime, projet)`` : une copie du couple synthétique, que le test peut modifier."""
    runtime = tmp_path / "Runtime" / "IHM_Demo"
    projet = tmp_path / "Projet" / "IHM_Demo"
    shutil.copytree(RUNTIME, runtime)
    shutil.copytree(PROJET, projet)
    return runtime, projet


# -- Couple réel -------------------------------------------------------------------------


def _load_expected() -> dict:
    if not EXPECTED.is_file():
        pytest.skip(f"résultat attendu du couple réel absent : {EXPECTED}")
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
    """Recopie les fichiers de ``src_root`` par-dessus la copie de travail."""
    n = 0
    for dirpath, _dirnames, filenames in os.walk(src_root):
        for name in filenames:
            if name == "manifest.json" and Path(dirpath) == src_root:
                continue
            src = Path(dirpath) / name
            dst = work / src.relative_to(src_root)
            if dst.exists():
                dst.unlink()
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
    work = tmp_path_factory.mktemp("couple_reel") / projet.name
    _mirror(projet, work)
    # Le projet réel a pu être modifié par l'outil lui-même : on remonte ses sauvegardes,
    # de la plus récente à la plus ancienne (la plus ancienne gagne), puis l'état d'avant merge.
    for backup in _backups_of(projet):
        _overlay(backup, work)
    _overlay(SAUVEGARDE, work)
    yield runtime, work


@pytest.fixture(scope="package")
def comparison(couple_reel: tuple[Path, Path], _interface_en_francais):
    """La comparaison complète du couple réel, calculée une fois."""
    from optixplus.modules.compare.core.analysis import compare

    runtime, projet = couple_reel
    return compare(runtime, projet)
