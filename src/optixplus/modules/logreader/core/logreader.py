r"""Lecture non bloquante et suivi en direct du fichier de log FT Optix.

Le fichier est en cours d'écriture par ``FTOptixRuntime.exe``. Deux précautions
sont indispensables :

1. **Ouvrir en partage total.** ``open()`` de Python autorise bien la lecture et
   l'écriture concurrentes, mais pas la suppression (``FILE_SHARE_DELETE``). Or
   la rotation du log renomme ``FTOptixRuntime.0.log`` en ``.1.log`` : sans ce
   drapeau, notre poignée de fichier ferait échouer la rotation du runtime.
   On passe donc par ``CreateFileW`` avec les trois drapeaux de partage.
2. **Ne valider que les lignes complètes.** Une interrogation peut tomber au
   milieu d'une écriture ; le fragment sans saut de ligne final est conservé
   pour la fois suivante.

La rotation est détectée par deux signaux complémentaires : une taille qui
diminue, et une signature des premiers octets qui change (cas d'un nouveau
fichier ayant déjà dépassé la taille lue précédemment).
"""

from __future__ import annotations

import ctypes
import hashlib
import msvcrt
import os
from ctypes import wintypes
from dataclasses import dataclass, field

from .logparser import LogEntry, decode_line, parse_line

GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
FILE_SHARE_DELETE = 0x00000004
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x00000080

#: Valeur renvoyée par ``CreateFileW`` en cas d'échec. Il faut la comparer sous
#: sa forme non signée : en 64 bits, la poignée revient sous la forme
#: 0xFFFFFFFFFFFFFFFF et jamais sous celle de l'entier -1.
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

#: Nombre d'octets en tête de fichier servant d'empreinte d'identité.
_SIGNATURE_SIZE = 1024

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateFileW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
    wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
]
# c_void_p plutôt que HANDLE : ctypes renvoie alors un entier non signé (ou
# None pour zéro), directement comparable à INVALID_HANDLE_VALUE.
_kernel32.CreateFileW.restype = ctypes.c_void_p


def open_shared(path: str):
    """Ouvre *path* en lecture sans jamais gêner l'écriture ni la rotation.

    Renvoie un objet fichier binaire Python classique ; le fermer libère la
    poignée Windows sous-jacente.
    """
    handle = _kernel32.CreateFileW(
        path,
        GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        None,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL,
        None,
    )
    if not handle or handle == INVALID_HANDLE_VALUE:
        # On rhabille le code Win32 en une erreur lisible : sans cela, la
        # poignée invalide filait jusqu'à msvcrt et ressortait en « Bad file
        # descriptor », message qui n'apprend rien à l'utilisateur.
        code = ctypes.get_last_error()
        details = ctypes.WinError(code)
        # Le chemin est passé en quatrième argument : Python l'ajoute lui-même
        # au message, inutile de le répéter dans le texte de l'erreur.
        raise OSError(details.errno, details.strerror.strip(), path, code)

    # msvcrt prend possession de la poignée : elle sera fermée avec le fichier.
    descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    return os.fdopen(descriptor, "rb")


def split_complete_lines(buffer: bytes) -> tuple[list[bytes], bytes]:
    """Sépare les lignes terminées du fragment en cours d'écriture."""
    if b"\n" not in buffer:
        return [], buffer
    head, _, tail = buffer.rpartition(b"\n")
    return head.split(b"\n"), tail


@dataclass
class PollResult:
    """Résultat d'une interrogation du fichier."""

    entries: list[LogEntry] = field(default_factory=list)
    #: Vrai si le fichier a été remplacé ou tronqué depuis la lecture précédente.
    rotated: bool = False
    #: Message d'erreur si le fichier est momentanément inaccessible.
    error: str = ""
    file_size: int = 0


