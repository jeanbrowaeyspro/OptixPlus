r"""Connexion authentifiée aux partages Windows (``\ip\Optix``).

On passe par ``WNetAddConnection2`` (mpr.dll) plutôt que par un appel à
``net use`` : pas de console qui clignote, pas d'analyse de messages d'erreur
localisés, et le code d'erreur Win32 exact est disponible.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

RESOURCETYPE_DISK = 0x00000001

NO_ERROR = 0
ERROR_ACCESS_DENIED = 5
ERROR_BAD_NET_NAME = 67
ERROR_ALREADY_ASSIGNED = 85
ERROR_INVALID_PASSWORD = 86
ERROR_NETWORK_UNREACHABLE = 1231
ERROR_NO_NET_OR_BAD_PATH = 1203
ERROR_BAD_NETPATH = 53
ERROR_LOGON_FAILURE = 1326
ERROR_SESSION_CREDENTIAL_CONFLICT = 1219
ERROR_NOT_CONNECTED = 2250

#: Codes signifiant « les identifiants sont refusés », par opposition à
#: « la machine est injoignable » : seul le premier cas justifie d'essayer
#: un autre jeu d'identifiants.
_CREDENTIAL_ERRORS = frozenset(
    {ERROR_ACCESS_DENIED, ERROR_INVALID_PASSWORD, ERROR_LOGON_FAILURE, ERROR_SESSION_CREDENTIAL_CONFLICT}
)

_MESSAGES = {
    ERROR_ACCESS_DENIED: "accès refusé (identifiants incorrects ou droits insuffisants)",
    ERROR_BAD_NET_NAME: "le partage n'existe pas sur cette machine",
    ERROR_BAD_NETPATH: "chemin réseau introuvable",
    ERROR_INVALID_PASSWORD: "mot de passe incorrect",
    ERROR_LOGON_FAILURE: "nom d'utilisateur ou mot de passe incorrect",
    ERROR_SESSION_CREDENTIAL_CONFLICT: "une session est déjà ouverte vers cette machine avec d'autres identifiants",
    ERROR_NETWORK_UNREACHABLE: "réseau injoignable",
    ERROR_NO_NET_OR_BAD_PATH: "machine injoignable ou chemin invalide",
}


class NETRESOURCEW(ctypes.Structure):
    _fields_ = [
        ("dwScope", wintypes.DWORD),
        ("dwType", wintypes.DWORD),
        ("dwDisplayType", wintypes.DWORD),
        ("dwUsage", wintypes.DWORD),
        ("lpLocalName", wintypes.LPWSTR),
        ("lpRemoteName", wintypes.LPWSTR),
        ("lpComment", wintypes.LPWSTR),
        ("lpProvider", wintypes.LPWSTR),
    ]


_mpr = ctypes.WinDLL("mpr", use_last_error=True)
_mpr.WNetAddConnection2W.argtypes = [
    ctypes.POINTER(NETRESOURCEW), wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD
]
_mpr.WNetAddConnection2W.restype = wintypes.DWORD
_mpr.WNetCancelConnection2W.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.BOOL]
_mpr.WNetCancelConnection2W.restype = wintypes.DWORD


def error_message(code: int) -> str:
    """Message lisible pour un code d'erreur Win32 réseau."""
    if code in _MESSAGES:
        return _MESSAGES[code]
    return f"erreur Windows {code}"


def is_credential_error(code: int) -> bool:
    """Vrai si l'échec vient des identifiants et non de la joignabilité."""
    return code in _CREDENTIAL_ERRORS


def unc_path(host: str, share: str) -> str:
    r"""Chemin UNC ``\\host\share``."""
    return "\\\\" + host + "\\" + share


def connect(host: str, share: str, username: str = "", password: str = "") -> int:
    r"""Ouvre une connexion vers ``\\host\share``. Renvoie un code Win32.

    Un ``username`` vide demande à Windows d'utiliser la session courante, ce
    qui suffit lorsque le partage est ouvert ou que le poste est dans le même
    domaine.
    """
    resource = NETRESOURCEW(
        dwScope=0,
        dwType=RESOURCETYPE_DISK,
        dwDisplayType=0,
        dwUsage=0,
        lpLocalName=None,
        lpRemoteName=unc_path(host, share),
        lpComment=None,
        lpProvider=None,
    )
    user = username or None
    pwd = password if username else None
    return _mpr.WNetAddConnection2W(ctypes.byref(resource), pwd, user, 0)


def disconnect(host: str, share: str, force: bool = True) -> int:
    """Ferme la connexion vers le partage. ``ERROR_NOT_CONNECTED`` n'est pas une erreur."""
    return _mpr.WNetCancelConnection2W(unc_path(host, share), 0, force)


def connect_with_fallback(
    host: str, share: str, credentials, on_attempt=None
) -> tuple[bool, str, object | None]:
    """Tente la connexion : session courante d'abord, puis chaque identifiant.

    Renvoie ``(succès, message, identifiant_utilisé)``. ``identifiant_utilisé``
    vaut ``None`` lorsque la session Windows courante a suffi.

    Un conflit de session (``ERROR_SESSION_CREDENTIAL_CONFLICT``) est traité en
    fermant la connexion existante avant de réessayer : sans cela, Windows
    refuse tout nouvel identifiant vers un serveur déjà monté.
    """
    if on_attempt:
        on_attempt("session Windows courante")
    code = connect(host, share)
    if code == NO_ERROR or code == ERROR_ALREADY_ASSIGNED:
        return True, "connecté avec la session Windows courante", None

    last_message = error_message(code)
    for credential in credentials:
        if on_attempt:
            on_attempt(credential.username)
        code = connect(host, share, credential.username, credential.password)
        if code == ERROR_SESSION_CREDENTIAL_CONFLICT:
            disconnect(host, share)
            code = connect(host, share, credential.username, credential.password)
        if code in (NO_ERROR, ERROR_ALREADY_ASSIGNED):
            return True, f"connecté en tant que « {credential.username} »", credential
        last_message = error_message(code)
        if not is_credential_error(code):
            # Machine injoignable ou partage absent : inutile d'essayer les
            # autres identifiants, l'échec ne vient pas d'eux.
            break

    return False, last_message, None
