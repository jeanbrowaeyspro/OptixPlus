"""Connexions à des signaux durables depuis des widgets éphémères."""

from __future__ import annotations

import weakref

import shiboken6
from PySide6.QtCore import QObject, SignalInstance


def follow(signal: SignalInstance, receiver: QObject, slot) -> None:
    """Relaie ``signal`` vers ``slot`` (méthode de ``receiver``) tant que ``receiver`` existe.

    PySide ne coupe pas la connexion quand le widget est détruit (fenêtre fermée ou
    reconstruite), et déconnecter une méthode d'un objet détruit échoue : on passe par
    un relais qui ne garde qu'une référence faible et vérifie l'objet C++.
    """
    method = weakref.WeakMethod(slot)

    def relay(*args) -> None:
        bound = method()
        if bound is not None and shiboken6.isValid(bound.__self__):
            bound(*args)

    def drop(*_args) -> None:
        try:
            signal.disconnect(relay)
        except (RuntimeError, TypeError):
            pass

    signal.connect(relay)
    receiver.destroyed.connect(drop)


def track(owner: object, attribute: str, dialog: QObject) -> None:
    """Range ``dialog`` dans ``owner.attribute`` et l'en retire à sa destruction.

    La destruction d'une boîte fermée est différée : si une nouvelle boîte a pris sa place
    entre-temps (reconstruction en l'état), la référence à la nouvelle n'est pas effacée.
    """
    setattr(owner, attribute, dialog)

    def forget(*_args) -> None:
        if getattr(owner, attribute, None) is dialog:
            setattr(owner, attribute, None)

    dialog.destroyed.connect(forget)
