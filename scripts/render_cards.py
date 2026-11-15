#!/usr/bin/env python3
"""Draw the profile README cards as animated SVGs, and the README that lays them out.

    GITHUB_TOKEN=... python3 scripts/render_cards.py

Fetches the contribution calendar into data/contributions.json (or reuses the
cached one when there is no token), writes every card into cards/ and rewrites
README.md. STATIC=1 draws each card at its final frame, for a screenshot.

The palette and type are arthur-babkin.vercel.app's: ultramarine, lime, ink on
pale paper; Unbounded for figures and headings, Manrope for text. Every card is
a solid block, so one version reads on GitHub's light and dark themes alike.

Spacing. GitHub strips every style from a README, so no gap between two
pictures can be trusted to the page: a space between tags is a few pixels
here and none there, and a paragraph adds 16px only where markdown decided it
was a paragraph. So the gaps are drawn into the cards themselves. Every card
carries a transparent GX margin either side and GY below it, the README has no
whitespace between its tags, and every picture is align="top" so it does not
sit on a text baseline with a strip of line-height under it. Two cards side by
side are then 2*GX apart, two rows GY apart, and the outer edges of every row
line up. Inside, every card keeps P to its own edge.
"""
import base64
import datetime as dt
import json
import math
import os
import re
import urllib.request
from collections import OrderedDict
from pathlib import Path
from xml.sax.saxutils import escape

from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "scripts" / "fonts"
CARDS = ROOT / "cards"
DATA = ROOT / "data" / "contributions.json"
README = ROOT / "README.md"
LOGIN = "ArthurBabkin"
STATIC = os.environ.get("STATIC") == "1"

BLUE, LIME, INK = "#4200ff", "#d4ff3a", "#0b0b12"
PAPER = "#f3f3f1"  # the light cards: a cooler, quieter grey than the site's paper
WHITE, MUTED, LINE = "#ffffff", "#5d5d6b", "#d6d6cf"
EASE = "cubic-bezier(0.23, 1, 0.32, 1)"  # the site's one curve

# the grid, as on the site: 12px between blocks
GX, GY = 6, 12          # transparent margin: each side, and below
ROW = 892               # one row of the README, margins included
FULL = ROW - 2 * GX     # 880, a full-width card
P = 32                  # every card's inner padding
R = 28                  # the site's block radius

FAMILY = {"ub8": ("Unbounded", 800), "ub6": ("Unbounded", 600), "gm8": ("Geist Mono", 800),
          "mr5": ("Manrope", 500), "mr7": ("Manrope", 700)}
_fonts = {k: TTFont(FONTS / f"{k}.woff") for k in FAMILY}


def width(s, font, size, tracking=0.0):
    f = _fonts[font]
    cmap, hmtx, upm = f.getBestCmap(), f["hmtx"], f["head"].unitsPerEm
    return sum(hmtx[cmap.get(ord(c), ".notdef")][0] for c in s) / upm * size + tracking * len(s)


def css(*fonts, extra=""):
    faces = "".join(
        f"@font-face{{font-family:'{FAMILY[k][0]}';font-weight:{FAMILY[k][1]};"
        f"src:url(data:font/woff;base64,{base64.b64encode((FONTS / f'{k}.woff').read_bytes()).decode()}) format('woff')}}"
        for k in fonts
    )
    return faces + f"""
text{{font-family:'Manrope',system-ui,sans-serif;font-weight:500}}
.d{{font-family:'Unbounded','Arial Black',sans-serif;font-weight:800}}
.d6{{font-family:'Unbounded','Arial Black',sans-serif;font-weight:600}}
.b{{font-weight:700}}
.cap{{font-family:'Manrope',sans-serif;font-weight:700;letter-spacing:.14em}}
.r{{opacity:0;animation:rise .8s {EASE} forwards}}
@keyframes rise{{from{{opacity:0;transform:translateY(16px)}}to{{opacity:1;transform:none}}}}
@keyframes fade{{to{{opacity:1}}}}
{extra}
@media (prefers-reduced-motion:reduce){{*{{animation:none!important}}.r{{opacity:1}}}}
"""


