"""Amorçage de l'application : arguments, instance unique, langue, thème, journal.

Arguments reconnus :
- ``--installe`` / ``--decouverte`` : force le mode de lancement ;
- ``--demarrage`` : lancé par la clé Run de Windows, sans ouvrir la fenêtre ;
- ``--outil <id>`` : ouvre directement un outil.
Sans argument de mode, l'application est en mode installé si elle s'exécute depuis son
dossier d'installation, en mode découverte sinon.
"""

from __future__ import annotations

import argparse
import logging
import sys
import traceback
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from .common import i18n, logging_setup, paths, qt_translation, startup, win32, workers
from .common.i18n import tr
from .common.settings import Settings
from .common.single_instance import SingleInstance
from .common.theme import install_manager
from .shell.context import LaunchMode
from .version import APP_ID, APP_NAME, ORGANIZATION, __version__

log = logging.getLogger("optixplus.app")

INSTALL_KEY = r"Software\OptixPlus"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="optixplus", add_help=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--installe", action="store_true", help="mode installé (tray, surveillance)")
    mode.add_argument("--decouverte", action="store_true", help="mode découverte (sans tray)")
    parser.add_argument("--demarrage", action="store_true", help="lancement par Windows, fenêtre masquée")
    parser.add_argument("--outil", metavar="ID", help="outil à ouvrir")
    parser.add_argument("--apres-maj", action="store_true", help="relance par l'installateur après une mise à jour")
    parser.add_argument("--migrer", metavar="TACHES", default="", help="reprise des anciens outils : reglages,autovalidate")
    args, _unknown = parser.parse_known_args(argv)
    return args


def _install_dir() -> Path | None:
    """Dossier d'installation inscrit par l'installateur, s'il existe."""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, INSTALL_KEY) as key:
            value, _kind = winreg.QueryValueEx(key, "InstallDir")
            return Path(value)
    except OSError:
        return None


def detect_mode(args: argparse.Namespace) -> LaunchMode:
    if args.installe:
        return LaunchMode.INSTALLED
    if args.decouverte:
        return LaunchMode.DISCOVERY
    install_dir = _install_dir()
    if install_dir is not None and paths.is_frozen():
        try:
            if Path(sys.executable).resolve().parent == install_dir.resolve():
                return LaunchMode.INSTALLED
        except OSError:
            pass
    return LaunchMode.DISCOVERY


def forwarded_message(args: argparse.Namespace) -> list[str]:
    """Demande transmise à l'instance déjà lancée."""
    if args.outil:
        return ["open-tool", args.outil]
    return ["show"]


def run_migration(tasks_text: str, settings: Settings) -> None:
    """Reprise des anciens outils demandée par l'installateur, avant la création des services."""
    from . import migration

    tasks = migration.parse_tasks(tasks_text)
    lines: list[str] = []
    if migration.TASK_SETTINGS in tasks:
        imported = migration.migrate_settings(settings)
        from .modules import MODULES

        titles = [tr(spec.title) for spec in MODULES if spec.id in imported]
        lines.append(
            tr("Settings imported: {tools}.").format(tools=", ".join(titles))
            if titles
            else tr("No settings of the former tools to import.")
        )
    if migration.TASK_AUTOVALIDATE in tasks:
        if migration.remove_legacy_autostart():
            lines.append(tr("The former OptixAutoValidate no longer starts with Windows."))
        if migration.legacy_autovalidate_running():
            answer = QMessageBox.question(
                None,
                APP_NAME,
                tr("The former OptixAutoValidate is still running and would validate the same dialogs as OptixPlus. Close it now?"),
            )
            if answer == QMessageBox.StandardButton.Yes and migration.stop_legacy_autovalidate():
                lines.append(tr("The former OptixAutoValidate has been closed."))
    if lines:
        lines.append(tr("Nothing was deleted from the former tools."))
        QMessageBox.information(None, APP_NAME, "\n".join(lines))


def _install_excepthook() -> None:
    """Sans console, une exception non gérée serait invisible : journal + message, sans quitter."""

    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        log.error("Exception non gérée :\n%s", text)
        if QApplication.instance() is not None:
            QMessageBox.critical(
                None, APP_NAME, tr("An unexpected error occurred:\n{error}\n\nDetails are in the log.").format(error=exc)
            )

    sys.excepthook = hook


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    win32.set_app_user_model_id(APP_ID)

    QApplication.setApplicationName(APP_NAME)
    QApplication.setApplicationDisplayName(APP_NAME)
    QApplication.setApplicationVersion(__version__)
    QApplication.setOrganizationName(ORGANIZATION)
    app = QApplication(sys.argv[:1])

    settings = Settings.load()
    language = i18n.resolve_language(settings.general.language)
    i18n.install(language)
    qt_translation.apply(app, language)

    instance = SingleInstance(APP_NAME)
    if not instance.acquire():
        win32.allow_any_foreground()
        if args.demarrage or instance.send(forwarded_message(args)):
            return 0
        QMessageBox.warning(None, APP_NAME, tr("OptixPlus is already running but does not respond."))
        return 1

    logging_setup.configure()
    _install_excepthook()

    mode = detect_mode(args)
    log.info(
        "Démarrage %s %s (%s, mode %s, langue %s)",
        APP_NAME,
        __version__,
        "exe" if paths.is_frozen() else "sources",
        mode.value,
        language,
    )
    instance.listen()
    if mode is LaunchMode.INSTALLED:
        startup.refresh_command_if_enabled()

    from .common import icons
    from .shell.controller import AppController

    if args.migrer:
        run_migration(args.migrer, settings)

    theme = install_manager(app, settings.general.theme)
    app.setWindowIcon(icons.app_icon())
    controller = AppController(app, settings, theme, mode, instance)
    controller.start_services()
    controller.start_updates()
    # Première ouverture d'une nouvelle version (ou relance après mise à jour) : Nouveautés.
    controller.whats_new_pending = args.apres_maj or settings.general.last_seen_version != __version__
    app.setQuitOnLastWindowClosed(False)

    if not (args.demarrage and controller.tray is not None):
        if args.outil:
            controller.open_tool(args.outil)
        else:
            controller.show_main_window()

    code = app.exec()
    instance.release()
    return workers.exit_code(code)
