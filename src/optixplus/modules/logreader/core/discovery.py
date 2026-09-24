"""Découverte des IPC FactoryTalk Optix sur le réseau.

La séquence pour chaque adresse est celle demandée : un ping d'abord, puis une
tentative de connexion au partage avec chaque jeu d'identifiants jusqu'à ce que
l'un fonctionne. Deux ajouts pragmatiques :

* le ping utilise ``IcmpSendEcho`` (iphlpapi.dll) plutôt qu'un appel à
  ``ping.exe``, ce qui évite une fenêtre de console qui clignote et donne un
  délai d'attente précis ;
* si l'ICMP ne répond pas, on tente une ouverture TCP sur le port 445, car
  certains IPC filtrent l'ICMP tout en exposant leurs partages.

Le nom de la machine est obtenu par une requête NetBIOS en UDP/137, qui ne
demande aucune authentification et répond en quelques millisecondes. Le nom du
projet Optix en cours d'exécution est lu dans ``FTOptixRuntime.xml``, à la
racine du partage, une fois la connexion établie.
"""

from __future__ import annotations

import ctypes
import ntpath
import os
import re
import socket
import struct
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from ctypes import wintypes
from dataclasses import dataclass, field

from ....common.i18n import tr
from . import netshare

# --------------------------------------------------------------------- ping

_IP_SUCCESS = 0

try:  # pragma: no cover - dépend de la plateforme
    _iphlpapi = ctypes.WinDLL("iphlpapi", use_last_error=True)
    _iphlpapi.IcmpCreateFile.restype = wintypes.HANDLE
    _iphlpapi.IcmpCloseHandle.argtypes = [wintypes.HANDLE]
    _iphlpapi.IcmpSendEcho.argtypes = [
        wintypes.HANDLE,      # IcmpHandle
        wintypes.ULONG,       # DestinationAddress
        wintypes.LPVOID,      # RequestData
        wintypes.USHORT,      # RequestSize
        wintypes.LPVOID,      # RequestOptions
        wintypes.LPVOID,      # ReplyBuffer
        wintypes.DWORD,       # ReplySize
        wintypes.DWORD,       # Timeout
    ]
    _iphlpapi.IcmpSendEcho.restype = wintypes.DWORD
    _ICMP_AVAILABLE = True
except (OSError, AttributeError):  # pragma: no cover
    _ICMP_AVAILABLE = False

_PING_PAYLOAD = b"pyFTOLogReader"
_INVALID_HANDLE = wintypes.HANDLE(-1).value


def ping(host: str, timeout_ms: int = 700) -> tuple[bool, int]:
    """Ping ICMP silencieux. Renvoie ``(répond, temps_aller_retour_ms)``."""
    if not _ICMP_AVAILABLE:
        return False, -1
    try:
        packed = socket.inet_aton(socket.gethostbyname(host))
    except (OSError, socket.gaierror):
        return False, -1

    destination = struct.unpack("<L", packed)[0]
    handle = _iphlpapi.IcmpCreateFile()
    if handle == _INVALID_HANDLE:
        return False, -1

    request = ctypes.create_string_buffer(_PING_PAYLOAD, len(_PING_PAYLOAD))
    # Le tampon doit contenir l'en-tête de réponse, les données renvoyées et
    # une marge pour les options IP ; 256 octets couvrent largement le cas.
    reply_size = 256
    reply = ctypes.create_string_buffer(reply_size)
    try:
        count = _iphlpapi.IcmpSendEcho(
            handle, destination, request, len(_PING_PAYLOAD),
            None, reply, reply_size, timeout_ms,
        )
    finally:
        _iphlpapi.IcmpCloseHandle(handle)

    if not count:
        return False, -1
    # ICMP_ECHO_REPLY : Address (4o), Status (4o), RoundTripTime (4o).
    status, rtt = struct.unpack_from("<LL", reply.raw, 4)
    if status != _IP_SUCCESS:
        return False, -1
    return True, rtt


