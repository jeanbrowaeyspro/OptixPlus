"""OptixPlus lancé en administrateur se relance en utilisateur normal (sauf --admin)."""

from __future__ import annotations

from optixplus import app
from optixplus.common import win32


def _patch(monkeypatch, elevated: bool, relaunched: bool = True):
    calls = []
    monkeypatch.setattr(win32, "is_elevated", lambda: elevated)
    monkeypatch.setattr(win32, "run_as_desktop_user", lambda command: calls.append(command) or relaunched)
    return calls


def test_normal_launch_is_left_alone(monkeypatch):
    calls = _patch(monkeypatch, elevated=False)
    assert not app.drop_elevation([], app.parse_args([]))
    assert calls == []


def test_elevated_launch_relaunches_as_the_desktop_user_with_the_same_arguments(monkeypatch):
    calls = _patch(monkeypatch, elevated=True)
    argv = ["--installe", "--outil", "logreader"]
    assert app.drop_elevation(argv, app.parse_args(argv))
    assert len(calls) == 1 and calls[0].endswith('"--installe" "--outil" "logreader"')


def test_admin_option_keeps_the_rights(monkeypatch):
    calls = _patch(monkeypatch, elevated=True)
    assert not app.drop_elevation(["--admin"], app.parse_args(["--admin"]))
    assert calls == []


def test_failed_relaunch_keeps_running(monkeypatch):
    _patch(monkeypatch, elevated=True, relaunched=False)
    assert not app.drop_elevation([], app.parse_args([]))
