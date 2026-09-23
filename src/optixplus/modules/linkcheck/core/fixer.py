"""Correction des liens dynamiques cassés, par édition texte des YAML (formatage conservé).

Deux opérations, reprises de Link Checker :
- remplacer la cible d'un lien (ligne ``Value:`` du DynamicLink) ;
- supprimer le bloc DynamicLink (la propriété garde sa valeur statique).

Corrections par rapport à l'outil d'origine :
- **tout ou rien** : toutes les modifications sont d'abord calculées en mémoire et
  vérifiées ; si l'une échoue, aucun fichier n'est touché. Puis sauvegarde de chaque
  fichier, écriture (fichier temporaire puis remplacement), relecture et contrôle
  d'empreinte ; au premier échec, les fichiers déjà écrits sont restaurés ;
- le remplacement porte sur la **valeur exacte** de la ligne ``Value:``, et non sur la
  première occurrence du texte dans la ligne ;
- fins de ligne (CRLF/LF) et BOM conservés ligne par ligne.

FT Optix Studio doit être fermé pendant l'opération.
"""

from __future__ import annotations

import datetime
import hashlib
import os
import re
import shutil
from dataclasses import dataclass

from ....common.i18n import tr
from ....common.progress import ProgressCallback, report
from .project import BrokenLink, OptixProject

ACTION_REPLACE = "replace"
ACTION_REMOVE = "remove"

_VALUE_LINE = re.compile(r"^(?P<head>\s*(?:-\s+)?Value:[ \t]*)(?P<quote>[\"']?)(?P<value>.*?)(?P=quote)(?P<tail>[ \t]*)$")
# Caractères qui imposent des guillemets en tête d'un scalaire YAML nu.
_YAML_SPECIAL_START = tuple("!&*[]{}|>'\"%@`#,?:-")


@dataclass
class Fix:
    link: BrokenLink
    action: str  # ACTION_REPLACE | ACTION_REMOVE
    new_target: str = ""


@dataclass
class FixResult:
    backup_dir: str
    files: int
    journal: list[str]


class FixError(Exception):
    """Correction impossible ; aucun fichier n'a été modifié (ou tous ont été restaurés)."""


def propose_prefix_fixes(project: OptixProject, broken: list[BrokenLink]) -> tuple[list[Fix], list[tuple[BrokenLink, str, str]]]:
    """Pour chaque lien visant un autre projet : même chemin sous le projet courant, si la cible existe.

    Renvoie (corrections, ignorés) ; un ignoré est (lien, cible proposée, raison)."""
    fixes: list[Fix] = []
    skipped: list[tuple[BrokenLink, str, str]] = []
    for link in broken:
        foreign = project.foreign_project_prefix(link.target)
        if not foreign:
            continue
        new_target = link.target.replace(f"/Objects/{foreign}/", f"/Objects/{project.name}/", 1)
        node, code, _detail = project.resolve(new_target, project.objects)
        if node is not None or code == "pointer":
            fixes.append(Fix(link, ACTION_REPLACE, new_target))
        else:
            skipped.append((link, new_target, code))
    return fixes, skipped


def backup_dir_for(project: OptixProject) -> str:
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    folder = project.folder.rstrip("\\/")
    return os.path.join(os.path.dirname(folder), f"{os.path.basename(folder)}_linkcheck_backup_{stamp}")


# ---- lecture / écriture en conservant le format ----------------------------------------
@dataclass
class _Text:
    lines: list[str]  # contenu des lignes, sans fin de ligne
    endings: list[str]  # fin de chaque ligne (« \r\n », « \n » ou « » pour la dernière)
    bom: bool

    def encode(self) -> bytes:
        data = "".join(line + end for line, end in zip(self.lines, self.endings)).encode("utf-8")
        return (b"\xef\xbb\xbf" + data) if self.bom else data


def _parse(raw: bytes) -> _Text:
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw[3:].decode("utf-8") if bom else raw.decode("utf-8")
    lines, endings = [], []
    for chunk in text.splitlines(keepends=True):
        body = chunk.rstrip("\r\n")
        lines.append(body)
        endings.append(chunk[len(body):])
    return _Text(lines, endings, bom)


def _quote_for(value: str, original_quote: str) -> str:
    if original_quote:
        return original_quote
    if value.startswith(_YAML_SPECIAL_START) or ": " in value or " #" in value or value != value.strip():
        return "'"
    return ""


def _replace_value(line: str, expected: str, new_value: str, where: str) -> str:
    match = _VALUE_LINE.match(line)
    if match is None or match.group("value") != expected:
        raise FixError(
            tr("{where}: the expected target is no longer there (file changed since the analysis?)").format(where=where)
        )
    quote = _quote_for(new_value, match.group("quote"))
    if quote == "'":
        new_value = new_value.replace("'", "''")
    return f"{match.group('head')}{quote}{new_value}{quote}{match.group('tail')}"


