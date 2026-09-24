"""Traduction vérifiée sur l'interface réelle : chaque texte affiché est dans la bonne langue.

L'application est construite hors écran dans chaque langue ; on relève tout texte visible
(libellés, boutons, infobulles, actions, menus, onglets, en-têtes, listes) des pages et des
boîtes de dialogue. Un texte est fautif s'il est dans l'autre langue du catalogue : clé
anglaise affichée en français (``tr`` oublié ou appelé trop tôt), ou traduction française
affichée en anglais (texte français écrit en dur).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QGroupBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QTabBar,
    QTabWidget,
    QWidget,
)

from linkcheck_fixture import make_project
from optixplus.common import i18n, logging_setup, qt_translation
from optixplus.common.settings import Settings
from optixplus.common.theme import install_manager
from optixplus.modules import MODULES
from optixplus.shell.context import LaunchMode
from optixplus.shell.controller import AppController
from support import MessageBoxes, wait_until

pytestmark = pytest.mark.slow  # toute l'interface construite deux fois, analyses comprises

TESTS = Path(__file__).resolve().parents[1]
CATALOG = json.loads((TESTS.parent / "src" / "optixplus" / "i18n" / "fr.json").read_text(encoding="utf-8"))
COMPARE = TESTS / "compare" / "fixtures"


def _texts_of(widget: QWidget) -> set[str]:
    """Textes visibles d'un widget et de ses enfants, actions et menus compris."""
    found: set[str] = set()

    def add(text) -> None:
        if isinstance(text, str) and text.strip():
            found.add(text.replace("&", "").strip())

    for w in (widget, *widget.findChildren(QWidget)):
        add(w.toolTip())
        add(w.windowTitle())
        if isinstance(w, (QLabel, QAbstractButton)):
            add(w.text())
        if isinstance(w, QLineEdit):
            add(w.placeholderText())
        if isinstance(w, QGroupBox):
            add(w.title())
        if isinstance(w, QComboBox):
            for i in range(w.count()):
                add(w.itemText(i))
        if isinstance(w, QTabBar):
            for i in range(w.count()):
                add(w.tabText(i))
                add(w.tabToolTip(i))
        if isinstance(w, QTabWidget):
            for i in range(w.count()):
                add(w.tabText(i))
        if isinstance(w, QHeaderView) and w.model() is not None:
            for section in range(w.count()):
                add(w.model().headerData(section, w.orientation(), Qt.ItemDataRole.DisplayRole))
                add(w.model().headerData(section, w.orientation(), Qt.ItemDataRole.ToolTipRole))
        for action in w.actions():  # les sous-menus sont des QMenu enfants, parcourus eux aussi
            add(action.text())
            add(action.toolTip())
        if isinstance(w, QMenu):
            add(w.title())
    return found


