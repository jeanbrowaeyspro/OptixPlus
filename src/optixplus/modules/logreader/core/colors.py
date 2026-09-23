"""Utilitaires de couleur partagés par l'interface et l'export."""

from __future__ import annotations


def parse_hex(color: str) -> tuple[int, int, int]:
    """Convertit ``#RRGGBB`` (ou ``RRGGBB``) en triplet RVB."""
    value = color.lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    if len(value) != 6:
        raise ValueError(f"couleur invalide : {color!r}")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def blend(foreground: str, background: str, alpha: float) -> str:
    """Superpose *foreground* sur *background* avec l'opacité *alpha*."""
    fr, fg, fb = parse_hex(foreground)
    br, bg, bb = parse_hex(background)
    mix = lambda f, b: round(f * alpha + b * (1.0 - alpha))  # noqa: E731
    return to_hex((mix(fr, br), mix(fg, bg), mix(fb, bb)))


def relative_luminance(color: str) -> float:
    """Luminance relative WCAG, entre 0 (noir) et 1 (blanc)."""
    channels = []
    for value in parse_hex(color):
        c = value / 255.0
        channels.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def readable_text_color(background: str, dark: str = "#101114", light: str = "#F5F6F8") -> str:
    """Choisit entre un texte sombre et un texte clair selon le fond."""
    return dark if relative_luminance(background) > 0.42 else light