def svg(w, h, style, body, label):
    """A card of w×h, drawn inside its share of the grid's margins."""
    if STATIC:
        body = re.sub(r"<(animate|animateTransform|set)\b[^>]*/>", "", body)
        style = style.replace("@media (prefers-reduced-motion:reduce)", "@media all")
    W, H = w + 2 * GX, h + GY
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:g} {H:g}" width="{W:g}" height="{H:g}" '
            f'role="img" aria-label="{escape(label)}"><style>{style}</style>'
            f'<g transform="translate({GX} 0)">{body}</g></svg>\n')


def arrow(cx, cy, r, bg, fg, kind="ne", cls=""):
    """The site's round button with an arrow drawn in it, not typed."""
    s = r * 0.42
    if kind == "ne":
        d = f"M{cx - s:.2f} {cy + s:.2f}L{cx + s:.2f} {cy - s:.2f}M{cx - s * .45:.2f} {cy - s:.2f}H{cx + s:.2f}V{cy + s * .45:.2f}"
    else:
        d = f"M{cx:.2f} {cy - s:.2f}V{cy + s:.2f}M{cx - s * .8:.2f} {cy + s * .2:.2f}L{cx:.2f} {cy + s:.2f}L{cx + s * .8:.2f} {cy + s * .2:.2f}"
    return (f'<g class="{cls}"><circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r}" fill="{bg}"/>'
            f'<path d="{d}" fill="none" stroke="{fg}" stroke-width="{max(2, r * .11):.1f}" '
            f'stroke-linecap="round" stroke-linejoin="round"/></g>')


def edge(w, h, r):
    """A hairline that only shows where ink meets GitHub's own near-black."""
    return (f'<rect x=".75" y=".75" width="{w - 1.5:.2f}" height="{h - 1.5:.2f}" rx="{r - .75}" fill="none" '
            f'stroke="#ffffff" stroke-opacity=".16" stroke-width="1.5"/>')


def outline(w, h, r=R):
    return (f'<rect x="1" y="1" width="{w - 2:.2f}" height="{h - 2:.2f}" rx="{r - 1}" '
            f'fill="{PAPER}" stroke="{INK}" stroke-width="2"/>')


def chip(x, y, text, bg, fg, size=12.5):
    w, h = width(text, "mr7", size) + 26, size + 15
    return (f'<rect x="{x}" y="{y}" width="{w:.1f}" height="{h}" rx="{h / 2}" fill="{bg}"/>'
            f'<text x="{x + w / 2:.1f}" y="{y + h / 2 + size * .36:.1f}" text-anchor="middle" '
            f'class="b" font-size="{size}" fill="{fg}">{escape(text)}</text>'), w, h


# ── data ────────────────────────────────────────────────────────────────────
def contributions():
    token = os.environ.get("CARDS_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        q = ('{user(login:"%s"){contributionsCollection{contributionCalendar{totalContributions '
             'weeks{contributionDays{date contributionCount contributionLevel}}}}}}' % LOGIN)
        req = urllib.request.Request(
            "https://api.github.com/graphql", data=json.dumps({"query": q}).encode(),
            headers={"Authorization": f"bearer {token}", "User-Agent": "profile-cards"})
        with urllib.request.urlopen(req, timeout=30) as r:
            cal = json.load(r)["data"]["user"]["contributionsCollection"]["contributionCalendar"]
        DATA.parent.mkdir(exist_ok=True)
        DATA.write_text(json.dumps(cal, indent=1))
    return json.loads(DATA.read_text())


def stats(days):
    longest = run = 0
    for d in days:
        run = run + 1 if d["contributionCount"] else 0
        longest = max(longest, run)
    months = OrderedDict()
    last = dt.date.fromisoformat(days[-1]["date"])
    for i in range(11, -1, -1):  # the last twelve calendar months, this one included
        y, m = divmod(last.year * 12 + last.month - 1 - i, 12)
        months[(y, m + 1)] = 0
    for d in days:
        k = (int(d["date"][:4]), int(d["date"][5:7]))
        if k in months:
            months[k] += d["contributionCount"]
    return dict(longest=longest, months=months,
                busiest=max(days, key=lambda d: d["contributionCount"]))


