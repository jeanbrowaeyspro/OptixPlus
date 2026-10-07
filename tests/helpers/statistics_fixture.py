"""Résultat d'analyse factice pour les tests de l'outil Statistiques (aucune donnée réelle)."""

from __future__ import annotations

from optixplus.modules.statistics.core.model import (
    KIND_RUNTIME,
    VIEW_DIALOG,
    VIEW_SCREEN,
    PageStats,
    ProjectStatistics,
    PageRow,
    StationStats,
)


def make_statistics(folder: str = "C:/demo/Demo", *, runtime: bool = False) -> ProjectStatistics:
    home = PageStats("Home", "Home", VIEW_SCREEN, "UI/Home", is_main=True, links=12, tags=8, subviews=1)
    work = PageStats("Work", "Work", VIEW_SCREEN, "UI/Work", is_main=True, links=60, tags=40, approximate=True, subviews=3)
    supervision = PageStats("Supervision", "Supervision", VIEW_SCREEN, "UI/Supervision", is_main=True, links=30, tags=25)
    dialog = PageStats("Confirm", "Confirm", VIEW_DIALOG, "UI/Confirm", links=2, tags=2)
    rows = [
        PageRow("Home", "UI/Home", [], 12, 8, False, 1),
        PageRow("Work", "UI/Work", [], 60, 40, True, 3),
        PageRow("Supervision", "UI/Supervision", ["Axes"], 18, 13, False),
        PageRow("Supervision", "UI/Supervision", ["Overview", "Detail"], 14, 12, False),
    ]
    return ProjectStatistics(
        name="Demo",
        folder=folder,
        kind=KIND_RUNTIME if runtime else "project",
        ide_version="1.6.4.11-Stable",
        product_version="1.6.4.11",
        studio_counts={"Nodes": 900},
        nodes=910,
        files=14,
        stations=[
            StationStats("Station1", "UI/Station1", "CODESYSDriver", "CODESYSStation", "192.0.2.10", "11740", tags=120, structures=6),
            StationStats("Station2", "UI/Station2", "CODESYSDriver", "CODESYSStation", "", "", tags=30, structures=0),
        ],
        tags_total=150,
        structures_total=6,
        pages=[home, work, supervision, dialog],
        main_pages=3,
        average_tags_per_view=18.0,
        busiest_row=rows[1],
        work_page=work,
        supervision_page=supervision,
        rows=rows,
        work_row=rows[1],
        supervision_row=rows[3],
        alarms=12,
        netlogic=3,
        loggers=2,
        image_files=20,
        image_bytes=3 * 1024 * 1024,
        font_files=2,
        font_bytes=300 * 1024,
        project_files_bytes=5 * 1024 * 1024,
        runtime_files=[("Retentive.db", 2048), ("Data.sqlite", 4 * 1024 * 1024)] if runtime else [],
        warnings=["Some dynamic paths could not be resolved."],
    )