def _interface_texts(tmp_path: Path, monkeypatch, language: str) -> set[str]:
    from optixplus.modules.logreader.core.config import Settings as ReaderSettings
    from optixplus.modules.logreader.session import LogSession
    from optixplus.modules.logreader.ui.connect_dialog import ConnectDialog

    monkeypatch.setattr(ConnectDialog, "start_scan", lambda self: None)  # pas de réseau
    i18n.install(language)
    qt_translation.apply(QCoreApplication.instance(), language)  # comme app.py : textes propres à Qt
    logging_setup.configure(to_file=False)
    settings = Settings.load(tmp_path / f"settings-{language}.json")
    settings.general.language = language
    controller = AppController(QCoreApplication.instance(), settings, install_manager(QCoreApplication.instance(), "light"), LaunchMode.INSTALLED)
    texts: set[str] = set()
    try:
        window = controller.show_main_window()
        for spec in MODULES:
            window.show_page(spec.id)
        texts |= _texts_of(window)

        # Contrôle des liens : un projet analysé (tableau, résumé).
        linkcheck = window.module("linkcheck").page
        linkcheck.open_project(str(make_project(tmp_path / language)))
        assert wait_until(lambda: not linkcheck.busy and linkcheck.project is not None, 60)
        texts |= _texts_of(linkcheck)

        # Comparaison : résultats, plan et application.
        compare = window.module("compare").page
        compare.setup_page.runtime.set_path(COMPARE / "runtime" / "IHM_Demo")
        compare.setup_page.projet.set_path(COMPARE / "projet" / "IHM_Demo")
        compare.setup_page.compare_button.click()
        assert wait_until(lambda: compare.comparison is not None and not compare.busy, 60)
        results = compare.results_page
        results.semantic.mass_action("ajouts", tout=True)
        texts |= _texts_of(compare)
        plan = results.open_plan_dialog()
        assert wait_until(lambda: plan.preview is not None and not plan.busy, 60)
        texts |= _texts_of(plan)
        apply = results.open_apply_dialog(plan.preview, plan)
        texts |= _texts_of(apply)
        apply.close()
        plan.close()

        # Lecteur de logs : un onglet, ses réglages et la boîte de connexion.
        reader = window.module("logreader").page
        reader._add_tab(LogSession(reader.settings))
        texts |= _texts_of(reader)
        texts |= _texts_of(ConnectDialog(ReaderSettings(), reader.tabs[0].palette_, reader, auto_connect=False))

        from optixplus.shell.updates import UpdateDialog
        from optixplus.update.github import Asset, Release, Version

        release = Release(Version.parse("9.9.9"), "v9.9.9", "9.9.9", "notes", "https://example.invalid", "",
                          (Asset("OptixPlus-Setup-9.9.9.exe", "u"), Asset("OptixPlus-Setup-9.9.9.exe.sha256", "u")))
        for can_install in (True, False):
            texts |= _texts_of(UpdateDialog(release, can_install, window))
        controller.open_settings()
        controller.open_about()
        controller.open_whats_new(full=True)
        for dialog in (controller._settings_dialog, controller._about_dialog, controller._changelog_dialog):
            texts |= _texts_of(dialog)
            dialog.close()
        window.show_page("home")
        texts |= _texts_of(window.home)
    finally:
        if controller.window is not None:
            controller.window.close()
        i18n.install("en")
        qt_translation.apply(QCoreApplication.instance(), "en")
    return texts


@pytest.fixture(scope="module")
def texts(qapp, tmp_path_factory):
    # Relevé construit une fois pour le module : fixtures de fonction (``controller``,
    # ``message_boxes``) inutilisables ici, d'où ces équivalents directs.
    monkeypatch = pytest.MonkeyPatch()
    MessageBoxes().install(monkeypatch)
    try:
        base = tmp_path_factory.mktemp("i18n-ui")
        yield {lang: _interface_texts(base, monkeypatch, lang) for lang in ("fr", "en")}
    finally:
        monkeypatch.undo()


def test_french_interface_shows_no_english_source_text(texts):
    english = {key for key, value in CATALOG.items() if value != key}
    # Mots identiques dans les deux langues pour une autre clé (« Code », « Message »…).
    shared = set(CATALOG.values())
    leaks = sorted(t for t in texts["fr"] if t in english and t not in shared)
    assert leaks == [], f"Textes anglais affichés en français : {leaks}"


def test_english_interface_shows_no_french_text(texts):
    french = {value for key, value in CATALOG.items() if value != key}
    leaks = sorted(t for t in texts["en"] if t in french and t not in CATALOG)
    assert leaks == [], f"Textes français affichés en anglais : {leaks}"
    # Textes composés (« {n} lignes… ») que la comparaison exacte ne voit pas : accents français.
    accents = re.compile(r"[àâçéèêëîïôûùüÿœ«»]", re.IGNORECASE)
    fragments = sorted(t for t in texts["en"] if accents.search(t.replace("Français", "")))
    assert fragments == [], f"Fragments français dans l'interface anglaise : {fragments}"


def test_every_page_was_visited(texts):
    # Garde-fou du relevé lui-même : un texte de chaque outil est présent.
    for lang, samples in (("fr", ("Nouvel onglet…", "Comparer")), ("en", ("New tab…", "Run the comparison"))):
        for sample in samples:
            assert sample in texts[lang], (lang, sample)
