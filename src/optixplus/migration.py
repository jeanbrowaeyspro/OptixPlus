"""Reprise des réglages des quatre anciens outils (``--migrer=reglages,autovalidate``).

Proposée par l'installateur (cases décochées par défaut), jamais silencieuse :

- ``reglages`` : importe les réglages de Log Reader (``%APPDATA%\\pyFTOLogReader\\settings.json``),
  de Link Checker et de Compare (``QSettings`` dans le registre) et d'Auto Validate
  (``%APPDATA%\\OptixAutoValidate\\config.json``) ;
- ``autovalidate`` : retire le démarrage automatique de l'ancien OptixAutoValidate et
  propose de fermer le processus s'il tourne.

Rien n'est supprimé des anciens outils, et un réglage déjà présent dans OptixPlus n'est
jamais écrasé : chaque section n'est importée que si OptixPlus ne l'a pas encore.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import fields
from pathlib import Path

from .common import win32
from .common.recent import add_recent_controller, add_recent_project
from .common.settings import Settings

log = logging.getLogger("optixplus.migration")

LOGREADER_DIR = "pyFTOLogReader"
AUTOVALIDATE_DIR = "OptixAutoValidate"
AUTOVALIDATE_EXE = "OptixAutoValidate.exe"
AUTOVALIDATE_RUN_VALUE = "OptixAutoValidate"
LINKCHECK_APP = "OptixLinkCheck"
COMPARE_APP = "FTOCompare"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

TASK_SETTINGS = "reglages"
TASK_AUTOVALIDATE = "autovalidate"
TASKS = (TASK_SETTINGS, TASK_AUTOVALIDATE)


def _appdata() -> Path:
    return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        log.warning("Ancien réglage illisible %s : %s", path, exc)
        return None
    return data if isinstance(data, dict) else None


def _has_content(settings: Settings, section: str) -> bool:
    value = settings.to_dict().get(section)
    return isinstance(value, dict) and bool(value)


# --------------------------------------------------------------------------- registre (QSettings)
def legacy_qsettings_values(app_name: str) -> dict[str, object] | None:
    """Valeurs QSettings d'un ancien outil, trouvées sous ``HKCU\\Software\\<éditeur>\\<app_name>``.

    L'éditeur n'est pas connu à l'avance : on cherche la clé de l'outil sous chaque éditeur.
    """
    try:
        import winreg
    except ImportError:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Software") as software:
            index = 0
            while True:
                try:
                    publisher = winreg.EnumKey(software, index)
                except OSError:
                    return None
                index += 1
                try:
                    winreg.OpenKey(software, f"{publisher}\\{app_name}").Close()
                except OSError:
                    continue
                from PySide6.QtCore import QSettings

                qsettings = QSettings(publisher, app_name)
                return {key: qsettings.value(key) for key in qsettings.allKeys()}
    except OSError:
        return None


# --------------------------------------------------------------------------- outils
def import_logreader(settings: Settings, appdata: Path) -> bool:
    from .modules.logreader.core.config import Settings as ReaderSettings

    data = _read_json(appdata / LOGREADER_DIR / "settings.json")
    if data is None or _has_content(settings, "logreader"):
        return False
    reader = ReaderSettings.from_dict(data)  # mots de passe relus par la DPAPI, même format
    store = settings.store("logreader")
    store.update(reader.to_dict())
    if reader.last_host:
        add_recent_controller(settings, reader.last_host, reader.last_host)
    log.info("Réglages de Log Reader importés")
    return True


def import_linkcheck(settings: Settings, values: dict | None) -> bool:
    if not values:
        return False
    project = values.get("last_project")
    if isinstance(project, str) and project and Path(project).is_dir():
        add_recent_project(settings, project)
        log.info("Dernier projet de Link Checker repris : %s", project)
        return True
    return False


def import_compare(settings: Settings, values: dict | None) -> bool:
    if not values or _has_content(settings, "compare"):
        return False
    store = settings.store("compare")
    for key, value in values.items():
        if key == "couples" or key == "dernier_export" or key.startswith("plans/"):
            store[key] = str(value)
    try:
        couples = json.loads(store.get("couples", "[]"))
    except ValueError:
        couples = []
    for couple in reversed(couples if isinstance(couples, list) else []):
        if isinstance(couple, list) and len(couple) == 2 and Path(str(couple[1])).is_dir():
            add_recent_project(settings, str(couple[1]))
    log.info("Réglages de Compare importés (%d clé(s))", len(store))
    return True


def import_autovalidate(settings: Settings, appdata: Path) -> bool:
    from .modules.autovalidate.core.config import AutoValidateSettings

    data = _read_json(appdata / AUTOVALIDATE_DIR / "config.json")
    if data is None or _has_content(settings, AutoValidateSettings.SECTION):
        return False
    target = settings.section(AutoValidateSettings)
    known = {f.name for f in fields(AutoValidateSettings)}
    # « notify » n'est pas repris : dans OptixPlus, la notification à chaque validation est
    # désactivée par défaut, choix confirmé par Jean ; l'ancien défaut l'activait.
    for key, value in data.items():
        if key in known and key != "notify" and isinstance(value, type(getattr(target, key))):
            setattr(target, key, value)
    target.normalized()
    log.info("Réglages d'Auto Validate importés")
    return True


def remove_legacy_autostart() -> bool:
    """Retire la valeur Run de l'ancien OptixAutoValidate ; vrai si elle existait."""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, AUTOVALIDATE_RUN_VALUE)
    except (ImportError, FileNotFoundError):
        return False
    except OSError as exc:
        log.warning("Retrait du démarrage automatique d'OptixAutoValidate impossible : %s", exc)
        return False
    log.info("Démarrage automatique de l'ancien OptixAutoValidate retiré")
    return True


def legacy_autovalidate_running() -> bool:
    return win32.process_running(AUTOVALIDATE_EXE)


def stop_legacy_autovalidate() -> bool:
    try:
        result = subprocess.run(
            ["taskkill", "/IM", AUTOVALIDATE_EXE, "/F"],
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
    except OSError as exc:
        log.warning("Arrêt d'OptixAutoValidate impossible : %s", exc)
        return False
    log.info("Arrêt de l'ancien OptixAutoValidate : code %s", result.returncode)
    return result.returncode == 0


# --------------------------------------------------------------------------- ensemble
def parse_tasks(value: str) -> list[str]:
    return [t for t in (part.strip().lower() for part in value.split(",")) if t in TASKS]


def migrate_settings(settings: Settings, appdata: Path | None = None) -> list[str]:
    """Importe les réglages des anciens outils ; renvoie les identifiants des outils repris."""
    appdata = appdata or _appdata()
    done = []
    if import_logreader(settings, appdata):
        done.append("logreader")
    if import_linkcheck(settings, legacy_qsettings_values(LINKCHECK_APP)):
        done.append("linkcheck")
    if import_compare(settings, legacy_qsettings_values(COMPARE_APP)):
        done.append("compare")
    if import_autovalidate(settings, appdata):
        done.append("autovalidate")
    if done:
        settings.save()
    return done
