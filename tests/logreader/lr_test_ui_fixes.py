"""Controles des comportements d'interface signales par l'utilisateur.

1. Le bouton « Changer d'automate » ne doit pas se connecter tout seul.
2. Le survol des boutons ne doit pas virer au jaune illisible.
3. Le tableau doit absorber l'espace gagne quand la fenetre grandit.
4. Les en-tetes de colonnes doivent filtrer, pas seulement trier.

Rendu hors ecran : aucune fenetre n'apparait.

Lancement : .venv/Scripts/python.exe tests/test_ui_fixes.py
"""
import os
import shutil
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Le rendu hors ecran ne charge aucune police par defaut : sans cela, les
# captures produites par les tests n'affichent que des carres.
if sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts"))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QEventLoop, QThread, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from optixplus.modules.logreader.core import netshare
from optixplus.common import theme
from optixplus.modules.logreader.core.config import Controller, Settings
from optixplus.modules.logreader.core.discovery import Ipc
from optixplus.modules.logreader.ui.connect_dialog import ConnectDialog
from optixplus.modules.logreader.ui.filter_header import MAX_DISTINCT_VALUES, ColumnFilterPopup, FilterHeaderView
from optixplus.modules.logreader.ui.log_filter import RULE_ANY, RULE_NONE
from optixplus.modules.logreader.ui.log_model import COLUMN_LEVEL, COLUMN_MESSAGE, COLUMN_SOURCE
from optixplus.common import i18n as _i18n

_i18n.install("fr")  # les vérifications portent sur les libellés français
from optixplus.modules.logreader.ui.log_tab import LogTab as MainWindow  # l'onglet reprend la fenêtre d'origine

FAILURES = []


def check(label, condition, detail=""):
    status = "OK  " if condition else "ECHEC"
    if not condition:
        FAILURES.append(label)
    print(f"  [{status}] {label}{('  -> ' + detail) if detail else ''}")


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


_REAL_DISCOVERY_WORKER = None


def install_fake_discovery(results):
    """Remplace le balayage reseau par un resultat fige.

    Sans cela, le vrai balayage demarre en parallele du test, efface la liste
    et remet ses propres resultats : le test mesurerait l'etat du reseau au
    lieu du comportement de la fenetre.
    """
    global _REAL_DISCOVERY_WORKER
    import optixplus.modules.logreader.ui.connect_dialog as module

    if _REAL_DISCOVERY_WORKER is None:
        _REAL_DISCOVERY_WORKER = module.DiscoveryWorker

    class FakeDiscoveryWorker(QThread):
        hostProbed = module.DiscoveryWorker.hostProbed
        finishedScan = module.DiscoveryWorker.finishedScan

        def __init__(self, *args, parent=None, **kwargs):
            super().__init__(parent)

        def run(self):
            for item in results:
                self.hostProbed.emit(item)
            self.finishedScan.emit(list(results))

    module.DiscoveryWorker = FakeDiscoveryWorker


def restore_discovery():
    import optixplus.modules.logreader.ui.connect_dialog as module

    if _REAL_DISCOVERY_WORKER is not None:
        module.DiscoveryWorker = _REAL_DISCOVERY_WORKER


def line(n, level, source, msg):
    return f"07-09-2026 09:{n // 60:02d}:{n % 60:02d}.000;{level};{source};;{msg};;Root/X\r\n"


def build_log(directory):
    """Journal de test : 3 niveaux, 3 sources, messages repetes."""
    path = os.path.join(directory, "FTOptixRuntime.0.log")
    levels = ["INFO", "ERROR", "WARNING"]
    sources = ["urn:FTOptix:CODESYS", "FTOptixRuntime", "urn:FTOptix:WebUI"]
    messages = ["Communication error", "Communication established", "Store online"]
    with open(path, "wb") as handle:
        for i in range(30):
            handle.write(line(i, levels[i % 3], sources[i % 3], messages[i % 3]).encode())
    return path