def tcp_probe(host: str, port: int = 445, timeout: float = 0.7) -> bool:
    """Teste l'ouverture d'un port TCP (repli lorsque l'ICMP est filtré)."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# ----------------------------------------------------------------- NetBIOS

def netbios_name(host: str, timeout: float = 0.8, attempts: int = 2) -> str:
    """Nom de machine obtenu par une requête NetBIOS Node Status (UDP/137).

    Renvoie une chaîne vide si l'hôte ne répond pas ou si le service NetBIOS
    est désactivé. La requête passe en UDP sans acquittement : une réponse se
    perd de temps en temps, d'où la seconde tentative avant d'abandonner et
    d'afficher l'adresse à la place du nom.
    """
    for attempt in range(attempts):
        name = _netbios_query(host, timeout)
        if name:
            return name
    return ""


def _netbios_query(host: str, timeout: float) -> str:
    """Une tentative de requête NetBIOS Node Status."""
    # En-tête DNS-like + nom générique encodé « * » (CKA...A) + type NBSTAT.
    query = struct.pack(">H", 0x4B4C) + b"\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00"
    query += b"\x20" + b"CKAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" + b"\x00"
    query += b"\x00\x21\x00\x01"

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(query, (host, 137))
        data, _ = sock.recvfrom(2048)
    except OSError:
        return ""
    finally:
        sock.close()

    if len(data) < 57:
        return ""
    count = data[56]
    for i in range(count):
        offset = 57 + i * 18
        if offset + 18 > len(data):
            break
        name = data[offset:offset + 15].decode("ascii", "replace").strip()
        suffix = data[offset + 15]
        flags = struct.unpack_from(">H", data, offset + 16)[0]
        is_group = bool(flags & 0x8000)
        # Suffixe 0x00 « unique » = nom de la station de travail.
        if suffix == 0x00 and not is_group and name:
            return name
    return ""


# ------------------------------------------------------------ projet Optix

_XML_DECLARATION_RE = re.compile(r"^\s*<\?xml.*?\?>", re.DOTALL)


def _extract_tag(text: str, tag: str) -> str:
    """Extraction directe d'une balise simple, sans parseur XML."""
    match = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL)
    return match.group(1).strip() if match else ""


def read_runtime_info(folder: str) -> tuple[str, str]:
    """Lit ``FTOptixRuntime.xml`` du dossier ``folder`` : ``(nom_du_projet, version_runtime)``.

    ``folder`` est le dossier parent de celui des journaux (racine du partage « Optix »).
    Nécessite que le partage soit déjà accessible. Toute erreur renvoie des
    chaînes vides : l'IPC reste utilisable même si ce fichier est absent.

    Attention : FT Optix écrit une déclaration XML invalide
    (``encoding="utf - 8"``, avec des espaces) que le parseur refuse. On retire
    donc la déclaration avant l'analyse, et on retombe sur une extraction par
    expression régulière si le document reste illisible.
    """
    path = os.path.join(folder, "FTOptixRuntime.xml")
    try:
        with open(path, "rb") as handle:
            raw = handle.read(65536)
    except OSError:
        return "", ""

    text = raw.decode("utf-8", "replace")
    body = _XML_DECLARATION_RE.sub("", text, count=1).lstrip("﻿ \t\r\n")

    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return _extract_tag(text, "MainProject"), _extract_tag(text, "RuntimeVersion")

    project = root.findtext("MainProject", default="") or ""
    version = root.findtext("RuntimeVersion", default="") or ""
    return project.strip(), version.strip()


# ------------------------------------------------------------------ résultat

