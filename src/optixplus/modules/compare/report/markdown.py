"""Rapport Markdown : synthèse, inventaire, résumé sémantique complet, vues spécialisées.

Le niveau de détail visé est celui de ``docs/cas-reel.md``.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from ..core.analysis import Comparison, FileDiff
from ..core.diffing import LIBELLE_SENS

SYMBOLE = {"ajout_runtime": "➕", "branche_projet": "➖", "valeur_modifiee": "✏️"}


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
    compat = "✅ identiques" if s.versions_compatibles else "⚠️ **différentes — résultats à interpréter avec prudence**"
    rows = [
        ("Runtime (référence)", str(c.runtime_root)),
        ("Projet (à corriger)", str(c.projet_root)),
        ("Version IDE", f"runtime `{s.version_runtime}` ⇄ projet `{s.version_projet}` — {compat}"),
        ("Fichiers comparés", f"{s.nb_fichiers_compares} (dont {s.nb_yaml_communs} YAML)"),
        ("Divergences", f"{s.nb_divergents} (dont {s.nb_yaml_divergents} YAML)"),
        ("➕ Ajouts runtime", s.nb_ajouts_runtime),
        ("➖ Branche projet", s.nb_branche_projet),
        ("✏️ Valeurs modifiées", s.nb_valeurs_modifiees),
        ("Écarts non significatifs", s.nb_non_significatifs),
        ("Fichiers attendus d'un seul côté", s.nb_attendus),
        ("Durée de l'analyse", f"{s.duree_s:.1f} s"),
    ]
    return "## 1. Synthèse\n\n" + table(("", ""), rows)


def _section_inventaire(c: Comparison) -> str:
    inv = c.inventory
    rows = []
    for e in inv.divergents():
        fd = c.diffs.get(e.rel)
        sens = LIBELLE_SENS.get(fd.sens, fd.sens) if fd else {"runtime_seul": "runtime seul", "projet_seul": "projet seul"}.get(e.status, e.status)
        rows.append((f"`{e.rel}`", sens, e.size_projet if e.size_projet is not None else "—", e.size_runtime if e.size_runtime is not None else "—", len(fd.significatifs) if fd else ""))
    out = ["## 2. Fichiers divergents", "", table(("Fichier", "Sens", "Taille projet", "Taille runtime", "Écarts"), rows)]
    orphelins = c.orphelins_projet + c.orphelins_runtime
    if orphelins:
        out += ["", "⚠️ YAML orphelins (non référencés par un `- File:`) :", ""]
        out += [f"- `{rel}`" for rel in orphelins]
    attendus = inv.attendus()
    if attendus:
        out += ["", f"### Différences structurelles normales ({len(attendus)} fichiers, non comptées)", ""]
        raisons: dict[str, int] = {}
        for e in attendus:
            raisons[e.raison_attendu] = raisons.get(e.raison_attendu, 0) + 1
        out += [f"- {raison} : {n}" for raison, n in raisons.items()]
    return "\n".join(out)


def _section_semantique(c: Comparison) -> str:
    out = ["## 3. Résumé sémantique", ""]
    for rel, fd in c.diffs.items():
        out.append(f"### `{rel}` — {LIBELLE_SENS.get(fd.sens, fd.sens)}")
        out.append("")
        rows = []
        for s in fd.semantic:
            sens = f"{SYMBOLE.get(s.sens, '')} {LIBELLE_SENS[s.sens]}" if s.significatif else "· non significatif"
            rows.append((sens, ", ".join(f"`{n}`" for n in s.noeuds) or "—", s.chemin, s.detail))
        out.append(table(("Sens", "Nœud", "Chemin", "Détail"), rows))
        out.append("")
    return "\n".join(out)


def _section_specialisees(c: Comparison) -> str:
    out = ["## 4. Vues spécialisées", ""]
    for rel, d in c.tags.items():
        out += [f"### Tags CoDeSys — `{rel}`", ""]
        if d.runtime_seul:
            out += ["Présents dans le **runtime**, absents du projet :", ""]
            out.append(table(("Tag", "Type", "DataType", "SymbolName", "Membres"), [(t.name, t.type, t.data_type + (f"[{t.array}]" if t.array else ""), f"`{t.symbol}`", ", ".join(t.membres)) for t in d.runtime_seul]))
            out.append("")
        if d.projet_seul:
            out += ["Présents dans le **projet**, absents du runtime :", ""]
            out.append(table(("Tag", "Type", "SymbolName", "Membres"), [(t.name, t.type, f"`{t.symbol}`", ", ".join(t.membres)) for t in d.projet_seul]))
            out.append("")
        if d.modifies:
            out += ["Modifiés (type, DataType ou dimensions) :", ""]
            out.append(table(("SymbolName", "Projet", "Runtime"), [(r.symbol, " ".join(r.projet.signature()), " ".join(r.runtime.signature())) for r in d.modifies if r.projet and r.runtime]))
            out.append("")
    for rel, d in c.translations.items():
        out += [f"### Traductions — `{rel}`", "", f"Dimensions : projet `{list(d.dimensions_projet or ())}` ⇄ runtime `{list(d.dimensions_runtime or ())}`", ""]
        header = (d.runtime or d.projet).header if (d.runtime or d.projet) else []
        if d.runtime_seul:
            out += ["Lignes présentes côté runtime seulement :", "", table(header or ["clé"], d.runtime_seul), ""]
        if d.projet_seul:
            out += ["Lignes présentes côté projet seulement :", "", table(header or ["clé"], d.projet_seul), ""]
        if d.modifies:
            out += ["Lignes modifiées (projet puis runtime) :", "", table(header or ["clé"], [r for pair in d.modifies for r in pair]), ""]
    if c.types is not None and (c.types.projet_seul or c.types.runtime_seul):
        out += ["### Types utilisateur — `ProjectFiles/UserDefinedModule.xml`", "", f"{len(c.types.projet)} TypeMapping côté projet, {len(c.types.runtime)} côté runtime.", ""]
        rows = [(g, c.type_names.get(g, "?"), "projet seul") for g in c.types.projet_seul] + [(g, c.type_names.get(g, "?"), "runtime seul") for g in c.types.runtime_seul]
        out += [table(("GUID", "Nom", "État"), rows), ""]
    if c.netlogic is not None and (c.netlogic.projet_seul or c.netlogic.runtime_seul):
        out += ["### NetLogic — classes des DLL", ""]
        rows = [(n, c.netlogic.sources_projet.get(n, ""), "projet seul") for n in c.netlogic.projet_seul] + [(n, "", "runtime seul") for n in c.netlogic.runtime_seul]
        out += [table(("Classe", "Source projet", "État"), rows), ""]
    if c.optix is not None:
        out += ["### Statistiques `.optix` (informatives, recalculées par l'IDE)", "", table(("Statistique", "Projet", "Runtime"), [(k, "" if p is None else p, "" if r is None else r) for k, p, r in c.optix.stats_rows()]), ""]
    return "\n".join(out)


def build_markdown(c: Comparison, titre: str = "FTOCompare — rapport de comparaison") -> str:
    parts = [
        f"# {titre}",
        "",
        f"Généré le {datetime.now():%Y-%m-%d %H:%M} par FTOCompare.",
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
    lines = []
    for fd in diffs:
        lines.append(f"{fd.rel} : {fd.nb_ajouts_runtime} ajouts, {fd.nb_branche_projet} retraits, {fd.nb_valeurs_modifiees} valeurs")
    return "\n".join(lines)
