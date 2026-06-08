# Research note — curve geometry, the curvy export, and an organic future

**Date:** 2026-06-07 · **Context:** designing the curvy "Export Kit" and choosing the smoothing engine.

## TL;DR decision
- **Core curvy engine → arc-fillets** (circular arcs + straight lines), replacing the quad-Bézier
  corner smoother as the *default*. Smoothing slider becomes a true **corner radius** (0 = straight →
  ½ cell = "really curvy").
- **Keep the Bézier smoother, parked** — dormant alt renderer, not wired to the clean export.
- **Export Kit is built on the arc engine** so it can emit exact, offsettable outlines.
- **"Organic" (coral/brain) = a future phase**, its own generator + spline rendering.

## Why arc-fillets, not Béziers (the load-bearing reason)
The export's job is to turn passage **centerlines** into cut **edges** = the centerline offset by
±½ passage. The whole thing hinges on how curves behave under offset:

| | Offset of a … | Result |
|---|---|---|
| Line | line | parallel line — **exact** |
| Circular arc | arc | concentric arc (r ± d) — **exact** |
| Bézier | — | **not a Bézier**; only approximable by subdivision |

So with **arc/line centerlines, the cut outline is itself exact arcs+lines** (`L`/`A` in SVG) — the app
can generate finished, filled, CAM-native geometry directly, no "Outline Stroke" step, no library.
With Béziers we'd be stuck approximating offsets (which is exactly why the current export leans on
Illustrator's Outline Stroke). Arc geometry is also the CAD/CAM standard: eliminates over-cutting,
smoother curvature → higher feedrates / shorter cycle times, memory-efficient, native G2/G3.

**Visual cost of the swap: ~none.** A 90° quad-Bézier corner and a quarter-circle differ by a few %
(Bézier bulges a hair fuller). Confirmed in `smoothing-style.html` — side-by-side mazes are
indistinguishable; the difference only shows in a magnified single corner.

## Caveats (so we don't oversell)
- Arc math makes *offsetting* exact; **merging** overlapping corridors into one path is still a
  boolean union. Unneeded for **fill-based** cutting (overlapping fills read as one region); needed for
  **path-based**. Either way the inputs are now clean exact arcs.
- A few **inner-corner cases** (fillet tighter than ½ passage → inside edge is a sharp corner, not an
  arc) — finite and exact, unlike the open-ended Bézier mess.
- Offset+boolean for arc/line is a solved, library-grade problem ([CavalierContours]) — hand-rollable /
  inlineable later for the "app does its own union, for users without vector tools" goal.

## Why "keep Bézier for coral/brain" needed a correction
Coral / brain-coral / gyrification forms don't come from Bézier *corner-rounding* — they come from
**generative systems**: reaction-diffusion (Gray-Scott), differential growth, space colonization.
Those produce wandering/branching **centerlines**, which you then *render* with splines/Béziers. So the
Bézier's future is real, but at the **rendering layer of a separate generator**, not as the smoother.
→ Organic is its own future phase; reference hub: [morphogenesis-resources].

## Square mode
None of this applies. Square walls are straight line segments — already clean, editable, no teardrop
islands, nothing to "polish." All curvy-only.

## Sources
- Biarc offsets (closed under offset): https://www.ag.jku.at/pubs/2006sfj.pdf
- Biarc CAM fillets (curvature/feedrate): Purdue CGVLAB, Ahn, *Computer-Aided Design* 43 (2011)
- CavalierContours (2D offset/boolean): https://github.com/jbuckmccready/CavalierContours
- morphogenesis-resources (digital morphogenesis hub): https://github.com/jasonwebb/morphogenesis-resources

[CavalierContours]: https://github.com/jbuckmccready/CavalierContours
[morphogenesis-resources]: https://github.com/jasonwebb/morphogenesis-resources
