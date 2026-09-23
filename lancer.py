"""Lance OptixPlus depuis les sources, sur n'importe quel poste disposant de Python ≥ 3.11.

Au premier lancement, crée un environnement Python dédié (``.venv-lanceur``, à côté de ce
fichier) et y installe les dépendances de ``requirements.txt``, sans toucher au Python du
poste. Les lancements suivants démarrent directement ; les dépendances ne sont
réinstallées que si ``requirements.txt`` change.

Usage : ``python lancer.py`` (mode découverte) ou ``python lancer.py --installe`` (tray).
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

MIN_PYTHON = (3, 11)
ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv-lanceur"
REQUIREMENTS = ROOT / "requirements.txt"
MARKER = VENV / "requirements.sha256"


def _venv_python(windowed: bool = False) -> Path:
    return VENV / "Scripts" / ("pythonw.exe" if windowed else "python.exe")


def _in_venv() -> bool:
    try:
        return Path(sys.prefix).resolve() == VENV.resolve()
    except OSError:
        return False


def _fail(message: str) -> int:
    print(f"\nERREUR : {message}")
    if sys.stdin and sys.stdin.isatty():
        input("Appuyez sur Entrée pour fermer…")
    return 1


def _requirements_hash() -> str:
    return hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()


def _venv_works() -> bool:
    python = _venv_python()
    if not python.exists():
        return False
    try:
        return subprocess.run([str(python), "-c", "import sys"], capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _prepare() -> int:
    """Crée l'environnement et installe les dépendances si besoin ; 0 si tout est prêt."""
    if not _venv_works():
        if VENV.exists():
            print("Environnement existant inutilisable (copié depuis un autre poste ?) : recréation…")
            shutil.rmtree(VENV, ignore_errors=True)
        print(f"Création de l'environnement Python dans {VENV} …")
        result = subprocess.run([sys.executable, "-m", "venv", str(VENV)])
        if result.returncode != 0 or not _venv_works():
            return _fail("impossible de créer l'environnement Python (module venv).")

    wanted = _requirements_hash()
    if MARKER.exists() and MARKER.read_text(encoding="ascii").strip() == wanted:
        return 0
    print("Installation des dépendances (PySide6, QtAds, openpyxl, PyYAML)…")
    print("Cela prend une à deux minutes la première fois.\n")
    python = str(_venv_python())
    steps = [
        [python, "-m", "pip", "install", "--upgrade", "pip"],
        [python, "-m", "pip", "install", "-r", str(REQUIREMENTS)],
    ]
    for step in steps:
        if subprocess.run(step).returncode != 0:
            return _fail(
                "l'installation des dépendances a échoué. Vérifiez l'accès à Internet (ou au proxy) "
                "puis relancez."
            )
    MARKER.write_text(wanted, encoding="ascii")
    print("\nDépendances installées.")
    return 0


def _run_app() -> int:
    sys.path.insert(0, str(ROOT / "src"))
    from optixplus.app import main

    return main()


def main() -> int:
    if _in_venv():
        return _run_app()
    if sys.version_info < MIN_PYTHON:
        return _fail(
            f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} ou plus récent est nécessaire "
            f"(version actuelle : {sys.version.split()[0]}). Téléchargement : https://www.python.org/downloads/"
        )
    if not REQUIREMENTS.exists():
        return _fail(f"fichier introuvable : {REQUIREMENTS}")
    code = _prepare()
    if code:
        return code
    # Relance dans l'environnement dédié, sans console (pythonw), puis rend la main.
    windowed = _venv_python(windowed=True)
    interpreter = windowed if windowed.exists() else _venv_python()
    flags = subprocess.DETACHED_PROCESS if os.name == "nt" and interpreter == windowed else 0
    subprocess.Popen([str(interpreter), str(Path(__file__).resolve()), *sys.argv[1:]], creationflags=flags)
    return 0


if __name__ == "__main__":
    sys.exit(main())
