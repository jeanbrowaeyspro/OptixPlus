"""Lecture et écriture de fichiers texte en préservant octet pour octet la convention de fin de ligne.

Les YAML FactoryTalk Optix sont en CRLF. Les lire en mode texte Python convertirait
silencieusement en ``\\n`` et toute réécriture produirait un fichier intégralement modifié.
On lit donc en binaire, on détecte le séparateur, on découpe soi-même, et on réécrit avec
le même séparateur et la même terminaison finale.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

BOM_UTF8 = b"\xef\xbb\xbf"

# Extensions considérées comme texte sans examen du contenu.
TEXT_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".yaml",
        ".yml",
        ".xml",
        ".cs",
        ".txt",
        ".csv",
        ".json",
        ".optix",
        ".design",
        ".references",
        ".csproj",
        ".sln",
        ".props",
        ".targets",
        ".md",
        ".cmd",
        ".vbs",
        ".ps1",
        ".bat",
        ".ini",
        ".config",
        ".editorconfig",
    }
)


@dataclass(slots=True)
class TextFile:
    """Contenu d'un fichier texte découpé en lignes, avec ce qu'il faut pour le réécrire à l'identique.

    ``lines`` ne contient pas les séparateurs. ``eol`` est le séparateur détecté (``b"\\r\\n"``
    ou ``b"\\n"``) et ``final_eol`` indique si le fichier se terminait par un séparateur.
    ``bom`` conserve un éventuel BOM UTF-8 de tête.
    """

    lines: list[bytes] = field(default_factory=list)
    eol: bytes = b"\r\n"
    final_eol: bool = True
    bom: bytes = b""

    def to_bytes(self) -> bytes:
        """Reconstitue le contenu binaire exact."""
        body = self.eol.join(self.lines)
        if self.final_eol and self.lines:
            body += self.eol
        return self.bom + body

    def text_lines(self, encoding: str = "utf-8") -> list[str]:
        """Les lignes décodées, pour affichage. Les octets invalides sont remplacés, jamais levés."""
        return [line.decode(encoding, errors="replace") for line in self.lines]

    @property
    def eol_name(self) -> str:
        """Nom lisible du séparateur : ``CRLF`` ou ``LF``."""
        return "CRLF" if self.eol == b"\r\n" else "LF"


def detect_eol(raw: bytes) -> bytes:
    """Détecte le séparateur de lignes d'un contenu binaire.

    Un fichier sans aucun saut de ligne est réputé CRLF : c'est la convention Optix, et
    cela n'a d'effet que si l'on ajoute des lignes.
    """
    if b"\r\n" in raw:
        return b"\r\n"
    if b"\n" in raw:
        return b"\n"
    return b"\r\n"


def split_lines(raw: bytes) -> TextFile:
    """Découpe un contenu binaire en lignes sans jamais altérer les octets."""
    bom = b""
    if raw.startswith(BOM_UTF8):
        bom = BOM_UTF8
        raw = raw[len(BOM_UTF8) :]
    eol = detect_eol(raw)
    if not raw:
        return TextFile(lines=[], eol=eol, final_eol=False, bom=bom)
    final_eol = raw.endswith(eol)
    body = raw[: -len(eol)] if final_eol else raw
    return TextFile(lines=body.split(eol), eol=eol, final_eol=final_eol, bom=bom)


def read_text_file(path: Path | str) -> TextFile:
    """Lit un fichier en binaire et le découpe en lignes."""
    return split_lines(Path(path).read_bytes())


def write_text_file(path: Path | str, content: TextFile) -> str:
    """Écrit le fichier puis le relit depuis le disque pour vérifier le hash. Retourne le MD5 relu.

    Lève ``OSError`` si la relecture ne correspond pas à ce qui devait être écrit :
    on ne se fie jamais au seul succès de l'écriture.
    """
    expected = content.to_bytes()
    target = Path(path)
    target.write_bytes(expected)
    actual = target.read_bytes()
    if actual != expected:
        from ....common.i18n import tr

        raise OSError(tr("Verification after writing failed for {file}").format(file=target))
    return hashlib.md5(actual).hexdigest()


def is_probably_text(raw_head: bytes, suffix: str = "") -> bool:
    """Heuristique texte/binaire : extension connue, sinon absence d'octet nul dans l'en-tête."""
    if suffix.lower() in TEXT_EXTENSIONS:
        return True
    if not raw_head:
        return True
    return b"\x00" not in raw_head


def md5_of_file(path: Path | str, chunk_size: int = 1 << 20) -> str:
    """MD5 d'un fichier, lu par blocs pour ne pas charger 6 Mo d'un coup inutilement."""
    digest = hashlib.md5()
    with open(path, "rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def md5_of_bytes(raw: bytes) -> str:
    """MD5 d'un contenu déjà en mémoire."""
    return hashlib.md5(raw).hexdigest()
