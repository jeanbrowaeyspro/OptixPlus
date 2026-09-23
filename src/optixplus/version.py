"""Identité de l'application : source unique de la version et des métadonnées."""

from __future__ import annotations

__version__ = "1.0.0"

APP_NAME = "OptixPlus"
APP_ID = "JeanBrowaeys.OptixPlus"  # AppUserModelID Windows
ORGANIZATION = "Jean Browaeys"
AUTHOR = "Jean Browaeys"
POWERED_BY = "Claude Opus 5.5"
GITHUB_REPO = "jeanbrowaeyspro/OptixPlus"
GITHUB_URL = f"https://github.com/{GITHUB_REPO}"


def build_date() -> str:
    """Date de build injectée par ``tools/build.py`` ; vide en exécution depuis les sources."""
    try:
        from ._build_info import BUILD_DATE  # type: ignore[import-not-found]
    except ImportError:
        return ""
    return BUILD_DATE
