"""État de la connexion d'un onglet : libellé et couleur de sa pastille."""

from __future__ import annotations

from ....common.i18n import tr
from ....common.theme import Palette

STATE_OFFLINE = "offline"      # aucun automate connecté
STATE_CONNECTING = "connecting"  # connexion ou reconnexion en cours
STATE_ONLINE = "online"        # journal lu normalement
STATE_LOST = "lost"            # connexion perdue


def _labels() -> dict[str, str]:
    return {
        STATE_OFFLINE: tr("No controller connected"),
        STATE_CONNECTING: tr("Connecting…"),
        STATE_ONLINE: tr("Connection established"),
        STATE_LOST: tr("Connection lost — automatic reconnection in progress"),
    }


def state_label(state: str) -> str:
    return _labels().get(state, state)


def state_colour(state: str, palette: Palette) -> str:
    """Verte quand la liaison est bonne, rouge perdue, orange en cours, grise sans automate."""
    return {STATE_ONLINE: palette.success, STATE_LOST: palette.error, STATE_CONNECTING: palette.warning}.get(
        state, palette.text_muted
    )
