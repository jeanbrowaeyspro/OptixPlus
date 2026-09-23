"""Controles du voyant de connexion et de la reconnexion automatique.

Le voyant de la barre du bas doit passer au rouge des que le journal devient
illisible, puis revenir au vert de lui-meme une fois l'acces retabli, sans
aucune action de l'utilisateur.

La coupure est simulee en renommant le fichier de journal : c'est le meme
symptome que celui d'un partage devenu injoignable, du point de vue du lecteur.

Rendu hors ecran : aucune fenetre n'apparait.

Lancement : .venv/Scripts/python.exe tests/test_connection.py
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

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from optixplus.modules.logreader.core import netshare
from optixplus.modules.logreader import theme
from optixplus.modules.logreader.core.config import Settings
from optixplus.modules.logreader.core.discovery import Ipc
from optixplus.modules.logreader.ui.status_indicator import (
    STATE_LOST, STATE_OFFLINE, STATE_ONLINE, ConnectionIndicator,
)
from optixplus.modules.logreader.ui.main_window import MainWindow
from optixplus.modules.logreader.workers import LogWatcher

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


def wait_for(predicate, timeout_ms=6000, step=150):
    """Attend qu'une condition devienne vraie, sans depasser le delai."""
    waited = 0
    while waited < timeout_ms:
        if predicate():
            return True
        pump(step)
        waited += step
    return predicate()


def line(n):
    return (f"07-09-2026 09:00:{n:02d}.000;INFO;FTOptixRuntime;;"
            f"Evenement {n};;Root/X\r\n").encode()


def main():
    app = QApplication(sys.argv)
    palette = theme.apply(app, "light")

    # La reconnexion attend normalement trois secondes entre deux tentatives ;
    # on raccourcit ce delai pour que le test reste rapide.
    LogWatcher.RECONNECT_INTERVAL_MS = 300

    root = tempfile.mkdtemp(prefix="ftolog_conn_")
    log_dir = os.path.join(root, "Optix", "Log")
    os.makedirs(log_dir)
    log_path = os.path.join(log_dir, "FTOptixRuntime.0.log")
    with open(log_path, "wb") as handle:
        for i in range(5):
            handle.write(line(i))

    settings = Settings()
    settings.poll_interval_ms = 200
    settings.remember_last_host = False

    real_unc = netshare.unc_path
    netshare.unc_path = lambda host, share: os.path.join(root, share)

    window = MainWindow(settings, palette)
    window.resize(1300, 760)
    window.show()
    pump(200)

    print("=== avant toute connexion ===")
    check("le voyant existe dans la barre du bas",
          isinstance(window.connection_dot, ConnectionIndicator))
    check("il est eteint tant qu'aucun automate n'est connecte",
          window.connection_dot.state == STATE_OFFLINE,
          window.connection_dot.state)

    print("=== connexion etablie ===")
    window.connect_to(Ipc(host="local", netbios_name="BANC-TEST",
                          reachable=True, log_available=True))
    check("le voyant passe au vert une fois le journal lu",
          wait_for(lambda: window.connection_dot.state == STATE_ONLINE, 4000),
          window.connection_dot.state)
    check("5 lignes chargees", window.model.rowCount() == 5,
          f"{window.model.rowCount()} lignes")
    vert = window.connection_dot._colour().name()
    check("la pastille est verte", vert.lower() == palette.success.lower(),
          f"{vert} (attendu {palette.success})")

    print("=== connexion perdue ===")
    ecarte = os.path.join(root, "hors-ligne.log")
    shutil.move(log_path, ecarte)
    check("le voyant passe au rouge",
          wait_for(lambda: window.connection_dot.state == STATE_LOST, 5000),
          window.connection_dot.state)
    rouge = window.connection_dot._colour().name()
    check("la pastille est rouge", rouge.lower() == palette.error.lower(),
          f"{rouge} (attendu {palette.error})")
    check("la barre du bas annonce la reconnexion",
          "reconnexion" in window.status_live.text().lower(),
          window.status_live.text())
    check("l'infobulle du voyant donne la raison",
          "perdue" in window.connection_dot.toolTip().lower(),
          window.connection_dot.toolTip().splitlines()[0])

    # C'est le point qui manquait : un message temporaire de la barre d'etat
    # masque les widgets « normaux », et le voyant s'evanouissait au moment ou
    # il devenait utile.
    window.statusBar().showMessage("Message temporaire quelconque", 0)
    pump(250)
    check("le voyant reste visible malgre un message temporaire",
          window.connection_dot.isVisible() and window.connection_dot.state == STATE_LOST,
          f"visible={window.connection_dot.isVisible()}, etat={window.connection_dot.state}")
    check("le nom de l'automate reste visible lui aussi",
          window.status_connection.isVisible())
    window.statusBar().clearMessage()
    pump(150)

    print("=== reconnexion automatique ===")
    # Aucune action de l'utilisateur : on remet simplement le fichier en place.
    shutil.move(ecarte, log_path)
    check("le voyant repasse au vert tout seul",
          wait_for(lambda: window.connection_dot.state == STATE_ONLINE, 6000),
          window.connection_dot.state)
    check("la mention de reconnexion disparait",
          "reconnexion" not in window.status_live.text().lower(),
          window.status_live.text())

    print("=== le suivi reprend apres la coupure ===")
    with open(log_path, "ab") as handle:
        for i in range(5, 9):
            handle.write(line(i))
    check("les nouvelles lignes arrivent de nouveau",
          wait_for(lambda: window.model.rowCount() == 9, 5000),
          f"{window.model.rowCount()} lignes")

    print("=== deconnexion ===")
    window._stop_watcher()
    pump(200)
    check("le voyant s'eteint quand le suivi s'arrete",
          window.connection_dot.state == STATE_OFFLINE,
          window.connection_dot.state)

    print("=== captures ===")
    out = tempfile.mkdtemp(prefix="ftolog_conn_shots_")
    for state, nom in ((STATE_ONLINE, "vert"), (STATE_LOST, "rouge")):
        window.connection_dot.set_state(state, "detail")
        pump(150)
        window.statusBar().grab().save(os.path.join(out, f"footer_{nom}.png"))
    print("  captures dans:", out)

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
