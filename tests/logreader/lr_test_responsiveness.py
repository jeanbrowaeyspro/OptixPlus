"""L'interface ne doit jamais dependre de l'etat du reseau.

Cable debranche, une simple ouverture de fichier sur un chemin UNC peut ne
rendre la main qu'au bout de dizaines de secondes. On verifie ici que :

- la fenetre continue de traiter ses evenements pendant qu'une lecture est
  suspendue ;
- le voyant passe au rouge en moins de deux secondes, sans attendre que la
  lecture echoue formellement ;
- il repasse au vert des que la lecture redevient possible ;
- changer d'automate ou fermer la fenetre ne l'attend pas.

La suspension est simulee en remplacant l'ouverture de fichier par une version
qui dort : du point de vue du fil de suivi, c'est exactement ce que produit un
partage devenu muet.

Rendu hors ecran : aucune fenetre n'apparait.

Lancement : .venv/Scripts/python.exe tests/test_responsiveness.py
"""
import os
import shutil
import sys
import tempfile
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32":
    os.environ.setdefault(
        "QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts")
    )

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtWidgets import QApplication

from optixplus.modules.logreader.core import logreader, netshare
from optixplus.common import theme
from optixplus.modules.logreader.core.config import Settings
from optixplus.modules.logreader.core.discovery import Ipc
from optixplus.common import i18n as _i18n
from optixplus.common import workers as _workers

_i18n.install("fr")  # les vérifications portent sur les libellés français
from optixplus.modules.logreader.ui.log_tab import LogTab as MainWindow  # l'onglet reprend la fenêtre d'origine
from optixplus.modules.logreader.ui.status_indicator import STATE_LOST, STATE_OFFLINE, STATE_ONLINE

FAILURES = []

#: Duree de la fausse suspension, tres au-dela du seuil de detection.
HANG_SECONDS = 8.0


def check(label, condition, detail=""):
    status = "OK  " if condition else "ECHEC"
    if not condition:
        FAILURES.append(label)
    print(f"  [{status}] {label}{('  -> ' + detail) if detail else ''}")


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_for(predicate, timeout_ms=6000):
    """Attend une condition dans une seule boucle d'evenements continue.

    Enchainer de courtes boucles imbriquees ferait perdre des battements entre
    deux d'entre elles et laisserait croire, a tort, que la fenetre s'est
    figee. Une boucle unique mesure ce qui se passe vraiment.
    """
    loop = QEventLoop()
    debut = time.monotonic()
    resultat = {"ecoule": -1.0}

    def verifier():
        atteint = predicate()
        ecoule = (time.monotonic() - debut) * 1000
        if atteint or ecoule >= timeout_ms:
            resultat["ecoule"] = ecoule if atteint else -1.0
            loop.quit()

    surveillant = QTimer()
    surveillant.setTimerType(Qt.TimerType.PreciseTimer)
    surveillant.setInterval(25)
    surveillant.timeout.connect(verifier)
    surveillant.start()
    loop.exec()
    surveillant.stop()
    return resultat["ecoule"]


class Heartbeat:
    """Compte les battements du fil de l'interface.

    Si la fenetre se fige, le minuteur cesse de battre : c'est exactement ce
    qu'on cherche a detecter. Le minuteur est declare « precis » car, par
    defaut, Qt s'accorde une tolerance calee sur la resolution d'horloge de
    Windows — environ 15,6 ms — ce qui suffirait a perdre un quart des
    battements d'un minuteur a 50 ms, sans que rien ne soit fige.
    """

    def __init__(self, interval_ms=50):
        self.count = 0
        self.timer = QTimer()
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(interval_ms)
        self.timer.timeout.connect(self._tick)
        self.interval = interval_ms

    def _tick(self):
        self.count += 1

    def start(self):
        self.count = 0
        self.timer.start()

    def stop(self):
        self.timer.stop()

    def expected(self, elapsed_ms):
        return elapsed_ms // self.interval


