"""Point d'entrée : ``python -m optixplus`` ou l'exécutable construit."""

from __future__ import annotations

import sys


def main() -> int:
    from .app import main as app_main

    return app_main(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
