"""Fenêtre principale de pyFTOLogReader."""

from __future__ import annotations

import os
from datetime import datetime

from PySide6.QtCore import QDateTime, QModelIndex, Qt, QTime, QTimer, Signal
from PySide6.QtGui import QAction, QGuiApplication, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
    QProgressDialog, QPushButton, QSizePolicy, QSplitter, QTableView, QToolBar,
    QVBoxLayout, QWidget,
)

from .. import APP_TITLE
from ..core import export, logreader, netshare
from ..core.config import Settings
from ..core.discovery import Ipc
from ..core.highlight import Highlighter
from ..core.logparser import KNOWN_LEVELS
from ..theme import Palette, THEME_DARK, THEME_LIGHT, THEME_SYSTEM
from ..workers import ArchiveLoader, DiscoveryWorker, ExportWorker, LogWatcher, retire
from .connect_dialog import ConnectDialog
from .datetime_range import DateTimeField
from .detail_panel import DetailPanel
from .filter_header import MAX_DISTINCT_VALUES, ColumnFilterPopup, FilterHeaderView
from .log_filter import RULE_ANY, RULE_NONE, LogFilterProxy
from .log_model import (
    COLUMNS, COLUMN_LINE, COLUMN_MESSAGE, COLUMN_SOURCE, ENTRY_ROLE, LogTableModel,
    level_label,
)
from .settings_dialog import SettingsDialog
from .status_indicator import (
    STATE_CONNECTING, STATE_LOST, STATE_OFFLINE, STATE_ONLINE, ConnectionIndicator,
)

#: Marge en pixels sous laquelle on considère que l'utilisateur regarde le bas
#: du tableau et souhaite donc continuer à suivre les nouvelles lignes.
AUTOSCROLL_TOLERANCE = 48


