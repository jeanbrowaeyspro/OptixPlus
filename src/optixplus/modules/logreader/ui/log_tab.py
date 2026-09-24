"""Onglet du Lecteur de logs : l'affichage d'une session (tableau, filtres, détail, état).

Reprend le corps de la fenêtre de pyFTOLogReader. Les données et les fils vivent dans la
session (``session.LogSession``) : l'onglet n'en est qu'une vue, que l'on peut détruire
et recréer sans rien perdre (changement de langue). Les noms publics (``model``,
``proxy``, ``connect_to``, ``status_live``…) sont ceux de l'ancienne fenêtre, ce qui
garde valables les scripts de test d'origine.
"""

from __future__ import annotations

import os
from datetime import datetime

from PySide6.QtCore import QByteArray, QDateTime, QModelIndex, QSize, Qt, QTime, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ....common import theme as common_theme
from ....common.i18n import tr, tr_n
from ....common.widgets import ElidedLabel, FlowLayout, scrollbar_below_header
from ..core import export
from ..core.config import Settings
from ..core.discovery import Ipc
from ..core.logparser import KNOWN_LEVELS
from ..session import LogSession
from ..workers import ExportWorker
from .connect_dialog import ConnectDialog
from .datetime_range import DateTimeField
from .detail_panel import DetailPanel
from .filter_header import MAX_DISTINCT_VALUES, ColumnFilterPopup, FilterHeaderView
from .log_filter import RULE_ANY, RULE_NONE
from .log_model import COLUMN_LINE, COLUMN_MESSAGE, COLUMN_SOURCE, ENTRY_ROLE, column_titles, columns, level_label
from .status_indicator import STATE_OFFLINE, state_label

#: Marge en pixels sous laquelle on considère que l'utilisateur regarde le bas du
#: tableau et souhaite donc continuer à suivre les nouvelles lignes.
AUTOSCROLL_TOLERANCE = 48
#: Rafraîchissement du voyant. Le minuteur ne fait aucune entrée-sortie (il lit un
#: flottant protégé par un verrou) et ne tourne que tant qu'un suivi est actif.
HEALTH_INTERVAL_MS = 400
#: Largeur minimale de la zone de recherche avant de passer les niveaux à la ligne.
SEARCH_MIN_WIDTH = 220


class _FilterBar(QWidget):
    """Recherche, niveaux et boutons sur une ligne ; les niveaux passent dessous si la place manque.

    Deux onglets côte à côte doivent tenir dans une fenêtre ordinaire : la barre ne
    doit pas imposer la largeur d'une ligne complète.
    """

    def __init__(self, search: QWidget, levels: QWidget, tail: list[QWidget]) -> None:
        super().__init__()
        self._search, self._levels, self._tail = search, levels, tail
        search.setMinimumWidth(SEARCH_MIN_WIDTH)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)
        outer.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self._row = QHBoxLayout()
        self._row.setSpacing(8)
        self._row.addWidget(search, 3)
        self._row.addWidget(levels)
        for widget in tail:
            self._row.addWidget(widget)
        self._second = QHBoxLayout()
        self._second.setSpacing(8)
        outer.addLayout(self._row)
        outer.addLayout(self._second)
        self._wide = True

    def _tail_width(self) -> int:
        return sum(w.sizeHint().width() for w in self._tail) + 8 * len(self._tail)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (API Qt)
        width = max(SEARCH_MIN_WIDTH + self._tail_width(), self._levels.sizeHint().width())
        return QSize(width, super().minimumSizeHint().height())

    def resizeEvent(self, event) -> None:  # noqa: N802 (API Qt)
        super().resizeEvent(event)
        wide = self.width() >= SEARCH_MIN_WIDTH + self._levels.sizeHint().width() + 8 + self._tail_width()
        if wide == self._wide:
            return
        self._wide = wide
        if wide:
            self._second.removeWidget(self._levels)
            while self._second.count():  # l'espace extensible : la seconde ligne disparaît
                self._second.takeAt(0)
            self._row.insertWidget(1, self._levels)
        else:
            self._row.removeWidget(self._levels)
            self._second.addWidget(self._levels)
            self._second.addStretch(1)
        self.updateGeometry()

    @property
    def wide(self) -> bool:
        return self._wide


