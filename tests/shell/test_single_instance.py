"""Instance unique : le second lancement transmet sa demande à la première instance.

Le second lancement tourne dans un vrai processus séparé : dans le même thread, l'envoi
bloquant empêcherait la première instance de traiter la connexion.
"""

from __future__ import annotations

import subprocess
import sys
import time

from optixplus.common.single_instance import SingleInstance
from support import wait_until

SECOND_LAUNCH = """
import sys
from PySide6.QtCore import QCoreApplication
from optixplus.common.single_instance import SingleInstance
app = QCoreApplication([])
second = SingleInstance(sys.argv[1])
if second.acquire():
    sys.exit(2)  # aurait dû trouver la première instance
sys.exit(0 if second.send(["open-tool", "compare"]) else 1)
"""


def test_second_instance_forwards_message(qapp):
    key = f"OptixPlusTest{int(time.time() * 1000)}"
    first = SingleInstance(key)
    assert first.acquire()
    assert first.listen()
    received: list[list[str]] = []
    first.message_received.connect(received.append)

    process = subprocess.Popen([sys.executable, "-c", SECOND_LAUNCH, key])
    try:
        wait_until(lambda: process.poll() is not None and received, timeout=10)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(5)
        first.release()
    assert process.returncode == 0
    assert received == [["open-tool", "compare"]]
