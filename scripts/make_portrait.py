#!/usr/bin/env python3
"""Turn a cut-out portrait into the rows of characters the hero draws.

    python3 scripts/make_portrait.py photo.png [--rows 80] [--mode light|dark] [--stroke 2.2] [--out data/portrait.txt]

Run once, by hand, whenever the photo changes: it writes data/portrait.txt and
render_cards.py only ever reads that, so the daily redraw needs neither the
photo nor Pillow. The photo must have a transparent background — whatever is
transparent becomes blank, so the head sits on the hero's own blue.

Two mappings. --mode dark puts the dense characters where the photo is dark:
curls, brows, eyes and lips come out dense, the lit skin sparse, and the face
reads as a drawing. --mode light puts them where it is light: the skin comes
out dense and the hair falls back, the way a photograph prints. Either way the
edges of the features are drawn in on top as strokes, because the lids, the
nostrils and the parting of the lips carry almost no tone of their own.
"""
import argparse
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "portrait.txt"

RAMP = " .:-=+*#%@"   # sparse to dense
CELL = 0.6 / 1.12     # a monospace cell, width over line height


def main(src, rows=80, mode="light", stroke=2.2, out=OUT):
    im = Image.open(src).convert("RGBA")
    alpha = im.getchannel("A")
    bbox = alpha.point(lambda a: 255 if a > 128 else 0).getbbox()
    im, alpha = im.crop(bbox), alpha.crop(bbox)

    w, h = im.size
    cols = round(rows * (w / h) / CELL)
    grey = ImageOps.grayscale(im)
    # equalise the tones of the head only, so the transparent ground does not
    # count as black: skin, hair and the features each get their share of
    # the ramp instead of the skin taking the top of it whole
    grey = ImageOps.equalize(grey, mask=alpha.point(lambda a: 255 if a > 128 else 0))

    # brows, eyes and lips are what make a face someone's: sharpen them
    # before they are averaged into cells
    grey = grey.filter(ImageFilter.UnsharpMask(radius=6, percent=160, threshold=2))
    # and the soft lines of the drawing — lids, nostrils, the parting of the
    # lips — carry almost no tone, so their edges are drawn in as strokes
    mask = alpha.point(lambda a: 255 if a > 200 else 0).filter(ImageFilter.MinFilter(9))
    edges = ImageOps.grayscale(im).filter(ImageFilter.GaussianBlur(2)).filter(ImageFilter.FIND_EDGES)
    edges = Image.composite(edges, Image.new("L", edges.size, 0), mask)
    edges = ImageOps.autocontrast(edges, cutoff=1)

    small = grey.resize((cols, rows), Image.LANCZOS)
    small_edges = edges.resize((cols, rows), Image.BOX)
    small_alpha = alpha.resize((cols, rows), Image.LANCZOS)

    lines = []
    for y in range(rows):
        line = ""
        for x in range(cols):
            if small_alpha.getpixel((x, y)) < 110:
                line += " "
                continue
            v = small.getpixel((x, y)) / 255
            if mode == "dark":
                v = 1 - v
            v = max(v, min(1, stroke * small_edges.getpixel((x, y)) / 255))
            line += RAMP[min(len(RAMP) - 1, 1 + int(v * (len(RAMP) - 1)))]
        lines.append(line.rstrip())
    out = Path(out)
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    print(f"{rows} rows × {cols} columns, {mode} → {out}")


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("photo")
    a.add_argument("--rows", type=int, default=80)
    a.add_argument("--mode", choices=("light", "dark"), default="light")
    a.add_argument("--stroke", type=float, default=2.2)
    a.add_argument("--out", default=OUT)
    o = a.parse_args()
    main(o.photo, o.rows, o.mode, o.stroke, o.out)
