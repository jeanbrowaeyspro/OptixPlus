"""Nouveautés : les notes de version de CHANGELOG.md, depuis la dernière version vue ou en entier."""

from __future__ import annotations

from PySide6.QtCore import QByteArray
from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QLabel, QTextBrowser, QVBoxLayout, QWidget

from ..common import i18n
from ..common.i18n import tr
from ..update import changelog
from ..version import APP_NAME, __version__


class ChangelogDialog(QDialog):
    def __init__(self, last_seen: str = "", full: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("What's new in {app}").format(app=APP_NAME))
        self.resize(640, 520)
        self._sections = changelog.load()
        self._news = changelog.news_since(self._sections, last_seen, __version__)

        layout = QVBoxLayout(self)
        intro = QLabel(tr("Version {version}").format(version=__version__))
        intro.setProperty("heading", True)
        layout.addWidget(intro)
        if i18n.current_language() != "fr":
            note = QLabel(tr("The release notes are written in French."))
            note.setProperty("muted", True)
            layout.addWidget(note)
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        layout.addWidget(self.browser, 1)
        self.full_history = QCheckBox(tr("Show the full history"))
        self.full_history.setChecked(full or not self._news)
        self.full_history.toggled.connect(self._render)
        layout.addWidget(self.full_history)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._render()

    def _render(self, *_args) -> None:
        sections = self._sections if self.full_history.isChecked() else self._news
        if sections:
            self.browser.setMarkdown("\n".join(s.markdown() for s in sections))
        else:
            self.browser.setPlainText(tr("No release notes available."))

    def snapshot(self) -> dict:
        return {
            "full": self.full_history.isChecked(),
            "scroll": self.browser.verticalScrollBar().value(),
            "geometry": bytes(self.saveGeometry().toBase64().data()),
        }

    def restore(self, state: dict) -> None:
        self.full_history.setChecked(state.get("full", self.full_history.isChecked()))
        if state.get("geometry"):
            self.restoreGeometry(QByteArray.fromBase64(state["geometry"]))
        self.browser.verticalScrollBar().setValue(state.get("scroll", 0))
