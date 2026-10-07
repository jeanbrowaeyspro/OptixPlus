"""Export CSV des tableaux d'une analyse : stations et pages (sans Qt)."""

from __future__ import annotations

import csv
from pathlib import Path

from .model import ProjectStatistics

SEPARATOR = ";"  # Excel en français ouvre ce séparateur directement


def station_address(address: str, port: str) -> str:
    """Adresse d'une station sous la forme ``adresse:port`` (l'un ou l'autre peut manquer)."""
    return f"{address}:{port}" if address and port else address or port


def write_csv(
    path: str | Path,
    stats: ProjectStatistics,
    *,
    station_titles: list[str],
    page_titles: list[str],
    section_titles: tuple[str, str],
    kind_labels: dict[str, str],
) -> None:
    """Écrit les stations puis les pages (deux sections séparées par une ligne vide), en UTF-8 avec BOM.

    ``station_titles`` : 5 colonnes (station, pilote, adresse:port, tags, structures) ;
    ``page_titles`` : 8 colonnes (titre, nom, type, principale, tags, liaisons, sous-vues, approximatif).
    """
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=SEPARATOR)
        writer.writerow([section_titles[0]])
        writer.writerow(station_titles)
        for s in stats.stations:
            writer.writerow([s.name, s.driver_type, station_address(s.address, s.port), s.tags, s.structures])
        writer.writerow([])
        writer.writerow([section_titles[1]])
        writer.writerow(page_titles)
        for p in stats.pages:
            writer.writerow(
                [p.title, p.name, kind_labels.get(p.kind, p.kind), int(p.is_main), p.tags, p.links, p.subviews, int(p.approximate)]
            )
