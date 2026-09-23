"""Thèmes clair, sombre et suivi automatique du thème Windows.

Le mode ``system`` s'appuie sur ``QStyleHints.colorScheme()`` (Qt 6.5+), qui
reflète le réglage « Mode Application » de Windows et émet un signal lorsque
l'utilisateur le change en cours d'exécution. Un repli par lecture du registre
couvre les cas où Qt ne renseigne pas l'information.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette

THEME_SYSTEM = "system"
THEME_LIGHT = "light"
THEME_DARK = "dark"

THEME_LABELS = {
    THEME_SYSTEM: "Système",
    THEME_LIGHT: "Clair",
    THEME_DARK: "Sombre",
}


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


LIGHT = Palette(
    name=THEME_LIGHT,
    dark=False,
    window="#F2F4F7",
    surface="#FFFFFF",
    surface_alt="#F7F9FB",
    border="#DCE1E8",
    text="#161A1F",
    text_muted="#6B7480",
    accent="#2D6FE0",
    accent_text="#FFFFFF",
    selection="#CFE0FB",
    selection_text="#0F1A2B",
    error="#D32F2F",
    warning="#B87A00",
    info="#3A7BD5",
    success="#2E9E5B",
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
    accent="#5B9BFF",
    accent_text="#0B1220",
    selection="#2B4468",
    selection_text="#EAF1FF",
    error="#F0736C",
    warning="#E2B04A",
    info="#6FA8F5",
    success="#5DC98A",
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
    QToolBar::separator {{
        background: {p.border};
        width: 1px;
        margin: 4px 6px;
    }}

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
    QPushButton[accent="true"]:hover {{ background: {p.info}; border-color: {p.info}; }}
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
    QMenu::item {{ padding: 6px 24px 6px 14px; border-radius: 5px; }}
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
    app.setPalette(build_qpalette(palette))
    app.setStyleSheet(build_stylesheet(palette))
    return palette
