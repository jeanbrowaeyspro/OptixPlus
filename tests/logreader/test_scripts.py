"""Scripts de test d'origine de pyFTOLogReader, exécutés chacun dans son propre processus.

Ces scripts créent leur propre QApplication et vérifient une série de points ; ils
renvoient un code de sortie nul si tout passe. Ils sont exécutés tels quels (seuls les
chemins d'import ont changé), en rendu hors écran.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SRC = HERE.parents[1] / "src"
SCRIPTS = sorted(p.name for p in HERE.glob("lr_test_*.py"))


@pytest.mark.parametrize("script", SCRIPTS)
def test_script(script: str, tmp_path: Path) -> None:
    env = {
        **os.environ,
        "PYTHONPATH": str(SRC),
        "QT_QPA_PLATFORM": "offscreen",
        "PYTHONIOENCODING": "utf-8",
        "APPDATA": str(tmp_path),  # jamais les réglages réels de l'utilisateur
    }
    result = subprocess.run(
        [sys.executable, str(HERE / script)], capture_output=True, text=True, encoding="utf-8", env=env, timeout=600
    )
    assert result.returncode == 0, result.stdout[-4000:] + "\n" + result.stderr[-4000:]
