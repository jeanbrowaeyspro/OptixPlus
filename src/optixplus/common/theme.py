"""Thèmes clair, sombre et suivi automatique du thème Windows (base : Log Reader).

La palette et la feuille de style sont communes à tous les outils : aucun module ne
pose de couleur, de police ou de feuille de style globale de son côté. L'accent violet
reprend la couleur de l'icône OptixPlus.

Le mode ``system`` s'appuie sur ``QStyleHints.colorScheme()`` (Qt 6.5+), qui
reflète le réglage « Mode Application » de Windows et émet un signal lorsque
l'utilisateur le change en cours d'exécution. Un repli par lecture du registre
couvre les cas où Qt ne renseigne pas l'information.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPalette

from . import paths, signals
from .i18n import tr

THEME_SYSTEM = "system"
THEME_LIGHT = "light"
THEME_DARK = "dark"

THEMES = (THEME_SYSTEM, THEME_LIGHT, THEME_DARK)


def theme_label(theme: str) -> str:
    """Libellé traduit d'un thème (traduit à l'affichage, pas à l'import)."""
    return {THEME_SYSTEM: tr("System"), THEME_LIGHT: tr("Light"), THEME_DARK: tr("Dark")}.get(theme, theme)


@dataclass(frozen=True)
class Palette:
    """Jeu de couleurs d'un thème."""

    name: str
    dark: bool
    window: str          # fond général de la fenêtre
    surface: str         # fond des panneaux et du tableau
    surface_alt: str     # lignes alternées, en-têtes
    border: str
    text: str
    text_muted: str
    accent: str
    accent_text: str
    selection: str
    selection_text: str
    error: str
    warning: str
    info: str
    success: str
    accent_hover: str


LIGHT = Palette(
    name=THEME_LIGHT,
    dark=False,
    window="#F2F4F7",
    surface="#FFFFFF",
    surface_alt="#F7F9FB",
    border="#DCE1E8",
    text="#161A1F",
    text_muted="#6B7480",
    accent="#7C3AED",
    accent_text="#FFFFFF",
    selection="#E9DDFD",
    selection_text="#2E1065",
    error="#D32F2F",
    warning="#B87A00",
    info="#3A7BD5",
    success="#2E9E5B",
    accent_hover="#6D28D9",
)

DARK = Palette(
    name=THEME_DARK,
    dark=True,
    window="#15171C",
    surface="#1E2127",
    surface_alt="#23272F",
    border="#333944",
    text="#E4E7EC",
    text_muted="#98A2B0",
    accent="#A78BFA",
    accent_text="#1A0B3D",
    selection="#3B2A66",
    selection_text="#F1EAFF",
    error="#F0736C",
    warning="#E2B04A",
    info="#6FA8F5",
    success="#5DC98A",
    accent_hover="#C4B5FD",
)


def system_is_dark() -> bool:
    """Vrai si Windows est réglé sur le thème sombre pour les applications."""
    hints = QGuiApplication.styleHints()
    scheme = getattr(hints, "colorScheme", None)
    if scheme is not None:
        value = scheme()
        if value == Qt.ColorScheme.Dark:
            return True
        if value == Qt.ColorScheme.Light:
            return False

    # Repli : réglage « Mode Application » du registre Windows.
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        with key:
            apps_use_light, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return not bool(apps_use_light)
    except OSError:
        return False


def resolve(theme: str) -> Palette:
    """Convertit un réglage (``system``/``light``/``dark``) en palette concrète."""
    if theme == THEME_DARK:
        return DARK
    if theme == THEME_LIGHT:
        return LIGHT
    return DARK if system_is_dark() else LIGHT


