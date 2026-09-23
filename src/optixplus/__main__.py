"""Point d'entrée : ``python -m optixplus`` ou l'exécutable construit."""

from __future__ import annotations

import sys


def main() -> int:
    argv = sys.argv[1:]
    if argv and argv[0] == "linkcheck":
        from .modules.linkcheck.cli import main as linkcheck_main

        return linkcheck_main(argv[1:])
    from .app import main as app_main

    return app_main(argv)


if __name__ == "__main__":
    sys.exit(main())