class MainWindow(QMainWindow):
    """Fenêtre principale : tableau du journal, filtres et détail."""

    themeChanged = Signal(str)

    def __init__(self, settings: Settings, palette: Palette, icon: QIcon | None = None):
        super().__init__()
        self.settings = settings
        self.palette_ = palette
        self.app_icon = icon

        self.highlighter = Highlighter(settings.highlight_rules, dark=palette.dark)
        self.model = LogTableModel(self.highlighter, settings.max_rows, self)
        self.proxy = LogFilterProxy(self)
        self.proxy.setSourceModel(self.model)

        self.watcher: LogWatcher | None = None
        self.archive_loader: ArchiveLoader | None = None
        self.export_worker: ExportWorker | None = None
        self._export_progress: QProgressDialog | None = None
        self.current_ipc: Ipc | None = None
        self.current_path = ""
        self._archives_loaded = False
        self._suspend_filter_signals = False
        #: Fils dont on a demandé l'arrêt et qu'on ne veut surtout pas attendre.
        self._retiring: list = []
        self._link_detail = ""
        self._probe_worker: DiscoveryWorker | None = None

        self.setWindowTitle(APP_TITLE)
        if icon is not None:
            self.setWindowIcon(icon)
        self.resize(1360, 820)

        self._build_toolbar()
        self._build_body()
        self._build_status_bar()
        self._apply_palette(palette)
        self._update_actions()

        # Ce minuteur ne fait aucune entrée-sortie : il lit un flottant protégé
        # par un verrou. C'est ce qui permet de signaler une liaison muette
        # tout de suite, sans attendre qu'une lecture réseau bloquée rende la
        # main — ce qui, câble débranché, peut prendre une minute.
        self._health_timer = QTimer(self)
        self._health_timer.setInterval(400)
        self._health_timer.timeout.connect(self._refresh_connection_state)
        self._health_timer.start()

    # =======================================================  construction

    def _build_toolbar(self) -> None:
        bar = QToolBar("Actions")
        bar.setMovable(False)
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.addToolBar(bar)

        self.action_connect = QAction("Changer d'automate", self)
        self.action_connect.setShortcut(QKeySequence("Ctrl+O"))
        # Sans lambda, QAction transmettrait son booléen « checked » comme
        # premier argument, qui atterrirait dans auto_connect.
        self.action_connect.triggered.connect(lambda: self.choose_ipc(auto_connect=False))
        bar.addAction(self.action_connect)

        bar.addSeparator()

        self.action_pause = QAction("Suspendre le suivi", self)
        self.action_pause.setCheckable(True)
        self.action_pause.setShortcut(QKeySequence("Ctrl+P"))
        self.action_pause.toggled.connect(self._toggle_pause)
        bar.addAction(self.action_pause)

        self.action_autoscroll = QAction("Suivre le bas", self)
        self.action_autoscroll.setCheckable(True)
        self.action_autoscroll.setChecked(self.settings.autoscroll)
        self.action_autoscroll.setToolTip(
            "Fait défiler automatiquement jusqu'à la dernière ligne reçue."
        )
        self.action_autoscroll.toggled.connect(self._set_autoscroll)
        bar.addAction(self.action_autoscroll)

        self.action_archives = QAction("Charger l'historique", self)
        self.action_archives.setToolTip(
            "Ajoute les fichiers de rotation (.1, .2, .3) avant les lignes actuelles."
        )
        self.action_archives.triggered.connect(self.load_archives)
        bar.addAction(self.action_archives)

        bar.addSeparator()

        self.action_export_xlsx = QAction("Exporter en Excel", self)
        self.action_export_xlsx.setShortcut(QKeySequence("Ctrl+E"))
        self.action_export_xlsx.triggered.connect(lambda: self.export_log(as_csv=False))
        bar.addAction(self.action_export_xlsx)

        self.action_export_csv = QAction("Exporter en CSV", self)
        self.action_export_csv.triggered.connect(lambda: self.export_log(as_csv=True))
        bar.addAction(self.action_export_csv)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bar.addWidget(spacer)

        self.theme_combo = QComboBox()
        self.theme_combo.setToolTip("Thème de l'interface")
        for value, label in ((THEME_SYSTEM, "Thème : système"),
                             (THEME_LIGHT, "Thème : clair"),
                             (THEME_DARK, "Thème : sombre")):
            self.theme_combo.addItem(label, value)
        index = self.theme_combo.findData(self.settings.theme)
        self.theme_combo.setCurrentIndex(index if index >= 0 else 0)
        self.theme_combo.currentIndexChanged.connect(self._theme_selected)
        bar.addWidget(self.theme_combo)

        self.action_settings = QAction("Paramètres", self)
        self.action_settings.triggered.connect(self.open_settings)
        bar.addAction(self.action_settings)

    def _build_body(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 10, 12, 8)
        layout.setSpacing(8)

        layout.addWidget(self._build_filter_bar())
        layout.addWidget(self._build_period_bar())

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(26)

        header = FilterHeaderView(self.palette_, self.table)
        self.table.setHorizontalHeader(header)
        header.setSectionsMovable(True)
        # La dernière colonne occupe tout ce qui reste : son bord droit est
        # ainsi toujours collé au bord du tableau, qu'on redimensionne la
        # fenêtre ou n'importe quelle colonne. Aucun vide ne subsiste à droite.
        header.setStretchLastSection(True)
        for position, (_key, _title, width) in enumerate(COLUMNS):
            header.resizeSection(position, width)
        header.setSectionResizeMode(COLUMN_MESSAGE, QHeaderView.ResizeMode.Interactive)
        header.filterRequested.connect(self._open_column_filter)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._show_column_menu)
        self.header = header
        self._restore_hidden_columns()
        # Tri chronologique croissant par défaut : c'est ce qui garantit que la
        # ligne qui vient d'arriver s'affiche tout en bas. Sans cet appel
        # explicite, activer le tri laisse Qt choisir l'ordre décroissant.
        self.table.sortByColumn(COLUMN_LINE, Qt.SortOrder.AscendingOrder)
        splitter.addWidget(self.table)

        self.detail = DetailPanel(self.palette_)
        detail_container = QWidget()
        detail_layout = QVBoxLayout(detail_container)
        detail_layout.setContentsMargins(2, 6, 2, 2)
        detail_layout.addWidget(self.detail)
        splitter.addWidget(detail_container)

        # Sans facteurs d'étirement, le splitter répartit l'espace gagné entre
        # ses deux enfants : en plein écran, le panneau de détail grandissait
        # autant que le tableau. Tout le supplément va désormais au tableau.
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        detail_container.setMinimumHeight(150)
        splitter.setSizes([640, 200])
        self.splitter = splitter
        layout.addWidget(splitter, 1)

        self.setCentralWidget(central)

        self.table.selectionModel().currentRowChanged.connect(self._selection_changed)
        self.model.countChanged.connect(self._update_counts)
        self.proxy.rowsInserted.connect(self._maybe_autoscroll)
        self.proxy.modelReset.connect(self._update_counts)
        self.proxy.rowsInserted.connect(self._update_counts)
        self.proxy.rowsRemoved.connect(self._update_counts)

    def _build_filter_bar(self) -> QWidget:
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(
            "Rechercher…  (plusieurs mots = toutes les conditions doivent être réunies)"
        )
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._search_changed)
        layout.addWidget(self.search_edit, 3)

        self.level_checks: dict[str, QCheckBox] = {}
        for level in KNOWN_LEVELS:
            check = QCheckBox(level_label(level))
            check.setChecked(True)
            check.toggled.connect(self._levels_changed)
            self.level_checks[level] = check
            layout.addWidget(check)
        self._recolor_level_checks()

        self.period_button = QPushButton("Période…")
        self.period_button.setCheckable(True)
        self.period_button.toggled.connect(self._toggle_period_bar)
        layout.addWidget(self.period_button)

        self.reset_button = QPushButton("Réinitialiser")
        self.reset_button.clicked.connect(self.reset_filters)
        layout.addWidget(self.reset_button)

        return bar

    def _build_period_bar(self) -> QWidget:
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(QLabel("De"))
        self.from_edit = DateTimeField(self.palette_)
        self.from_edit.valueChanged.connect(self._period_changed)
        self.from_edit.dateEdited.connect(
            lambda date: self._snap_time_to_events(self.from_edit, date, start=True)
        )
        layout.addWidget(self.from_edit)

        layout.addWidget(QLabel("à"))
        self.to_edit = DateTimeField(self.palette_)
        self.to_edit.valueChanged.connect(self._period_changed)
        self.to_edit.dateEdited.connect(
            lambda date: self._snap_time_to_events(self.to_edit, date, start=False)
        )
        layout.addWidget(self.to_edit)

        span = QPushButton("Toute la plage")
        span.setToolTip("Replace les bornes sur la première et la dernière ligne chargées.")
        span.clicked.connect(self._reset_period_bounds)
        layout.addWidget(span)

        last_hour = QPushButton("Dernière heure")
        last_hour.setToolTip("Ne garde que les soixante dernières minutes de journal.")
        last_hour.clicked.connect(self._set_last_hour)
        layout.addWidget(last_hour)

        layout.addStretch(1)
        self.period_bar = bar
        bar.hide()
        return bar

    def _snap_time_to_events(self, field, date, start: bool) -> None:
        """Cale l'heure sur les événements du jour qui vient d'être choisi.

        La borne de début se pose sur le premier événement de la journée, celle
        de fin sur le dernier : on encadre ainsi exactement ce qui s'est passé
        ce jour-là. Sans aucun événement, on retombe sur les bornes naturelles
        de la journée, minuit et 23:59:59.
        """
        target = date.toPython()
        times = [
            entry.timestamp.time()
            for entry in self.model.entries
            if entry.timestamp is not None and entry.timestamp.date() == target
        ]
        if times:
            chosen = min(times) if start else max(times)
            value = QTime(chosen.hour, chosen.minute, chosen.second)
        else:
            value = QTime(0, 0, 0) if start else QTime(23, 59, 59)
        field.set_time(value, silent=True)

    def _set_last_hour(self) -> None:
        end = QDateTime.currentDateTime()
        self._suspend_filter_signals = True
        self.from_edit.setDateTime(end.addSecs(-3600), silent=True)
        self.to_edit.setDateTime(end, silent=True)
        self._suspend_filter_signals = False
        self._period_changed()

    def _build_status_bar(self) -> None:
        status = self.statusBar()

        self.connection_dot = ConnectionIndicator(self.palette_)
        self.status_connection = QLabel("Aucun automate connecté")

        identity = QWidget()
        identity_layout = QHBoxLayout(identity)
        identity_layout.setContentsMargins(0, 0, 0, 0)
        identity_layout.setSpacing(6)
        identity_layout.addWidget(self.connection_dot)
        identity_layout.addWidget(self.status_connection, 1)

        # En widget « permanent » et non « normal » : un message temporaire de
        # la barre d'état masque les widgets normaux, et le voyant disparaissait
        # au moment précis où il devenait utile. Le facteur d'étirement le
        # maintient à gauche, devant les compteurs.
        status.addPermanentWidget(identity, 3)

        # Les messages passagers ont leur propre mention plutôt que la zone de
        # message de QStatusBar : celle-ci n'a plus de place une fois le bloc
        # identité posé, et surtout elle masque les widgets « normaux » tant
        # qu'un message reste affiché.
        self.status_notice = QLabel("")
        self.status_notice.setProperty("muted", True)
        status.addPermanentWidget(self.status_notice, 2)

        self._notice_timer = QTimer(self)
        self._notice_timer.setSingleShot(True)
        self._notice_timer.timeout.connect(lambda: self.status_notice.setText(""))

        self.status_counts = QLabel("")
        status.addPermanentWidget(self.status_counts)

        self.status_live = QLabel("")
        status.addPermanentWidget(self.status_live)

    def notify(self, text: str, duration_ms: int = 8000) -> None:
        """Affiche une mention passagère dans la barre du bas."""
        self.status_notice.setText(text)
        self._notice_timer.stop()
        if duration_ms > 0:
            self._notice_timer.start(duration_ms)

    # =========================================================  apparence

    def _apply_palette(self, palette: Palette) -> None:
        self.palette_ = palette
        self.highlighter.set_dark(palette.dark)
        self.detail.set_palette_colors(palette)
        if hasattr(self, "header"):
            self.header.set_palette_colors(palette)
        if hasattr(self, "connection_dot"):
            self.connection_dot.set_palette_colors(palette)
        for name in ("from_edit", "to_edit"):
            field = getattr(self, name, None)
            if field is not None:
                field.set_palette_colors(palette)
        self.model.refresh_highlighting()
        self._recolor_level_checks()

    def _recolor_level_checks(self) -> None:
        """Donne à chaque case de niveau la couleur de son niveau, pour que le
        lien avec les lignes du tableau saute aux yeux."""
        colours = {
            "ERROR": self.palette_.error,
            "WARNING": self.palette_.warning,
            "INFO": self.palette_.info,
        }
        for level, check in getattr(self, "level_checks", {}).items():
            colour = colours.get(level, self.palette_.accent)
            check.setStyleSheet(
                f"QCheckBox::indicator:checked {{ background: {colour}; "
                f"border-color: {colour}; }}"
            )

    def _theme_selected(self) -> None:
        theme = self.theme_combo.currentData()
        if theme == self.settings.theme:
            return
        self.settings.theme = theme
        self.settings.save()
        self.themeChanged.emit(theme)

    def apply_theme(self, palette: Palette) -> None:
        """Appelée par l'application quand la palette effective change."""
        self._apply_palette(palette)
        index = self.theme_combo.findData(self.settings.theme)
        if index >= 0 and index != self.theme_combo.currentIndex():
            self.theme_combo.blockSignals(True)
            self.theme_combo.setCurrentIndex(index)
            self.theme_combo.blockSignals(False)

    # =========================================================  connexion

    def choose_ipc(self, auto_connect: bool = False) -> bool:
        """Ouvre la fenêtre de découverte. Renvoie vrai si une connexion a eu lieu.

        ``auto_connect`` n'est vrai qu'au démarrage de l'application. Lorsque
        l'utilisateur a lui-même demandé à changer d'automate, la fenêtre attend
        son choix même s'il n'y a qu'une seule machine disponible : se refermer
        toute seule reviendrait à ignorer le clic qui vient d'être fait.
        """
        dialog = ConnectDialog(self.settings, self.palette_, self, auto_connect=auto_connect)
        dialog.settingsRequested.connect(lambda: self._open_settings_from(dialog))
        if dialog.exec() != ConnectDialog.DialogCode.Accepted or dialog.selected is None:
            return False
        self.connect_to(dialog.selected)
        return True

    def try_reconnect_last_host(self) -> None:
        """Retente le dernier automate utilisé sans bloquer le démarrage.

        Le sondage — ping, NetBIOS, ouverture du partage — est une suite
        d'appels réseau qui, machine éteinte, prennent plusieurs secondes. Les
        faire ici figerait la fenêtre avant même qu'elle ne s'affiche.
        """
        host = self.settings.last_host
        if not host:
            self.choose_ipc(auto_connect=True)
            return

        self.connection_dot.set_state(STATE_CONNECTING, host)
        self.status_connection.setText(f"Recherche de {host}…")

        self._probe_worker = DiscoveryWorker(
            [host],
            self.settings.share_name,
            self.settings.log_relative_path(),
            self.settings.enabled_credentials(),
            self.settings.ping_timeout_ms,
            parent=self,
        )
        self._probe_worker.finishedScan.connect(self._on_last_host_probed)
        self._probe_worker.start()

    def _on_last_host_probed(self, results: list) -> None:
        retire(self._probe_worker, self._retiring)
        self._probe_worker = None

        usable = [ipc for ipc in results if ipc.log_available]
        if usable:
            self.connect_to(usable[0])
            return

        self.connection_dot.set_state(STATE_OFFLINE)
        self.status_connection.setText("Aucun automate connecté")
        self.choose_ipc(auto_connect=True)

    def _open_settings_from(self, dialog: ConnectDialog) -> None:
        if self.open_settings():
            dialog.start_scan()

    def connect_to(self, ipc: Ipc) -> None:
        """Ouvre le journal de l'IPC choisi et démarre le suivi."""
        self._stop_watcher()

        self.current_ipc = ipc
        self.current_path = os.path.join(
            netshare.unc_path(ipc.host, self.settings.share_name),
            self.settings.log_relative_path(),
        )
        self._archives_loaded = False
        self.model.clear()
        self.detail.show_entry(None)

        if self.settings.remember_last_host:
            self.settings.last_host = ipc.host
            self.settings.save()

        title_bits = [APP_TITLE, ipc.display_name]
        self.setWindowTitle("  —  ".join(title_bits))
        self.status_connection.setText(
            f"{ipc.display_name}   ·   {ipc.host}   ·   {self.current_path}"
        )
        # Le libellé se fait rogner quand une mention passagère occupe la barre :
        # l'infobulle garde le chemin complet à portée de souris.
        self.status_connection.setToolTip(
            "\n".join((ipc.display_name, ipc.host, self.current_path))
        )
        self.status_live.setText("Chargement…")

        self.connection_dot.set_state(STATE_CONNECTING, self.current_path)

        self.watcher = LogWatcher(
            self.current_path, self.settings.poll_interval_ms, self,
            host=ipc.host,
            share=self.settings.share_name,
            credentials=self.settings.enabled_credentials(),
        )
        self.watcher.initialLoaded.connect(self._on_initial_loaded)
        self.watcher.entriesAdded.connect(self._on_entries_added)
        self.watcher.fileRotated.connect(self._on_file_rotated)
        self.watcher.errorChanged.connect(self._on_watcher_error)
        self.watcher.connectionChanged.connect(self._on_connection_changed)
        self.watcher.set_paused(self.action_pause.isChecked())
        self.watcher.start()
        self._update_actions()

    def _stop_watcher(self) -> None:
        # On ne l'attend pas : s'il est coincé dans une lecture réseau, il ne
        # rendra la main que dans plusieurs dizaines de secondes, et la fenêtre
        # resterait figée d'autant.
        retire(self.watcher, self._retiring)
        self.watcher = None
        self._link_detail = ""
        if hasattr(self, "connection_dot"):
            self.connection_dot.set_state(STATE_OFFLINE)

    # ------------------------------------------------------------- réception

    def _on_initial_loaded(self, result) -> None:
        self.model.set_entries(result.entries)
        self._reset_period_bounds()
        self._scroll_to_bottom()
        if result.error:
            self.status_live.setText("Journal illisible")
        else:
            self.status_live.setText(self._live_label())

    def _on_entries_added(self, entries: list) -> None:
        self.model.append_entries(entries)
        self.status_live.setText(self._live_label())

    def _on_file_rotated(self, entries: list) -> None:
        # Le runtime a basculé sur un nouveau fichier : les lignes déjà
        # affichées viennent de l'ancien, on enchaîne donc sans les perdre.
        self.model.append_entries(entries)
        self.notify(
            "Rotation du journal détectée : le suivi se poursuit sur le nouveau fichier."
        )
        self.status_live.setText(self._live_label())

    def _on_watcher_error(self, error: str) -> None:
        if error:
            self.status_live.setText("Journal inaccessible — nouvelle tentative en cours")
            self.notify(f"Lecture impossible : {error}", 10000)
        else:
            self.status_live.setText(self._live_label())

    def _on_connection_changed(self, connected: bool, detail: str) -> None:
        """Prend acte de ce que rapporte le fil de suivi."""
        self._link_detail = "" if connected else detail
        self._refresh_connection_state()

    def _refresh_connection_state(self) -> None:
        """Met le voyant à jour à partir de l'état réel de la liaison.

        Appelée à la fois par le fil de suivi et par le minuteur de
        surveillance : une lecture qui s'éternise suffit à déclarer la liaison
        perdue, sans attendre l'échec formel de l'appel.
        """
        if self.watcher is None:
            if self.connection_dot.state != STATE_OFFLINE:
                self.connection_dot.set_state(STATE_OFFLINE)
            return

        if not self.watcher.has_verdict() and not self.watcher.is_stalled():
            # Première lecture en cours : on laisse le voyant sur « connexion
            # en cours » plutôt que de trancher trop tôt dans un sens ou dans
            # l'autre.
            return

        stalled = self.watcher.is_stalled()
        connected = self.watcher.is_connected() and not stalled

        if connected:
            if self.connection_dot.state != STATE_ONLINE:
                self.connection_dot.set_state(STATE_ONLINE, self.current_path)
                self.status_live.setText(self._live_label())
            return

        if stalled and not self._link_detail:
            silence = self.watcher.io_stalled_ms() / 1000.0
            detail = f"aucune réponse depuis {silence:.0f} s"
        else:
            detail = self._link_detail or "liaison interrompue"

        # L'état de la liaison ne passe plus par un message temporaire : il
        # tiendrait le voyant caché tant qu'il resterait affiché. Le voyant
        # porte la couleur, son infobulle porte le motif, et la mention de
        # droite dit ce qui se passe.
        self.connection_dot.set_state(STATE_LOST, detail)
        self.status_live.setText(self._live_label())

    def _live_label(self) -> str:
        if self.watcher is None:
            return ""
        if not self.watcher.is_connected() or self.watcher.is_stalled():
            return "Connexion perdue  ·  reconnexion…"
        if self.action_pause.isChecked():
            return "Suivi suspendu"
        return "En direct  ·  " + datetime.now().strftime("%H:%M:%S")

    # =========================================================  archives

    def load_archives(self) -> None:
        if self.current_ipc is None:
            return
        if self._archives_loaded:
            QMessageBox.information(
                self, "Historique",
                "Les fichiers archivés sont déjà chargés dans la vue.",
            )
            return

        log_dir = os.path.join(
            netshare.unc_path(self.current_ipc.host, self.settings.share_name),
            self.settings.log_subdir,
        )

        self.action_archives.setEnabled(False)
        self.status_live.setText("Recherche des fichiers archivés…")
        # La recherche des fichiers est elle-même une entrée-sortie réseau :
        # elle se fait dans le fil, pas ici.
        self.archive_loader = ArchiveLoader(
            log_dir, self.settings.log_filename, self
        )
        self.archive_loader.loaded.connect(self._on_archives_loaded)
        self.archive_loader.start()

    def _on_archives_loaded(self, entries: list, error: str) -> None:
        self.archive_loader = None
        self.action_archives.setEnabled(True)

        if error and not entries:
            QMessageBox.warning(self, "Historique", f"Lecture impossible : {error}")
            self.status_live.setText(self._live_label())
            return

        if not entries:
            QMessageBox.information(
                self, "Historique",
                "Aucun fichier de rotation n'a été trouvé à côté du journal courant.",
            )
            self.status_live.setText(self._live_label())
            return

        # Les archives précèdent chronologiquement les lignes déjà affichées.
        self.model.set_entries(entries + list(self.model.entries))
        self._archives_loaded = True
        self._reset_period_bounds()
        self.notify(
            f"{len(entries)} ligne(s) d'historique ajoutée(s) avant les lignes en direct."
        )
        self.status_live.setText(self._live_label())
        self._update_actions()

    # =========================================================  filtres

    def _search_changed(self, text: str) -> None:
        if not self._suspend_filter_signals:
            self.proxy.set_search(text)

    def _levels_changed(self) -> None:
        if self._suspend_filter_signals:
            return
        selected = {level for level, check in self.level_checks.items() if check.isChecked()}
        # Tout cocher revient à ne pas filtrer : on évite un test inutile par ligne.
        self.proxy.set_levels(None if len(selected) == len(self.level_checks) else selected)

    def _toggle_period_bar(self, visible: bool) -> None:
        self.period_bar.setVisible(visible)
        if visible:
            self._period_changed()
        else:
            self.proxy.set_period(None, None)

    def _period_changed(self) -> None:
        if self._suspend_filter_signals or not self.period_bar.isVisible():
            return
        self.proxy.set_period(
            self.from_edit.dateTime().toPython(), self.to_edit.dateTime().toPython()
        )
        self._update_counts()

    def _reset_period_bounds(self) -> None:
        stamps = [e.timestamp for e in self.model.entries if e.timestamp is not None]
        self._suspend_filter_signals = True
        if stamps:
            self.from_edit.setDateTime(QDateTime(min(stamps)), silent=True)
            self.to_edit.setDateTime(QDateTime(max(stamps)), silent=True)
        self._suspend_filter_signals = False
        self._period_changed()

    def reset_filters(self) -> None:
        self._suspend_filter_signals = True
        self.search_edit.clear()
        for check in self.level_checks.values():
            check.setChecked(True)
        self.period_button.setChecked(False)
        self.period_bar.hide()
        self._suspend_filter_signals = False
        self.proxy.reset_filters()
        self._sync_filter_indicators()
        self._update_counts()

    # ------------------------------------------------------- colonnes visibles

    def _show_column_menu(self, position) -> None:
        """Menu de choix des colonnes affichées, au clic droit sur l'en-tête."""
        self._column_menu().exec(self.header.mapToGlobal(position))

    def _column_menu(self) -> QMenu:
        menu = QMenu(self)
        title = menu.addAction("Colonnes affichées")
        title.setEnabled(False)
        menu.addSeparator()
        for index, (_key, label, _width) in enumerate(COLUMNS):
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(not self.header.isSectionHidden(index))
            action.toggled.connect(
                lambda checked, i=index: self._set_column_visible(i, checked)
            )
        menu.addSeparator()
        menu.addAction("Tout afficher", self._show_all_columns)
        return menu

    def _set_column_visible(self, index: int, visible: bool) -> None:
        if not visible and self._visible_column_count() <= 1:
            # Masquer la dernière colonne laisserait un tableau vide.
            return
        if not visible:
            # Un filtre posé sur une colonne masquée serait invisible et donc
            # impossible à retirer : on l'enlève en même temps que la colonne.
            self.proxy.set_column_filter(index, None, "")
            self._sync_filter_indicators()
        self.header.setSectionHidden(index, not visible)
        self._save_hidden_columns()
        self._update_counts()

    def _show_all_columns(self) -> None:
        for index in range(len(COLUMNS)):
            self.header.setSectionHidden(index, False)
        self._save_hidden_columns()

    def _visible_column_count(self) -> int:
        return sum(
            1 for index in range(len(COLUMNS))
            if not self.header.isSectionHidden(index)
        )

    def _save_hidden_columns(self) -> None:
        self.settings.hidden_columns = [
            COLUMNS[index][0] for index in range(len(COLUMNS))
            if self.header.isSectionHidden(index)
        ]
        self.settings.save()

    def _restore_hidden_columns(self) -> None:
        """Réapplique les colonnes masquées lors de la session précédente."""
        keys = {key: index for index, (key, _label, _w) in enumerate(COLUMNS)}
        hidden = [keys[key] for key in self.settings.hidden_columns if key in keys]
        # On refuse de tout masquer, au cas où la configuration serait
        # incohérente : le tableau doit rester exploitable.
        if len(hidden) >= len(COLUMNS):
            return
        for index in hidden:
            self.header.setSectionHidden(index, True)

    # ---------------------------------------------------------------- filtres

    def _open_column_filter(self, column: int, position) -> None:
        """Ouvre le panneau de filtre d'une colonne, sous son en-tête."""
        values, truncated = self.model.distinct_values(column, MAX_DISTINCT_VALUES)
        selected, text = self.proxy.column_filter(column)

        popup = ColumnFilterPopup(
            column=column,
            title=COLUMNS[column][1],
            values=values,
            selected=selected,
            text=text,
            truncated=truncated,
            palette=self.palette_,
            parent=self,
        )
        popup.applied.connect(self._apply_column_filter)
        popup.sortRequested.connect(self.table.sortByColumn)
        popup.adjustSize()

        # On garde le panneau à l'intérieur de l'écran quand la colonne est
        # proche du bord droit.
        screen = self.screen().availableGeometry()
        x = min(position.x(), screen.right() - popup.width() - 8)
        y = min(position.y(), screen.bottom() - popup.height() - 8)
        popup.move(max(screen.left() + 8, x), max(screen.top() + 8, y))
        popup.show()

    def _apply_column_filter(self, column: int, values, text: str) -> None:
        self.proxy.set_column_filter(column, values, text)
        self._sync_filter_indicators()
        self._update_counts()

    def _sync_filter_indicators(self) -> None:
        self.header.set_filtered_columns(self.proxy.filtered_columns())

    def _highlight_menu(self) -> QMenu:
        """Sous-menu de filtrage par règle de surlignage.

        Le surlignage n'étant pas une colonne, il n'a pas d'entonnoir : ce menu
        est le seul endroit d'où l'on peut n'afficher, par exemple, que les
        lignes reconnues comme « Communication perdue ».
        """
        menu = QMenu("Surlignage", self)
        current = self.proxy.current_rule()

        entries = [("Tous les surlignages", RULE_ANY)]
        entries += [
            (rule.name or f"Règle {index + 1}", index)
            for index, rule in enumerate(self.highlighter.active_rules)
        ]
        entries.append(("Lignes non surlignées", RULE_NONE))

        for label, value in entries:
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(value == current)
            action.triggered.connect(lambda _=False, v=value: self._apply_rule_filter(v))
        return menu

    def _apply_rule_filter(self, rule: int) -> None:
        self.proxy.set_rule(rule)
        self._update_counts()

    # =========================================================  affichage

    def _selection_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if not current.isValid():
            self.detail.show_entry(None)
            return
        self.detail.show_entry(current.data(ENTRY_ROLE))

    def _set_autoscroll(self, enabled: bool) -> None:
        self.settings.autoscroll = enabled
        self.settings.save()
        if enabled:
            self._scroll_to_bottom()

    def _maybe_autoscroll(self, *_args) -> None:
        if not self.action_autoscroll.isChecked():
            return
        scrollbar = self.table.verticalScrollBar()
        # On ne force le défilement que si l'utilisateur regardait déjà le bas :
        # sinon on lui arracherait la vue pendant qu'il lit une ligne ancienne.
        if scrollbar.maximum() - scrollbar.value() <= AUTOSCROLL_TOLERANCE:
            QTimer.singleShot(0, self._scroll_to_bottom)

    def _scroll_to_bottom(self) -> None:
        self.table.scrollToBottom()

    def _update_counts(self, *_args) -> None:
        total = self.model.rowCount()
        visible = self.proxy.rowCount()
        counts = self.model.level_counts()
        text = (
            f"{visible:n} / {total:n} lignes"
            f"     ·     {counts.get('ERROR', 0):n} erreurs"
            f"     ·     {counts.get('WARNING', 0):n} avertissements"
        )
        self.status_counts.setText(text)

    def _update_actions(self) -> None:
        connected = self.current_ipc is not None
        for action in (self.action_pause, self.action_export_xlsx, self.action_export_csv):
            action.setEnabled(connected)
        self.action_archives.setEnabled(connected and not self._archives_loaded)

    def _toggle_pause(self, paused: bool) -> None:
        if self.watcher is not None:
            self.watcher.set_paused(paused)
        self.action_pause.setText("Reprendre le suivi" if paused else "Suspendre le suivi")
        self.status_live.setText(self._live_label())

    # =========================================================  menu contextuel

    def _show_context_menu(self, position) -> None:
        index = self.table.indexAt(position)
        if not index.isValid():
            return
        entry = index.data(ENTRY_ROLE)

        menu = QMenu(self)
        menu.addAction("Copier la ligne complète", lambda: self._copy_to_clipboard(entry.raw))
        menu.addAction("Copier le message", lambda: self._copy_to_clipboard(entry.message_multiline))
        if entry.node_path:
            menu.addAction(
                "Copier le chemin du nœud", lambda: self._copy_to_clipboard(entry.node_path)
            )
        menu.addAction("Copier la sélection", self._copy_selection)
        menu.addSeparator()
        if entry.source:
            menu.addAction(
                f"Ne montrer que la source « {entry.source} »",
                lambda: self._filter_on_source(entry.source),
            )
        menu.addAction(
            f"Ne montrer que le niveau « {level_label(entry.level)} »",
            lambda: self._filter_on_level(entry.level),
        )
        menu.addSeparator()
        menu.addMenu(self._highlight_menu())
        columns = self._column_menu()
        columns.setTitle("Colonnes affichées")
        menu.addMenu(columns)
        menu.addAction("Réinitialiser les filtres", self.reset_filters)
        menu.exec(self.table.viewport().mapToGlobal(position))

    def _filter_on_source(self, source: str) -> None:
        """Restreint la colonne Source à cette seule valeur.

        Passe par le filtre de colonne, donc l'entonnoir de « Source » se
        marque comme actif et le filtre s'y retire de la même façon.
        """
        self._apply_column_filter(COLUMN_SOURCE, {source}, "")

    def _filter_on_level(self, level: str) -> None:
        for name, check in self.level_checks.items():
            check.setChecked(name == level)

    @staticmethod
    def _copy_to_clipboard(text: str) -> None:
        QGuiApplication.clipboard().setText(text)

    def _copy_selection(self) -> None:
        """Copie les lignes sélectionnées en colonnes séparées par des tabulations,
        directement collables dans Excel."""
        rows = sorted({index.row() for index in self.table.selectionModel().selectedIndexes()})
        if not rows:
            return
        lines = ["\t".join(title for _key, title, _width in COLUMNS)]
        for row in rows:
            values = []
            for column in range(len(COLUMNS)):
                value = self.proxy.index(row, column).data(Qt.ItemDataRole.DisplayRole)
                values.append("" if value is None else str(value))
            lines.append("\t".join(values))
        self._copy_to_clipboard("\n".join(lines))
        self.notify(f"{len(rows)} ligne(s) copiée(s).", 4000)

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.StandardKey.Copy) and self.table.hasFocus():
            self._copy_selection()
            return
        if event.matches(QKeySequence.StandardKey.Find):
            self.search_edit.setFocus()
            self.search_edit.selectAll()
            return
        super().keyPressEvent(event)

    # =========================================================  export

    def export_log(self, as_csv: bool = False) -> None:
        entries = self.proxy.visible_entries()
        if not entries:
            QMessageBox.information(
                self, "Export", "Aucune ligne à exporter avec les filtres actuels."
            )
            return

        suggested = self._suggested_export_name("csv" if as_csv else "xlsx")
        if as_csv:
            caption, filters = "Exporter en CSV", "Fichier CSV (*.csv)"
        else:
            caption, filters = "Exporter en Excel", "Classeur Excel (*.xlsx)"

        path, _ = QFileDialog.getSaveFileName(self, caption, suggested, filters)
        if not path:
            return

        rule_names = {
            index: rule.name for index, rule in enumerate(self.highlighter.active_rules)
        }
        context = export.ExportContext(
            host=self.current_ipc.host if self.current_ipc else "",
            ipc_name=self.current_ipc.netbios_name if self.current_ipc else "",
            project=self.current_ipc.project if self.current_ipc else "",
            source_path=self.current_path,
            filter_summary=self.proxy.summary(rule_names),
            sort_summary=self.proxy.sort_summary(),
        )

        self._export_progress = QProgressDialog(
            "Écriture du fichier…", "Annuler", 0, len(entries), self
        )
        self._export_progress.setWindowTitle(caption)
        self._export_progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._export_progress.setMinimumDuration(400)
        self._export_progress.setAutoClose(True)

        self.export_worker = ExportWorker(
            path, entries, self.highlighter, context, as_csv=as_csv, parent=self
        )
        self.export_worker.progressed.connect(self._on_export_progress)
        self.export_worker.finishedExport.connect(self._on_export_finished)
        self.export_worker.start()

    def _suggested_export_name(self, extension: str) -> str:
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        if self.current_ipc is not None:
            name = self.current_ipc.netbios_name or self.current_ipc.host
        else:
            name = "journal"
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
        return os.path.join(
            os.path.expanduser("~/Documents"), f"FTOptix_{safe}_{stamp}.{extension}"
        )

    def _on_export_progress(self, written: int, total: int) -> None:
        if self._export_progress is not None:
            self._export_progress.setMaximum(total)
            self._export_progress.setValue(written)

    def _on_export_finished(self, path: str, error: str) -> None:
        if self._export_progress is not None:
            self._export_progress.close()
            self._export_progress = None
        self.export_worker = None

        if error:
            QMessageBox.critical(
                self, "Export",
                "L'écriture du fichier a échoué :\n\n"
                f"{error}\n\n"
                "Si le fichier est déjà ouvert dans Excel, fermez-le puis réessayez.",
            )
            return

        box = QMessageBox(self)
        box.setWindowTitle("Export terminé")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(f"Fichier écrit :\n{path}")
        open_button = box.addButton("Ouvrir", QMessageBox.ButtonRole.AcceptRole)
        folder_button = box.addButton("Afficher le dossier", QMessageBox.ButtonRole.ActionRole)
        box.addButton("Fermer", QMessageBox.ButtonRole.RejectRole)
        box.exec()

        if box.clickedButton() is open_button:
            export.open_in_default_app(path)
        elif box.clickedButton() is folder_button:
            os.startfile(os.path.dirname(path))

    # =========================================================  paramètres

    def open_settings(self) -> bool:
        """Ouvre les paramètres. Renvoie vrai si des réglages ont été enregistrés."""
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() != SettingsDialog.DialogCode.Accepted:
            return False

        previous_theme = self.settings.theme
        previous_path = self.settings.log_relative_path()

        self.settings = dialog.result_settings()
        self.settings.save()

        self.highlighter.set_rules(self.settings.highlight_rules)
        self.model.refresh_highlighting()
        self.model.set_max_rows(self.settings.max_rows)

        self.action_autoscroll.setChecked(self.settings.autoscroll)
        if self.watcher is not None:
            self.watcher.set_interval(self.settings.poll_interval_ms)

        if self.settings.theme != previous_theme:
            self.themeChanged.emit(self.settings.theme)

        if self.settings.log_relative_path() != previous_path and self.current_ipc is not None:
            # Le chemin du journal a changé : on relit depuis le nouveau fichier.
            self.connect_to(self.current_ipc)

        return True

    # =========================================================  cycle de vie

    def closeEvent(self, event) -> None:
        self._health_timer.stop()
        self._stop_watcher()
        self.settings.save()
        self._shutdown_threads()
        super().closeEvent(event)

    def _shutdown_threads(self) -> None:
        """Arrête les fils restants sans laisser la fermeture s'éterniser.

        Un export est laissé aller à son terme : il écrit un fichier, et
        l'interrompre livrerait un classeur tronqué. Les fils de lecture, eux,
        ne font que lire ; si l'un reste suspendu sur un partage devenu muet,
        on le coupe plutôt que de retenir la fenêtre indéfiniment.
        """
        if self.export_worker is not None and self.export_worker.isRunning():
            self.export_worker.wait(10000)

        readers = [t for t in (self.archive_loader, self._probe_worker, *self._retiring)
                   if t is not None]
        for thread in readers:
            thread.requestInterruption()
        for thread in readers:
            if thread.isRunning() and not thread.wait(1200):
                thread.terminate()
                thread.wait(300)
