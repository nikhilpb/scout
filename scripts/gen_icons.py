#!/usr/bin/env python3
"""Regenerate the PWA icons in src/scout/server/static/icons/.

A radar/scout motif: concentric rings with a sweep and a blip on a teal
square. Run with any python that has Pillow installed (it is intentionally
not a project dependency — the generated PNGs are committed):

    python3 scripts/gen_icons.py
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

OUT_DIR = Path(__file__).resolve().parent.parent / "src" / "scout" / "server" / "static" / "icons"

BG = (15, 118, 110, 255)  # teal-700, matches the app accent
FG = (255, 255, 255)
SS = 4  # supersampling factor


def _draw_mark(draw: ImageDraw.ImageDraw, size: int, scale: float) -> None:
    c = size / 2
    r_outer = size * 0.30 * scale
    r_inner = size * 0.19 * scale
    stroke = max(2, int(size * 0.022))

    sweep_deg = -38  # blip direction (degrees; PIL angles go clockwise from 3 o'clock)
    rad = math.radians(sweep_deg)

    # Sweep wedge behind the rings.
    wedge_r = r_outer * 0.97
    draw.pieslice(
        [c - wedge_r, c - wedge_r, c + wedge_r, c + wedge_r],
        start=sweep_deg,
        end=sweep_deg + 55,
        fill=FG + (38,),
    )

    for r in (r_outer, r_inner):
        draw.ellipse([c - r, c - r, c + r, c + r], outline=FG + (210,), width=stroke)

    # Needle from center towards the blip.
    bx = c + math.cos(rad) * r_outer
    by = c + math.sin(rad) * r_outer
    draw.line([c, c, bx, by], fill=FG + (210,), width=stroke)

    # Blip on the outer ring, and a center pivot.
    blip_r = size * 0.045 * scale
    draw.ellipse([bx - blip_r, by - blip_r, bx + blip_r, by + blip_r], fill=FG + (255,))
    pivot_r = size * 0.030 * scale
    draw.ellipse([c - pivot_r, c - pivot_r, c + pivot_r, c + pivot_r], fill=FG + (255,))


def make_icon(size: int, rounded: bool, content_scale: float) -> Image.Image:
    big = size * SS
    base = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(base)
    if rounded:
        radius = int(big * 0.22)
        draw.rounded_rectangle([0, 0, big - 1, big - 1], radius=radius, fill=BG)
    else:
        draw.rectangle([0, 0, big, big], fill=BG)
    # Draw the mark on its own layer: ImageDraw replaces pixels rather than
    # blending, so semi-transparent strokes drawn directly onto the background
    # would punch holes in it instead of tinting it.
    overlay = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    _draw_mark(ImageDraw.Draw(overlay), big, content_scale)
    return Image.alpha_composite(base, overlay).resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    make_icon(192, rounded=True, content_scale=1.0).save(OUT_DIR / "icon-192.png")
    make_icon(512, rounded=True, content_scale=1.0).save(OUT_DIR / "icon-512.png")
    # Maskable: full-bleed square, mark kept inside the ~80% safe zone.
    make_icon(512, rounded=False, content_scale=0.8).save(OUT_DIR / "icon-maskable-512.png")
    # iOS home-screen icon: full-bleed, iOS applies its own corner radius.
    make_icon(180, rounded=False, content_scale=0.9).save(OUT_DIR / "icon-180.png")
    print(f"wrote icons to {OUT_DIR}")


if __name__ == "__main__":
    main()
