"""Page d'accueil : choix des dossiers, versions de l'IDE, historique des couples."""

from __future__ import annotations

from pathlib import Path

import pytest

from optixplus.modules.compare.ui.setup_page import SetupPage

from .conftest import FIXTURES, PROJET, RUNTIME, ini_settings


@pytest.fixture
def settings(qapp, tmp_path: Path):
    return ini_settings(tmp_path / "compare.ini")


def test_detection_et_versions(settings, tmp_path: Path) -> None:
    page = SetupPage(settings)
    assert not page.compare_button.isEnabled()

    page.runtime.set_path(RUNTIME)
    assert page.runtime.path == RUNTIME and page.runtime.version == "1.3.2.9-Stable"
    assert not page.compare_button.isEnabled(), "il manque le projet"

    page.projet.set_path(tmp_path)
    assert page.projet.path is None and "pas un projet Optix" in page.projet.status.text()

    page.projet.set_path(FIXTURES / "projet")  # dossier parent : proposer de descendre
    assert page.projet.path is None
    assert page.projet.suggest_button.isVisibleTo(page)
    assert page.projet.suggest_button.text().startswith("Descendre")
    page.projet.suggest_button.click()
    assert page.projet.path == PROJET
    assert page.compare_button.isEnabled()
    assert "identiques" in page.hint.text()

    page.projet.set_path(RUNTIME)  # même dossier des deux côtés
    assert not page.compare_button.isEnabled() and "identiques" in page.hint.text()


def test_versions_differentes_bloquant_franchissable(settings) -> None:
    page = SetupPage(settings)
    page.runtime.set_path(RUNTIME)
    page.projet.set_path(PROJET)
    page.projet._version = "1.4.0.1-Stable"
    page._update_state()
    assert page.versions_differ()
    assert page.warning.isVisibleTo(page)
    assert not page.compare_button.isEnabled()
    page.override.setChecked(True)
    assert page.compare_button.isEnabled()


def test_historique(settings) -> None:
    page = SetupPage(settings)
    page.runtime.set_path(RUNTIME)
    page.projet.set_path(PROJET)
    received: list[tuple[str, str]] = []
    page.compare_requested.connect(lambda r, p: received.append((r, p)))
    page.compare_button.click()
    assert received == [(str(RUNTIME.resolve()), str(PROJET.resolve()))]
    assert page.couples() == [(str(RUNTIME.resolve()), str(PROJET.resolve()))]
    assert page.history.count() == 1

    autre = SetupPage(settings)  # l'historique survit à la page
    assert autre.history.count() == 1
    autre.runtime.set_path("")
    autre._pick_history(autre.history.item(0))
    assert autre.runtime.path == RUNTIME.resolve() and autre.projet.path == PROJET.resolve()


def test_libelles_deux_projets(settings) -> None:
    """Compare sert aussi à comparer deux projets : le premier côté le dit."""
    page = SetupPage(settings)
    assert "autre projet" in page.runtime.title()
