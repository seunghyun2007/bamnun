#!/usr/bin/env python3
"""Draw assets/bamnun.png, the desktop-entry icon.

Generated rather than committed as an opaque blob so it can be changed
without a binary diff. 밤눈 is "night eye": an eye under a crescent moon,
in the amber the overlay uses for a raised alert level.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "bamnun.png"
S = 512                       # rendered large, downscaled for smooth edges
BG = (18, 22, 32, 255)        # near-black, matches the overlay panel
AMBER = (255, 168, 40, 255)
PALE = (232, 238, 248, 255)


def main() -> int:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    d.rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * 0.22), fill=BG)

    # Eye: two arcs meeting at the corners, the almond the overlay draws too.
    cx, cy, w, h = S // 2, int(S * 0.56), int(S * 0.33), int(S * 0.20)
    d.arc([cx - w, cy - h, cx + w, cy + h], 180, 360, fill=PALE, width=int(S * 0.045))
    d.arc([cx - w, cy - h, cx + w, cy + h], 0, 180, fill=PALE, width=int(S * 0.045))

    r = int(S * 0.085)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=AMBER)
    r2 = int(S * 0.035)
    d.ellipse([cx - r2, cy - r2, cx + r2, cy + r2], fill=BG)

    # Crescent moon, carved by overlapping a background-coloured disc.
    mx, my, mr = int(S * 0.70), int(S * 0.27), int(S * 0.105)
    d.ellipse([mx - mr, my - mr, mx + mr, my + mr], fill=AMBER)
    d.ellipse([mx - mr + int(mr * 0.62), my - mr - int(mr * 0.12),
               mx + mr + int(mr * 0.62), my + mr - int(mr * 0.12)], fill=BG)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.resize((256, 256), Image.LANCZOS).save(OUT)
    print(f"wrote {OUT} (256x256)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
