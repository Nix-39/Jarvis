"""
Draws the app icon: a white-hot magenta star (like Nexus in the interface)
inside a black hexagon with a magenta edge (the same shape as the agents).

    python scripts/make_icon.py

Writes ui/assets/app.png (256 px, window/tray/favicon) and
ui/assets/app.ico (16-256 px, shortcuts and taskbar). Needs Pillow.
After a change, run scripts/install_desktop.ps1 again so Windows picks up the
new icon for the shortcuts.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ASSETS = Path(__file__).resolve().parent.parent / "ui" / "assets"
N = 1024                      # drawn large, scaled down for every size
C = N / 2
MAGENTA = (255, 46, 196)
BLACK = (10, 8, 12)
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def star(long: float, short: float, waist: float) -> list[tuple[float, float]]:
    """Four-point star: vertical tips `long`, horizontal tips `short`, thin `waist` between."""
    points = []
    for k in range(8):
        angle = -math.pi / 2 + k * math.pi / 4
        radius = waist if k % 2 else (long if k % 4 == 0 else short)
        points.append((C + math.cos(angle) * radius, C + math.sin(angle) * radius))
    return points


def hexagon(radius: float) -> list[tuple[float, float]]:
    return [(C + math.cos(math.pi / 6 + k * math.pi / 3) * radius, C + math.sin(math.pi / 6 + k * math.pi / 3) * radius)
            for k in range(6)]


def glow(draw_shape, blur: float, color: tuple[int, int, int], strength: float = 1.0) -> Image.Image:
    mask = Image.new("L", (N, N), 0)
    draw_shape(ImageDraw.Draw(mask))
    mask = mask.filter(ImageFilter.GaussianBlur(blur))
    layer = Image.new("RGBA", (N, N), color + (0,))
    layer.putalpha(mask.point(lambda v: int(v * strength)))
    return layer


def draw_icon() -> Image.Image:
    img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.polygon(hexagon(505), fill=MAGENTA + (255,))
    d.polygon(hexagon(470), fill=BLACK + (255,))

    s = 0.84
    outer = star(470 * s, 400 * s, 95 * s)
    inner = star(300 * s, 255 * s, 55 * s)
    img.alpha_composite(glow(lambda m: m.polygon(outer, fill=255), 60 * s, MAGENTA, 0.9))
    d.polygon(outer, fill=MAGENTA + (255,))
    img.alpha_composite(glow(lambda m: m.polygon(inner, fill=255), 18 * s, (255, 255, 255)))
    d.polygon(inner, fill=(255, 235, 250, 255))
    r = 70 * s
    img.alpha_composite(glow(lambda m: m.ellipse([C - r, C - r, C + r, C + r], fill=255), 30 * s, (255, 255, 255)))

    edge = Image.new("L", (N, N), 0)                 # nothing outside the hexagon
    ImageDraw.Draw(edge).polygon(hexagon(505), fill=255)
    img.putalpha(ImageChops.multiply(img.getchannel("A"), edge))
    return img


def main() -> None:
    icon = draw_icon()
    icon.resize((256, 256), Image.LANCZOS).save(ASSETS / "app.png", optimize=True)
    icon.save(ASSETS / "app.ico", sizes=ICO_SIZES)
    print(f"Wrote {ASSETS / 'app.png'} and {ASSETS / 'app.ico'}")


if __name__ == "__main__":
    main()
