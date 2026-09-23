"""Chiffrement des secrets locaux via la DPAPI Windows.

Les mots de passe de connexion aux IPC ne sont jamais écrits en clair dans le
fichier de configuration : ils sont chiffrés avec ``CryptProtectData`` et ne
peuvent être relus que par le même compte Windows sur le même poste. Si la
DPAPI est indisponible (poste non Windows lors d'un test), on retombe sur un
encodage réversible clairement identifié comme tel afin que l'application
reste utilisable sans jamais laisser croire que le secret est protégé.
"""

from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes

_ENC_PREFIX = "dpapi:"
_PLAIN_PREFIX = "plain:"


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _Blob:
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _blob_bytes(blob: _Blob) -> bytes:
    return ctypes.string_at(blob.pbData, blob.cbData)


try:  # pragma: no cover - dépend de la plateforme
    _crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _crypt32.CryptProtectData.restype = wintypes.BOOL
    _crypt32.CryptUnprotectData.restype = wintypes.BOOL
    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    _AVAILABLE = True
except (OSError, AttributeError):  # pragma: no cover
    _AVAILABLE = False


def available() -> bool:
    """Indique si la DPAPI Windows est utilisable sur ce poste."""
    return _AVAILABLE


def protect(secret: str) -> str:
    """Chiffre *secret* et renvoie une chaîne stockable dans le JSON."""
    if not secret:
        return ""
    if not _AVAILABLE:
        return _PLAIN_PREFIX + base64.b64encode(secret.encode("utf-8")).decode("ascii")

    src = _blob(secret.encode("utf-8"))
    out = _Blob()
    ok = _crypt32.CryptProtectData(
        ctypes.byref(src), "pyFTOLogReader", None, None, None, 0, ctypes.byref(out)
    )
    if not ok:
        return _PLAIN_PREFIX + base64.b64encode(secret.encode("utf-8")).decode("ascii")
    try:
        blob = _blob_bytes(out)
    finally:
        _kernel32.LocalFree(out.pbData)
    return _ENC_PREFIX + base64.b64encode(blob).decode("ascii")


def unprotect(stored: str) -> str:
    """Déchiffre une valeur produite par :func:`protect`."""
    if not stored:
        return ""
    if stored.startswith(_PLAIN_PREFIX):
        return base64.b64decode(stored[len(_PLAIN_PREFIX):]).decode("utf-8", "replace")
    if not stored.startswith(_ENC_PREFIX):
        # Valeur écrite à la main dans le fichier de configuration.
        return stored
    if not _AVAILABLE:
        return ""

    raw = base64.b64decode(stored[len(_ENC_PREFIX):])
    src = _blob(raw)
    out = _Blob()
    ok = _crypt32.CryptUnprotectData(
        ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out)
    )
    if not ok:
        return ""
    try:
        return _blob_bytes(out).decode("utf-8", "replace")
    finally:
        _kernel32.LocalFree(out.pbData)
