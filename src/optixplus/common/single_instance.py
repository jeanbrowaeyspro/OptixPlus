"""Instance unique et transmission des demandes d'un second lancement.

La première instance détient un mutex de session et écoute sur un canal local
(``QLocalServer``). Un second lancement (menu Démarrer, raccourci…) envoie sa demande,
par exemple ``["show"]`` ou ``["open-tool", "logreader"]``, puis s'arrête : la première
instance l'exécute et passe au premier plan.
"""

from __future__ import annotations

import getpass
import json
import logging
import time

from PySide6.QtCore import QByteArray, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from . import win32

log = logging.getLogger("optixplus.instance")


def _safe_user() -> str:
    try:
        return "".join(c for c in getpass.getuser() if c.isalnum()) or "user"
    except Exception:
        return "user"


class SingleInstance(QObject):
    """Garde d'instance unique avec canal de commandes."""

    message_received = Signal(list)

    def __init__(self, key: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.mutex_name = f"Local\\{key}_SingleInstance"
        self.server_name = f"{key}-{_safe_user()}"
        self._mutex = 0
        self._server: QLocalServer | None = None

    def acquire(self) -> bool:
        """Vrai si ce processus est la première instance."""
        self._mutex, already = win32.create_mutex(self.mutex_name)
        return not already

    def listen(self) -> bool:
        """Ouvre le canal de commandes (première instance uniquement)."""
        QLocalServer.removeServer(self.server_name)  # canal orphelin d'un plantage précédent
        server = QLocalServer(self)
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if not server.listen(self.server_name):
            log.error("Canal d'instance unique indisponible : %s", server.errorString())
            return False
        server.newConnection.connect(self._on_new_connection)
        self._server = server
        return True

    def _on_new_connection(self) -> None:
        assert self._server is not None
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            socket.readyRead.connect(lambda s=socket: self._read(s))
            socket.disconnected.connect(socket.deleteLater)

    def _read(self, socket: QLocalSocket) -> None:
        while socket.canReadLine():
            line = bytes(socket.readLine().data()).decode("utf-8", "replace").strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError:
                log.warning("Demande illisible reçue d'une autre instance : %r", line)
                continue
            if isinstance(message, list) and all(isinstance(m, str) for m in message):
                self.message_received.emit(message)

    def send(self, message: list[str], timeout_ms: int = 1500, attempts: int = 4) -> bool:
        """Envoie une demande à la première instance (second lancement)."""
        payload = QByteArray((json.dumps(message) + "\n").encode("utf-8"))
        for _attempt in range(attempts):
            socket = QLocalSocket()
            socket.connectToServer(self.server_name)
            if socket.waitForConnected(timeout_ms):
                socket.write(payload)
                ok = socket.waitForBytesWritten(timeout_ms)
                socket.disconnectFromServer()
                if ok:
                    return True
            # La première instance démarre peut-être encore : on laisse passer un instant.
            time.sleep(0.2)
        return False

    def release(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
        win32.close_handle(self._mutex)
        self._mutex = 0
