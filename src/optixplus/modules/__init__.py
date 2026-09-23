"""Registre des outils d'OptixPlus, dans l'ordre de la barre latérale."""

from __future__ import annotations

from .base import ModuleSpec

MODULES: tuple[ModuleSpec, ...] = (
    ModuleSpec(
        id="logreader",
        title="Log Reader",
        description="Follow the runtime log of FT Optix controllers live, filter it and export it.",
        icon="logreader",
        shortcut="Ctrl+1",
        import_path="optixplus.modules.logreader.module:LogReaderModule",
    ),
    ModuleSpec(
        id="linkcheck",
        title="Link Checker",
        description="Find and repair broken DynamicLinks in an FT Optix project.",
        icon="linkcheck",
        shortcut="Ctrl+2",
        import_path="optixplus.modules.linkcheck.module:LinkCheckModule",
        opens_projects=True,
    ),
    ModuleSpec(
        id="compare",
        title="Compare",
        description="Compare a deployed runtime with a project and apply the chosen fixes safely.",
        icon="compare",
        shortcut="Ctrl+3",
        import_path="optixplus.modules.compare.module:CompareModule",
        opens_projects=True,
    ),
    ModuleSpec(
        id="autovalidate",
        title="Auto Validate",
        description="Automatically confirm the “Project already exists” prompt of FT Optix Studio.",
        icon="autovalidate",
        shortcut="Ctrl+4",
        import_path="optixplus.modules.autovalidate.module:AutoValidateModule",
        service_path="optixplus.modules.autovalidate.service:AutoValidateService",
    ),
)


def spec(module_id: str) -> ModuleSpec | None:
    return next((m for m in MODULES if m.id == module_id), None)