# ── hero ────────────────────────────────────────────────────────────────────
# How the portrait is drawn on the blue. `fills` gives each step of the ramp,
# sparse to dense, its colour and opacity, so a tone is carried both by the
# character and by how bright it is.
def _steps(lo, hi, colour):
    return [(colour, round(lo + (hi - lo) * k / 8, 2)) for k in range(9)]


PORTRAIT = dict(file="portrait.txt", size=4.6, fills=_steps(.3, 1, LIME))


def hero():
    w, h = FULL, 380
    c1, w1, ch = chip(P, P, "LLM Research · AI products", LIME, INK)
    c2, _, _ = chip(P + w1 + 8, P, "GMT+3 · Innopolis — Kazan", INK, WHITE)

    # the portrait in characters, straight on the blue, on the right. Its rows
    # come in from the top one after another, and its neck runs off the bottom.
    rows = (DATA.parent / PORTRAIT["file"]).read_text().rstrip("\n").split("\n")
    size = PORTRAIT["size"]
    lh = size * 1.12
    cols = max(len(r) for r in rows)
    pw = cols * size * .6
    area = 400  # the right-hand part of the block the head is centred in
    px, py = w - area + (area - pw) / 2, 6
    ramp = " .:-=+*#%@"
    art = ""
    for i, r in enumerate(rows):
        if not r.strip():
            continue
        y, delay = py + (i + 1) * lh, f"animation-delay:{.3 + i * .02:.3f}s"
        for k, ch in enumerate(ramp[1:], 1):
            line = "".join(c if c == ch else " " for c in r).rstrip()
            if line.strip():
                art += f'<text class="t{k}" x="{px:.1f}" y="{y:.2f}" style="{delay}">{line}</text>'
    tiers = "".join(f".art .t{k + 1}{{fill:{c};fill-opacity:{o}}}" for k, (c, o) in enumerate(PORTRAIT["fills"]))
    style = css("ub8", "mr7", "gm8", extra=f"""
.art text{{font-family:'Geist Mono',ui-monospace,monospace;font-weight:800;font-size:{size}px;
  white-space:pre;opacity:0;animation:fade .25s ease forwards}}
{tiers}
@media (prefers-reduced-motion:reduce){{.art text{{opacity:1}}}}
""")
    x = P - 3  # Unbounded's capitals carry a little side bearing
    body = f"""
<defs><clipPath id="c"><rect width="{w}" height="{h}" rx="{R}"/></clipPath>
<linearGradient id="sh" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="220" y2="0" gradientTransform="translate(-300 0)">
  <stop offset="0" stop-color="{WHITE}"/><stop offset=".5" stop-color="{LIME}"/><stop offset="1" stop-color="{WHITE}"/>
  <animateTransform id="s" attributeName="gradientTransform" type="translate" from="-300 0" to="900 0"
    dur="1.8s" begin="1.6s;s.end+6s" fill="freeze"/>
</linearGradient></defs>
<g clip-path="url(#c)"><rect width="{w}" height="{h}" fill="{BLUE}"/>
  <g class="art" xml:space="preserve">{art}</g></g>
<g class="r" style="animation-delay:.05s">{c1}{c2}</g>
<text x="{x}" y="{h - P - 152}" class="d r" font-size="76" letter-spacing="-2" fill="url(#sh)" style="animation-delay:.2s;fill:url(#sh)">ARTHUR</text>
<text x="{x}" y="{h - P - 76}" class="d r" font-size="76" letter-spacing="-2" fill="url(#sh)" style="animation-delay:.3s;fill:url(#sh)">BABKIN</text>
<text x="{P}" y="{h - P - 28}" class="d r" font-size="21" letter-spacing="-.5" fill="{LIME}" style="animation-delay:.45s">I train language models</text>
<text x="{P}" y="{h - P}" class="d r" font-size="21" letter-spacing="-.5" fill="{LIME}" style="animation-delay:.55s">and build products on them</text>"""
    return svg(w, h, style, body, "Arthur Babkin, a portrait drawn in characters. I train language models and build "
               "products on them. LLM research and AI products. GMT+3, Innopolis — Kazan.")


