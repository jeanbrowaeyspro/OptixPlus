"""Script d'entrée de l'exécutable PyInstaller (le paquet reste importé en absolu)."""

import sys

from optixplus.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
