"""Automates du Lecteur de logs : modèle, reprise des anciens réglages, catégorie des Paramètres."""

from __future__ import annotations

import json

import pytest
from PySide6.QtWidgets import QMessageBox

from optixplus.common import dpapi, i18n, logging_setup
from optixplus.common.settings import Settings
from optixplus.common.theme import install_manager
from optixplus.modules.logreader.core import discovery
from optixplus.modules.logreader.core.config import DEFAULT_LOG_DIR, Controller
from optixplus.modules.logreader.core.config import Settings as ReaderSettings
from optixplus.shell.context import LaunchMode
from optixplus.shell.controller import AppController


# ----------------------------------------------------------------------------- modèle
def test_relative_folder_is_on_the_controller_share():
    plc = Controller(host="192.168.1.10")
    assert plc.log_dir == DEFAULT_LOG_DIR
    assert plc.log_folder() == r"\\192.168.1.10\Optix\Log"
    assert plc.network_share() == ("192.168.1.10", "Optix")
    assert plc.validation_error() == ""


def test_local_and_network_folders_are_used_as_is():
    local = Controller(log_dir=r"C:\Archives\Optix\Log")
    assert local.is_local() and local.network_share() is None
    assert local.log_folder() == r"C:\Archives\Optix\Log"
    assert local.validation_error() == ""  # adresse facultative pour un dossier local
    unc = Controller(log_dir=r"\\srv\Optix\Log")
    assert not unc.is_local() and unc.network_share() == ("srv", "Optix")


def test_ip_and_folder_are_the_only_required_fields():
    assert Controller().validation_error()  # adresse manquante
    assert Controller(host="10.0.0.1", log_dir="").validation_error()  # dossier manquant
    assert Controller(host="10.0.0.1").validation_error() == ""


def test_duplicate_keeps_every_field_with_a_new_identity():
    plc = Controller(name="Ligne 1", host="10.0.0.1", username="op", password="pw", log_dir=r"Optix\Log")
    copy = plc.duplicate()
    assert copy.id != plc.id
    assert (copy.host, copy.username, copy.password, copy.log_dir) == (plc.host, plc.username, plc.password, plc.log_dir)
    assert copy.name != plc.name and copy.name.startswith("Ligne 1")


def test_passwords_are_encrypted_on_disk_and_ids_kept():
    settings = ReaderSettings(controllers=[Controller(host="10.0.0.1", username="op", password="s3cret")])
    data = settings.to_dict()
    assert data["controllers"][0]["password"] != "s3cret"
    again = ReaderSettings.from_dict(json.loads(json.dumps(data)))
    assert again.controllers[0].password == "s3cret"
    assert again.controllers[0].id == settings.controllers[0].id


def test_former_addresses_and_credentials_become_controllers():
    data = {
        "hosts": ["10.0.0.1", "10.0.0.2"],
        "credentials": [
            {"label": "off", "username": "old", "password": dpapi.protect("x"), "enabled": False},
            {"label": "on", "username": "op", "password": dpapi.protect("pw"), "enabled": True},
        ],
        "share_name": "Optix",
        "log_subdir": "Log",
    }
    settings = ReaderSettings.from_dict(data)
    assert [(c.host, c.username, c.password, c.log_dir) for c in settings.controllers] == [
        ("10.0.0.1", "op", "pw", r"Optix\Log"),
        ("10.0.0.2", "op", "pw", r"Optix\Log"),
    ]


def test_local_folder_is_probed_without_network(tmp_path):
    folder = tmp_path / "Optix" / "Log"
    folder.mkdir(parents=True)
    (folder / "FTOptixRuntime.0.log").write_text("", encoding="utf-8")
    (tmp_path / "Optix" / "FTOptixRuntime.xml").write_text("<Root><MainProject>Demo</MainProject></Root>", encoding="utf-8")
    plc = Controller(name="Archives", log_dir=str(folder))
    ipc = discovery.probe_controller(plc, "FTOptixRuntime.0.log")
    assert ipc.log_available and ipc.project == "Demo"
    assert ipc.ref == plc.id and ipc.display_name == "Archives — Demo"
    missing = discovery.probe_controller(Controller(log_dir=str(tmp_path / "absent")), "FTOptixRuntime.0.log")
    assert not missing.reachable and not missing.log_available


# ------------------------------------------------------------------ catégorie des Paramètres
@pytest.fixture
def controller(qapp, tmp_path, monkeypatch):
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warnings.append(a[2])))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    i18n.install("fr")
    logging_setup.configure(to_file=False)
    settings = Settings.load(tmp_path / "settings.json")
    ctrl = AppController(qapp, settings, install_manager(qapp, "light"), LaunchMode.INSTALLED)
    ctrl.warnings = warnings
    yield ctrl
    if ctrl.window is not None:
        ctrl.window.close()
    i18n.install("en")


def test_controllers_are_added_duplicated_and_saved_from_the_settings_window(controller):
    controller.show_main_window()
    controller.open_settings("logreader")
    dialog = controller._settings_dialog
    page = dialog.tool_page("logreader")
    assert page.controllers_list.count() == 0

    page.add_button.click()
    page.name_edit.setText("Ligne 1")
    page.name_edit.textEdited.emit("Ligne 1")
    page.host_edit.setText("10.0.0.1")
    page.host_edit.textEdited.emit("10.0.0.1")
    page.username_edit.setText("op")
    page.username_edit.textEdited.emit("op")
    page.duplicate_button.click()
    assert page.controllers_list.count() == 2 and page.host_edit.text() == "10.0.0.1"
    page.host_edit.setText("10.0.0.2")
    page.host_edit.textEdited.emit("10.0.0.2")
    assert dialog._apply()

    saved = controller.context.settings.store("logreader")["controllers"]
    assert [(c["name"], c["host"], c["username"]) for c in saved] == [
        ("Ligne 1", "10.0.0.1", "op"),
        ("Ligne 1 (copie)", "10.0.0.2", "op"),
    ]
    assert not page.has_unsaved_changes()
    dialog.close()


def test_incomplete_controller_blocks_apply(controller):
    controller.show_main_window()
    controller.open_settings("logreader")
    dialog = controller._settings_dialog
    page = dialog.tool_page("logreader")
    page.add_button.click()  # ni adresse ni dossier local : incomplet
    assert not dialog._apply()
    assert controller.warnings and "adresse IP" in controller.warnings[0]
    assert "controllers" not in controller.context.settings.store("logreader")
    dialog.close()


def test_open_log_reader_tabs_receive_the_new_settings(controller):
    window = controller.show_main_window()
    window.show_page("logreader")
    reader = window.module("logreader").page
    controller.open_settings("logreader")
    page = controller._settings_dialog.tool_page("logreader")
    page.add_button.click()
    page.host_edit.setText("10.0.0.9")
    page.host_edit.textEdited.emit("10.0.0.9")
    assert controller._settings_dialog._apply()
    assert [c.host for c in reader.settings.controllers] == ["10.0.0.9"]
    controller._settings_dialog.close()


def test_reader_settings_action_opens_the_settings_window_on_its_category(controller):
    window = controller.show_main_window()
    window.show_page("logreader")
    window.module("logreader").page.action_settings.trigger()
    dialog = controller._settings_dialog
    assert dialog is not None and dialog._categories.currentItem().text() == "Lecteur de logs"
    dialog.close()
