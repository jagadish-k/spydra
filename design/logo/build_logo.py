#!/usr/bin/env python3
"""
Spydra logo generator.

One lattice, one spider, five variants. Generating rather than hand-drawing
each file is what keeps the favicon a true subset of the mark instead of a
lookalike that drifts — change the geometry here and every variant follows.

    python3 build_logo.py
"""
from __future__ import annotations

import math
from pathlib import Path

OUT = Path(__file__).parent

# ---------------------------------------------------------------- lattice ---
C = 32.0
ANGLES = [-90, -30, 30, 90, 150, 210]
R_HUB, R_INNER, R_OUTER, R_NODE = 4.0, 12.0, 20.0, 26.0


def p(r: float, deg: float) -> tuple[float, float]:
    a = math.radians(deg)
    return (round(C + r * math.cos(a), 2), round(C + r * math.sin(a), 2))


def ring(r: float) -> list[tuple[float, float]]:
    return [p(r, a) for a in ANGLES]


def polygon(r: float) -> str:
    return " ".join(f"{x},{y}" for x, y in ring(r))


# ------------------------------------------------------------------ spider ---
# Legs are defined polar, not by hand-placed points: each leg leaves the
# body at its own angle, bends back at the knee by a fixed amount, and the
# right side mirrors through x = 32. Defining them by angle is what keeps
# the four legs visually separated — hand-placed points drift parallel and
# the silhouette collapses into a blob.

HIP = (32.0, 30.6)          # common origin, on the thorax
LEG_ANGLES = [68, 31, -9, -45]   # 0° = outward horizontal, + = toward the front
R_HIP, R_KNEE, R_FOOT = 2.6, 6.6, 5.4
KNEE_BEND = 36              # degrees the lower segment drops below the upper

ABDOMEN = (32.0, 36.4, 4.6)      # larger, lower
THORAX = (32.0, 29.0, 2.4)       # smaller, upper — a visible waist between them


def _leg(angle: float) -> tuple[tuple[float, float], ...]:
    """One left-side leg as (hip, knee, foot), pointing out to the left."""
    a = math.radians(angle)
    hx = HIP[0] - R_HIP * math.cos(a)
    hy = HIP[1] - R_HIP * math.sin(a)
    kx = hx - R_KNEE * math.cos(a)
    ky = hy - R_KNEE * math.sin(a)
    b = math.radians(angle - KNEE_BEND)
    fx = kx - R_FOOT * math.cos(b)
    fy = ky - R_FOOT * math.sin(b)
    return (
        (round(hx, 2), round(hy, 2)),
        (round(kx, 2), round(ky, 2)),
        (round(fx, 2), round(fy, 2)),
    )


LEGS = [_leg(a) for a in LEG_ANGLES]


def mirror(pt: tuple[float, float]) -> tuple[float, float]:
    return (round(2 * C - pt[0], 2), pt[1])


def spider(colour: str, stroke: float = 1.35) -> str:
    parts = [f'<g fill="none" stroke="{colour}" stroke-width="{stroke}" '
             'stroke-linecap="round" stroke-linejoin="round">']
    for leg in LEGS:
        for side in (leg, tuple(mirror(q) for q in leg)):
            d = (f"M{side[0][0]},{side[0][1]} L{side[1][0]},{side[1][1]} "
                 f"L{side[2][0]},{side[2][1]}")
            parts.append(f'<path d="{d}"/>')
    parts.append("</g>")
    ax, ay, ar = ABDOMEN
    tx, ty, tr = THORAX
    parts.append(f'<circle cx="{ax}" cy="{ay}" r="{ar}" fill="{colour}"/>')
    parts.append(f'<circle cx="{tx}" cy="{ty}" r="{tr}" fill="{colour}"/>')
    return "\n    ".join(parts)