def main():
    app = QApplication(sys.argv)

    root = tempfile.mkdtemp(prefix="ftolog_ui_")
    log_dir = os.path.join(root, "Optix", "Log")
    os.makedirs(log_dir)
    build_log(log_dir)

    settings = Settings()
    settings.poll_interval_ms = 250
    settings.remember_last_host = False
    palette = theme.apply(app, "dark")

    real_unc = netshare.unc_path
    netshare.unc_path = lambda host, share: os.path.join(root, share)

    window = MainWindow(settings, palette)
    window.resize(1200, 700)
    window.show()
    pump(200)

    ipc = Ipc(host="local", netbios_name="BANC-TEST", project="ProjetSimule",
              reachable=True, share_accessible=True, log_available=True)
    window.connect_to(ipc)
    pump(1200)

    print("=== 1. le bouton Changer d'automate attend le clic ===")
    # Un seul automate exploitable : c'est exactement le cas ou l'ancien
    # comportement refermait la fenetre sous le nez de l'utilisateur.
    usable = Ipc(host="192.0.2.10", netbios_name="PC-TEST",
                 project="ProjetX", reachable=True, share_accessible=True,
                 log_available=True, status="pret")
    install_fake_discovery([usable])
    connect_settings = Settings()
    connect_settings.controllers = [Controller(host="192.0.2.10")]

    dialog = ConnectDialog(connect_settings, palette, window, auto_connect=False)
    dialog.show()
    pump(1800)   # bien plus que le delai de connexion automatique (900 ms)
    check("la fenetre reste ouverte malgre un seul automate",
          dialog.isVisible() and dialog.selected is None,
          f"visible={dialog.isVisible()} selection={dialog.selected}")
    check("l'automate est preselectionne, pret a valider",
          dialog.connect_button.isEnabled())
    dialog.close()
    pump(200)

    # Et au demarrage, la connexion automatique doit toujours avoir lieu.
    auto = ConnectDialog(connect_settings, palette, window, auto_connect=True)
    auto.show()
    pump(1800)
    check("au demarrage, la connexion automatique fonctionne toujours",
          auto.selected is not None,
          f"selection={auto.selected.host if auto.selected else None}")
    auto.close()
    pump(200)
    restore_discovery()

    print("=== 2. couleurs de survol ===")
    for name in ("light", "dark"):
        sheet = theme.build_stylesheet(theme.LIGHT if name == "light" else theme.DARK)
        # Un hexadecimal a huit chiffres serait relu par Qt comme #AARRGGBB.
        import re
        suspects = re.findall(r"#[0-9A-Fa-f]{8}\b", sheet)
        check(f"[{name}] aucune couleur hexadecimale ambigue a 8 chiffres",
              not suspects, ", ".join(suspects[:3]))
        check(f"[{name}] le survol passe par rgba()", "rgba(" in sheet)

    yellow = QColor("#FFFFFF14")
    check("l'ancienne notation etait bien un jaune opaque",
          (yellow.red(), yellow.green(), yellow.blue()) == (255, 255, 20),
          yellow.name())

    print("=== 3. le tableau absorbe l'espace gagne ===")
    pump(200)
    table_before = window.table.height()
    detail_before = window.splitter.widget(1).height()
    window.resize(1600, 1100)
    pump(500)
    table_after = window.table.height()
    detail_after = window.splitter.widget(1).height()
    grown_table = table_after - table_before
    grown_detail = detail_after - detail_before
    check("le tableau recupere l'espace supplementaire", grown_table > 300,
          f"+{grown_table} px")
    check("le panneau de detail ne grandit pas", grown_detail <= 2,
          f"+{grown_detail} px")

    print("=== 4. filtres sur les en-tetes de colonnes ===")
    check("l'en-tete est bien un en-tete filtrant",
          isinstance(window.table.horizontalHeader(), FilterHeaderView))

    values, truncated = window.model.distinct_values(COLUMN_LEVEL, MAX_DISTINCT_VALUES)
    check("valeurs distinctes de la colonne Niveau", len(values) == 3 and not truncated,
          str([v for v, _ in values]))
    check("les occurrences sont comptees", all(count == 10 for _, count in values),
          str([c for _, c in values]))

    total = window.proxy.rowCount()
    window._apply_column_filter(COLUMN_LEVEL, {"Erreur"}, "")
    pump(300)
    check("filtrer la colonne Niveau sur Erreur", window.proxy.rowCount() == 10,
          f"{window.proxy.rowCount()} / {total}")
    check("l'entonnoir de la colonne est marque actif",
          COLUMN_LEVEL in window.proxy.filtered_columns())

    window._apply_column_filter(COLUMN_SOURCE, None, "webui")
    pump(300)
    check("le filtre « contient » se combine avec le precedent",
          window.proxy.rowCount() == 0, f"{window.proxy.rowCount()} lignes")

    window._apply_column_filter(COLUMN_LEVEL, None, "")
    pump(300)
    check("retirer un filtre laisse l'autre en place", window.proxy.rowCount() == 10,
          f"{window.proxy.rowCount()} lignes")

    window._apply_column_filter(COLUMN_MESSAGE, None, "established")
    pump(300)
    check("filtre texte sur la colonne Message", window.proxy.rowCount() == 0,
          f"{window.proxy.rowCount()} lignes")

    summary = window.proxy.summary()
    check("le resume mentionne les filtres de colonnes",
          "Source" in summary and "Message" in summary, summary)

    window.reset_filters()
    pump(300)
    check("Reinitialiser efface aussi les filtres de colonnes",
          window.proxy.rowCount() == total and not window.proxy.filtered_columns(),
          f"{window.proxy.rowCount()} lignes")

    print("=== panneau de filtre ===")
    popup = ColumnFilterPopup(
        column=COLUMN_LEVEL, title="Niveau",
        values=values, selected=None, text="", truncated=False,
        palette=palette, parent=window,
    )
    popup.show()
    pump(300)
    check("le panneau liste toutes les valeurs", popup.list.count() == 3,
          f"{popup.list.count()} entrees")
    popup.list.item(0).setCheckState(Qt.CheckState.Unchecked)
    pump(100)
    check("decocher une valeur passe « Tout selectionner » en etat partiel",
          popup.select_all.checkState() == Qt.CheckState.PartiallyChecked)
    popup.close()
    pump(200)

    # Une colonne trop variee ne propose que le filtre « contient ».
    stamps, stamps_truncated = window.model.distinct_values(1, 5)
    check("une colonne trop variee est signalee comme non listable",
          stamps_truncated and not stamps)

    print("=== la barre de filtres est allegee ===")
    window.reset_filters()
    pump(200)
    check("plus de liste deroulante des sources",
          not hasattr(window, "source_combo"))
    check("plus de liste deroulante des surlignages",
          not hasattr(window, "rule_combo"))

    # La source se filtre desormais par la colonne, comme le reste.
    total_lignes = window.proxy.rowCount()
    window._filter_on_source("urn:FTOptix:WebUI")
    pump(300)
    check("« ne montrer que cette source » passe par le filtre de colonne",
          COLUMN_SOURCE in window.proxy.filtered_columns()
          and window.proxy.rowCount() == 10,
          f"{window.proxy.rowCount()} / {total_lignes} lignes")
    window.reset_filters()
    pump(200)

    print("=== le filtrage par surlignage reste accessible ===")
    menu = window._highlight_menu()
    libelles = [a.text() for a in menu.actions()]
    check("le sous-menu encadre les regles par les deux choix extremes",
          libelles[0] == "Tous les surlignages"
          and libelles[-1].startswith("Lignes non surlign"),
          " | ".join(libelles))
    check("une entree par regle, plus les deux extremes",
          len(libelles) == len(window.highlighter.active_rules) + 2,
          f"{len(libelles)} entrees pour "
          f"{len(window.highlighter.active_rules)} regles")

    window._apply_rule_filter(0)   # premiere regle : Erreurs
    pump(300)
    attendu = sum(1 for e in window.model.entries if e.highlight_index == 0)
    check("filtrer sur la premiere regle de surlignage",
          window.proxy.rowCount() == attendu and attendu > 0,
          f"{window.proxy.rowCount()} lignes (attendu {attendu})")

    coche = [a.text() for a in window._highlight_menu().actions() if a.isChecked()]
    check("le menu montre la regle retenue", len(coche) == 1, str(coche))

    window._apply_rule_filter(RULE_NONE)
    pump(300)
    sans = sum(1 for e in window.model.entries if e.highlight_index < 0)
    check("filtrer sur les lignes non surlignees",
          window.proxy.rowCount() == sans,
          f"{window.proxy.rowCount()} lignes (attendu {sans})")

    window.reset_filters()
    pump(300)
    check("reinitialiser retire aussi le filtre de surlignage",
          window.proxy.rowCount() == total_lignes
          and window.proxy.current_rule() == RULE_ANY,
          f"{window.proxy.rowCount()} lignes")

    print("=== captures ===")
    window.reset_filters()
    window._apply_column_filter(COLUMN_LEVEL, {"Erreur", "Avertissement"}, "")
    pump(400)
    out = tempfile.mkdtemp(prefix="ftolog_shots_")
    for name in ("light", "dark"):
        window.apply_theme(theme.apply(app, name))
        pump(300)
        shot = os.path.join(out, f"filtres_{name}.png")
        window.grab().save(shot)
        print("  capture:", shot)

    window.close()
    pump(300)
    netshare.unc_path = real_unc
    shutil.rmtree(root, ignore_errors=True)

    print()
    if FAILURES:
        print(f"RESULTAT : {len(FAILURES)} controle(s) en echec")
        for name in FAILURES:
            print("  -", name)
        return 1
    print("RESULTAT : tous les controles passent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