def build_qpalette(palette: Palette) -> QPalette:
    """Palette Qt native, pour que les widgets non stylés restent cohérents."""
    qp = QPalette()
    window, surface, text = QColor(palette.window), QColor(palette.surface), QColor(palette.text)
    muted = QColor(palette.text_muted)

    qp.setColor(QPalette.ColorRole.Window, window)
    qp.setColor(QPalette.ColorRole.WindowText, text)
    qp.setColor(QPalette.ColorRole.Base, surface)
    qp.setColor(QPalette.ColorRole.AlternateBase, QColor(palette.surface_alt))
    qp.setColor(QPalette.ColorRole.Text, text)
    qp.setColor(QPalette.ColorRole.Button, surface)
    qp.setColor(QPalette.ColorRole.ButtonText, text)
    qp.setColor(QPalette.ColorRole.ToolTipBase, surface)
    qp.setColor(QPalette.ColorRole.ToolTipText, text)
    qp.setColor(QPalette.ColorRole.Highlight, QColor(palette.selection))
    qp.setColor(QPalette.ColorRole.HighlightedText, QColor(palette.selection_text))
    qp.setColor(QPalette.ColorRole.Link, QColor(palette.accent))
    qp.setColor(QPalette.ColorRole.PlaceholderText, muted)

    disabled = QPalette.ColorGroup.Disabled
    qp.setColor(disabled, QPalette.ColorRole.Text, muted)
    qp.setColor(disabled, QPalette.ColorRole.ButtonText, muted)
    qp.setColor(disabled, QPalette.ColorRole.WindowText, muted)
    return qp