# ── buttons ─────────────────────────────────────────────────────────────────
BTN_H, BTN_SIZE, ICON = 52, 15, 17


def button_widths(specs):
    """Stretch the row so it runs edge to edge, like every other row."""
    natural = [width(label, "ub6", BTN_SIZE) + 40 + (2 * ICON + 6 if kind != "line" else 0)
               for label, kind in specs]
    room = ROW - 2 * GX * len(specs)
    extra = (room - sum(natural)) / len(specs)
    assert extra >= 0, f"buttons are {-extra * len(specs):.0f}px too wide for the row"
    return [n + extra for n in natural]


def button(label, kind, w):
    """kind: lime (the CV), ink, or line (outlined, like the site's nav)."""
    h = BTN_H
    bg, fg = {"lime": (LIME, INK), "ink": (INK, WHITE), "line": (PAPER, INK)}[kind]
    icon = kind != "line"
    ic, shine = "", ""
    if kind == "lime":
        ic = arrow(w - h / 2, h / 2, ICON, INK, LIME, "down", "bob")
        shine = (f'<rect x="-60" y="-10" width="34" height="{h + 20}" fill="#fff" opacity=".45" transform="skewX(-18)">'
                 f'<animate attributeName="x" values="-60;{w + 60:.0f}" dur="1.1s" begin="1.2s;7s;13s;19s;25s"/></rect>')
    elif kind == "ink":
        ic = arrow(w - h / 2, h / 2, ICON, BLUE, WHITE, "ne", "nudge")
    # the label is centred in what the icon leaves of the button
    tx = (w - (h / 2 + ICON) + 4) / 2 if icon else w / 2
    style = css("ub6", extra=f"""
.bob{{animation:bob 2.6s ease-in-out 1.4s infinite}}
@keyframes bob{{0%,70%,100%{{transform:none}}82%{{transform:translateY(3px)}}}}
.nudge{{animation:nudge 2.8s ease-in-out 1.6s infinite}}
@keyframes nudge{{0%,70%,100%{{transform:none}}82%{{transform:translate(2px,-2px)}}}}
""")
    frame = (f'<rect x="1" y="1" width="{w - 2:.2f}" height="{h - 2}" rx="{h / 2 - 1}" fill="none" stroke="{INK}" stroke-width="2"/>'
             if kind == "line" else edge(w, h, h / 2) if kind == "ink" else "")
    body = (f'<defs><clipPath id="c"><rect width="{w:.2f}" height="{h}" rx="{h / 2}"/></clipPath></defs>'
            f'<g clip-path="url(#c)"><rect width="{w:.2f}" height="{h}" fill="{bg}"/>{shine}</g>{frame}'
            f'<text x="{tx:.1f}" y="{h / 2 + 5.4}" text-anchor="middle" class="d6" font-size="{BTN_SIZE}" fill="{fg}">'
            f'{escape(label)}</text>{ic}')
    return svg(round(w, 2), h, style, body, label)


# ── tiles ───────────────────────────────────────────────────────────────────
TILE_W = round(ROW / 3 - 2 * GX, 2)


def count_frames(end, fmt, n=18):
    return [fmt(end * (1 - (1 - (i + 1) / n) ** 3)) for i in range(n)]


