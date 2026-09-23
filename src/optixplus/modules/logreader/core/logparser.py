"""Analyse des lignes du fichier ``FTOptixRuntime.<n>.log``.

Le format est stable : sept champs séparés par des points-virgules, une entrée
par ligne. Les tabulations à l'intérieur des champs « message » et « détails »
tiennent lieu de sauts de ligne (listes de jetons de licence, stack dumps).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

#: Horodatage FT Optix : ``19-08-2026 10:14:52.916``.
TIMESTAMP_FORMAT = "%d-%m-%Y %H:%M:%S.%f"

_TIMESTAMP_RE = re.compile(r"^\d{2}-\d{2}-\d{4} \d{2}:\d{2}:\d{2}\.\d{3}$")

LEVEL_ERROR = "ERROR"
LEVEL_WARNING = "WARNING"
LEVEL_INFO = "INFO"

#: Ordre d'affichage des niveaux dans les filtres, du plus grave au moins grave.
KNOWN_LEVELS = (LEVEL_ERROR, LEVEL_WARNING, LEVEL_INFO)


@dataclass(slots=True)
class LogEntry:
    """Une ligne de log décodée."""

    index: int
    timestamp: datetime | None
    timestamp_text: str
    level: str
    source: str
    code: str
    message: str
    details: str
    node_path: str
    #: Niveau tel qu'écrit dans le fichier (``level`` est normalisé en majuscules).
    #: Chaîne vide pour une ligne hors format, dont tout le texte est dans ``message``.
    level_text: str = ""
    #: Texte concaténé en minuscules, utilisé pour la recherche et le surlignage.
    search_text: str = field(default="", repr=False)
    #: Indice de la règle de surlignage retenue (-1 = aucune), calculé par
    #: :class:`app.highlight.Highlighter` et mis à jour quand les règles changent.
    highlight_index: int = -1

    @property
    def raw(self) -> str:
        """Ligne d'origine, reconstruite à l'identique à partir des champs.

        pyFTOLogReader la conservait en plus des champs découpés et de sa copie en
        minuscules : trois fois le même texte, multiplié par 500 000 lignes. Elle n'est
        plus stockée, seulement recomposée quand on la demande (copie de la ligne).
        """
        if not self.timestamp_text:
            return self.message
        return ";".join(
            (self.timestamp_text, self.level_text, self.source, self.code, self.message, self.details, self.node_path)
        )

    @property
    def message_multiline(self) -> str:
        """Message avec les tabulations rendues comme des sauts de ligne."""
        return self.message.replace("\t", "\n").rstrip()

    @property
    def details_multiline(self) -> str:
        return self.details.replace("\t", "\n").rstrip()


def decode_line(raw_bytes: bytes) -> str:
    """Décode une ligne brute.

    Le fichier est majoritairement en UTF-8 mais contient épisodiquement des
    octets CP1252 isolés (apostrophes typographiques). Un décodage UTF-8 strict
    du fichier entier échoue ; on décode donc ligne par ligne avec repli.
    """
    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return raw_bytes.decode("cp1252", "replace")


def parse_line(text: str, index: int) -> LogEntry | None:
    """Transforme une ligne de texte en :class:`LogEntry`.

    Renvoie ``None`` pour une ligne vide. Une ligne qui ne respecte pas le
    format attendu est conservée telle quelle dans le champ « message » plutôt
    que d'être silencieusement perdue.
    """
    text = text.rstrip("\r\n")
    if not text.strip():
        return None

    parts = text.split(";")
    if len(parts) >= 7 and _TIMESTAMP_RE.match(parts[0]):
        stamp_text, level, source, code, message, details = parts[:6]
        # Un chemin de nœud ne contient pas de « ; » mais on recolle par
        # sécurité si le message en contenait un de plus que prévu.
        node_path = ";".join(parts[6:])
        try:
            stamp = datetime.strptime(stamp_text, TIMESTAMP_FORMAT)
        except ValueError:
            stamp = None
    else:
        stamp_text, stamp = "", None
        level, source, code, details, node_path = "", "", "", "", ""
        message = text

    entry = LogEntry(
        index=index,
        timestamp=stamp,
        timestamp_text=stamp_text,
        level=level.strip().upper(),
        source=source,
        code=code,
        message=message,
        details=details,
        node_path=node_path,
        level_text=level,
    )
    entry.search_text = text.lower()
    return entry