class LogFollower:
    """Suit un fichier de log : lecture initiale puis lecture incrémentale."""

    def __init__(self, path: str, start_index: int = 0):
        self.path = path
        self._offset = 0
        self._pending = b""
        self._signature = b""
        #: Longueur figée de l'empreinte. Elle ne doit pas suivre la taille du
        #: fichier, sinon un log plus court que ``_SIGNATURE_SIZE`` verrait son
        #: empreinte changer à chaque ajout de ligne et déclencherait une fausse
        #: rotation à la première interrogation.
        self._signature_len = 0
        self._next_index = start_index

    # ------------------------------------------------------------------ état

    @property
    def next_index(self) -> int:
        """Prochain numéro de ligne qui sera attribué."""
        return self._next_index

    def reset(self, start_index: int | None = None) -> None:
        self._offset = 0
        self._pending = b""
        self._signature = b""
        self._signature_len = 0
        if start_index is not None:
            self._next_index = start_index

    def _capture_signature(self, head: bytes) -> None:
        """Fige l'empreinte d'identité du fichier sur les octets déjà connus."""
        self._signature_len = min(_SIGNATURE_SIZE, len(head))
        self._signature = hashlib.blake2b(
            head[:self._signature_len], digest_size=16
        ).digest()

    # ------------------------------------------------------------- lecture

    def _parse(self, raw_lines: list[bytes]) -> list[LogEntry]:
        entries = []
        for raw in raw_lines:
            entry = parse_line(decode_line(raw), self._next_index)
            if entry is not None:
                entries.append(entry)
                self._next_index += 1
        return entries

    def read_all(self) -> PollResult:
        """Lit le fichier depuis le début et réinitialise le suivi."""
        self.reset()
        try:
            with open_shared(self.path) as handle:
                data = handle.read()
        except OSError as exc:
            return PollResult(error=str(exc))

        self._capture_signature(data)
        self._offset = len(data)
        lines, self._pending = split_complete_lines(data)
        return PollResult(entries=self._parse(lines), file_size=len(data))

    def poll(self) -> PollResult:
        """Lit les octets ajoutés depuis l'appel précédent."""
        try:
            with open_shared(self.path) as handle:
                size = os.fstat(handle.fileno()).st_size

                if size < self._offset:
                    # Le fichier a rétréci : rotation ou troncature.
                    return self._reload(handle, size)

                if self._signature_len:
                    head = handle.read(self._signature_len)
                    if hashlib.blake2b(head, digest_size=16).digest() != self._signature:
                        # Taille égale ou supérieure mais tête différente :
                        # c'est un nouveau fichier déjà alimenté.
                        return self._reload(handle, size)

                if size == self._offset:
                    return PollResult(file_size=size)

                handle.seek(self._offset)
                chunk = handle.read(size - self._offset)
        except OSError as exc:
            return PollResult(error=str(exc))

        if not self._signature_len:
            # Le suivi a démarré sur un fichier vide : on fige l'empreinte dès
            # que du contenu apparaît.
            self._capture_signature(chunk)

        self._offset += len(chunk)
        lines, self._pending = split_complete_lines(self._pending + chunk)
        return PollResult(entries=self._parse(lines), file_size=size)

    def _reload(self, handle, size: int) -> PollResult:
        """Relit le fichier entier après une rotation, sans rouvrir la poignée."""
        handle.seek(0)
        data = handle.read()
        self._offset = len(data)
        self._capture_signature(data)
        lines, self._pending = split_complete_lines(data)
        return PollResult(entries=self._parse(lines), rotated=True, file_size=size)


def read_file(path: str, start_index: int = 0) -> tuple[list[LogEntry], str]:
    """Lecture ponctuelle d'un fichier complet (utilisée pour les archives).

    Renvoie ``(entrées, message_d_erreur)``.
    """
    try:
        with open_shared(path) as handle:
            data = handle.read()
    except OSError as exc:
        return [], str(exc)

    entries = []
    index = start_index
    for raw in data.split(b"\n"):
        entry = parse_line(decode_line(raw), index)
        if entry is not None:
            entries.append(entry)
            index += 1
    return entries, ""


def archive_paths(log_dir: str, current_filename: str, count: int = 4) -> list[str]:
    """Chemins des fichiers archivés ``FTOptixRuntime.1..3.log`` existants.

    Le nom courant est de la forme ``<base>.0.<ext>`` ; on en dérive les
    fichiers de rotation et on ne renvoie que ceux réellement présents.
    """
    stem, _, extension = current_filename.rpartition(".")
    base, _, _index = stem.rpartition(".")
    if not base:
        return []

    found = []
    for number in range(1, count):
        candidate = os.path.join(log_dir, f"{base}.{number}.{extension}")
        if os.path.isfile(candidate):
            found.append(candidate)
    return found
