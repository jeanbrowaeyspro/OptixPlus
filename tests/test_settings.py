"""Réglages : validation des types, conservation des sections inconnues, écriture atomique."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import ClassVar

from optixplus.common.settings import GeneralSettings, Settings, section_from_dict


@dataclass
class _Demo:
    SECTION: ClassVar[str] = "demo"
    count: int = 3
    ratio: float = 0.5
    enabled: bool = True
    name: str = "x"
    items: list[str] = field(default_factory=list)


def test_invalid_values_fall_back_to_defaults():
    demo = section_from_dict(_Demo, {"count": "12", "ratio": 2, "enabled": 1, "name": None, "items": ["a"]})
    assert demo.count == 3  # chaîne refusée
    assert demo.ratio == 2.0  # entier accepté pour un réel
    assert demo.enabled is True  # 1 n'est pas un booléen : défaut conservé
    assert demo.name == "x"
    assert demo.items == ["a"]


def test_bool_is_not_accepted_as_int():
    assert section_from_dict(_Demo, {"count": True}).count == 3


def test_round_trip_keeps_unknown_sections(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"future_tool": {"a": 1}, "general": {"theme": "dark"}}), encoding="utf-8")
    settings = Settings.load(path)
    assert settings.general.theme == "dark"
    settings.general.language = "fr"
    settings.save()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["future_tool"] == {"a": 1}
    assert data["general"]["language"] == "fr"
    assert data["schema"] == 1
    assert not path.with_suffix(".json.tmp").exists()


def test_same_section_instance_is_shared(tmp_path):
    settings = Settings.load(tmp_path / "s.json")
    assert settings.section(GeneralSettings) is settings.general


def test_corrupted_file_is_kept_aside(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{ pas du json", encoding="utf-8")
    settings = Settings.load(path)
    assert settings.general.language == "auto"
    assert path.with_suffix(".json.corrompu").exists()
