"""Lance OptixPlus depuis les sources, sans installation du paquet.

Usage : ``python lancer.py`` (mode découverte) ou ``python lancer.py --installe`` (tray).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from optixplus.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
