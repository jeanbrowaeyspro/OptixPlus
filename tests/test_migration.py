"""Reprise des anciens outils : import sans écrasement, mots de passe relus, rien de supprimé."""

from __future__ import annotations

import json

from optixplus import migration
from optixplus.common import dpapi
from optixplus.common.recent import recent_controllers, recent_projects
from optixplus.common.settings import Settings
from optixplus.modules.autovalidate.core.config import AutoValidateSettings


def _legacy_files(appdata, tmp_path):
    reader = appdata / "pyFTOLogReader"
    reader.mkdir(parents=True)
    (reader / "settings.json").write_text(json.dumps({
        "hosts": ["10.0.0.1"],
        "credentials": [{"label": "Atelier", "username": "op", "password": dpapi.protect("s3cret"), "enabled": True}],
        "poll_interval_ms": 1200,
        "last_host": "10.0.0.1",
        "hidden_columns": ["code"],
        "inconnu": 42,
    }), encoding="utf-8")
    validate = appdata / "OptixAutoValidate"
    validate.mkdir()
    (validate / "config.json").write_text(json.dumps({
        "enabled": False, "titles": ["Projet existant"], "interval_ms": 150, "notify": True, "max_retries": 5,
    }), encoding="utf-8")
    project = tmp_path / "Projet_A"
    project.mkdir()
    return project


def test_settings_of_every_former_tool_are_imported(tmp_path, monkeypatch):
    appdata = tmp_path / "appdata"
    project = _legacy_files(appdata, tmp_path)
    registry = {
        migration.LINKCHECK_APP: {"last_project": str(project), "theme": "dark"},
        migration.COMPARE_APP: {
            "couples": json.dumps([[str(tmp_path / "runtime"), str(project)]]),
            "plans/0123abcd": '{"version": 1}',
            "dernier_export": "C:/rapport.md",
            "geometry": b"ignored",
        },
    }
    monkeypatch.setattr(migration, "legacy_qsettings_values", registry.get)
    settings = Settings.load(tmp_path / "settings.json")

    done = migration.migrate_settings(settings, appdata)

    assert done == ["logreader", "linkcheck", "compare", "autovalidate"]
    saved = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    reader = saved["logreader"]
    assert reader["hosts"] == ["10.0.0.1"] and reader["poll_interval_ms"] == 1200 and reader["hidden_columns"] == ["code"]
    assert dpapi.unprotect(reader["credentials"][0]["password"]) == "s3cret"
    assert "inconnu" not in reader
    assert saved["compare"] == {
        "couples": registry[migration.COMPARE_APP]["couples"],
        "plans/0123abcd": '{"version": 1}',
        "dernier_export": "C:/rapport.md",
    }
    assert recent_projects(settings) == [str(project)]
    assert recent_controllers(settings) == [("10.0.0.1", "10.0.0.1")]
    validate = settings.section(AutoValidateSettings)
    assert validate.enabled is False and validate.titles == ["Projet existant"] and validate.max_retries == 5
    assert validate.notify is False  # choix d'OptixPlus conservé
    # Rien n'est supprimé des anciens outils.
    assert (appdata / "pyFTOLogReader" / "settings.json").exists()
    assert (appdata / "OptixAutoValidate" / "config.json").exists()


def test_existing_optixplus_settings_are_never_overwritten(tmp_path, monkeypatch):
    appdata = tmp_path / "appdata"
    _legacy_files(appdata, tmp_path)
    monkeypatch.setattr(migration, "legacy_qsettings_values", lambda app: None)
    settings = Settings.load(tmp_path / "settings.json")
    settings.store("logreader").update({"hosts": ["192.0.2.1"]})
    settings.section(AutoValidateSettings).max_retries = 2
    settings.save()

    settings = Settings.load(tmp_path / "settings.json")
    assert migration.migrate_settings(settings, appdata) == []
    saved = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert saved["logreader"] == {"hosts": ["192.0.2.1"]}
    assert saved["autovalidate"]["max_retries"] == 2


def test_nothing_to_import(tmp_path, monkeypatch):
    monkeypatch.setattr(migration, "legacy_qsettings_values", lambda app: None)
    settings = Settings.load(tmp_path / "settings.json")
    assert migration.migrate_settings(settings, tmp_path / "vide") == []
    assert not (tmp_path / "settings.json").exists()


def test_task_list_from_the_installer():
    assert migration.parse_tasks("reglages,autovalidate") == ["reglages", "autovalidate"]
    assert migration.parse_tasks(" Reglages , inconnu ") == ["reglages"]
    assert migration.parse_tasks("") == []


def test_real_registry_is_only_read():
    """Les QSettings des anciens outils présents sur ce poste se lisent sans erreur."""
    for app in (migration.COMPARE_APP, migration.LINKCHECK_APP, "OutilQuiNExistePas"):
        values = migration.legacy_qsettings_values(app)
        assert values is None or isinstance(values, dict)
    assert migration.legacy_qsettings_values("OutilQuiNExistePas") is None
