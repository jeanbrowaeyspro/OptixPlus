"""Traduction de l'interface, sans dépendance à Qt (utilisable par les moteurs ``core``).

Principe :
- le texte source est écrit **en anglais** dans le code et sert de clé : ``tr("Open project")`` ;
- ``i18n/fr.json`` associe chaque texte anglais à sa traduction française ;
- l'anglais n'a pas de catalogue : c'est la langue de repli.

Les fonctions s'appellent ``tr`` / ``tr_n`` et non ``_`` : ``_`` sert couramment de
variable jetable (``valeur, _ = …``), ce qui masquerait silencieusement la fonction.

Règle : traduire au moment de l'affichage, jamais dans une constante de module (le
catalogue n'est pas encore chargé à l'import).

La langue est fixée une fois au démarrage ; un changement s'applique au redémarrage.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger("optixplus.i18n")

CATALOG_DIR = Path(__file__).resolve().parent.parent / "i18n"
SUPPORTED = ("fr", "en")
LANG_FRENCH = 0x0C  # identifiant de langue principale Windows (PRIMARYLANGID)

_catalog: dict[str, str] = {}
_language = "en"


def language_from_langid(langid: int) -> str:
    """Langue retenue pour un LANGID Windows : français pour toute variante fr-*, anglais sinon."""
    return "fr" if (langid & 0x3FF) == LANG_FRENCH else "en"


def detect_windows_language() -> str:
    """Langue d'affichage de Windows, ramenée à ``fr`` ou ``en``."""
    try:
        import ctypes

        langid = int(ctypes.windll.kernel32.GetUserDefaultUILanguage())
        return language_from_langid(langid)
    except (AttributeError, OSError):
        import locale

        code = (locale.getlocale()[0] or "").lower()
        return "fr" if code.startswith(("fr", "french")) else "en"


def resolve_language(setting: str) -> str:
    """Convertit le réglage (``auto``/``fr``/``en``) en langue effective."""
    if setting in SUPPORTED:
        return setting
    return detect_windows_language()


def load_catalog(language: str) -> dict[str, str]:
    """Charge le catalogue d'une langue (vide pour l'anglais ou en cas d'erreur)."""
    if language == "en":
        return {}
    path = CATALOG_DIR / f"{language}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.error("Catalogue de traduction %s illisible : %s", path, exc)
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str) and v}


def install(language: str) -> None:
    """Active une langue pour tout le processus."""
    global _catalog, _language
    _language = language if language in SUPPORTED else "en"
    _catalog = load_catalog(_language)


def current_language() -> str:
    return _language


def tr(text: str) -> str:
    """Traduit un texte source anglais dans la langue active."""
    return _catalog.get(text, text)


def tr_noop(text: str) -> str:
    """Marque un texte source pour l'extraction sans le traduire (constantes de module).

    Le texte est traduit plus tard, à l'affichage, par ``tr(variable)``.
    """
    return text


def tr_n(singular: str, plural: str, n: int) -> str:
    """Traduit un texte qui dépend d'un nombre.

    En français, 0 et 1 prennent le singulier ; en anglais, seul 1 le prend.
    Le résultat est à formater par l'appelant : ``tr_n("{n} file", "{n} files", n).format(n=n)``.
    """
    use_singular = n <= 1 if _language == "fr" else n == 1
    key = singular if use_singular else plural
    return _catalog.get(key, key)