class LogTab(QWidget):
    """Vue d'une session de lecture."""

    # État de connexion changé (``connection_state``) : la pastille de l'onglet suit.
    connectionStateChanged = Signal()

    def __init__(self, session: LogSession | Settings, palette=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        if isinstance(session, Settings):  # commodité (scripts de test) : session propre
            session = LogSession(session, self)
        self.session = session
        self.palette_ = palette or common_theme.current()
        self.export_worker: ExportWorker | None = None
        self._export_progress: QProgressDialog | None = None
        self._suspend_filter_signals = False
        self.autoscroll = session.settings.autoscroll
        self.connection_state = STATE_OFFLINE
        self.connection_detail = ""

        self._build_body()
        self._build_status_bar()
        self._apply_palette(self.palette_)

        self._health_timer = QTimer(self)
        self._health_timer.setInterval(HEALTH_INTERVAL_MS)
        self._health_timer.timeout.connect(self._refresh_connection_state)
        self._notice_timer = QTimer(self)
        self._notice_timer.setSingleShot(True)
        self._notice_timer.timeout.connect(lambda: self.status_notice.setText(""))

        session.loaded.connect(self._on_initial_loaded)
        session.liveChanged.connect(self._on_live_changed)
        session.identityChanged.connect(self._update_identity)
        session.notice.connect(self.notify)
        session.archivesFinished.connect(self._on_archives_loaded)
        common_theme.follow(self, self.apply_theme)
        self._update_identity()
        self._on_live_changed()
        self._update_counts()

    # ================================================== accès (noms de l'ancienne fenêtre)
    @property
    def settings(self) -> Settings:
        return self.session.settings

    @property
    def model(self):
        return self.session.model

    @property
    def proxy(self):
        return self.session.proxy

    @property
    def highlighter(self):
        return self.session.highlighter

    @property
    def watcher(self):
        return self.session.watcher

    @property
    def current_ipc(self) -> Ipc | None:
        return self.session.ipc

    @property
    def current_path(self) -> str:
        return self.session.path

    def statusBar(self) -> QStatusBar:  # noqa: N802 (nom de l'ancienne fenêtre)
        return self._status_bar

    # ======================================================================= construction
    def _build_body(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 0)
        layout.setSpacing(8)
        layout.addWidget(self._build_filter_bar())
        layout.addWidget(self._build_period_bar())

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        self.table = QTableView()
        scrollbar_below_header(self.table)
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
        # La dernière colonne occupe tout ce qui reste : son bord droit est toujours
        # collé au bord du tableau, quelle que soit la largeur des autres.
        header.setStretchLastSection(True)
        for position, (_key, _title, width) in enumerate(columns()):
            header.resizeSection(position, width)
        header.setSectionResizeMode(COLUMN_MESSAGE, QHeaderView.ResizeMode.Interactive)
        header.filterRequested.connect(self._open_column_filter)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._show_column_menu)
        self.header = header
        self._restore_hidden_columns()
        # Tri chronologique croissant : la ligne qui arrive s'affiche tout en bas.
        self.table.sortByColumn(COLUMN_LINE, Qt.SortOrder.AscendingOrder)
        splitter.addWidget(self.table)

        self.detail = DetailPanel(self.palette_)
        detail_container = QWidget()
        detail_layout = QVBoxLayout(detail_container)
        detail_layout.setContentsMargins(2, 6, 2, 2)
        detail_layout.addWidget(self.detail)
        splitter.addWidget(detail_container)
        # Tout l'espace gagné va au tableau, le détail garde sa hauteur.
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        # Le chemin du nœud est dans l'en-tête du détail : une ligne de moins, rendue au tableau.
        detail_container.setMinimumHeight(124)
        splitter.setSizes([666, 174])
        self.splitter = splitter
        layout.addWidget(splitter, 1)

        self.table.selectionModel().currentRowChanged.connect(self._selection_changed)
        self.model.countChanged.connect(self._update_counts)
        self.proxy.rowsInserted.connect(self._maybe_autoscroll)
        self.proxy.modelReset.connect(self._update_counts)
        self.proxy.rowsInserted.connect(self._update_counts)
        self.proxy.rowsRemoved.connect(self._update_counts)

    def _build_filter_bar(self) -> QWidget:
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(tr("Search…  (several words = all conditions must be met)"))
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._search_changed)

        levels = QWidget()
        levels_layout = QHBoxLayout(levels)
        levels_layout.setContentsMargins(0, 0, 0, 0)
        levels_layout.setSpacing(8)
        self.level_checks: dict[str, QCheckBox] = {}
        for level in KNOWN_LEVELS:
            check = QCheckBox(level_label(level))
            check.setChecked(True)
            check.toggled.connect(self._levels_changed)
            self.level_checks[level] = check
            levels_layout.addWidget(check)

        self.period_button = QPushButton(tr("Period…"))
        self.period_button.setCheckable(True)
        self.period_button.toggled.connect(self._toggle_period_bar)
        self.reset_button = QPushButton(tr("Reset"))
        self.reset_button.setToolTip(tr("Clears every filter of this tab: search, levels, period and columns."))
        self.reset_button.clicked.connect(self.reset_filters)
        self.filter_bar = _FilterBar(self.search_edit, levels, [self.period_button, self.reset_button])
        return self.filter_bar

    def _build_period_bar(self) -> QWidget:
        # Trois groupes (« De … », « à … », boutons) qui passent à la ligne quand l'onglet
        # est étroit : deux journaux côte à côte gardent leur barre de période utilisable.
        bar = QWidget()
        layout = FlowLayout(bar)

        def group(*widgets: QWidget) -> QWidget:
            box = QWidget()
            row = QHBoxLayout(box)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            for widget in widgets:
                row.addWidget(widget)
            layout.addWidget(box)
            return box

        self.from_edit = DateTimeField(self.palette_)
        self.from_edit.valueChanged.connect(self._period_changed)
        self.from_edit.dateEdited.connect(lambda date: self._snap_time_to_events(self.from_edit, date, start=True))
        group(QLabel(tr("From")), self.from_edit)
        self.to_edit = DateTimeField(self.palette_)
        self.to_edit.valueChanged.connect(self._period_changed)
        self.to_edit.dateEdited.connect(lambda date: self._snap_time_to_events(self.to_edit, date, start=False))
        group(QLabel(tr("to")), self.to_edit)
        span = QPushButton(tr("Whole range"))
        span.setToolTip(tr("Puts the bounds back on the first and last loaded lines."))
        span.clicked.connect(self._reset_period_bounds)
        last_hour = QPushButton(tr("Last hour"))
        last_hour.setToolTip(tr("Keeps only the last sixty minutes of the log."))
        last_hour.clicked.connect(self._set_last_hour)
        group(span, last_hour)
        self.period_bar = bar
        bar.hide()
        return bar

    def _build_status_bar(self) -> None:
        status = QStatusBar()
        status.setSizeGripEnabled(False)
        self._status_bar = status
        self.layout().addWidget(status)

        # Fond de la page, pas celui d'une barre d'état de fenêtre.
        status.setProperty("embedded", True)
        # L'état de la connexion est la pastille de l'onglet ; la barre garde l'identité.
        self.status_connection = ElidedLabel(tr("No controller connected"))
        # Widgets « permanents » : un message temporaire de la barre masquerait les widgets normaux.
        status.addPermanentWidget(self.status_connection, 3)
        self.status_notice = ElidedLabel("")
        self.status_notice.setProperty("muted", True)
        status.addPermanentWidget(self.status_notice, 2)
        self.status_counts = ElidedLabel("")
        status.addPermanentWidget(self.status_counts)
        self.status_live = ElidedLabel("")
        status.addPermanentWidget(self.status_live)

    def notify(self, text: str, duration_ms: int = 8000) -> None:
        """Mention passagère dans la barre du bas."""
        self.status_notice.setText(text)
        self.status_notice.setToolTip(text)
        self._notice_timer.stop()
        if duration_ms > 0:
            self._notice_timer.start(duration_ms)

    # ========================================================================== apparence
    def _apply_palette(self, palette) -> None:
        self.palette_ = palette
        self.highlighter.set_dark(palette.dark)
        self.detail.set_palette_colors(palette)
        self.header.set_palette_colors(palette)
        for field in (self.from_edit, self.to_edit):
            field.set_palette_colors(palette)
        self.model.refresh_highlighting()
        self._recolor_level_checks()

    def _recolor_level_checks(self) -> None:
        """Chaque case de niveau prend la couleur de son niveau."""
        colours = {"ERROR": self.palette_.error, "WARNING": self.palette_.warning, "INFO": self.palette_.info}
        for level, check in self.level_checks.items():
            colour = colours.get(level, self.palette_.accent)
            check.setStyleSheet(f"QCheckBox::indicator:checked {{ background: {colour}; border-color: {colour}; }}")

    def apply_theme(self, palette) -> None:
        """Nouvelle palette (changement de thème)."""
        self._apply_palette(palette)

    # ========================================================================== connexion
    def choose_ipc(self, auto_connect: bool = False) -> bool:
        """Ouvre la fenêtre de découverte ; vrai si une connexion a eu lieu."""
        dialog = ConnectDialog(self.settings, self.palette_, self, auto_connect=auto_connect)
        if dialog.exec() != ConnectDialog.DialogCode.Accepted or dialog.selected is None:
            return False
        self.connect_to(dialog.selected)
        return True

    def connect_to(self, ipc: Ipc) -> None:
        self.detail.show_entry(None)
        self.session.connect_to(ipc)

    def _stop_watcher(self) -> None:
        self.session.stop_watcher()

    def _update_identity(self) -> None:
        session = self.session
        if session.ipc is None:
            text = tr("Searching for {host}…").format(host=session.probing_host) if session.probing_host else tr(
                "No controller connected"
            )
            self.status_connection.setText(text)
            self.status_connection.setToolTip("")
            return
        ipc = session.ipc
        self.status_connection.setText(f"{ipc.display_name}   ·   {ipc.host}   ·   {session.path}")
        # Le libellé se fait rogner quand une mention occupe la barre : l'infobulle
        # garde le chemin complet à portée de souris.
        self.status_connection.setToolTip("\n".join((ipc.display_name, ipc.host, session.path)))

    def _on_live_changed(self) -> None:
        running = self.session.watcher is not None or self.session.probe_worker is not None
        if running and not self._health_timer.isActive():
            self._health_timer.start()
        elif not running:
            self._health_timer.stop()
        self._refresh_connection_state()

    def _refresh_connection_state(self) -> None:
        state, detail = self.session.connection_state()
        if (state, detail) != (self.connection_state, self.connection_detail):
            self.connection_state, self.connection_detail = state, detail
            self.connectionStateChanged.emit()
        self.status_live.setText(self.session.live_label())

    @property
    def connection_tooltip(self) -> str:
        text = state_label(self.connection_state)
        return "\n".join((text, self.connection_detail)) if self.connection_detail else text

    # ========================================================================== réception
    def _on_initial_loaded(self, result) -> None:
        self._reset_period_bounds()
        self._scroll_to_bottom()
        if result.error:
            self.status_live.setText(tr("Unreadable log"))

    # ========================================================================== historique
    def load_archives(self) -> None:
        if self.session.ipc is None:
            return
        if self.session.archives_loaded:
            QMessageBox.information(self, tr("History"), tr("The archived files are already loaded in the view."))
            return
        if self.session.load_archives():
            self.status_live.setText(tr("Looking for archived files…"))

    def _on_archives_loaded(self, entries: list, error: str) -> None:
        if error and not entries:
            QMessageBox.warning(self, tr("History"), tr("Cannot read: {error}").format(error=error))
        elif not entries:
            QMessageBox.information(
                self, tr("History"), tr("No rotation file was found next to the current log.")
            )
        else:
            self._reset_period_bounds()
            self.notify(
                tr_n(
                    "{n} history line added before the live lines.",
                    "{n} history lines added before the live lines.",
                    len(entries),
                ).format(n=len(entries))
            )
        self.status_live.setText(self.session.live_label())

    # ========================================================================== filtres
    def _snap_time_to_events(self, field, date, start: bool) -> None:
        """Cale l'heure sur le premier (début) ou le dernier (fin) événement du jour choisi."""
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

    def _search_changed(self, text: str) -> None:
        if not self._suspend_filter_signals:
            self.proxy.set_search(text)

    def _levels_changed(self) -> None:
        if self._suspend_filter_signals:
            return
        selected = {level for level, check in self.level_checks.items() if check.isChecked()}
        # Tout cocher revient à ne pas filtrer : un test inutile par ligne évité.
        self.proxy.set_levels(None if len(selected) == len(self.level_checks) else selected)

    def _toggle_period_bar(self, visible: bool) -> None:
        self.period_bar.setVisible(visible)
        if visible:
            self._period_changed()
        else:
            self.proxy.set_period(None, None)

    def _period_changed(self) -> None:
        if self._suspend_filter_signals or not self.period_bar.isVisibleTo(self):
            return
        self.proxy.set_period(self.from_edit.dateTime().toPython(), self.to_edit.dateTime().toPython())
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

    # ------------------------------------------------------------------ colonnes
    def _show_column_menu(self, position) -> None:
        self._column_menu().exec(self.header.mapToGlobal(position))

    def _column_menu(self) -> QMenu:
        menu = QMenu(self)
        title = menu.addAction(tr("Displayed columns"))
        title.setEnabled(False)
        menu.addSeparator()
        for index, label in enumerate(column_titles()):
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(not self.header.isSectionHidden(index))
            action.toggled.connect(lambda checked, i=index: self._set_column_visible(i, checked))
        menu.addSeparator()
        menu.addAction(tr("Show all"), self._show_all_columns)
        return menu

    def _set_column_visible(self, index: int, visible: bool) -> None:
        if not visible and self._visible_column_count() <= 1:
            return  # masquer la dernière colonne laisserait un tableau vide
        if not visible:
            # Un filtre posé sur une colonne masquée serait invisible, donc impossible
            # à retirer : on l'enlève en même temps que la colonne.
            self.proxy.set_column_filter(index, None, "")
            self._sync_filter_indicators()
        self.header.setSectionHidden(index, not visible)
        self._save_hidden_columns()
        self._update_counts()

    def _show_all_columns(self) -> None:
        for index in range(len(columns())):
            self.header.setSectionHidden(index, False)
        self._save_hidden_columns()

    def _visible_column_count(self) -> int:
        return sum(1 for index in range(len(columns())) if not self.header.isSectionHidden(index))

    def _save_hidden_columns(self) -> None:
        self.settings.hidden_columns = [
            columns()[index][0] for index in range(len(columns())) if self.header.isSectionHidden(index)
        ]
        self.settings.save()

    def _restore_hidden_columns(self) -> None:
        keys = {key: index for index, (key, _label, _w) in enumerate(columns())}
        hidden = [keys[key] for key in self.settings.hidden_columns if key in keys]
        if len(hidden) >= len(columns()):
            return  # configuration incohérente : le tableau doit rester exploitable
        for index in hidden:
            self.header.setSectionHidden(index, True)

    # ------------------------------------------------------------------ filtres par colonne
    def _open_column_filter(self, column: int, position) -> None:
        values, truncated = self.model.distinct_values(column, MAX_DISTINCT_VALUES)
        selected, text = self.proxy.column_filter(column)
        popup = ColumnFilterPopup(
            column=column,
            title=column_titles()[column],
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
        """Filtrage par règle de surlignage (le surlignage n'a pas de colonne)."""
        menu = QMenu(tr("Highlighting"), self)
        current = self.proxy.current_rule()
        entries = [(tr("All highlightings"), RULE_ANY)]
        entries += [
            (rule.name or tr("Rule {n}").format(n=index + 1), index)
            for index, rule in enumerate(self.highlighter.active_rules)
        ]
        entries.append((tr("Lines not highlighted"), RULE_NONE))
        for label, value in entries:
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(value == current)
            action.triggered.connect(lambda _=False, v=value: self._apply_rule_filter(v))
        return menu

    def _apply_rule_filter(self, rule: int) -> None:
        self.proxy.set_rule(rule)
        self._update_counts()

    # ========================================================================== affichage
    def _selection_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        self.detail.show_entry(current.data(ENTRY_ROLE) if current.isValid() else None)

    def set_autoscroll(self, enabled: bool) -> None:
        self.autoscroll = enabled
        if enabled:
            self._scroll_to_bottom()

    def _maybe_autoscroll(self, *_args) -> None:
        if not self.autoscroll:
            return
        scrollbar = self.table.verticalScrollBar()
        # On ne suit le bas que si l'utilisateur y était déjà : sinon on lui
        # arracherait la vue pendant qu'il lit une ligne ancienne.
        if scrollbar.maximum() - scrollbar.value() <= AUTOSCROLL_TOLERANCE:
            QTimer.singleShot(0, self._scroll_to_bottom)

    def _scroll_to_bottom(self) -> None:
        self.table.scrollToBottom()

    def _update_counts(self, *_args) -> None:
        total = self.model.rowCount()
        visible = self.proxy.rowCount()
        counts = self.model.level_counts()
        self.status_counts.setText(
            tr("{visible:n} / {total:n} lines     ·     {errors:n} errors     ·     {warnings:n} warnings").format(
                visible=visible, total=total, errors=counts.get("ERROR", 0), warnings=counts.get("WARNING", 0)
            )
        )

    # ========================================================================== menu contextuel
    def _show_context_menu(self, position) -> None:
        index = self.table.indexAt(position)
        if not index.isValid():
            return
        entry = index.data(ENTRY_ROLE)
        menu = QMenu(self)
        menu.addAction(tr("Copy the whole line"), lambda: self._copy_to_clipboard(entry.raw))
        menu.addAction(tr("Copy the message"), lambda: self._copy_to_clipboard(entry.message_multiline))
        if entry.node_path:
            menu.addAction(tr("Copy the node path"), lambda: self._copy_to_clipboard(entry.node_path))
        menu.addAction(tr("Copy the selection"), self._copy_selection)
        menu.addSeparator()
        if entry.source:
            menu.addAction(
                tr("Show only the source “{source}”").format(source=entry.source),
                lambda: self._filter_on_source(entry.source),
            )
        menu.addAction(
            tr("Show only the level “{level}”").format(level=level_label(entry.level)),
            lambda: self._filter_on_level(entry.level),
        )
        menu.addSeparator()
        menu.addMenu(self._highlight_menu())
        column_menu = self._column_menu()
        column_menu.setTitle(tr("Displayed columns"))
        menu.addMenu(column_menu)
        menu.addAction(tr("Reset the filters"), self.reset_filters)
        menu.exec(self.table.viewport().mapToGlobal(position))

    def _filter_on_source(self, source: str) -> None:
        """Restreint la colonne Source à cette valeur (via son entonnoir, qui se marque actif)."""
        self._apply_column_filter(COLUMN_SOURCE, {source}, "")

    def _filter_on_level(self, level: str) -> None:
        for name, check in self.level_checks.items():
            check.setChecked(name == level)

    @staticmethod
    def _copy_to_clipboard(text: str) -> None:
        QGuiApplication.clipboard().setText(text)

    def _copy_selection(self) -> None:
        """Copie les lignes sélectionnées en colonnes séparées par des tabulations (collables dans Excel)."""
        rows = sorted({index.row() for index in self.table.selectionModel().selectedIndexes()})
        if not rows:
            return
        lines = ["\t".join(column_titles())]
        for row in rows:
            values = []
            for column in range(len(columns())):
                value = self.proxy.index(row, column).data(Qt.ItemDataRole.DisplayRole)
                values.append("" if value is None else str(value))
            lines.append("\t".join(values))
        self._copy_to_clipboard("\n".join(lines))
        self.notify(tr_n("{n} line copied.", "{n} lines copied.", len(rows)).format(n=len(rows)), 4000)

    def keyPressEvent(self, event) -> None:  # noqa: N802 (API Qt)
        if event.matches(QKeySequence.StandardKey.Copy) and self.table.hasFocus():
            self._copy_selection()
            return
        if event.matches(QKeySequence.StandardKey.Find):
            self.search_edit.setFocus()
            self.search_edit.selectAll()
            return
        super().keyPressEvent(event)

    # ========================================================================== export
    def export_log(self, as_csv: bool = False) -> None:
        entries = self.proxy.visible_entries()
        if not entries:
            QMessageBox.information(self, tr("Export"), tr("No line to export with the current filters."))
            return
        suggested = self._suggested_export_name("csv" if as_csv else "xlsx")
        if as_csv:
            caption, filters = tr("Export to CSV"), tr("CSV file (*.csv)")
        else:
            caption, filters = tr("Export to Excel"), tr("Excel workbook (*.xlsx)")
        path, _ = QFileDialog.getSaveFileName(self, caption, suggested, filters)
        if not path:
            return
        rule_names = {index: rule.name for index, rule in enumerate(self.highlighter.active_rules)}
        ipc = self.current_ipc
        context = export.ExportContext(
            host=ipc.host if ipc else "",
            ipc_name=ipc.netbios_name if ipc else "",
            project=ipc.project if ipc else "",
            source_path=self.current_path,
            filter_summary=self.proxy.summary(rule_names),
            sort_summary=self.proxy.sort_summary(),
        )
        self._export_progress = QProgressDialog(tr("Writing the file…"), tr("Cancel"), 0, len(entries), self)
        self._export_progress.setWindowTitle(caption)
        self._export_progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._export_progress.setMinimumDuration(400)
        self._export_progress.setAutoClose(True)
        self.export_worker = ExportWorker(path, entries, self.highlighter, context, as_csv=as_csv, parent=self)
        self.export_worker.progressed.connect(self._on_export_progress)
        self.export_worker.finishedExport.connect(self._on_export_finished)
        self.export_worker.start()

    def _suggested_export_name(self, extension: str) -> str:
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        ipc = self.current_ipc
        name = (ipc.netbios_name or ipc.host) if ipc is not None else "journal"
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
        return os.path.join(os.path.expanduser("~/Documents"), f"FTOptix_{safe}_{stamp}.{extension}")

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
                self,
                tr("Export"),
                tr("Writing the file failed:\n\n{error}\n\nIf the file is already open in Excel, close it and try again.").format(
                    error=error
                ),
            )
            return
        box = QMessageBox(self)
        box.setWindowTitle(tr("Export finished"))
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(tr("File written:\n{path}").format(path=path))
        open_button = box.addButton(tr("Open"), QMessageBox.ButtonRole.AcceptRole)
        folder_button = box.addButton(tr("Show the folder"), QMessageBox.ButtonRole.ActionRole)
        box.addButton(tr("Close"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is open_button:
            export.open_in_default_app(path)
        elif box.clickedButton() is folder_button:
            os.startfile(os.path.dirname(path))

    # ========================================================================== cycle de vie
    @property
    def busy(self) -> bool:
        """Vrai pendant un export ou un chargement d'historique (à ne pas interrompre)."""
        return self.export_worker is not None or self.session.busy

    def snapshot(self) -> dict:
        """Affichage courant, pour reconstruire l'onglet à l'identique sur la même session."""
        scrollbar = self.table.verticalScrollBar()
        current = self.table.currentIndex()
        return {
            "search": self.search_edit.text(),
            "levels": {level: check.isChecked() for level, check in self.level_checks.items()},
            "period": self.period_button.isChecked(),
            "from": self.from_edit.dateTime(),
            "to": self.to_edit.dateTime(),
            "header": bytes(self.header.saveState().toBase64().data()),
            "splitter": bytes(self.splitter.saveState().toBase64().data()),
            "at_bottom": scrollbar.maximum() - scrollbar.value() <= AUTOSCROLL_TOLERANCE,
            "scroll": scrollbar.value(),
            "current_row": current.row() if current.isValid() else -1,
            "notice": self.status_notice.text(),
        }

    def restore(self, state: dict) -> None:
        """Réapplique un instantané ; le filtre (proxy) a déjà l'état voulu : pas de refiltrage."""
        self._suspend_filter_signals = True
        self.search_edit.setText(state.get("search", ""))
        for level, checked in state.get("levels", {}).items():
            if level in self.level_checks:
                self.level_checks[level].setChecked(checked)
        self.period_button.blockSignals(True)
        self.period_button.setChecked(bool(state.get("period")))
        self.period_button.blockSignals(False)
        self.period_bar.setVisible(bool(state.get("period")))
        if state.get("from") is not None:
            self.from_edit.setDateTime(state["from"], silent=True)
        if state.get("to") is not None:
            self.to_edit.setDateTime(state["to"], silent=True)
        self._suspend_filter_signals = False
        if state.get("header"):
            self.header.restoreState(QByteArray.fromBase64(state["header"]))
        if state.get("splitter"):
            self.splitter.restoreState(QByteArray.fromBase64(state["splitter"]))
        self._sync_filter_indicators()
        if state.get("current_row", -1) >= 0:
            self.table.setCurrentIndex(self.proxy.index(state["current_row"], 0))
        scrollbar = self.table.verticalScrollBar()
        if state.get("at_bottom", True):
            QTimer.singleShot(0, self._scroll_to_bottom)
        else:
            QTimer.singleShot(0, lambda: scrollbar.setValue(state.get("scroll", 0)))
        if state.get("notice"):
            self.notify(state["notice"])
        self._update_counts()

    def closeEvent(self, event) -> None:  # noqa: N802 (API Qt)
        """Fermeture autonome (scripts de test) : la session s'arrête avec l'onglet."""
        self._health_timer.stop()
        if self.session.parent() is self:
            self.session.shutdown()
        super().closeEvent(event)