@dataclass
class Ipc:
    """État d'une adresse sondée."""

    host: str
    #: Automate décrit dans les réglages (identifiant et nom), vides pour une adresse seule.
    key: str = ""
    name: str = ""
    reachable: bool = False
    ping_ms: int = -1
    #: Vrai si l'ICMP a été filtré et que seul le port 445 a répondu.
    icmp_filtered: bool = False
    netbios_name: str = ""
    project: str = ""
    runtime_version: str = ""
    share_accessible: bool = False
    log_available: bool = False
    credential_label: str = ""
    status: str = field(default_factory=lambda: tr("not tested"))

    @property
    def ref(self) -> str:
        """Référence de l'automate : son identifiant s'il est décrit, sinon l'adresse."""
        return self.key or self.host

    @property
    def display_name(self) -> str:
        """Libellé principal : nom donné par l'utilisateur, sinon nom de la machine ; puis projet."""
        parts = [p for p in (self.name.strip() or self.netbios_name, self.project) if p]
        return " — ".join(parts) if parts else self.host

    @property
    def is_selectable(self) -> bool:
        return self.log_available


def probe_controller(controller, ping_timeout_ms: int = 700) -> Ipc:
    """Sonde un automate de bout en bout et renvoie son état.

    Dossier local : présence du dossier et du journal. Dossier réseau : ping (ou port
    445), nom NetBIOS, connexion au partage (session Windows, puis l'identifiant de
    l'automate), projet en cours et présence du journal.
    """
    result = Ipc(host=controller.host.strip(), key=controller.id, name=controller.name)
    folder = controller.log_folder()
    log_path = controller.log_path()
    target = controller.network_share()

    if target is None:  # dossier local : ni réseau ni identifiants
        if not os.path.isdir(folder):
            result.status = tr("folder not found: {path}").format(path=folder)
            return result
        result.reachable = result.share_accessible = True
        result.credential_label = tr("local folder")
    else:
        server, share = target
        responded, rtt = ping(server, ping_timeout_ms)
        if responded:
            result.reachable, result.ping_ms = True, rtt
        elif tcp_probe(server, 445, ping_timeout_ms / 1000.0):
            result.reachable, result.icmp_filtered = True, True
        else:
            result.status = tr("no answer")
            return result

        # Le nom NetBIOS ne demande pas d'authentification : on l'obtient même si
        # la connexion au partage échoue ensuite, ce qui rend le diagnostic plus
        # parlant dans la liste.
        result.netbios_name = netbios_name(server)
        connected, message, credential = netshare.connect_with_fallback(server, share, controller.credentials())
        result.status = message
        if not connected:
            return result
        result.share_accessible = True
        result.credential_label = credential.username if credential else tr("Windows session")

    result.project, result.runtime_version = read_runtime_info(ntpath.dirname(folder.rstrip("\\")))
    result.log_available = os.path.isfile(log_path)
    if not result.log_available:
        result.status = tr("folder accessible but {path} cannot be found").format(path=log_path)
    return result


def discover(controllers, ping_timeout_ms: int = 700, on_result=None,
             max_workers: int = 8) -> list[Ipc]:
    """Sonde tous les automates en parallèle ; résultats dans l'ordre de la liste fournie.

    ``on_result`` est appelé au fil de l'eau avec chaque :class:`Ipc` terminé,
    afin que l'interface se remplisse au lieu d'attendre la fin du balayage.
    """
    controllers = list(controllers)
    if not controllers:
        return []

    results: dict[str, Ipc] = {}
    with ThreadPoolExecutor(max_workers=min(max_workers, len(controllers))) as pool:
        futures = {
            pool.submit(probe_controller, controller, ping_timeout_ms): controller
            for controller in controllers
        }
        for future in as_completed(futures):
            controller = futures[future]
            try:
                ipc = future.result()
            except Exception as exc:  # pragma: no cover - filet de sécurité
                ipc = Ipc(host=controller.host, key=controller.id, name=controller.name,
                          status=tr("unexpected error: {error}").format(error=exc))
            results[controller.id] = ipc
            if on_result:
                on_result(ipc)

    return [results[c.id] for c in controllers if c.id in results]
