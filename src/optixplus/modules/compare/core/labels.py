"""Libellés des états, sens, genres et décisions — source unique, traduite, sans Qt.

FTOCompare définissait certains de ces libellés à deux ou trois endroits (moteur, vues,
rapport). Ils sont désormais ici seulement, traduits à l'affichage : l'interface et les
rapports les partagent.
"""

from __future__ import annotations

from ....common.i18n import tr

SYMBOLE_SENS: dict[str, str] = {
    "ajout_runtime": "➕",
    "branche_projet": "➖",
    "valeur_modifiee": "✏️",
    "mixte": "⇄",
    "non_significatif": "·",
    "identique": "=",
}


def etat_label(status: str) -> str:
    """État d'un fichier dans l'inventaire."""
    return {
        "identique": tr("identical"),
        "different": tr("different"),
        "runtime_seul": tr("runtime only"),
        "projet_seul": tr("project only"),
        "attendu": tr("expected"),
    }.get(status, status)


def sens_label(sens: str) -> str:
    """Sens d'un écart (ou d'un fichier)."""
    return {
        "ajout_runtime": tr("runtime addition"),
        "branche_projet": tr("project branch"),
        "valeur_modifiee": tr("modified value"),
        "mixte": tr("mixed"),
        "non_significatif": tr("not significant"),
        "identique": tr("identical"),
    }.get(sens, sens)


def genre_label(genre: str) -> str:
    """Nature d'un écart sémantique."""
    return {
        "bloc": tr("block"),
        "fichier": tr("file reference"),
        "valeur": tr("value"),
        "id": tr("identifier"),
        "dimensions": tr("derived counter"),
        "lignes": tr("lines"),
        "deplacement": tr("move"),
    }.get(genre, genre)


def decision_label(decision: str) -> str:
    """Décision du plan pour un écart."""
    return {
        "ignorer": tr("Ignore"),
        "prendre_runtime": tr("Take the runtime"),
        "garder_projet": tr("Keep the project"),
    }.get(decision, decision)


def line_state_label(state: str) -> str:
    """État d'une ligne dans les vues spécialisées (tags, traductions, GUID, NetLogic)."""
    return {
        "identique": tr("identical"),
        "runtime_seul": tr("runtime only"),
        "projet_seul": tr("project only"),
        "modifie": tr("modified"),
    }.get(state, state)
