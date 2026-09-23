"""Boîte « À propos » : version, auteur, composants, emplacements des fichiers."""

from __future__ import annotations

import os
import platform

import PySide6
from PySide6.QtCore import QSize, Qt, QUrl, qVersion
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..common import icons, paths
from ..common.i18n import tr
from ..version import APP_NAME, AUTHOR, GITHUB_URL, POWERED_BY, __version__, build_date


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("About {app}").format(app=APP_NAME))
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(16)
        logo = QLabel()
        logo.setPixmap(icons.app_icon().pixmap(QSize(72, 72)))
        header.addWidget(logo, 0, Qt.AlignmentFlag.AlignTop)
        titles = QVBoxLayout()
        name = QLabel(APP_NAME)
        name.setProperty("title", True)
        version = QLabel(tr("Version {version}").format(version=__version__))
        version.setProperty("heading", True)
        built = build_date()
        date = QLabel(tr("Built on {date}").format(date=built) if built else tr("Run from source"))
        date.setProperty("muted", True)
        author = QLabel(f"{AUTHOR} — {tr('Independent automation engineer')}")
        powered = QLabel(tr("Powered by {model}").format(model=POWERED_BY))
        powered.setProperty("muted", True)
        link = QLabel(f'<a href="{GITHUB_URL}">{GITHUB_URL}</a>')
        link.setOpenExternalLinks(True)
        for widget in (name, version, date, author, powered, link):
            titles.addWidget(widget)
        header.addLayout(titles, 1)
        layout.addLayout(header)

        details = QGridLayout()
        details.setHorizontalSpacing(12)
        rows = [
            ("Python", platform.python_version()),
            ("PySide6", PySide6.__version__),
            ("Qt", qVersion()),
        ]
        for row, (label, value) in enumerate(rows):
            key = QLabel(label)
            key.setProperty("muted", True)
            details.addWidget(key, row, 0)
            details.addWidget(QLabel(value), row, 1)
        details.setColumnStretch(1, 1)
        layout.addLayout(details)

        folders = QHBoxLayout()
        for text, target in (
            (tr("Open settings folder"), paths.data_dir()),
            (tr("Open log folder"), paths.log_dir()),
        ):
            button = QPushButton(text)
            button.clicked.connect(lambda _c=False, t=target: QDesktopServices.openUrl(QUrl.fromLocalFile(os.fspath(t))))
            folders.addWidget(button)
        folders.addStretch(1)
        layout.addLayout(folders)

        licenses = QLabel(
            tr(
                "Third-party components: Qt and PySide6 (LGPL v3), Qt Advanced Docking System (LGPL v2.1), "
                "openpyxl (MIT), PyYAML (MIT)."
            )
        )
        licenses.setProperty("muted", True)
        licenses.setWordWrap(True)
        layout.addWidget(licenses)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