# -------------------------------------------------------------------- web ---
def web(strand: str, node: str, screens: bool = True, stroke: float = 1.1) -> str:
    out = [f'<g fill="none" stroke="{strand}" stroke-width="{stroke}" '
           'stroke-linecap="round" stroke-linejoin="round">']
    for a in ANGLES:                                  # radials, hub → node ring
        x1, y1 = p(R_HUB, a)
        x2, y2 = p(R_NODE, a)
        out.append(f'<path d="M{x1},{y1} L{x2},{y2}"/>')
    for r in (R_INNER, R_OUTER):                      # chord rings
        out.append(f'<polygon points="{polygon(r)}"/>')
    out.append("</g>")

    out.append(f'<g stroke="{node}" stroke-width="1.3" fill="none" '
               'stroke-linejoin="round">')
    for a in ANGLES:                                  # device bezels
        x, y = p(R_NODE, a)
        out.append(f'<rect x="{round(x-3.2,2)}" y="{round(y-3.2,2)}" '
                   'width="6.4" height="6.4" rx="1.6"/>')
    out.append("</g>")

    if screens:                                       # device screens
        out.append(f'<g fill="{node}">')
        for a in ANGLES:
            x, y = p(R_NODE, a)
            out.append(f'<rect x="{round(x-1.2,2)}" y="{round(y-1.2,2)}" '
                       'width="2.4" height="2.4" rx="0.6"/>')
        out.append("</g>")
    return "\n    ".join(out)


# --------------------------------------------------------------- variants ---
HEAD = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" '
        'width="{w}" height="{h}" fill="none" role="img" '
        'aria-label="{label}">\n  <title>{label}</title>\n')

INK = "#3730A3"      # brand-700  — spider
STRAND = "#CDD2DA"   # neutral-300 — web silk
NODE = "#4F56D9"     # brand-500  — devices


def mark(ink=INK, strand=STRAND, node=NODE, screens=True) -> str:
    return f"  <g>\n    {web(strand, node, screens)}\n  </g>\n  <g>\n    {spider(ink)}\n  </g>\n"


def write(name: str, body: str) -> None:
    (OUT / name).write_text(body, encoding="utf-8")
    print(f"  {name}")


def wordmark(x: float, y: float, size: float, fill: str) -> str:
    # Space Grotesk, medium, −2% tracking. Production lockups should have
    # this converted to outlines; see BRAND.md.
    return (f'<text x="{x}" y="{y}" font-family="Space Grotesk, Inter, '
            f'-apple-system, sans-serif" font-size="{size}" font-weight="500" '
            f'letter-spacing="{round(-0.02 * size, 3)}" fill="{fill}">Spydra</text>')


print("Spydra logo variants:")

# 1 — mark, full colour
write("spydra-mark.svg",
      HEAD.format(vb="0 0 64 64", w=64, h=64, label="Spydra") + mark() + "</svg>\n")

# 2 — mark, theme-adaptive (follows currentColor; for the app sidebar)
write("spydra-mark-adaptive.svg",
      HEAD.format(vb="0 0 64 64", w=64, h=64, label="Spydra")
      + '  <g opacity="0.38">\n    ' + web("currentColor", "currentColor", True)
      + '\n  </g>\n  <g>\n    ' + spider("currentColor") + "\n  </g>\n</svg>\n")

# 3 — monochrome, single ink
write("spydra-mono.svg",
      HEAD.format(vb="0 0 64 64", w=64, h=64, label="Spydra")
      + mark(ink="currentColor", strand="currentColor", node="currentColor")
      + "</svg>\n")

# 4 — horizontal lockup. Clear space = one cap height (12u) on all sides.
write("spydra-lockup-horizontal.svg",
      HEAD.format(vb="0 0 232 64", w=232, h=64, label="Spydra")
      + mark() + "  " + wordmark(78, 41.5, 27, "#16191F") + "\n</svg>\n")

# 5 — stacked lockup
write("spydra-lockup-stacked.svg",
      HEAD.format(vb="0 0 140 104", w=140, h=104, label="Spydra")
      + '  <g transform="translate(38 0)">\n' + mark() + "  </g>\n  "
      + f'<g text-anchor="middle">{wordmark(70, 95, 24, "#16191F")}</g>\n</svg>\n')

# 6 — favicon. Spider only: below 24 px the silk is thinner than a pixel
#     and the nodes collapse into noise, so they are dropped rather than
#     shrunk. Scaled 1.55× about centre to fill the tile.
write("spydra-favicon.svg",
      HEAD.format(vb="0 0 64 64", w=64, h=64, label="Spydra")
      + '  <g transform="translate(32 32) scale(1.55) translate(-32 -32)">\n    '
      + spider("#4338CA", stroke=1.45) + "\n  </g>\n</svg>\n")

print("done")