def _remove_block(text: _Text, link: BrokenLink, where: str) -> int:
    """Supprime le bloc DynamicLink ; renvoie la ligne de fin (1-based, exclusive)."""
    start = link.block_start - 1
    if start >= len(text.lines) or "Name: DynamicLink" not in text.lines[start]:
        raise FixError(tr("{where}: DynamicLink block not found").format(where=where))
    # Sécurité : ne supprimer que les lignes plus indentées que le « - Name » du bloc.
    indent = len(text.lines[start]) - len(text.lines[start].lstrip())
    end = start + 1
    while end < len(text.lines) and (
        not text.lines[end].strip() or len(text.lines[end]) - len(text.lines[end].lstrip()) > indent
    ):
        end += 1
    declared_end = link.block_end - 1
    if declared_end > start:
        end = min(end, declared_end)
    # La fin de ligne de la ligne précédente est conservée telle quelle.
    del text.lines[start:end]
    del text.endings[start:end]
    return end + 1


def prepare(project: OptixProject, fixes: list[Fix]) -> tuple[dict[str, tuple[bytes, bytes]], list[str]]:
    """Calcule toutes les modifications en mémoire, sans rien écrire.

    Renvoie ({fichier: (contenu d'origine, nouveau contenu)}, journal). Lève ``FixError``
    à la première incohérence : aucun fichier n'est alors modifié."""
    by_file: dict[str, list[Fix]] = {}
    for fix in fixes:
        by_file.setdefault(fix.link.file, []).append(fix)
    changes: dict[str, tuple[bytes, bytes]] = {}
    journal: list[str] = []
    for path, file_fixes in by_file.items():
        rel = os.path.relpath(path, project.folder)
        try:
            with open(path, "rb") as fh:
                original = fh.read()
        except OSError as exc:
            raise FixError(tr("Cannot read {file}: {error}").format(file=rel, error=exc)) from exc
        text = _parse(original)
        # Les suppressions décalent les lignes : traitement du bas vers le haut.
        for fix in sorted(file_fixes, key=lambda f: -f.link.block_start):
            link = fix.link
            if fix.action == ACTION_REPLACE:
                where = tr("{file} line {line}").format(file=rel, line=link.line)
                index = link.line - 1
                if index >= len(text.lines):
                    raise FixError(tr("{where}: line not found").format(where=where))
                text.lines[index] = _replace_value(text.lines[index], link.target, fix.new_target, where)
                journal.append(
                    tr("{file} line {line}: {old} → {new}").format(
                        file=rel, line=link.line, old=link.target, new=fix.new_target
                    )
                )
            elif fix.action == ACTION_REMOVE:
                where = tr("{file} line {line}").format(file=rel, line=link.block_start)
                end = _remove_block(text, link, where)
                journal.append(
                    tr("{file} lines {first}-{last}: link removed ({target})").format(
                        file=rel, first=link.block_start, last=end - 1, target=link.target
                    )
                )
            else:
                raise FixError(tr("unknown action: {action}").format(action=fix.action))
        changes[path] = (original, text.encode())
    return changes, journal


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def apply_fixes(
    project: OptixProject,
    fixes: list[Fix],
    backup_dir: str | None = None,
    progress: ProgressCallback | None = None,
) -> FixResult:
    """Applique les corrections en tout ou rien ; lève ``FixError`` si rien n'a (ou plus rien n'a) changé."""
    if not fixes:
        return FixResult("", 0, [])
    changes, journal = prepare(project, fixes)
    backup_dir = backup_dir or backup_dir_for(project)
    total = len(changes)

    # 1. Sauvegarde de tous les fichiers avant la moindre écriture.
    phase = tr("Backing up files")
    backups: dict[str, str] = {}
    try:
        for i, path in enumerate(changes, 1):
            rel = os.path.relpath(path, project.folder)
            report(progress, phase, rel, i, total)
            destination = os.path.join(backup_dir, rel)
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            shutil.copy2(path, destination)
            backups[path] = destination
    except OSError as exc:
        raise FixError(tr("Backup failed, nothing was modified: {error}").format(error=exc)) from exc

    # 2. Écriture puis relecture ; au premier échec, restauration de ce qui a été écrit.
    phase = tr("Writing files")
    written: list[str] = []
    try:
        for i, (path, (_original, new)) in enumerate(changes.items(), 1):
            report(progress, phase, os.path.relpath(path, project.folder), i, total)
            temporary = path + ".optixplus.tmp"
            with open(temporary, "wb") as fh:
                fh.write(new)
            os.replace(temporary, path)
            written.append(path)
            with open(path, "rb") as fh:
                if _digest(fh.read()) != _digest(new):
                    raise OSError(tr("verification failed after writing {file}").format(file=path))
    except OSError as exc:
        restore_errors = []
        for path in written:
            try:
                shutil.copy2(backups[path], path)
            except OSError as restore_exc:
                restore_errors.append(f"{path} : {restore_exc}")
        try:
            os.remove(path + ".optixplus.tmp")
        except OSError:
            pass
        if restore_errors:
            raise FixError(
                tr("Writing failed ({error}) and some files could not be restored; backup: {backup}\n{details}").format(
                    error=exc, backup=backup_dir, details="\n".join(restore_errors)
                )
            ) from exc
        raise FixError(tr("Writing failed, all files were restored: {error}").format(error=exc)) from exc
    return FixResult(backup_dir, total, journal)
