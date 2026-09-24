"""Mises à jour : versions, API GitHub simulée, planification des vérifications."""

from __future__ import annotations

import urllib.error
from datetime import datetime, timedelta, timezone

import pytest

from fakes import FakeGitHub, release_json
from optixplus.update import github
from optixplus.update.github import UpdateError, Version, is_check_due


# --------------------------------------------------------------------------- versions
@pytest.mark.parametrize(
    ("older", "newer"),
    [
        ("1.0.0", "1.0.1"),
        ("1.0.9", "1.1.0"),
        ("1.9.0", "2.0.0"),
        ("1.0.0-beta.2", "1.0.0-beta.10"),
        ("1.0.0-beta.10", "1.0.0-rc.1"),
        ("1.0.0-rc.1", "1.0.0"),
        ("v0.9.0", "1.0.0"),
    ],
)
def test_semantic_version_order(older, newer):
    assert Version.parse(older) < Version.parse(newer)
    assert Version.parse(newer) > Version.parse(older)


def test_version_parsing():
    assert str(Version.parse("v1.2.3")) == "1.2.3"
    assert Version.parse("1.2.3-beta.1").is_prerelease
    assert Version.parse("1.2.3") == Version.parse("v1.2.3")
    with pytest.raises(ValueError):
        Version.parse("1.2")


# --------------------------------------------------------------------------- API GitHub
def test_latest_release_is_read_with_a_user_agent_only():
    fake = FakeGitHub({f"{github.API_URL}/latest": release_json("v1.2.0")})
    release = github.latest_release(opener=fake)
    assert release.version == Version.parse("1.2.0")
    assert release.installable and release.installer.name == "OptixPlus-Setup-1.2.0.exe"
    request = fake.requests[0]
    assert request.get_header("User-agent").startswith("OptixPlus/")
    assert request.get_header("Authorization") is None


def test_prereleases_only_when_asked():
    listing = [release_json("v1.2.0"), release_json("v1.3.0-beta.1", prerelease=True), release_json("v9.0.0", draft=True)]
    fake = FakeGitHub({f"{github.API_URL}/latest": release_json("v1.2.0"), f"{github.API_URL}?per_page=20": listing})
    assert str(github.latest_release(False, fake).version) == "1.2.0"
    assert str(github.latest_release(True, fake).version) == "1.3.0-beta.1"  # le brouillon est ignoré


def test_available_update_rules():
    fake = FakeGitHub({f"{github.API_URL}/latest": release_json("v1.2.0")})
    assert github.available_update("1.1.0", opener=fake).version == Version.parse("1.2.0")
    assert github.available_update("1.2.0", opener=fake) is None
    assert github.available_update("1.3.0", opener=fake) is None
    assert github.available_update("1.1.0", skipped="1.2.0", opener=fake) is None


def test_no_published_release_is_not_an_error():
    assert github.latest_release(opener=FakeGitHub({})) is None


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (urllib.error.HTTPError("u", 403, "rate limited", {}, None), "hour"),
        (urllib.error.HTTPError("u", 500, "boom", {}, None), "500"),
        (urllib.error.URLError("no route"), "no route"),
        (TimeoutError("timed out"), "timed out"),
    ],
)
def test_network_errors_become_readable_messages(error, message):
    fake = FakeGitHub({f"{github.API_URL}/latest": error})
    with pytest.raises(UpdateError, match=message):
        github.latest_release(opener=fake)


# --------------------------------------------------------------------------- planification
NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("last", "frequency", "at_startup", "due"),
    [
        ("", "daily", True, True),
        ("", "startup", False, False),
        ("", "startup", True, True),
        ((NOW - timedelta(minutes=20)).isoformat(), "startup", True, False),  # moins d'une heure
        ((NOW - timedelta(hours=5)).isoformat(), "daily", False, False),
        ((NOW - timedelta(hours=25)).isoformat(), "daily", False, True),
        ((NOW - timedelta(days=3)).isoformat(), "weekly", True, False),
        ((NOW - timedelta(days=8)).isoformat(), "weekly", False, True),
        ("n'importe quoi", "daily", False, True),
    ],
)
def test_check_schedule(last, frequency, at_startup, due):
    assert is_check_due(last, frequency, NOW, at_startup) is due