def tile(bg, fg, sub, frames, lines, delay, label, ring):
    w, h = TILE_W, 236
    size = min(64, (w - 2 * P) / (width(frames[-1], "ub8", 64, -2) / 64))
    base = h - P - 21 * len(lines) - 22  # the figure sits on the text, the text on P
    start, step = delay + .35, .055
    if len(frames) == 1:
        num = f'<text x="{P - 2}" y="{base}" class="d" font-size="{size:.1f}" letter-spacing="-2" fill="{fg}">{escape(frames[0])}</text>'
    else:
        num = ""
        for i, f in enumerate(frames):
            last = i == len(frames) - 1
            s = (f'<set attributeName="visibility" to="hidden" begin="0s" dur="{start + i * step:.3f}s"/>' if last else
                 f'<set attributeName="visibility" to="visible" begin="{start + i * step:.3f}s" dur="{step:.3f}s"/>')
            num += (f'<text x="{P - 2}" y="{base}" class="d" font-size="{size:.1f}" letter-spacing="-2" fill="{fg}" '
                    f'visibility="{"visible" if last else "hidden"}">{escape(f)}{s}</text>')
    text = "".join(f'<text x="{P}" y="{h - P - 21 * (len(lines) - 1 - i)}" font-size="15.5" fill="{sub}">{escape(t)}</text>'
                   for i, t in enumerate(lines))
    r = 17
    btn = arrow(w - P - r, P + r, r, LIME if bg != LIME else INK, INK if bg != LIME else LIME, "ne", "nudge")
    style = css("ub8", "mr5", extra=f"""
.tile{{opacity:0;transform-origin:50% 100%;animation:swing .9s {EASE} {delay}s forwards}}
@keyframes swing{{0%{{opacity:0;transform:translateY(24px) rotate(2.5deg)}}
  60%{{opacity:1;transform:translateY(-3px) rotate(-.6deg)}}100%{{opacity:1;transform:none}}}}
.nudge{{animation:nudge 2.8s ease-in-out {delay + 1.2}s infinite}}
@keyframes nudge{{0%,70%,100%{{transform:none}}82%{{transform:translate(2px,-2px)}}}}
@media (prefers-reduced-motion:reduce){{.tile{{opacity:1}}}}
""")
    body = f"""
<defs><clipPath id="c"><rect width="{w}" height="{h}" rx="{R}"/></clipPath></defs>
<g class="tile"><g clip-path="url(#c)">
  <rect width="{w}" height="{h}" fill="{bg}"/>
  <circle cx="{w - P - r:.2f}" cy="{P + r}" r="0" fill="none" stroke="{ring}" stroke-width="1.4">
    <animate attributeName="r" values="{r};90" dur="3.2s" begin="{delay + .8}s" repeatCount="indefinite"/>
    <animate attributeName="opacity" values=".5;0" dur="3.2s" begin="{delay + .8}s" repeatCount="indefinite"/>
  </circle>
  <rect x="-90" y="-20" width="60" height="{h + 40}" fill="#fff" opacity=".12" transform="skewX(-18)">
    <animate attributeName="x" values="-90;{w + 120:.0f}" dur="1.3s" begin="{delay + 1.6}s;{delay + 8}s;{delay + 14}s;{delay + 20}s"/>
  </rect>
  {num}{text}{btn}
</g>{edge(w, h, R) if bg == INK else ""}</g>"""
    return svg(w, h, style, body, label)


# ── the contribution grid ───────────────────────────────────────────────────
LEVEL = {"NONE": "#e4e4dc", "FIRST_QUARTILE": "#c7b8ff", "SECOND_QUARTILE": "#9472ff",
         "THIRD_QUARTILE": "#6a3cff", "FOURTH_QUARTILE": BLUE}