def build_stylesheet(p: Palette) -> str:
    """Feuille de style de l'application pour la palette donnée."""
    # Attention au format : Qt interprète un hexadécimal à huit chiffres comme
    # #AARRGGBB et non #RRGGBBAA. « #FFFFFF14 » n'est donc pas un blanc à 8 %
    # mais un jaune vif opaque, et « #00000010 » un noir entièrement
    # transparent. On passe par rgba(), qui ne prête pas à confusion.
    mode = "dark" if p.dark else "light"
    qss_icon = lambda name: paths.resource_path("icons", "qss", f"{name}-{mode}.svg").as_posix()  # noqa: E731
    arrow_down, arrow_up, check = qss_icon("arrow-down"), qss_icon("arrow-up"), qss_icon("check")
    dot, chevrons = qss_icon("dot"), qss_icon("chevrons")
    close_icon, detach_icon = qss_icon("close"), qss_icon("detach")
    hover = "rgba(255, 255, 255, 0.09)" if p.dark else "rgba(0, 0, 0, 0.06)"
    pressed = "rgba(255, 255, 255, 0.16)" if p.dark else "rgba(0, 0, 0, 0.11)"
    return f"""
    QWidget {{
        color: {p.text};
        font-family: "Segoe UI", "Inter", sans-serif;
        font-size: 13px;
    }}
    QMainWindow, QDialog {{ background: {p.window}; }}

    QToolBar {{
        background: {p.surface};
        border: none;
        border-bottom: 1px solid {p.border};
        padding: 6px 8px;
        spacing: 6px;
    }}
    QToolBar QToolButton {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: 6px;
        padding: 5px 10px;
    }}
    QToolBar QToolButton:hover {{ background: {hover}; border-color: {p.border}; }}
    QToolBar QToolButton:pressed {{ background: {pressed}; }}
    QToolBar QToolButton:checked {{
        background: {p.selection};
        color: {p.selection_text};
        border-color: {p.accent};
    }}
    QToolBar QToolButton:disabled {{ color: {p.text_muted}; }}
    QToolBar QToolButton:disabled:hover {{
        background: transparent;
        border-color: transparent;
    }}
    /* Bouton « » » des actions qui ne tiennent pas dans la barre : bien visible. */
    QToolBar QToolBarExtension {{
        padding: 0px;
        qproperty-icon: url({chevrons});
    }}
    QToolBar::separator {{
        background: {p.border};
        width: 1px;
        margin: 4px 6px;
    }}

    /* Onglets détachables (Qt Advanced Docking System, Lecteur de logs). Le style par
       défaut de QtAds est retiré du gestionnaire : ces règles s'appliquent aussi aux
       fenêtres flottantes. */
    ads--CDockContainerWidget, ads--CDockAreaWidget {{ background: {p.window}; }}
    ads--CDockContainerWidget > QSplitter {{ padding: 1px 0; }}
    ads--CDockContainerWidget ads--CDockSplitter::handle {{ background: {p.border}; }}
    ads--CDockAreaTitleBar {{
        background: {p.surface};
        border-bottom: 1px solid {p.border};
    }}
    ads--CDockWidgetTab {{
        background: {p.surface};
        border: none;
        border-right: 1px solid {p.border};
        border-bottom: 2px solid transparent;
        padding: 0 2px;
    }}
    ads--CDockWidgetTab:hover {{ background: {hover}; }}
    ads--CDockWidgetTab[activeTab="true"] {{
        background: {p.window};
        border-bottom: 2px solid {p.text_muted};
    }}
    ads--CDockWidgetTab[activeTab="true"][focused="true"] {{ border-bottom: 2px solid {p.accent}; }}
    ads--CDockWidgetTab QLabel {{ color: {p.text_muted}; background: transparent; }}
    ads--CDockWidgetTab[activeTab="true"] QLabel {{ color: {p.text}; }}
    ads--CDockWidget {{ background: {p.window}; border: none; }}
    QScrollArea#dockWidgetScrollArea {{ padding: 0px; border: none; }}
    ads--CTitleBarButton, #tabCloseButton {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: 4px;
        padding: 2px;
        qproperty-iconSize: 12px;
    }}
    ads--CTitleBarButton:hover, #tabCloseButton:hover {{ background: {hover}; border-color: {p.border}; }}
    ads--CTitleBarButton:pressed, #tabCloseButton:pressed {{ background: {pressed}; }}
    #tabCloseButton, #dockAreaCloseButton {{ qproperty-icon: url({close_icon}); }}
    #detachGroupButton {{ qproperty-icon: url({detach_icon}); }}
    #tabsMenuButton {{ qproperty-icon: url({arrow_down}); }}
    #tabsMenuButton::menu-indicator {{ image: none; }}

    QStatusBar {{
        background: {p.surface};
        border-top: 1px solid {p.border};
        color: {p.text_muted};
    }}
    QStatusBar::item {{ border: none; }}

    /* Même hauteur utile que les boutons : sans cette contrainte, une liste
       déroulante et un bouton placés sur la même ligne ne s'alignent pas. */
    QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTextEdit, QAbstractSpinBox {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: 6px;
        padding: 5px 8px;
        min-height: 19px;
        selection-background-color: {p.selection};
        selection-color: {p.selection_text};
    }}
    QPlainTextEdit, QTextEdit {{ min-height: 0; }}

    /* Le bouton déroulant reste à l'intérieur du cadre, coins droits
       arrondis, pour ne pas recouvrir la bordure du champ. */
    QComboBox::drop-down {{
        subcontrol-origin: border;
        subcontrol-position: center right;
        width: 22px;
        margin: 1px 1px 1px 0;
        border: none;
        border-top-right-radius: 5px;
        border-bottom-right-radius: 5px;
        background: transparent;
    }}
    QComboBox {{ padding-right: 26px; }}
    QComboBox::down-arrow {{ image: url({arrow_down}); width: 10px; height: 10px; }}

    /* Flèches des compteurs : sans ces règles, le remplissage général les masque. */
    QAbstractSpinBox {{ padding-right: 22px; }}
    QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
        subcontrol-origin: border;
        width: 20px;
        border: none;
        background: transparent;
    }}
    QAbstractSpinBox::up-button {{ subcontrol-position: top right; margin: 2px 2px 0 0; }}
    QAbstractSpinBox::down-button {{ subcontrol-position: bottom right; margin: 0 2px 2px 0; }}
    QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{
        background: {hover};
        border-radius: 4px;
    }}
    QAbstractSpinBox::up-arrow {{ image: url({arrow_up}); width: 9px; height: 9px; }}
    QAbstractSpinBox::down-arrow {{ image: url({arrow_down}); width: 9px; height: 9px; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus,
    QPlainTextEdit:focus, QTextEdit:focus {{ border-color: {p.accent}; }}
    QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{
        background: {p.surface_alt};
        color: {p.text_muted};
    }}
    QComboBox QAbstractItemView {{
        background: {p.surface};
        border: 1px solid {p.border};
        selection-background-color: {p.selection};
        selection-color: {p.selection_text};
        outline: none;
    }}

    QPushButton {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: 6px;
        padding: 5px 14px;
        min-height: 19px;
    }}
    QPushButton:hover {{ background: {hover}; }}
    QPushButton:pressed {{ background: {pressed}; }}
    QPushButton:disabled, QPushButton:disabled:hover {{
        color: {p.text_muted};
        background: {p.surface_alt};
        border-color: {p.border};
    }}
    QPushButton[accent="true"] {{
        background: {p.accent};
        color: {p.accent_text};
        border-color: {p.accent};
        font-weight: 600;
    }}
    QPushButton[accent="true"]:hover {{ background: {p.accent_hover}; border-color: {p.accent_hover}; }}
    QPushButton[accent="true"]:disabled {{
        background: {p.surface_alt};
        color: {p.text_muted};
        border-color: {p.border};
    }}

    QTableView, QTreeView, QListView {{
        background: {p.surface};
        alternate-background-color: {p.surface_alt};
        border: 1px solid {p.border};
        border-radius: 8px;
        gridline-color: {p.border};
        selection-background-color: {p.selection};
        selection-color: {p.selection_text};
        outline: none;
    }}
    QTableView::item {{ padding: 0 6px; }}
    QHeaderView {{ background: transparent; }}
    /* La marge droite est réservée à l'entonnoir de filtre et à l'indicateur
       de tri, dessinés par FilterHeaderView : sans elle, le titre de la
       colonne passerait dessous. */
    QHeaderView::section {{
        background: {p.surface_alt};
        color: {p.text_muted};
        border: none;
        border-right: 1px solid {p.border};
        border-bottom: 1px solid {p.border};
        padding: 7px 36px 7px 10px;
        font-weight: 600;
    }}
    QHeaderView::section:hover {{ color: {p.text}; }}
    QTableView QTableCornerButton::section {{
        background: {p.surface_alt};
        border: none;
        border-bottom: 1px solid {p.border};
    }}

    QGroupBox {{
        border: 1px solid {p.border};
        border-radius: 8px;
        margin-top: 14px;
        padding-top: 10px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 5px;
        color: {p.text_muted};
        font-weight: 600;
    }}

    QTabWidget::pane {{
        border: 1px solid {p.border};
        border-radius: 8px;
        top: -1px;
    }}
    QTabBar::tab {{
        background: transparent;
        color: {p.text_muted};
        border: 1px solid transparent;
        border-top-left-radius: 7px;
        border-top-right-radius: 7px;
        padding: 7px 16px;
    }}
    QTabBar::tab:hover {{ color: {p.text}; }}
    QTabBar::tab:selected {{
        background: {p.surface};
        color: {p.text};
        border-color: {p.border};
        border-bottom-color: {p.surface};
        font-weight: 600;
    }}

    QSplitter::handle {{ background: {p.border}; }}
    QSplitter::handle:horizontal {{ width: 1px; }}
    QSplitter::handle:vertical {{ height: 1px; }}
    QSplitter[cards="true"]::handle {{ background: transparent; }}

    QScrollBar:vertical {{
        background: transparent; width: 11px; margin: 2px;
    }}
    QScrollBar:horizontal {{
        background: transparent; height: 11px; margin: 2px;
    }}
    QScrollBar::handle {{ background: {p.border}; border-radius: 5px; }}
    QScrollBar::handle:vertical {{ min-height: 30px; }}
    QScrollBar::handle:horizontal {{ min-width: 30px; }}
    QScrollBar::handle:hover {{ background: {p.text_muted}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    QCheckBox, QRadioButton {{ spacing: 7px; }}
    QCheckBox::indicator, QRadioButton::indicator {{
        width: 15px; height: 15px;
        border: 1px solid {p.border};
        background: {p.surface};
    }}
    QCheckBox::indicator {{ border-radius: 4px; }}
    QRadioButton::indicator {{ border-radius: 8px; }}
    QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
        background: {p.accent};
        border-color: {p.accent};
    }}
    QCheckBox::indicator:checked {{ image: url({check}); }}

    /* Les cases des vues tabulaires ne sont pas des QCheckBox : sans cette
       règle, l'état coché s'affiche comme une coche nue, sans cadre, ce qui
       jure avec les cases voisines. */
    QTableWidget::indicator, QTableView::indicator, QTreeView::indicator {{
        width: 15px; height: 15px;
        border: 1px solid {p.border};
        border-radius: 4px;
        background: {p.surface};
    }}
    QTableWidget::indicator:checked, QTableView::indicator:checked,
    QTreeView::indicator:checked {{
        background: {p.accent};
        border-color: {p.accent};
        image: url({check});
    }}

    QToolTip {{
        background: {p.surface};
        color: {p.text};
        border: 1px solid {p.border};
        padding: 5px 7px;
    }}

    QMenu {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: 8px;
        padding: 5px;
    }}
    /* Marge à gauche de l'icône : sans elle, l'icône colle au bord du surlignage. */
    QMenu::item {{ padding: 6px 24px 6px 32px; border-radius: 5px; }}
    QMenu::icon {{ padding-left: 10px; }}
    /* Cases et pastilles des entrées à cocher : visibles aussi à l'état décoché. */
    QMenu::indicator {{ width: 14px; height: 14px; left: 10px; }}
    QMenu::indicator:non-exclusive:unchecked {{
        border: 1px solid {p.text_muted}; border-radius: 4px; background: {p.surface};
    }}
    QMenu::indicator:non-exclusive:checked {{
        border: 1px solid {p.accent}; border-radius: 4px; background: {p.accent}; image: url({check});
    }}
    QMenu::indicator:exclusive:unchecked {{
        border: 1px solid {p.text_muted}; border-radius: 7px; background: {p.surface};
    }}
    QMenu::indicator:exclusive:checked {{
        border: 1px solid {p.accent}; border-radius: 7px; background: {p.accent}; image: url({dot});
    }}
    QMenu::item:selected {{ background: {p.selection}; color: {p.selection_text}; }}
    QMenu::separator {{ height: 1px; background: {p.border}; margin: 4px 8px; }}

    QProgressBar {{
        background: {p.surface_alt};
        border: 1px solid {p.border};
        border-radius: 6px;
        height: 6px;
        text-align: center;
    }}
    QProgressBar::chunk {{ background: {p.accent}; border-radius: 5px; }}

    QLabel[muted="true"] {{ color: {p.text_muted}; }}
    QLabel[heading="true"] {{ font-size: 15px; font-weight: 600; }}
    QLabel[title="true"] {{ font-size: 20px; font-weight: 600; }}

    /* Barre latérale de navigation. */
    QFrame#sidebar {{
        background: {p.surface};
        border: none;
        border-right: 1px solid {p.border};
    }}
    QFrame#sidebar QToolButton {{
        background: transparent;
        color: {p.text_muted};
        border: none;
        border-left: 3px solid transparent;
        border-radius: 0;
        padding: 8px 2px 6px 2px;
        font-size: 11px;
    }}
    QFrame#sidebar QToolButton:hover {{ background: {hover}; color: {p.text}; }}
    QFrame#sidebar QToolButton:checked {{
        background: {p.selection};
        color: {p.selection_text};
        border-left-color: {p.accent};
        font-weight: 600;
    }}

    /* Tuiles et cartes de la page d'accueil. */
    QFrame[card="true"] {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: 10px;
    }}
    QFrame[card="true"] QLabel {{ background: transparent; border: none; }}
    QToolButton[link="true"] {{
        background: transparent;
        border: none;
        color: {p.accent};
        padding: 2px 0;
        text-align: left;
    }}
    QToolButton[link="true"]:hover {{ text-decoration: underline; }}
    QFrame[tile="true"] {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: 10px;
    }}
    QFrame[tile="true"]:hover, QFrame[tile="true"]:focus {{
        border-color: {p.accent};
        background: {p.surface_alt};
    }}
    QFrame[tile="true"] QLabel {{ background: transparent; border: none; }}

    QDockWidget {{ color: {p.text}; }}
    QDockWidget::title {{
        background: {p.surface_alt};
        padding: 5px 8px;
        border-bottom: 1px solid {p.border};
    }}
    QMenuBar {{ background: {p.window}; }}
    QMenuBar::item {{ padding: 5px 10px; background: transparent; border-radius: 5px; }}
    QMenuBar::item:selected {{ background: {hover}; }}
    """


