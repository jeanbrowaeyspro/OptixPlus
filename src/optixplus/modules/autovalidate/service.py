"""Service de surveillance : détecte le popup de FT Optix Studio et le valide par Entrée.

Détection par événements Windows (``WinEventHook``) : l'apparition d'une fenêtre ou
l'ouverture d'une boîte de dialogue déclenche l'examen de cette seule fenêtre. Une
vérification lente (2 s par défaut) sert de filet de sécurité. Au repos, le service ne
consomme rien : plus de parcours de toutes les fenêtres toutes les 150 ms.

Séquence de validation, reprise d'Auto Validate :
  1. mémoriser la fenêtre au premier plan ;
  2. mettre le popup au premier plan — **sans focus, Entrée n'est pas envoyée** ;
  3. envoyer Entrée (bouton par défaut « Mettre à jour ») ;
  4. vérifier après ``retry_delay_ms`` que la fenêtre a disparu, sinon réessayer ;
  5. rendre le focus à la fenêtre précédente, **seulement** si le focus est resté chez
     FT Optix Studio : si l'utilisateur est passé à autre chose, on ne le lui vole pas.

Le service vit aussi longtemps que l'application, fenêtre principale ouverte ou non.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from time import monotonic
from types import ModuleType

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QWidget

from ...common.i18n import tr, tr_n
from ..base import BackgroundService, CheckedSync, ModuleSpec
from .activity import ActivityLog
from .core import matching, winapi
from .core.config import AutoValidateSettings

ERROR_LOG_MIN_INTERVAL_S = 10.0


@dataclass
class _Pending:
    hwnd: int
    title: str
    previous_foreground: int
    attempt: int = 0


class AutoValidateService(BackgroundService):
    validated = Signal(str)

    def __init__(self, spec: ModuleSpec, context, parent: QObject | None = None, api: ModuleType = winapi) -> None:
        super().__init__(spec, context, parent)
        self._api = api
        self.settings = context.settings.section(AutoValidateSettings).normalized()
        self.activity = ActivityLog()
        self.log = self.activity.logger
        self._patterns = matching.normalize_patterns(self.settings.titles)
        self._cooldowns = matching.Cooldowns()
        self._pending: _Pending | None = None
        self._enabled = False
        self._last_error_log = 0.0
        self.validation_count = 0
        self.last_validation = ""
        # En mode découverte, la surveillance démarre suspendue et son état n'est pas
        # enregistré : elle ne vit que le temps de la fenêtre.
        self._persist_state = context.installed

        self._hook = api.WinEventHook(self._on_win_event)
        self._fallback = QTimer(self)
        self._fallback.setInterval(self.settings.fallback_scan_ms)
        self._fallback.timeout.connect(self._scan_all)

    # ---- cycle de vie ------------------------------------------------------------
    def start(self) -> None:
        if self._persist_state and self.settings.enabled:
            self._activate()
        else:
            self.state_changed.emit()

    def stop(self) -> None:
        self._deactivate()
        self.activity.close()

    # ---- état ------------------------------------------------------------------
    @property
    def persistent(self) -> bool:
        """Faux en mode découverte : la surveillance s'arrête avec la fenêtre."""
        return self._persist_state

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def suspended(self) -> bool:
        return not self._enabled

    def set_enabled(self, enabled: bool) -> None:
        if enabled == self._enabled:
            return
        if enabled:
            self._activate()
            self.log.info("Surveillance activée")
        else:
            self._deactivate()
            self.log.info("Surveillance suspendue")
        if self._persist_state:
            self.settings.enabled = enabled
            self.context.settings.save()

    def _activate(self) -> None:
        if not self._hook.install():
            self.log.warning("Événements Windows indisponibles : vérification périodique seule")
        self._fallback.start()
        self._enabled = True
        QTimer.singleShot(0, self._scan_all)  # un popup déjà affiché est traité tout de suite
        self.state_changed.emit()

    def _deactivate(self) -> None:
        self._hook.uninstall()
        self._fallback.stop()
        self._pending = None
        was_enabled = self._enabled
        self._enabled = False
        if was_enabled:
            self.state_changed.emit()

    def apply_settings(self) -> None:
        """À appeler après modification de ``self.settings`` (catégorie de la boîte Paramètres)."""
        self.settings.normalized()
        self._patterns = matching.normalize_patterns(self.settings.titles)
        self._fallback.setInterval(self.settings.fallback_scan_ms)
        self._cooldowns.clear()
        self.context.settings.save()
        s = self.settings
        self.log.info(
            "Réglages appliqués : titres=%s, processus=%s, restauration du focus=%s, notification=%s",
            s.titles,
            s.process_name,
            "oui" if s.restore_focus else "non",
            "oui" if s.notify else "non",
        )
        self.state_changed.emit()

    # ---- détection --------------------------------------------------------------
    def _on_win_event(self, _event: int, hwnd: int) -> None:
        """Rappel Windows : doit rester très court (il s'exécute dans la boucle de l'interface)."""
        if not self._enabled or self._pending is not None:
            return
        api = self._api
        if not api.is_top_level(hwnd):
            return
        title = api.window_title(hwnd)
        if matching.title_matches(title, self._patterns):
            QTimer.singleShot(0, lambda: self._guarded(self._consider, hwnd, title))

    def _scan_all(self) -> None:
        if not self._enabled or self._pending is not None:
            return

        def scan() -> None:
            for hwnd, title in self._api.enum_visible_windows():
                if matching.title_matches(title, self._patterns) and self._consider(hwnd, title):
                    return

        self._guarded(scan)

    def _guarded(self, fn, *args) -> None:
        """Une exception ne doit jamais arrêter la surveillance ; journal limité à une par 10 s."""
        try:
            fn(*args)
        except Exception:
            self._pending = None
            now = monotonic()
            if now - self._last_error_log >= ERROR_LOG_MIN_INTERVAL_S:
                self._last_error_log = now
                self.log.exception("Erreur dans la surveillance")

    def _consider(self, hwnd: int, title: str) -> bool:
        """Examine une fenêtre au bon titre ; vrai si une validation démarre."""
        if not self._enabled or self._pending is not None:
            return False
        api = self._api
        now = monotonic()
        self._cooldowns.prune(now, api.is_window)
        if self._cooldowns.active(hwnd, now) or not api.is_window_alive(hwnd):
            return False
        process = api.window_process_name(hwnd)
        if not matching.same_process(process, self.settings.process_name):
            self._cooldowns.add(hwnd, matching.FOREIGN_COOLDOWN_S, now)
            self.log.info(
                "Fenêtre ignorée « %s » : processus « %s » différent de « %s »",
                title,
                process or "?",
                self.settings.process_name,
            )
            return False
        self.log.info(
            "Détection : « %s » (hwnd=0x%X, classe=%s, processus=%s)",
            title,
            hwnd,
            api.window_class_name(hwnd),
            process,
        )
        self._pending = _Pending(hwnd=hwnd, title=title, previous_foreground=api.get_foreground_window())
        self._attempt()
        return True

    # ---- validation -------------------------------------------------------------
    def _attempt(self) -> None:
        pending = self._pending
        if pending is None:
            return
        pending.attempt += 1
        api = self._api
        if not api.is_window_alive(pending.hwnd):
            self._finish(success=True, note="fermée avant l'envoi")
            return
        retries = self.settings.max_retries
        if api.force_foreground(pending.hwnd):
            sent = api.send_enter()
            self.log.info(
                "Envoi d'Entrée (tentative %d/%d)%s", pending.attempt, retries, "" if sent else " : SendInput a échoué"
            )
        else:
            # Sans focus sur le popup, Entrée irait à une autre application : on s'abstient.
            self.log.warning(
                "Mise au premier plan impossible (tentative %d/%d), Entrée non envoyée", pending.attempt, retries
            )
        QTimer.singleShot(self.settings.retry_delay_ms, lambda: self._guarded(self._verify))

    def _verify(self) -> None:
        pending = self._pending
        if pending is None:
            return
        if not self._api.is_window_alive(pending.hwnd):
            self._finish(success=True)
        elif pending.attempt < self.settings.max_retries:
            self._attempt()
        else:
            self._finish(success=False)

    def _finish(self, success: bool, note: str = "") -> None:
        pending, self._pending = self._pending, None
        if pending is None:
            return
        now = monotonic()
        if not success:
            self._cooldowns.add(pending.hwnd, matching.FAIL_COOLDOWN_S, now)
            self.log.warning(
                "Échec : « %s » toujours affichée après %d tentative(s) ; nouvel essai dans %d s",
                pending.title,
                pending.attempt,
                matching.FAIL_COOLDOWN_S,
            )
            return
        self.validation_count += 1
        self._cooldowns.add(pending.hwnd, matching.SUCCESS_COOLDOWN_S, now)
        self.last_validation = datetime.now().strftime("%H:%M:%S")
        self.log.info("Validé : « %s »%s", pending.title, f" ({note})" if note else f" après {pending.attempt} tentative(s)")
        self._restore_focus(pending)
        self.validated.emit(pending.title)
        if self.settings.notify:
            self.notification.emit(tr("“{title}” was confirmed automatically (Update).").format(title=pending.title))
        self.state_changed.emit()

    def _restore_focus(self, pending: _Pending) -> None:
        if not self.settings.restore_focus:
            return
        api = self._api
        previous = pending.previous_foreground
        if not previous or previous == pending.hwnd or not api.is_window(previous):
            return
        # Le focus n'est rendu que s'il est resté chez FT Optix Studio (ou nulle part) :
        # si l'utilisateur a entre-temps cliqué ailleurs, on ne le dérange pas.
        current = api.get_foreground_window()
        if current and not matching.same_process(api.window_process_name(current), self.settings.process_name):
            return
        if api.force_foreground(previous):
            self.log.info("Focus rendu à « %s »", api.window_title(previous))
        else:
            self.log.warning("Impossible de rendre le focus à la fenêtre précédente")

    # ---- intégration à la coquille ------------------------------------------------
    def background_notice(self) -> str:
        return tr(
            "OptixPlus keeps running in the background: it goes on confirming the “Project already exists” "
            "prompt of FT Optix Studio automatically. To quit it, right-click its icon in the notification "
            "area, then Quit."
        )

    def status_text(self) -> str:
        state = tr("active") if self._enabled else tr("suspended")
        count = tr_n("{n} confirmation", "{n} confirmations", self.validation_count).format(n=self.validation_count)
        return tr("Monitoring {state} · {count}").format(state=state, count=count)

    def tray_actions(self, parent: QObject) -> list[QAction | None]:
        toggle = QAction(tr("Monitoring active"), parent)
        toggle.setCheckable(True)
        toggle.setChecked(self._enabled)
        toggle.toggled.connect(self.set_enabled)
        CheckedSync(toggle, self.state_changed, lambda: self._enabled)
        return [toggle]

    def summary_widget(self, parent: QWidget) -> QWidget | None:
        from .ui.summary import MonitoringSummary

        return MonitoringSummary(self, parent)
