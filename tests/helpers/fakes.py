"""Simulations partagées : bureau Windows (Validation auto) et API GitHub (mises à jour)."""

from __future__ import annotations

import io
import json
import urllib.error

STUDIO = "FTOptixStudio.exe"


# --------------------------------------------------------------------------- bureau Windows
class FakeWindows:
    """Bureau simulé à la place du module ``winapi`` : fenêtres (titre, processus), premier plan, Entrée.

    Aucune vraie fenêtre n'est touchée.
    """

    def __init__(self) -> None:
        self.windows: dict[int, tuple[str, str]] = {}
        self.foreground = 0
        self.can_focus = True
        self.enter_closes = True
        self.enter_count = 0
        self.hook: FakeWindows.WinEventHook | None = None
        fake = self

        class WinEventHook:
            def __init__(self, callback) -> None:
                self.callback = callback
                self.installed = False
                fake.hook = self

            def install(self) -> bool:
                self.installed = True
                return True

            def uninstall(self) -> None:
                self.installed = False

        self.WinEventHook = WinEventHook

    # fenêtres
    def open(self, hwnd: int, title: str, process: str = STUDIO) -> None:
        self.windows[hwnd] = (title, process)
        if self.hook is not None and self.hook.installed:
            self.hook.callback(0x8002, hwnd)

    def is_top_level(self, hwnd: int) -> bool:
        return hwnd in self.windows

    def window_title(self, hwnd: int) -> str:
        return self.windows.get(hwnd, ("", ""))[0]

    def window_class_name(self, hwnd: int) -> str:
        return "#32770"

    def window_process_name(self, hwnd: int) -> str:
        return self.windows.get(hwnd, ("", ""))[1]

    def is_window(self, hwnd: int) -> bool:
        return hwnd in self.windows

    def is_window_alive(self, hwnd: int) -> bool:
        return hwnd in self.windows

    def enum_visible_windows(self) -> list[tuple[int, str]]:
        return [(h, t) for h, (t, _p) in self.windows.items()]

    # focus et clavier
    def get_foreground_window(self) -> int:
        return self.foreground

    def force_foreground(self, hwnd: int) -> bool:
        if self.can_focus and hwnd in self.windows:
            self.foreground = hwnd
            return True
        return False

    def send_enter(self) -> bool:
        self.enter_count += 1
        if self.enter_closes and self.foreground in self.windows:
            del self.windows[self.foreground]
            self.foreground = 0
        return True


# --------------------------------------------------------------------------- API GitHub
class _Response(io.BytesIO):
    def __init__(self, data: bytes, headers: dict | None = None) -> None:
        super().__init__(data)
        self.headers = headers or {}


class FakeGitHub:
    """Ouvreur d'URL simulé : répond aux URL connues, lève l'erreur prévue ou 404 pour les autres."""

    def __init__(self, routes: dict[str, object]) -> None:
        self.routes = routes
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        answer = self.routes.get(request.full_url)
        if isinstance(answer, Exception):
            raise answer
        if answer is None:
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)
        data = answer if isinstance(answer, bytes) else json.dumps(answer).encode()
        return _Response(data, {"Content-Length": str(len(data))})


def release_json(tag: str, prerelease: bool = False, draft: bool = False, assets: bool = True) -> dict:
    """Publication GitHub telle que renvoyée par l'API, avec installateur et empreinte."""
    version = tag.lstrip("v")
    base = f"https://example.invalid/{version}"
    return {
        "tag_name": tag,
        "name": f"OptixPlus {version}",
        "body": f"## Nouveautés {version}",
        "html_url": f"https://github.com/x/releases/{tag}",
        "prerelease": prerelease,
        "draft": draft,
        "assets": [
            {"name": f"OptixPlus-Setup-{version}.exe", "browser_download_url": f"{base}/setup.exe", "size": 3},
            {"name": f"OptixPlus-Setup-{version}.exe.sha256", "browser_download_url": f"{base}/setup.sha256"},
        ] if assets else [],
    }


def release():
    """La publication 1.2.0 simulée, lue comme par l'application."""
    from optixplus.update import github

    return github.release_from_json(release_json("v1.2.0"))