def main():
    app = QApplication(sys.argv)
    palette = theme.apply(app, "light")

    root = tempfile.mkdtemp(prefix="ftolog_resp_")
    log_dir = os.path.join(root, "Optix", "Log")
    os.makedirs(log_dir)
    log_path = os.path.join(log_dir, "FTOptixRuntime.0.log")
    with open(log_path, "wb") as handle:
        for i in range(5):
            handle.write(
                f"07-09-2026 09:00:{i:02d}.000;INFO;FTOptixRuntime;;"
                f"Evenement {i};;Root/X\r\n".encode()
            )

    # Ouverture de fichier pilotable : quand le drapeau est leve, elle dort,
    # comme le ferait un partage injoignable.
    hang = threading.Event()
    real_open = logreader.open_shared

    def hanging_open(path):
        if hang.is_set():
            time.sleep(HANG_SECONDS)
        return real_open(path)

    logreader.open_shared = hanging_open

    settings = Settings()
    settings.poll_interval_ms = 200
    settings.remember_last_host = False

    real_unc = netshare.unc_path
    netshare.unc_path = lambda host, share: os.path.join(root, share)

    window = MainWindow(settings, palette)
    window.resize(1300, 760)
    window.show()
    pump(200)
    window.connect_to(Ipc(host="local", netbios_name="BANC-TEST",
                          reachable=True, log_available=True))
    check("connexion etablie",
          wait_for(lambda: window.connection_dot.state == STATE_ONLINE, 4000) >= 0,
          window.connection_dot.state)

    print("=== la fenetre reste vivante pendant une lecture suspendue ===")
    heart = Heartbeat()
    heart.start()
    debut = time.monotonic()
    hang.set()

    attente = wait_for(lambda: window.connection_dot.state == STATE_LOST, 4000)
    ecoule = (time.monotonic() - debut) * 1000
    heart.stop()

    check("le voyant passe au rouge sans attendre la fin de la lecture",
          attente >= 0 and ecoule < HANG_SECONDS * 1000 * 0.6,
          f"{ecoule:.0f} ms, alors que la lecture dort {HANG_SECONDS:.0f} s")
    check("la detection tient en moins de deux secondes", ecoule < 2500,
          f"{ecoule:.0f} ms")

    attendus = heart.expected(ecoule)
    check("le fil de l'interface n'a pas cesse de battre",
          heart.count >= attendus * 0.9,
          f"{heart.count} battements pour {attendus} attendus")
    check("la barre du bas annonce la reconnexion",
          "reconnexion" in window.status_live.text().lower(),
          window.status_live.text())
    check("le voyant reste affiche",
          window.connection_dot.isVisible(),
          f"visible={window.connection_dot.isVisible()}")

    print("=== changer d'automate n'attend pas le fil bloque ===")
    heart.start()
    debut = time.monotonic()
    window._stop_watcher()
    duree = (time.monotonic() - debut) * 1000
    heart.stop()
    check("l'arret du suivi est immediat", duree < 150, f"{duree:.0f} ms")
    check("le voyant s'eteint aussitot",
          window.connection_dot.state == STATE_OFFLINE,
          window.connection_dot.state)

    print("=== la fenetre repond toujours pendant que le fil agonise ===")
    heart.start()
    debut = time.monotonic()
    wait_for(lambda: False, 1000)          # une seule boucle, une seconde pleine
    observe = (time.monotonic() - debut) * 1000
    heart.stop()
    check("battements normaux malgre le fil encore suspendu",
          heart.count >= heart.expected(observe) * 0.9,
          f"{heart.count} battements pour {heart.expected(observe)} attendus")

    print("=== reprise apres retablissement ===")
    hang.clear()
    window.connect_to(Ipc(host="local", netbios_name="BANC-TEST",
                          reachable=True, log_available=True))
    check("le voyant repasse au vert",
          wait_for(lambda: window.connection_dot.state == STATE_ONLINE, 5000) >= 0,
          window.connection_dot.state)
    check("la mention de reconnexion a disparu",
          "reconnexion" not in window.status_live.text().lower(),
          window.status_live.text())
    check("les lignes sont bien la", window.model.rowCount() == 5,
          f"{window.model.rowCount()} lignes")

    print("=== nouvelle coupure puis retablissement, sans intervention ===")
    hang.set()
    check("rouge de nouveau",
          wait_for(lambda: window.connection_dot.state == STATE_LOST, 4000) >= 0,
          window.connection_dot.state)
    hang.clear()
    check("vert de nouveau, tout seul",
          wait_for(lambda: window.connection_dot.state == STATE_ONLINE, 15000) >= 0,
          window.connection_dot.state)

    print("=== fermeture ===")
    hang.set()
    pump(400)
    heart.start()
    debut = time.monotonic()
    window.close()
    fermeture = (time.monotonic() - debut) * 1000
    heart.stop()
    check("la fermeture ne s'eternise pas", fermeture < 3000,
          f"{fermeture:.0f} ms")

    hang.clear()
    pump(300)
    logreader.open_shared = real_open
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
    # Comme l'application : le fil encore suspendu est abandonné, pas attendu.
    code = main()
    _workers.wait_retired()
    sys.exit(_workers.exit_code(code))