def heatmap(cal):
    weeks = cal["weeks"]
    w, cell = FULL, 12
    pitch = (w - 2 * P - cell) / (len(weeks) - 1)  # the grid spans P to P
    y0 = P + 72
    grid_bottom = y0 + 6 * pitch + cell
    h = round(grid_bottom + 22 + P)
    label_y = h - P
    rects, labels, seen = [], [], set()
    for wi, wk in enumerate(weeks):
        for d in wk["contributionDays"]:
            day = dt.date.fromisoformat(d["date"])
            row = (day.weekday() + 1) % 7  # Sunday on top, as GitHub draws it
            x, y = P + wi * pitch, y0 + row * pitch
            rects.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{cell}" height="{cell}" rx="3" '
                         f'fill="{LEVEL[d["contributionLevel"]]}" style="animation-delay:{.25 + wi * .018:.3f}s"/>')
            if day.day <= 7 and row == 0 and wi > 0 and (day.year, day.month) not in seen:
                seen.add((day.year, day.month))
                labels.append(f'<text x="{x:.1f}" y="{label_y}" font-size="11.5" fill="{MUTED}">{day.strftime("%b")}</text>')
    # the legend closes the title line, flush with the grid's right edge
    title_y = P + 44
    lw_less, lw_more = width("less", "mr5", 11.5), width("more", "mr5", 11.5)
    lx = w - P - lw_more - 6 - (4 * 16 + cell) - 6 - lw_less
    sw = lx + lw_less + 6
    legend = (f'<text x="{lx:.1f}" y="{title_y - 2}" font-size="11.5" fill="{MUTED}">less</text>'
              + "".join(f'<rect x="{sw + i * 16:.1f}" y="{title_y - 12}" width="{cell}" height="{cell}" rx="3" fill="{c}"/>'
                        for i, c in enumerate(LEVEL.values()))
              + f'<text x="{w - P}" y="{title_y - 2}" text-anchor="end" font-size="11.5" fill="{MUTED}">more</text>')
    style = css("ub8", "mr5", "mr7", extra=f"""
.cells rect{{transform-box:fill-box;transform-origin:center;opacity:0;animation:pop .5s {EASE} forwards}}
@keyframes pop{{from{{opacity:0;transform:scale(.2)}}to{{opacity:1;transform:none}}}}
@media (prefers-reduced-motion:reduce){{.cells rect{{opacity:1}}}}
""")
    body = f"""{outline(w, h)}
<text x="{P}" y="{P + 8}" class="cap" font-size="11" fill="{MUTED}">REFRESHED DAILY</text>
<text x="{P - 2}" y="{title_y}" class="d r" font-size="28" letter-spacing="-.8" fill="{INK}">EVERY DAY, <tspan fill="{BLUE}">IN BLUE</tspan></text>
{legend}
<g class="cells">{"".join(rects)}</g>
{"".join(labels)}"""
    return svg(w, h, style, body, f"GitHub contributions over the last year: {cal['totalContributions']}")


# ── the year in bars ────────────────────────────────────────────────────────
def activity(cal, st):
    w, h = FULL, 396
    months = list(st["months"].items())
    peak = max(v for _, v in months) or 1
    best = max(range(len(months)), key=lambda i: months[i][1])
    sx = 640                          # the stats column, running to P
    chart_r = sx - 48                 # the bars end a gutter before it
    bw = 38
    gap = (chart_r - P - 12 * bw) / 11
    tick_y = h - P
    by = tick_y - 22                  # bars stand on the month names
    bh = by - (P + 120)               # and rise to under the headline
    bars, ticks = [], []
    for i, ((y, m), v) in enumerate(months):
        x = P + i * (bw + gap)
        bar = max(4, v / peak * bh)
        fill = BLUE if i == best else ("#c9c9c0" if i == len(months) - 1 else INK)
        bars.append(f'<rect x="{x:.1f}" y="{by - bar:.1f}" width="{bw}" height="{bar:.1f}" rx="6" fill="{fill}" '
                    f'style="animation-delay:{.3 + i * .06:.2f}s"/>')
        ticks.append(f'<text x="{x + bw / 2:.1f}" y="{tick_y}" text-anchor="middle" font-size="11.5" fill="{MUTED}">'
                     f'{dt.date(y, m, 1).strftime("%b")}</text>')
        if i == best:
            bars.append(f'<text x="{x + bw / 2:.1f}" y="{by - bar - 10:.1f}" text-anchor="middle" class="b pk" '
                        f'font-size="12.5" fill="{BLUE}">{v:,}</text>')
    busiest = st["busiest"]
    bdate = dt.date.fromisoformat(busiest["date"])
    side = [
        (f"{st['longest']}", " days" if st["longest"] != 1 else " day", "longest streak"),
        (f"{busiest['contributionCount']}", "", f"on the busiest day, {bdate.strftime('%b')} {bdate.day}"),
        (f"{months[best][1]:,}", "", f"in {dt.date(*months[best][0], 1).strftime('%B')}, the best month"),
    ]
    # three rows, the last caption on the bars' floor
    pitch = 82
    sides = ""
    for i, (big, unit, small) in enumerate(side):
        cap_y = by - (2 - i) * pitch
        y = cap_y - 26
        sides += (f'<g class="r" style="animation-delay:{.5 + i * .12:.2f}s">'
                  f'<text x="{sx - 2}" y="{y}" class="d" font-size="30" letter-spacing="-1" fill="{INK}">{big}'
                  f'<tspan class="d6" font-size="18" fill="{BLUE}">{unit}</tspan></text>'
                  f'<text x="{sx}" y="{cap_y}" font-size="13.5" fill="{MUTED}">{escape(small)}</text></g>')
        if i < 2:
            ly = cap_y + 20
            sides += f'<line x1="{sx}" x2="{w - P}" y1="{ly}" y2="{ly}" stroke="{LINE}" stroke-width="1.5"/>'
    total = f"{cal['totalContributions']:,}"
    style = css("ub8", "ub6", "mr5", "mr7", extra=f"""
.bars rect{{transform-box:fill-box;transform-origin:50% 100%;transform:scaleY(0);animation:grow .9s {EASE} forwards}}
@keyframes grow{{to{{transform:none}}}}
.pk{{opacity:0;animation:fade .3s ease 1.3s forwards}}
@media (prefers-reduced-motion:reduce){{.bars rect{{transform:none}}.pk{{opacity:1}}}}
""")
    body = f"""{outline(w, h)}
<text x="{P}" y="{P + 8}" class="cap" font-size="11" fill="{MUTED}">THE LAST 12 MONTHS ON GITHUB</text>
<text x="{P - 2}" y="{P + 54}" class="d r" font-size="38" letter-spacing="-1.4" fill="{INK}">{total} <tspan fill="{BLUE}">CONTRIBUTIONS</tspan></text>
<g class="bars">{"".join(bars)}</g>{"".join(ticks)}
{sides}"""
    return svg(w, h, style, body, f"{total} contributions in the last 12 months; longest streak {st['longest']} days.")


