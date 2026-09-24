"""Fenêtre de connexion : la connexion automatique n'a lieu qu'au démarrage.

Le balayage réseau est remplacé par un résultat figé : un seul automate exploitable,
exactement le cas où l'ancien comportement refermait la fenêtre sous le nez de
l'utilisateur qui voulait changer d'automate.
"""

from __future__ import annotations

import pytest

from optixplus.common import i18n, theme
from optixplus.modules.logreader.core.config import Controller
from optixplus.modules.logreader.core.config import Settings as ReaderSettings
from optixplus.modules.logreader.core.discovery import Ipc
from optixplus.modules.logreader.ui import connect_dialog
from optixplus.modules.logreader.ui.connect_dialog import ConnectDialog

from .conftest import settle, wait_for

USABLE = Ipc(host="192.0.2.10", netbios_name="PC-TEST", project="ProjetX", reachable=True,
             share_accessible=True, log_available=True, status="pret")


@pytest.fixture
def dialog_factory(qapp, monkeypatch):
    def fake_scan(self) -> None:
        self._on_host_probed(USABLE)
        self._on_scan_finished([USABLE])

    monkeypatch.setattr(ConnectDialog, "start_scan", fake_scan)
    monkeypatch.setattr(connect_dialog, "AUTO_CONNECT_DELAY_MS", 0)
    i18n.install("fr")
    settings = ReaderSettings(controllers=[Controller(host="192.0.2.10")])
    dialogs: list[ConnectDialog] = []

    def build(auto_connect: bool) -> ConnectDialog:
        dialog = ConnectDialog(settings, theme.LIGHT, auto_connect=auto_connect)
        dialogs.append(dialog)
        dialog.show()
        return dialog

    yield build
    for dialog in dialogs:
        dialog.close()
    i18n.install("en")


def test_change_controller_waits_for_the_click(dialog_factory):
    dialog = dialog_factory(auto_connect=False)
    assert wait_for(lambda: dialog.list.count() == 1)
    settle()
    assert dialog._auto_timer is None  # aucune connexion programmée
    assert dialog.isVisible() and dialog.selected is None
    assert dialog.connect_button.isEnabled()  # automate présélectionné, prêt à valider


def test_startup_connects_automatically(dialog_factory):
    dialog = dialog_factory(auto_connect=True)
    assert wait_for(lambda: dialog.selected is not None)
    assert dialog.selected.host == "192.0.2.10"
    assert dialog.result() == ConnectDialog.DialogCode.Accepted
