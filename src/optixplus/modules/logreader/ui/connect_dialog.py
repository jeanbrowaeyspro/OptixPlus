"""Fenêtre de découverte et de sélection de l'automate.

Le balayage démarre dès l'ouverture. Si une seule machine expose un journal
lisible, la connexion se fait automatiquement sans intervention ; sinon la
liste reste affichée avec, pour chaque adresse, le nom de l'IPC, le projet
Optix en cours et l'état du sondage.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QProgressBar, QPushButton, QStyle, QStyledItemDelegate, QVBoxLayout,
)

from ..core.discovery import Ipc
from ..theme import Palette
from ..workers import DiscoveryWorker, retire

IPC_ROLE = Qt.ItemDataRole.UserRole + 1

#: Délai laissé à l'utilisateur pour interrompre la connexion automatique.
AUTO_CONNECT_DELAY_MS = 900


class IpcDelegate(QStyledItemDelegate):
    """Dessine une entrée sur deux lignes : nom en évidence, adresse et état."""

    def __init__(self, palette: Palette, parent=None):
        super().__init__(parent)
        self.palette_ = palette

    def sizeHint(self, option, index) -> QSize:
        return QSize(option.rect.width(), 62)

    def paint(self, painter: QPainter, option, index) -> None:
        ipc: Ipc = index.data(IPC_ROLE)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = option.rect.adjusted(4, 3, -4, -3)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        if selected:
            painter.setBrush(QColor(self.palette_.selection))
            painter.setPen(QPen(QColor(self.palette_.accent), 1))
        elif hovered:
            painter.setBrush(QColor(self.palette_.surface_alt))
            painter.setPen(Qt.PenStyle.NoPen)
        else:
            painter.setBrush(QColor(self.palette_.surface))
            painter.setPen(QPen(QColor(self.palette_.border), 1))
        painter.drawRoundedRect(rect, 8, 8)

        # Pastille d'état : vert = journal lisible, ambre = joignable mais
        # journal inaccessible, gris = aucune réponse.
        if ipc.log_available:
            dot = QColor(self.palette_.success)
        elif ipc.reachable:
            dot = QColor(self.palette_.warning)
        else:
            dot = QColor(self.palette_.border)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(dot)
        painter.drawEllipse(rect.left() + 14, rect.center().y() - 5, 10, 10)

        text_left = rect.left() + 38
        text_width = rect.width() - 48
        text_colour = QColor(self.palette_.selection_text if selected else self.palette_.text)
        muted = QColor(self.palette_.text_muted)

        name_font = QFont(option.font)
        name_font.setPointSizeF(option.font.pointSizeF() + 0.5)
        name_font.setBold(True)
        painter.setFont(name_font)
        painter.setPen(text_colour)
        painter.drawText(
            QRect(text_left, rect.top() + 9, text_width, 20),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            painter.fontMetrics().elidedText(ipc.display_name, Qt.TextElideMode.ElideRight, text_width),
        )

        detail_font = QFont(option.font)
        detail_font.setPointSizeF(max(7.5, option.font.pointSizeF() - 1.0))
        painter.setFont(detail_font)
        painter.setPen(muted)
        painter.drawText(
            QRect(text_left, rect.top() + 30, text_width, 20),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            painter.fontMetrics().elidedText(_detail_line(ipc), Qt.TextElideMode.ElideRight, text_width),
        )

        painter.restore()


def _detail_line(ipc: Ipc) -> str:
    parts = [ipc.host]
    if ipc.reachable and ipc.ping_ms >= 0:
        parts.append(f"{ipc.ping_ms} ms")
    elif ipc.icmp_filtered:
        parts.append("ICMP filtré, port 445 ouvert")
    if ipc.runtime_version:
        parts.append(f"runtime {ipc.runtime_version}")
    parts.append(ipc.status)
    return "  ·  ".join(parts)


class ConnectDialog(QDialog):
    """Sélection de l'IPC sur lequel lire le journal."""

    settingsRequested = Signal()

    def __init__(self, settings, palette: Palette, parent=None, auto_connect: bool = True):
        super().__init__(parent)
        self.settings = settings
        self.palette_ = palette
        self._auto_connect = auto_connect
        self._worker: DiscoveryWorker | None = None
        self._retiring: list = []
        self._results: dict[str, Ipc] = {}
        self._auto_timer: QTimer | None = None
        self.selected: Ipc | None = None

        self.setWindowTitle("Connexion à un automate")
        self.setMinimumSize(560, 460)
        self._build()
        QTimer.singleShot(0, self.start_scan)

    # ----------------------------------------------------------- composition

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        title = QLabel("Automates détectés")
        title.setProperty("heading", True)
        layout.addWidget(title)

        self.subtitle = QLabel("Recherche en cours…")
        self.subtitle.setProperty("muted", True)
        self.subtitle.setWordWrap(True)
        layout.addWidget(self.subtitle)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)          # animation indéterminée
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        layout.addWidget(self.progress)

        self.list = QListWidget()
        self.list.setItemDelegate(IpcDelegate(self.palette_, self.list))
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setMouseTracking(True)
        self.list.setSpacing(1)
        self.list.itemSelectionChanged.connect(self._selection_changed)
        self.list.itemDoubleClicked.connect(self._accept_if_usable)
        layout.addWidget(self.list, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)

        self.rescan_button = QPushButton("Relancer la recherche")
        self.rescan_button.clicked.connect(self.start_scan)
        buttons.addWidget(self.rescan_button)

        self.settings_button = QPushButton("Paramètres…")
        self.settings_button.clicked.connect(self.settingsRequested.emit)
        buttons.addWidget(self.settings_button)

        buttons.addStretch(1)

        cancel = QPushButton("Annuler")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)

        self.connect_button = QPushButton("Se connecter")
        self.connect_button.setProperty("accent", True)
        self.connect_button.setDefault(True)
        self.connect_button.setEnabled(False)
        self.connect_button.clicked.connect(self._accept_if_usable)
        buttons.addWidget(self.connect_button)

        layout.addLayout(buttons)

    # -------------------------------------------------------------- balayage

    def start_scan(self) -> None:
        self._cancel_auto_connect()
        self._stop_worker()

        self._results.clear()
        self.list.clear()
        self.progress.show()
        self.rescan_button.setEnabled(False)
        self.connect_button.setEnabled(False)

        hosts = self.settings.hosts
        if not hosts:
            self.progress.hide()
            self.rescan_button.setEnabled(True)
            self.subtitle.setText(
                "Aucune adresse à tester. Ajoutez-en dans les paramètres."
            )
            return

        plural = "s" if len(hosts) > 1 else ""
        self.subtitle.setText(f"Test de {len(hosts)} adresse{plural}…")

        self._worker = DiscoveryWorker(
            hosts,
            self.settings.share_name,
            self.settings.log_relative_path(),
            self.settings.enabled_credentials(),
            self.settings.ping_timeout_ms,
            parent=self,
        )
        self._worker.hostProbed.connect(self._on_host_probed)
        self._worker.finishedScan.connect(self._on_scan_finished)
        self._worker.start()

    def _stop_worker(self) -> None:
        # Le balayage sonde des machines éventuellement injoignables : on ne
        # l'attend pas, sous peine de figer la fenêtre le temps que ses délais
        # réseau s'épuisent.
        retire(self._worker, self._retiring)
        self._worker = None

    def _on_host_probed(self, ipc: Ipc) -> None:
        self._results[ipc.host] = ipc
        self._rebuild_list()

    def _rebuild_list(self) -> None:
        """Réaffiche la liste dans l'ordre des adresses configurées, les
        machines exploitables en tête."""
        previous = self._selected_host()
        self.list.clear()

        ordered = [self._results[h] for h in self.settings.hosts if h in self._results]
        ordered.sort(key=lambda i: (not i.log_available, not i.reachable))

        for ipc in ordered:
            item = QListWidgetItem()
            item.setData(IPC_ROLE, ipc)
            item.setSizeHint(QSize(0, 62))
            if not ipc.log_available:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.list.addItem(item)
            if ipc.host == previous:
                self.list.setCurrentItem(item)

    def _on_scan_finished(self, results: list) -> None:
        self.progress.hide()
        self.rescan_button.setEnabled(True)
        self._worker = None

        usable = [ipc for ipc in results if ipc.log_available]
        if not usable:
            reachable = [ipc for ipc in results if ipc.reachable]
            if reachable:
                self.subtitle.setText(
                    "Aucun journal accessible. Les machines répondent mais le partage "
                    "ou le fichier de log est hors de portée — vérifiez les identifiants "
                    "dans les paramètres."
                )
            else:
                self.subtitle.setText(
                    "Aucun automate n'a répondu. Vérifiez le réseau et la liste "
                    "d'adresses dans les paramètres."
                )
            return

        if len(usable) == 1:
            self._select_host(usable[0].host)
            if self._auto_connect:
                self.subtitle.setText(
                    f"Un seul automate trouvé : {usable[0].display_name}. Connexion…"
                )
                self._start_auto_connect()
                return
            self.subtitle.setText(f"Un automate trouvé : {usable[0].display_name}.")
            return

        self.subtitle.setText(
            f"{len(usable)} automates disponibles. Sélectionnez celui à consulter."
        )
        self._select_host(usable[0].host)

    # --------------------------------------------------- connexion auto

    def _start_auto_connect(self) -> None:
        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.timeout.connect(self._accept_if_usable)
        self._auto_timer.start(AUTO_CONNECT_DELAY_MS)

    def _cancel_auto_connect(self) -> None:
        if self._auto_timer is not None:
            self._auto_timer.stop()
            self._auto_timer = None

    # ------------------------------------------------------------- sélection

    def _selected_host(self) -> str:
        item = self.list.currentItem()
        if item is None:
            return ""
        return item.data(IPC_ROLE).host

    def _select_host(self, host: str) -> None:
        for row in range(self.list.count()):
            item = self.list.item(row)
            if item.data(IPC_ROLE).host == host:
                self.list.setCurrentItem(item)
                return

    def _selection_changed(self) -> None:
        item = self.list.currentItem()
        usable = item is not None and item.data(IPC_ROLE).log_available
        self.connect_button.setEnabled(usable)

    def _accept_if_usable(self, *_args) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        ipc: Ipc = item.data(IPC_ROLE)
        if not ipc.log_available:
            return
        self.selected = ipc
        self.accept()

    # ----------------------------------------------------------- cycle de vie

    def mousePressEvent(self, event) -> None:
        # Toute action de l'utilisateur annule la connexion automatique.
        self._cancel_auto_connect()
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        self._cancel_auto_connect()
        super().keyPressEvent(event)

    def reject(self) -> None:
        self._cancel_auto_connect()
        self._stop_worker()
        super().reject()

    def closeEvent(self, event) -> None:
        self._cancel_auto_connect()
        self._stop_worker()
        super().closeEvent(event)