# ── repo cards ──────────────────────────────────────────────────────────────
REPO_W = round(ROW / 2 - 2 * GX, 2)


def repo(name, desc, tag, delay):
    w, h = REPO_W, 140
    c, _, ch = chip(P, P, tag, LIME, INK, 11.5)
    r = 15
    room = w - 2 * P
    assert width(name, "ub6", 17, -.4) <= room and width(desc, "mr5", 14) <= room, f"{name}: text runs past P"
    style = css("ub6", "mr5", "mr7", extra=f"""
.card{{opacity:0;animation:rise .8s {EASE} {delay}s forwards}}
@media (prefers-reduced-motion:reduce){{.card{{opacity:1}}}}
""")
    body = f"""
<g class="card">{outline(w, h, R - 4)}
{c}
{arrow(w - P - r, P + ch / 2, r, INK, LIME, "ne")}
<text x="{P}" y="{h - P - 24}" class="d6" font-size="17" letter-spacing="-.4" fill="{INK}">{escape(name)}</text>
<text x="{P}" y="{h - P}" font-size="14" fill="{MUTED}">{escape(desc)}</text>
</g>"""
    return svg(w, h, style, body, f"{name}: {desc}. {tag}")


# ── the page ────────────────────────────────────────────────────────────────
SITE = "https://arthur-babkin.vercel.app"
BUTTONS = [  # stem, label, kind, href
    ("btn-cv", "Download CV", "lime", f"{SITE}/cv-arthur-babkin-en.pdf"),
    ("btn-write", "Write to me", "ink", "https://t.me/theother_archeee"),
    ("btn-site", "Website", "line", f"{SITE}/en"),
    ("btn-linkedin", "LinkedIn", "line", "https://www.linkedin.com/in/arthur-babkin-19954632b/"),
    ("btn-hf", "Hugging Face", "line", "https://huggingface.co/archeee"),
]
TILES = [  # stem, href, alt
    ("tile-tbank", f"{SITE}/en#experience", "116M requests a month through the T-Bank models I work on"),
    ("tile-paper", "https://arxiv.org/abs/2609.01572", "A* paper accepted at EMNLP 2026"),
    ("tile-deeplit", f"{SITE}/en#awards", "Top-1 EdTech startup in Russia, named by HSE and Alfa-Bank, 2024"),
]
REPOS = [  # stem, title, description, badge, href — titles and figures as the site words them
    ("parimate", "PariMate", "Habit video reports checked by AI, not a moderator", "Audience prize · AIWW 2025",
     "https://github.com/ArthurBabkin/Parimate"),
    ("akbars", "Risk-Tech ML hackathon", "Price per square metre on Kazan's secondary market", "1st of 22 · Ak Bars Bank",
     "https://github.com/I-y6o-I/risk_tech_hack_akbars"),
    ("admet", "ADMET Prediction hackathon", "Drug properties from a molecule's SMILES", "2nd of 27 · Innopolis",
     "https://github.com/ArthurBabkin/ADMET_2024_Hackathon"),
    ("grantbot", "Startup grant assistant", "Fills in student startup grant applications", "300 MAU · 3-day MVP",
     "https://github.com/ArthurBabkin/stud_startup_bot"),
]