def popup_stylesheet(name: str, p: Palette) -> str:
    """Feuille de style d'un panneau surgissant, ancrée sur son nom d'objet.

    Un sélecteur ``QFrame`` nu s'appliquerait aussi aux ``QLabel`` que le
    panneau contient, ``QLabel`` héritant de ``QFrame`` : les intitulés se
    retrouveraient entourés d'un cadre et passeraient pour des champs de
    saisie. Toutes les règles sont donc préfixées par ``QFrame#<nom>``.
    """
    return f"""
    QFrame#{name} {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: 8px;
    }}
    QFrame#{name} QLabel {{
        border: none;
        background: transparent;
        padding: 0;
    }}
    /* Les cases des grilles d'heures et de minutes sont trop étroites pour le
       remplissage général des boutons, qui y rognerait les deux chiffres.

       La taille minimale doit être répétée ici : Qt recalcule le minimum d'un
       widget à partir du « min-height » de la feuille de style et du
       remplissage effectif, et ce minimum écrase celui posé par setFixedSize.
       Avec un remplissage nul, le « min-height: 19px » des boutons ordinaires
       ramenait ces cases à 21 pixels de haut au lieu de 28. */
    QFrame#{name} QPushButton[grid="true"] {{
        padding: 0;
        font-size: 12px;
        min-width: 40px;
        min-height: 26px;
    }}
    QFrame#{name} QPushButton[grid="true"]:checked {{
        background: {p.accent};
        color: {p.accent_text};
        border-color: {p.accent};
        font-weight: 700;
    }}
    /* Les compteurs de la saisie précise sont dépourvus de flèches : tout le
       champ revient à son texte, centré. */
    QFrame#{name} QSpinBox {{
        padding: 5px 6px;
        min-height: 21px;
        font-size: 14px;
    }}

    /* Calendrier du sélecteur de date. */
    QFrame#{name} QCalendarWidget QAbstractItemView {{
        background: {p.surface};
        selection-background-color: {p.accent};
        selection-color: {p.accent_text};
        outline: none;
        border: none;
    }}
    QFrame#{name} QCalendarWidget QWidget#qt_calendar_navigationbar {{
        background: {p.surface_alt};
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
    }}
    QFrame#{name} QCalendarWidget QToolButton {{
        background: transparent;
        border: none;
        border-radius: 5px;
        padding: 4px 8px;
        color: {p.text};
    }}
    QFrame#{name} QCalendarWidget QToolButton:hover {{ background: {p.selection}; }}
    QFrame#{name} QCalendarWidget QSpinBox {{ font-size: 13px; }}
    """


