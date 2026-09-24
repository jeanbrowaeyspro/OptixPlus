"""Feuille de style : aucune couleur ambiguë.

Un hexadécimal à huit chiffres est relu par Qt comme ``#AARRGGBB`` : « #FFFFFF14 »,
écrit pour un blanc translucide, donnait un jaune opaque au survol des boutons.
"""

from __future__ import annotations

import re

import pytest

from optixplus.common import theme


@pytest.mark.parametrize("palette", [theme.LIGHT, theme.DARK], ids=["light", "dark"])
def test_stylesheet_has_no_ambiguous_colour(palette):
    sheet = theme.build_stylesheet(palette)
    assert re.findall(r"#[0-9A-Fa-f]{8}\b", sheet) == []
    assert "rgba(" in sheet  # la transparence du survol passe par rgba()
