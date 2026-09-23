"""Controles sur les colonnes du tableau.

- viser la separation entre deux colonnes redimensionne, sans ouvrir le filtre ;
- viser l'entonnoir ouvre bien le filtre ;
- les colonnes se masquent et l'etat survit a une reouverture de l'application.

Rendu hors ecran : aucune fenetre n'apparait.

Lancement : .venv/Scripts/python.exe tests/test_columns.py
"""
import os
import shutil
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32":
    os.environ.setdefault(
        "QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts")
    )

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QEventLoop, QPoint, QRect, Qt, QTimer
from PySide6.QtWidgets import QApplication

from optixplus.modules.logreader.core import netshare
from optixplus.modules.logreader import theme
from optixplus.modules.logreader.core.config import Settings
from optixplus.modules.logreader.core.discovery import Ipc
from optixplus.modules.logreader.ui.log_model import COLUMNS, COLUMN_LEVEL, COLUMN_NODE, COLUMN_SOURCE
from optixplus.modules.logreader.ui.main_window import MainWindow

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


def build_log(directory):
    path = os.path.join(directory, "FTOptixRuntime.0.log")
    levels = ["INFO", "ERROR", "WARNING"]
    with open(path, "wb") as handle:
        for i in range(12):
            handle.write(
                f"07-09-2026 09:00:{i:02d}.000;{levels[i % 3]};FTOptixRuntime;;"
                f"Evenement {i};;Root/X\r\n".encode()
            )
    return path


def open_window(app, root, settings):
    window = MainWindow(settings, theme.resolve("light"))
    window.resize(1500, 820)
    window.show()
    pump(200)
    window.connect_to(Ipc(host="local", reachable=True, log_available=True))
    pump(900)
    return window


def main():
    app = QApplication(sys.argv)
    theme.apply(app, "light")

    root = tempfile.mkdtemp(prefix="ftolog_cols_")
    log_dir = os.path.join(root, "Optix", "Log")
    os.makedirs(log_dir)
    build_log(log_dir)

    config_dir = tempfile.mkdtemp(prefix="ftolog_cfg_")
    Settings.config_dir = staticmethod(lambda: __import__("pathlib").Path(config_dir))

    real_unc = netshare.unc_path
    netshare.unc_path = lambda host, share: os.path.join(root, share)

    # Réglages adossés à une section de settings.json simulée (dictionnaire en mémoire).
    store: dict = {}
    settings = Settings.bound(store, lambda: None)
    settings.poll_interval_ms = 250
    settings.remember_last_host = False
    window = open_window(app, root, settings)
    header = window.header

    print("=== la separation des colonnes reste attrapable ===")

    def section_rect(index):
        return QRect(header.sectionViewportPosition(index), 0,
                     header.sectionSize(index), header.height())

    rect = section_rect(COLUMN_LEVEL)
    edge = QPoint(rect.right() - 1, rect.height() // 2)
    check("le bord droit d'une colonne n'ouvre pas le filtre",
          header._near_section_edge(edge), f"x={edge.x()} (bord a {rect.right()})")

    for offset in (0, 2, 4, 6):
        point = QPoint(rect.right() - offset, rect.height() // 2)
        check(f"a {offset} px de la separation, c'est le redimensionnement",
              header._near_section_edge(point))

    funnel = header._funnel_rect(rect)
    centre = QPoint(funnel.center().x(), rect.height() // 2)
    check("le centre de l'entonnoir declenche bien le filtre",
          header._hit_zone(rect).contains(centre) and not header._near_section_edge(centre),
          f"entonnoir x={funnel.left()}..{funnel.right()}, bord a {rect.right()}")

    check("l'entonnoir ne mord pas sur la poignee",
          funnel.right() < rect.right() - header._grip_margin() + 1,
          f"entonnoir finit a {funnel.right()}, poignee des "
          f"{rect.right() - header._grip_margin()}")

    opened = []
    header.filterRequested.connect(lambda column, _pos: opened.append(column))

    print("=== colonnes masquables ===")
    check("toutes les colonnes visibles au depart",
          window._visible_column_count() == len(COLUMNS),
          f"{window._visible_column_count()} / {len(COLUMNS)}")

    window._set_column_visible(COLUMN_SOURCE, False)
    pump(200)
    check("masquer une colonne la retire du tableau",
          header.isSectionHidden(COLUMN_SOURCE))
    check("le reglage est enregistre",
          settings.hidden_columns == [COLUMNS[COLUMN_SOURCE][0]],
          str(settings.hidden_columns))

    # Un filtre posé sur une colonne masquée serait invisible : il doit partir.
    window._apply_column_filter(COLUMN_LEVEL, {"Erreur"}, "")
    pump(200)
    avant = window.proxy.rowCount()
    window._set_column_visible(COLUMN_LEVEL, False)
    pump(250)
    check("masquer une colonne filtree retire son filtre",
          COLUMN_LEVEL not in window.proxy.filtered_columns()
          and window.proxy.rowCount() > avant,
          f"{avant} -> {window.proxy.rowCount()} lignes")

    print("=== le reglage survit a une reouverture ===")
    window.close()
    pump(300)

    relu = Settings.bound(store, lambda: None)
    check("la configuration relue contient les colonnes masquees",
          set(relu.hidden_columns) == {COLUMNS[COLUMN_SOURCE][0], COLUMNS[COLUMN_LEVEL][0]},
          str(relu.hidden_columns))

    relu.poll_interval_ms = 250
    relu.remember_last_host = False
    window2 = open_window(app, root, relu)
    check("les colonnes masquees le restent a la reouverture",
          window2.header.isSectionHidden(COLUMN_SOURCE)
          and window2.header.isSectionHidden(COLUMN_LEVEL),
          f"{window2._visible_column_count()} colonnes visibles")

    print("=== garde-fous ===")
    for index in range(len(COLUMNS)):
        window2._set_column_visible(index, False)
    pump(200)
    check("il reste toujours au moins une colonne",
          window2._visible_column_count() >= 1,
          f"{window2._visible_column_count()} colonne(s)")

    window2._show_all_columns()
    pump(200)
    check("« Tout afficher » restaure tout",
          window2._visible_column_count() == len(COLUMNS)
          and relu.hidden_columns == [],
          f"{window2._visible_column_count()} colonnes, "
          f"reglage {relu.hidden_columns}")

    check("la derniere colonne reste ancree au bord droit",
          window2.table.viewport().width()
          - sum(window2.header.sectionSize(i) for i in range(window2.header.count())) <= 0)

    print("=== capture ===")
    out = tempfile.mkdtemp(prefix="ftolog_cols_shots_")
    window2._set_column_visible(COLUMN_NODE, False)
    pump(300)
    window2.grab().save(os.path.join(out, "colonnes.png"))
    print("  capture:", os.path.join(out, "colonnes.png"))

    window2.close()
    pump(300)
    netshare.unc_path = real_unc
    shutil.rmtree(root, ignore_errors=True)
    shutil.rmtree(config_dir, ignore_errors=True)

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
