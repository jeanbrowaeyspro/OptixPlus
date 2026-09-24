"""Validation auto : décisions pures (titres, processus, délais) et réglages."""

from __future__ import annotations

from fakes import STUDIO
from optixplus.modules.autovalidate.core import matching
from optixplus.modules.autovalidate.core.config import DEFAULT_TITLES, AutoValidateSettings


def test_title_and_process_matching_is_case_insensitive():
    patterns = matching.normalize_patterns(["Le projet existe déjà", "  ", "Project already exists"])
    assert patterns == ("le projet existe déjà", "project already exists")
    assert matching.title_matches("FT Optix — LE PROJET EXISTE DÉJÀ", patterns)  # sous-chaîne
    assert not matching.title_matches("Autre fenêtre", patterns)
    assert not matching.title_matches("", patterns)
    assert matching.same_process("ftoptixstudio.EXE", STUDIO)
    assert not matching.same_process("", STUDIO)
    assert not matching.same_process("notepad.exe", STUDIO)


def test_cooldowns_expire_and_forget_dead_windows():
    cooldowns = matching.Cooldowns()
    cooldowns.add(1, 5, now=100)
    cooldowns.add(2, 5, now=100)
    assert cooldowns.active(1, now=104)
    assert not cooldowns.active(1, now=106)
    cooldowns.prune(now=101, alive=lambda h: h != 2)
    assert len(cooldowns) == 1


def test_settings_are_normalized():
    s = AutoValidateSettings(titles=["", "  "], process_name=" ", max_retries=50, retry_delay_ms=1, fallback_scan_ms=10)
    s.normalized()
    assert s.titles == list(DEFAULT_TITLES)
    assert s.process_name == STUDIO
    assert (s.max_retries, s.retry_delay_ms, s.fallback_scan_ms) == (10, 50, 500)


def test_restore_defaults_keeps_state():
    s = AutoValidateSettings(enabled=False, titles=["x"], notify=True)
    s.restore_defaults()
    assert s.enabled is False
    assert s.titles == list(DEFAULT_TITLES)
    assert s.notify is False  # notification désactivée par défaut
