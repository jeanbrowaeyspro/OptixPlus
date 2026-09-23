"""Controles du selecteur de periode et de la largeur des colonnes.

- la derniere colonne reste ancree au bord droit du tableau, qu'on
  redimensionne la fenetre ou n'importe quelle colonne ;
- le champ date affiche la date entiere sans etre rogne par le calendrier, et
  toute la ligne de periode a la meme hauteur ;
- l'heure se choisit dans un panneau, pas seulement au clavier, et les trois
  champs de saisie precise se partagent la largeur sans etre masques par
  leurs fleches ;
- changer la date cale l'heure sur le premier (ou dernier) evenement du jour.

Rendu hors ecran : aucune fenetre n'apparait.

Lancement : .venv/Scripts/python.exe tests/test_period.py
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

from PySide6.QtCore import QDate, QEventLoop, QTime, QTimer
from PySide6.QtWidgets import QAbstractSpinBox, QApplication

from optixplus.modules.logreader.core import netshare
from optixplus.common import theme
from optixplus.modules.logreader.core.config import Settings
from optixplus.modules.logreader.core.discovery import Ipc
from optixplus.modules.logreader.ui.datetime_range import DateTimeField, TimePickerPopup
from optixplus.modules.logreader.ui.log_model import COLUMN_MESSAGE
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


def build_log(directory):
    """Journal sur deux journees, avec des heures bien distinctes.

    Le 05/09 va de 08:15:10 a 17:40:55, le 07/09 de 06:05:00 a 22:30:00.
    Le 06/09 ne contient aucun evenement : c'est le cas de repli.
    """
    moments = [
        ("05-09-2026", ["08:15:10", "11:02:33", "17:40:55"]),
        ("07-09-2026", ["06:05:00", "13:20:41", "22:30:00"]),
    ]
    path = os.path.join(directory, "FTOptixRuntime.0.log")
    with open(path, "wb") as handle:
        for day, hours in moments:
            for hour in hours:
                handle.write(
                    f"{day} {hour}.000;INFO;FTOptixRuntime;;Evenement {day} {hour};;Root/X\r\n"
                    .encode()
                )
    return path


def main():
    app = QApplication(sys.argv)

    root = tempfile.mkdtemp(prefix="ftolog_period_")
    log_dir = os.path.join(root, "Optix", "Log")
    os.makedirs(log_dir)
    build_log(log_dir)

    settings = Settings()
    settings.poll_interval_ms = 250
    settings.remember_last_host = False
    palette = theme.apply(app, "light")

    real_unc = netshare.unc_path
    netshare.unc_path = lambda host, share: os.path.join(root, share)

    window = MainWindow(settings, palette)
    window.resize(1200, 700)
    window.show()
    pump(200)
    window.connect_to(Ipc(host="local", reachable=True, log_available=True))
    pump(1000)
    check("journal de test charge", window.model.rowCount() == 6,
          f"{window.model.rowCount()} lignes")

    print("=== la derniere colonne est ancree au bord droit ===")
    header = window.header

    def right_gap():
        """Espace vide entre la fin de la derniere colonne et le bord du tableau."""
        total = sum(
            header.sectionSize(i) for i in range(header.count())
            if not header.isSectionHidden(i)
        )
        return window.table.viewport().width() - total

    # Un ecart negatif signifie que les colonnes debordent : une barre de
    # defilement apparait, mais il n'y a aucun vide, ce qui est le point
    # demande. Seul un ecart positif serait un defaut.
    for width, height in ((1100, 700), (1500, 820), (1920, 1080), (2560, 1400)):
        window.resize(width, height)
        pump(350)
        gap = right_gap()
        check(f"aucun vide a droite en fenetre de {width} px",
              gap <= 0,
              "colonnes ajustees au bord" if gap == 0 else f"debordement de {-gap} px")

    # Sur une fenetre assez large pour tout contenir, la derniere colonne doit
    # s'etirer jusqu'au bord exactement.
    window.resize(2400, 1000)
    pump(350)
    check("en fenetre large, la derniere colonne va jusqu'au bord",
          right_gap() == 0, f"{right_gap()} px")

    # Retrecir une colonne du milieu doit profiter a la derniere, pas laisser
    # un trou : c'est le cas que le calage sur la seule colonne Message ratait.
    window.resize(1900, 900)
    pump(350)
    before = header.sectionSize(header.count() - 1)
    header.resizeSection(COLUMN_MESSAGE, 300)
    pump(250)
    check("retrecir une colonne agrandit la derniere, sans laisser de vide",
          right_gap() == 0 and header.sectionSize(header.count() - 1) > before,
          f"vide {right_gap()} px, derniere colonne {before} -> "
          f"{header.sectionSize(header.count() - 1)} px")

    header.resizeSection(COLUMN_MESSAGE, 900)
    pump(250)
    check("elargir une colonne ne laisse pas non plus de vide",
          right_gap() <= 0, f"{right_gap()} px")

    print("=== champ date lisible ===")
    window.period_button.setChecked(True)
    pump(300)
    field = window.from_edit
    metrics = field.date_button.fontMetrics()
    needed = metrics.horizontalAdvance("31/12/2026")
    check("le bouton date est plus large que la date la plus longue",
          field.date_button.width() >= needed + 30,
          f"bouton {field.date_button.width()} px, texte {needed} px")
    check("le bouton date affiche la date en entier",
          field.date_button.text() == field.date().toString("dd/MM/yyyy"),
          field.date_button.text())
    time_needed = field.time_button.fontMetrics().horizontalAdvance("00:00:00")
    check("l'heure est un bouton distinct, dimensionne sur son texte",
          field.time_button.isVisible()
          and field.time_button.width() >= time_needed + 20
          and field.time_button.text() == field.time().toString("HH:mm:ss"),
          f"bouton {field.time_button.width()} px pour un texte de {time_needed} px")

    # Champ date, bouton heure et boutons de raccourci partagent la meme ligne :
    # une difference de hauteur s'y voit immediatement.
    heights = {
        "bouton date": field.date_button.height(),
        "bouton heure": field.time_button.height(),
        "bouton raccourci": window.period_bar.findChild(
            type(field.time_button), None
        ).height(),
    }
    check("tous les controles de la ligne ont la meme hauteur",
          len(set(heights.values())) == 1,
          ", ".join(f"{k}={v}" for k, v in heights.items()))

    # Le calendrier s'ouvre depuis le bouton, sans sous-controle a habiller.
    from optixplus.modules.logreader.ui.datetime_range import DatePickerPopup

    field._open_date_picker()
    pump(300)
    calendriers = [w for w in QApplication.topLevelWidgets()
                   if isinstance(w, DatePickerPopup)]
    check("le bouton date ouvre bien le calendrier", len(calendriers) == 1,
          f"{len(calendriers)} panneau(x)")
    if calendriers:
        calendriers[0]._pick(QDate(2026, 9, 7))
        pump(200)
        check("choisir dans le calendrier met la date a jour",
              field.date() == QDate(2026, 9, 7), field.date().toString("dd/MM/yyyy"))

    print("=== panneau de choix de l'heure ===")
    popup = TimePickerPopup(QTime(9, 30, 0), palette, window)
    popup.show()
    pump(250)
    check("24 heures proposees", len(popup._hour_buttons) == 24)
    check("12 minutes proposees par pas de 5", len(popup._minute_buttons) == 12)
    check("l'heure courante est mise en evidence",
          popup._hour_buttons[9].isChecked() and popup._minute_buttons[30].isChecked())

    picked = []
    popup.timePicked.connect(picked.append)
    popup._hour_buttons[14].click()
    popup._minute_buttons[45].click()
    pump(150)
    check("cliquer heure puis minute compose l'heure voulue",
          popup._time == QTime(14, 45, 0), popup._time.toString("HH:mm:ss"))

    largeurs = [popup.hour_spin.width(), popup.minute_spin.width(), popup.second_spin.width()]
    ligne = sum(largeurs) + 2 * 6 + 2 * 5
    check("les trois champs precis se partagent toute la ligne",
          min(largeurs) >= 70 and ligne >= popup.width() - 40,
          f"largeurs {largeurs}, ligne {ligne} px pour un panneau de {popup.width()} px")
    # Un pixel d'ecart vient du partage entier de la largeur : invisible.
    check("les trois champs precis ont la meme largeur",
          max(largeurs) - min(largeurs) <= 2, str(largeurs))
    check("les champs precis n'ont plus de fleches",
          all(spin.buttonSymbols() == QAbstractSpinBox.ButtonSymbols.NoButtons
              for spin in (popup.hour_spin, popup.minute_spin, popup.second_spin)))
    check("les cases de la grille gardent leur taille",
          popup._hour_buttons[0].height() == 28
          and popup._hour_buttons[0].width() == 42,
          f"{popup._hour_buttons[0].width()}x{popup._hour_buttons[0].height()} px")

    popup.second_spin.setValue(30)
    pump(100)
    check("la saisie precise ajoute les secondes",
          popup._time == QTime(14, 45, 30), popup._time.toString("HH:mm:ss"))
    popup._apply(popup._time)
    pump(150)
    check("valider transmet l'heure choisie",
          picked and picked[-1] == QTime(14, 45, 30),
          picked[-1].toString("HH:mm:ss") if picked else "rien")

    print("=== l'heure suit les evenements du jour choisi ===")
    window.from_edit.set_date(QDate(2026, 9, 5))
    pump(300)
    check("borne de debut : premier evenement du 05/09",
          window.from_edit.time() == QTime(8, 15, 10),
          window.from_edit.time().toString("HH:mm:ss"))

    window.to_edit.set_date(QDate(2026, 9, 5))
    pump(300)
    check("borne de fin : dernier evenement du 05/09",
          window.to_edit.time() == QTime(17, 40, 55),
          window.to_edit.time().toString("HH:mm:ss"))

    check("la periode ainsi cadree retient les 3 lignes du 05/09",
          window.proxy.rowCount() == 3, f"{window.proxy.rowCount()} lignes")

    window.from_edit.set_date(QDate(2026, 9, 7))
    window.to_edit.set_date(QDate(2026, 9, 7))
    pump(300)
    check("changer de jour recale les deux bornes",
          window.from_edit.time() == QTime(6, 5, 0)
          and window.to_edit.time() == QTime(22, 30, 0),
          f"{window.from_edit.time().toString('HH:mm:ss')} -> "
          f"{window.to_edit.time().toString('HH:mm:ss')}")
    check("la periode retient les 3 lignes du 07/09",
          window.proxy.rowCount() == 3, f"{window.proxy.rowCount()} lignes")

    # Le 06/09 ne contient rien : on retombe sur les bornes de la journee.
    window.from_edit.set_date(QDate(2026, 9, 6))
    window.to_edit.set_date(QDate(2026, 9, 6))
    pump(300)
    check("jour sans evenement : la borne de debut reste a minuit",
          window.from_edit.time() == QTime(0, 0, 0),
          window.from_edit.time().toString("HH:mm:ss"))
    check("jour sans evenement : la borne de fin va a 23:59:59",
          window.to_edit.time() == QTime(23, 59, 59),
          window.to_edit.time().toString("HH:mm:ss"))
    check("aucune ligne ce jour-la", window.proxy.rowCount() == 0,
          f"{window.proxy.rowCount()} lignes")

    print("=== raccourcis de periode ===")
    window._reset_period_bounds()
    pump(300)
    check("« Toute la plage » retrouve les 6 lignes", window.proxy.rowCount() == 6,
          f"{window.proxy.rowCount()} lignes")

    window.period_button.setChecked(False)
    pump(200)
    check("refermer la periode retire le filtre de date",
          window.proxy.rowCount() == 6, f"{window.proxy.rowCount()} lignes")

    print("=== captures ===")
    out = tempfile.mkdtemp(prefix="ftolog_period_shots_")
    window.resize(1500, 820)
    window.period_button.setChecked(True)
    pump(400)
    for name in ("light", "dark"):
        window.apply_theme(theme.apply(app, name))
        pump(300)
        window.grab().save(os.path.join(out, f"periode_{name}.png"))
        picker = TimePickerPopup(QTime(13, 20, 0), window.palette_, window)
        picker.show()
        pump(300)
        picker.grab().save(os.path.join(out, f"heure_{name}.png"))
        picker.close()
        pump(150)
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
