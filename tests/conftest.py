"""Configuration commune des tests : interface hors écran, données dans un dossier temporaire."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Avant tout import de Qt ou d'optixplus : rendu hors écran et %APPDATA% isolé, pour
# ne jamais toucher aux réglages réels de l'utilisateur.
os.environ["QT_QPA_PLATFORM"] = "offscreen"
_APPDATA = tempfile.mkdtemp(prefix="optixplus-tests-")
os.environ["APPDATA"] = _APPDATA

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def appdata() -> Path:
    return Path(_APPDATA)
