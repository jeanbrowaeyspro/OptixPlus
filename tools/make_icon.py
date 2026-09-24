"""Génère les icônes .ico et .png de l'application à partir des SVG maîtres.

Icône OptixPlus : l'icône de FT Optix Studio reproduite en vectoriel (relevée au pixel
sur son 64 px), en violet, le « x » tourné de 45° en « + ».
La variante grise signale la surveillance suspendue.

Chaque taille est rendue directement depuis le vecteur (pas de réduction d'une grande
image), ce qui garde les petites tailles nettes.

Usage : ``python tools/make_icon.py``
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ICON_DIR = Path(__file__).resolve().parent.parent / "src" / "optixplus" / "resources" / "icons"
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def render(svg_path: Path, size: int) -> Image.Image:
    renderer = QSvgRenderer(QByteArray(svg_path.read_bytes()))
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return Image.open(io.BytesIO(bytes(buffer.data().data()))).convert("RGBA")


def build(name: str) -> None:
    svg = ICON_DIR / f"{name}.svg"
    images = [render(svg, s) for s in SIZES]
    largest = images[-1]
    largest.save(ICON_DIR / f"{name}_256.png")
    largest.save(
        ICON_DIR / f"{name}.ico",
        format="ICO",
        sizes=[(s, s) for s in SIZES],
        append_images=images[:-1],
    )
    print(f"{name}.ico / {name}_256.png générés")


def main() -> int:
    QGuiApplication(sys.argv[:1])
    for name in ("app", "app_suspended"):
        build(name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
