"""Nouveautés : sections du journal des modifications depuis la dernière version vue."""

from __future__ import annotations

from optixplus.update import changelog

CHANGELOG = """# Nouveautés

Intro.

## [Non publié]
- à venir

## [1.2.0] - 2026-10-01
- deux

## [1.1.0] - 2026-09-01
- un

## [1.0.0] - 2026-08-01
- zéro
"""


def test_changelog_sections_since_last_seen():
    sections = changelog.parse(CHANGELOG)
    assert [s.title for s in sections] == ["Non publié", "1.2.0", "1.1.0", "1.0.0"]
    assert [s.title for s in changelog.news_since(sections, "1.0.0", "1.2.0")] == ["1.2.0", "1.1.0"]
    assert [s.title for s in changelog.news_since(sections, "", "1.1.0")] == ["1.1.0"]  # premier lancement
    assert [s.title for s in changelog.news_since(sections, "1.2.0", "1.3.0")] == ["Non publié"]  # sources
    assert "2026-10-01" in sections[1].markdown()


def test_embedded_changelog_is_found():
    assert changelog.changelog_path() is not None
    assert changelog.load()