def pct(outer):
    """A card's share of the row, rounded down so a row never wraps."""
    return f"{math.floor(outer / ROW * 100000) / 1000:g}%"


def img(stem, alt, outer, href=None):
    tag = f'<img src="cards/{stem}.svg" width="{pct(outer)}" align="top" alt="{escape(alt, {chr(34): "&quot;"})}">'
    return f'<a href="{href}">{tag}</a>' if href else tag


def readme(btn_widths):
    rows = [
        [img("hero", "Arthur Babkin — I train language models and build products on them", ROW, f"{SITE}/en")],
        [img(s, label, bw + 2 * GX, href) for (s, label, _, href), bw in zip(BUTTONS, btn_widths)],
        [img(s, alt, TILE_W + 2 * GX, href) for s, href, alt in TILES],
        [img("heatmap", "GitHub contributions over the last year", ROW)],
        [img("activity", "The last 12 months on GitHub", ROW)],
        *[[img(f"repo-{s}", f"{n} — {d}. {b}", REPO_W + 2 * GX, href) for s, n, d, b, href in REPOS[i:i + 2]]
          for i in (0, 2)],
    ]
    # No whitespace anywhere between two pictures. A newline between tags is a
    # space on the page; a newline inside a tag, before its '>', is nothing.
    text = "<p>" + "<br>".join("".join(row) for row in rows) + "</p>"
    text = re.sub(r"><(?=a |/p>)", "\n><", text)
    README.write_text(text + "\n")


def main():
    CARDS.mkdir(exist_ok=True)
    cal = contributions()
    days = [d for w in cal["weeks"] for d in w["contributionDays"]]
    st = stats(days)
    btn_widths = button_widths([(label, kind) for _, label, kind, _ in BUTTONS])

    out = {
        "hero": hero(),
        "heatmap": heatmap(cal),
        "activity": activity(cal, st),
        "tile-tbank": tile(LIME, INK, INK, count_frames(116, lambda v: f"{round(v)}M"),
                           ("requests a month through", "the T-Bank models I work on"), .9, TILES[0][2], ring=INK),
        "tile-paper": tile(INK, WHITE, "#c9c9d4", ["A*"], ("paper accepted at", "EMNLP 2026"), 1.05,
                           TILES[1][2], ring=LIME),
        "tile-deeplit": tile(BLUE, LIME, WHITE, ["Top-1"], ("EdTech startup in Russia, named", "by HSE and Alfa-Bank, 2024"),
                             1.2, TILES[2][2], ring=LIME),
    }
    for (stem, label, kind, _), bw in zip(BUTTONS, btn_widths):
        out[stem] = button(label, kind, bw)
    for i, (stem, n, d, tag, _) in enumerate(REPOS):
        out[f"repo-{stem}"] = repo(n, d, tag, .2 + i * .1)
    for old in CARDS.glob("*.svg"):
        if old.stem not in out:
            old.unlink()
    for stem, s in out.items():
        (CARDS / f"{stem}.svg").write_text(s)
    readme(btn_widths)
    print(f"{len(out)} cards, {cal['totalContributions']} contributions, streak {st['longest']}")


if __name__ == "__main__":
    main()