def apply(app, theme: str) -> Palette:
    """Applique le thème à l'application et renvoie la palette retenue."""
    palette = resolve(theme)
    app.setStyle("Fusion")
    app.setPalette(build_qpalette(palette))
    app.setStyleSheet(build_stylesheet(palette))
    return palette


class ThemeManager(QObject):
    """Thème courant de l'application ; suit le thème Windows en mode « Système ».

    Les widgets qui dessinent eux-mêmes (icônes colorées, pastilles…) s'abonnent à
    ``changed`` pour se redessiner avec la nouvelle palette.
    """

    changed = Signal(object)  # Palette

    def __init__(self, app, theme: str) -> None:
        super().__init__(app)
        self._app = app
        self._theme = theme if theme in THEMES else THEME_SYSTEM
        self.palette = apply(app, self._theme)
        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(self._on_system_changed)

    @property
    def theme(self) -> str:
        return self._theme

    def set_theme(self, theme: str) -> None:
        self._theme = theme if theme in THEMES else THEME_SYSTEM
        self._reapply()

    def _on_system_changed(self, *_args) -> None:
        if self._theme == THEME_SYSTEM:
            self._reapply()

    def _reapply(self) -> None:
        self.palette = apply(self._app, self._theme)
        self.changed.emit(self.palette)


_manager: ThemeManager | None = None


def install_manager(app, theme: str) -> ThemeManager:
    global _manager
    _manager = ThemeManager(app, theme)
    return _manager


def follow(receiver: QObject, slot) -> None:
    """Appelle ``slot(palette)`` à chaque changement de thème, tant que ``receiver`` existe."""
    if _manager is not None:
        signals.follow(_manager.changed, receiver, slot)


def manager() -> ThemeManager | None:
    return _manager


def current() -> Palette:
    """Palette active (clair par défaut si aucun thème n'est encore installé)."""
    return _manager.palette if _manager is not None else LIGHT
