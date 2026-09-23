"""Traduction : choix de la langue selon Windows, pluriels, couverture du catalogue français."""

from __future__ import annotations

import pytest

import i18n_check
from optixplus.common import i18n


@pytest.mark.parametrize(
    ("langid", "expected"),
    [
        (0x040C, "fr"),  # fr-FR
        (0x080C, "fr"),  # fr-BE
        (0x0C0C, "fr"),  # fr-CA
        (0x100C, "fr"),  # fr-CH
        (0x0409, "en"),  # en-US
        (0x0407, "en"),  # de-DE
        (0x0410, "en"),  # it-IT
    ],
)
def test_language_follows_windows(langid, expected):
    assert i18n.language_from_langid(langid) == expected


def test_explicit_setting_wins():
    assert i18n.resolve_language("fr") == "fr"
    assert i18n.resolve_language("en") == "en"
    assert i18n.resolve_language("auto") in ("fr", "en")


def test_translation_and_plural():
    try:
        i18n.install("fr")
        assert i18n.tr("Settings") == "Paramètres"
        assert i18n.tr("Texte inconnu") == "Texte inconnu"
        # En français, 0 prend le singulier ; en anglais, le pluriel.
        assert i18n.tr_n("{n} file", "{n} files", 0) == "{n} file"
        i18n.install("en")
        assert i18n.tr("Settings") == "Settings"
        assert i18n.tr_n("{n} file", "{n} files", 0) == "{n} files"
        assert i18n.tr_n("{n} file", "{n} files", 1) == "{n} file"
    finally:
        i18n.install("en")


def test_french_catalog_is_complete():
    missing, _orphans = i18n_check.check()
    assert missing == [], f"Traductions françaises manquantes : {missing}"
