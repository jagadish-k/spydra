# Spydra mark — construction geometry

All variants derive from one 64×64 grid. Nothing is drawn by eye; every
coordinate below comes from the same hexagonal lattice, which is why the
mark stays crisp when scaled and why the favicon is a true subset rather
than a redrawing.

## Lattice

Centre `C = (32, 32)`. Six directions at 60° intervals, starting at −90°
(a vertex at top, so the mark reads as upright rather than rotated):

    θ ∈ { −90°, −30°, 30°, 90°, 150°, 210° }
    P(r, θ) = (32 + r·cos θ, 32 + r·sin θ)

| Ring | r | Role |
| --- | --- | --- |
| Hub | 4 | Radial strands begin here, hidden under the spider |
| Inner chord ring | 12 | First polygonal ring |
| Outer chord ring | 20 | Second polygonal ring |
| Node ring | 26 | Device glyph centres; radials terminate here |

Chords are straight lines between adjacent vertices, not arcs — real orb
webs are built from straight silk between radials, and straight chords
also stay sharp at 16 px where a curve turns to mush.

### Vertex coordinates

    r=12 : (32,20) (42.39,26) (42.39,38) (32,44) (21.61,38) (21.61,26)
    r=20 : (32,12) (49.32,22) (49.32,42) (32,52) (14.68,42) (14.68,22)
    r=26 : (32,6)  (54.52,19) (54.52,45) (32,58) (9.48,45)  (9.48,19)

## Device node glyph

A 6.4 × 6.4 rounded square (r 1.6, stroke 1.3) with a filled 2.4 × 2.4
rounded square inside it: bezel plus screen. Orientation-neutral, so the
same glyph works at all six positions — six upright monitors around a
hexagon reads as clip-art, this reads as a topology.

Below 24 px the inner square is dropped; below 16 px the whole web is
dropped (see the favicon variant).

## Spider

Two circles on the vertical axis, legs as four mirrored pairs of
two-segment strokes with a bend at the joint:

    abdomen        C (32, 35.6)  r 4.2
    cephalothorax  C (32, 29.4)  r 2.8

    leg 1  (30,29.0) → (23.0,24.6) → (18.8,26.6)
    leg 2  (30,31.2) → (22.2,30.2) → (17.0,33.0)
    leg 3  (30,33.6) → (22.2,35.2) → (18.0,39.2)
    leg 4  (30,35.8) → (23.2,39.0) → (19.8,44.0)

Right side mirrors through x = 32. Stroke 1.6, round caps and joins.

No eyes, no fangs, no hair. It is a weaver and a sensor, not a threat.
