"""Rapport Markdown : synthèse, inventaire, résumé sémantique complet, vues spécialisées.

Le niveau de détail visé est celui de l'étude de cas de FTOCompare. Le rapport est
rédigé dans la langue de l'interface au moment de l'export ; les libellés d'état et de sens
viennent de ``core.labels``, source unique partagée avec l'interface.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from ....common.i18n import tr
from ..core.analysis import Comparison, FileDiff
from ..core.labels import SYMBOLE_SENS, etat_label, sens_label


def _cell(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def table(header: Iterable[str], rows: Iterable[Iterable[object]]) -> str:
    head = list(header)
    lines = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(_cell(c) for c in row) + " |")
    return "\n".join(lines)


def _section_synthese(c: Comparison) -> str:
    s = c.synthese()
    compat = "✅ " + tr("identical (versions)") if s.versions_compatibles else "⚠️ **" + tr("different — interpret the results with care") + "**"
    rows = [
        (tr("Runtime (reference)"), str(c.runtime_root)),
        (tr("Project (to fix)"), str(c.projet_root)),
        (tr("IDE version"), tr("runtime `{runtime}` ⇄ project `{project}`").format(runtime=s.version_runtime, project=s.version_projet) + f" — {compat}"),
        (tr("Compared files"), tr("{n} (including {yaml} YAML)").format(n=s.nb_fichiers_compares, yaml=s.nb_yaml_communs)),
        (tr("Differences"), tr("{n} (including {yaml} YAML)").format(n=s.nb_divergents, yaml=s.nb_yaml_divergents)),
        ("➕ " + tr("Runtime additions"), s.nb_ajouts_runtime),
        ("➖ " + tr("Project branch"), s.nb_branche_projet),
        ("✏️ " + tr("Modified values"), s.nb_valeurs_modifiees),
        (tr("Non-significant differences"), s.nb_non_significatifs),
        (tr("Files expected on one side only"), s.nb_attendus),
        (tr("Analysis duration"), f"{s.duree_s:.1f} s"),
    ]
    return "## 1. " + tr("Summary") + "\n\n" + table(("", ""), rows)


def _section_inventaire(c: Comparison) -> str:
    inv = c.inventory
    rows = []
    for e in inv.divergents():
        fd = c.diffs.get(e.rel)
        sens = sens_label(fd.sens) if fd else etat_label(e.status)
        rows.append(
            (
                f"`{e.rel}`",
                sens,
                e.size_projet if e.size_projet is not None else "—",
                e.size_runtime if e.size_runtime is not None else "—",
                len(fd.significatifs) if fd else "",
            )
        )
    out = [
        "## 2. " + tr("Diverging files"),
        "",
        table((tr("File"), tr("Direction"), tr("Project size"), tr("Runtime size"), tr("Differences")), rows),
    ]
    orphelins = c.orphelins_projet + c.orphelins_runtime
    if orphelins:
        out += ["", "⚠️ " + tr("Orphan YAML files (not referenced by a `- File:`):"), ""]
        out += [f"- `{rel}`" for rel in orphelins]
    attendus = inv.attendus()
    if attendus:
        out += ["", "### " + tr("Normal structural differences ({n} files, not counted)").format(n=len(attendus)), ""]
        raisons: dict[str, int] = {}
        for e in attendus:
            raisons[e.raison_attendu] = raisons.get(e.raison_attendu, 0) + 1
        out += [f"- {raison} : {n}" for raison, n in raisons.items()]
    return "\n".join(out)


def _section_semantique(c: Comparison) -> str:
    out = ["## 3. " + tr("Semantic summary"), ""]
    for rel, fd in c.diffs.items():
        out.append(f"### `{rel}` — {sens_label(fd.sens)}")
        out.append("")
        rows = []
        for s in fd.semantic:
            sens = f"{SYMBOLE_SENS.get(s.sens, '')} {sens_label(s.sens)}" if s.significatif else "· " + sens_label("non_significatif")
            rows.append((sens, ", ".join(f"`{n}`" for n in s.noeuds) or "—", s.chemin, s.detail))
        out.append(table((tr("Direction"), tr("Node"), tr("Path"), tr("Detail")), rows))
        out.append("")
    return "\n".join(out)


def _section_specialisees(c: Comparison) -> str:
    out = ["## 4. " + tr("Specialised views"), ""]
    for rel, d in c.tags.items():
        out += [f"### {tr('CoDeSys tags')} — `{rel}`", ""]
        if d.runtime_seul:
            out += [tr("Present in the **runtime**, missing from the project:"), ""]
            out.append(
                table(
                    ("Tag", tr("Type"), "DataType", "SymbolName", tr("Members")),
                    [
                        (t.name, t.type, t.data_type + (f"[{t.array}]" if t.array else ""), f"`{t.symbol}`", ", ".join(t.membres))
                        for t in d.runtime_seul
                    ],
                )
            )
            out.append("")
        if d.projet_seul:
            out += [tr("Present in the **project**, missing from the runtime:"), ""]
            out.append(
                table(
                    ("Tag", tr("Type"), "SymbolName", tr("Members")),
                    [(t.name, t.type, f"`{t.symbol}`", ", ".join(t.membres)) for t in d.projet_seul],
                )
            )
            out.append("")
        if d.modifies:
            out += [tr("Modified (type, DataType or dimensions):"), ""]
            out.append(
                table(
                    ("SymbolName", tr("Project"), tr("Runtime")),
                    [(r.symbol, " ".join(r.projet.signature()), " ".join(r.runtime.signature())) for r in d.modifies if r.projet and r.runtime],
                )
            )
            out.append("")
    for rel, d in c.translations.items():
        out += [
            f"### {tr('Translations')} — `{rel}`",
            "",
            tr("Dimensions: project `{project}` ⇄ runtime `{runtime}`").format(
                project=list(d.dimensions_projet or ()), runtime=list(d.dimensions_runtime or ())
            ),
            "",
        ]
        header = (d.runtime or d.projet).header if (d.runtime or d.projet) else []
        key = [tr("key")]
        if d.runtime_seul:
            out += [tr("Lines present on the runtime side only:"), "", table(header or key, d.runtime_seul), ""]
        if d.projet_seul:
            out += [tr("Lines present on the project side only:"), "", table(header or key, d.projet_seul), ""]
        if d.modifies:
            out += [tr("Modified lines (project then runtime):"), "", table(header or key, [r for pair in d.modifies for r in pair]), ""]
    if c.types is not None and (c.types.projet_seul or c.types.runtime_seul):
        out += [
            f"### {tr('User types')} — `ProjectFiles/UserDefinedModule.xml`",
            "",
            tr("{project} TypeMapping on the project side, {runtime} on the runtime side.").format(
                project=len(c.types.projet), runtime=len(c.types.runtime)
            ),
            "",
        ]
        rows = [(g, c.type_names.get(g, "?"), etat_label("projet_seul")) for g in c.types.projet_seul] + [
            (g, c.type_names.get(g, "?"), etat_label("runtime_seul")) for g in c.types.runtime_seul
        ]
        out += [table(("GUID", tr("Name"), tr("State")), rows), ""]
    if c.netlogic is not None and (c.netlogic.projet_seul or c.netlogic.runtime_seul):
        out += ["### " + tr("NetLogic — DLL classes"), ""]
        rows = [(n, c.netlogic.sources_projet.get(n, ""), etat_label("projet_seul")) for n in c.netlogic.projet_seul] + [
            (n, "", etat_label("runtime_seul")) for n in c.netlogic.runtime_seul
        ]
        out += [table((tr("Class"), tr("Project source"), tr("State")), rows), ""]
    if c.optix is not None:
        out += [
            "### " + tr("`.optix` statistics (for information, recomputed by the IDE)"),
            "",
            table(
                (tr("Statistic"), tr("Project"), tr("Runtime")),
                [(k, "" if p is None else p, "" if r is None else r) for k, p, r in c.optix.stats_rows()],
            ),
            "",
        ]
    return "\n".join(out)


def build_markdown(c: Comparison, titre: str | None = None) -> str:
    parts = [
        f"# {titre or tr('OptixPlus — comparison report')}",
        "",
        tr("Generated on {date} by OptixPlus (Compare).").format(date=f"{datetime.now():%Y-%m-%d %H:%M}"),
        "",
        _section_synthese(c),
        "",
        _section_inventaire(c),
        "",
        _section_semantique(c),
        "",
        _section_specialisees(c),
    ]
    return "\n".join(parts).rstrip() + "\n"


def diffs_summary(diffs: Iterable[FileDiff]) -> str:
    """Résumé court multi-fichiers, réutilisé par les boîtes de dialogue."""
    return "\n".join(
        tr("{file}: {additions} additions, {removals} removals, {values} values").format(
            file=fd.rel, additions=fd.nb_ajouts_runtime, removals=fd.nb_branche_projet, values=fd.nb_valeurs_modifiees
        )
        for fd in diffs
    )
