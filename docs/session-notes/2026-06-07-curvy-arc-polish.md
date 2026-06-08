# Session Notes — 2026-06-07 — Curvy arc-fillet engine + island/tip polish (Phase 1)

Phase 1 of the curvy-polish + Export-Kit work (spec: `docs/superpowers/specs/2026-06-07-curvy-polish-and-export-kit-design.md`,
plan: `docs/superpowers/plans/2026-06-07-curvy-arc-polish-phase1.md`). Built via subagent-driven
development with controller (browser) verification. **On `curvy` branch; NOT merged** — hold for user
sign-off on the preview + Phase 2.

## What shipped
- **Arc-fillet smoothing is now the default** (`smoothCanvasPath` via `ctx.arcTo`; `smoothSvgD` emits
  `L`+`A` true arcs). The old quad-Bézier smoothers are **parked** as `smoothBezierPath` /
  `smoothBezierSvgD` (defined, never called) for a future "soft/organic" style. Rationale: arcs+lines
  are closed under offset → exact CAM-clean export later; visually ~identical to Bézier at maze scale.
  SVG arc **sweep flag** (`cross<0?1:0`) visually verified to match the canvas.
- **Island polish** — `islandComponents(cmap,N)` + `wallTips(cmap)` + helpers
  (`_wallH/_wallV/_allIn/_frameVtx/_bounds`) detect wall-lattice components disconnected from the
  boundary frame, and degree-1 dead-end wall tips. Boundary-agnostic (frame = vertex touching ≥1
  inside and ≥1 outside cell) — works on rect AND polygon (hex) boundaries.
- **`drawCurvyIslands(C)`** (called in `drawCurvyMaze` after `drawCurvyFillets`, before `ctx.restore()`):
  - **Single-vertex pillars** (2×2-loop centers) → erase footprint to passage, repaint a rounded shape
    in wall color, radius = `(wall/2)·smoothing` → square (sm 0) → squircle → circle (sm 1).
  - **Wall tips** → additive rounded caps (never redraw the edge).
- **Negative-zoom guard** in `drawCurvyMaze` (`if(!(S.vs>0))return;`) — fixes a headless/unsized-canvas
  crash (negative arc radius).

## Key refinement (found in verification)
The island repaint is **limited to single-vertex pillars**. Heavy braiding (e.g. 85%) fragments the wall
structure into large disconnected blobs that `islandComponents()` correctly flags as islands; erase+
repainting *those* left faint seam/notch artifacts across the plate. Only single-vertex pillars actually
erode into teardrops. **Bars / L / T / large fragments render fine as the solid plate**, and their
dead-ends are rounded by the wall-tip caps (= clean stadiums for free). Net: zero artifacts.

## Verified
- `bash test/extract-check.sh` → `node --check OK`; `node test/island-geom.test.js` → `OK`.
- Browser sweep on a braided maze: curvy sm=1 (clean circle islands, no teardrops, no seams, rounded
  tips), sm=0 (clean squares), and **square mode unchanged**.
- Non-rect **hex** boundary: islands/tips detected correctly (no mis-detection at the angled edge),
  clean render.
- SVG: valid XML; 0 `Q` commands, channels now arc (`A`); sweep matches canvas.

## Known minor items (carry into Phase 2 / sign-off — non-blocking)
- Canvas vs SVG fillet radius diverges slightly at sub-53° corners (cosmetic, export-side; 90° corners
  agree exactly). Fold into Phase 2 export work.
- Tip-cap vs `_open` complexity-chamber interaction unverified (low likelihood/severity) — spot-check in
  a high-complexity custom-path maze.
- `drawCurvyIslands` keeps a now-no-op multi-vertex edge loop (intentional — door open for re-enabling
  bar repaint if ever wanted).

## Next
- **Phase 2 — Export Kit** (raw layered SVG + polished both-layer cut geometry + info doc + zip), built
  on the arc engine. Then merge path `curvy → dev → main` after sign-off.
- Prod backup tag: `backup-prod-2026-06-07`.

## Follow-up fixes (preview feedback)
- **Hairline seams** (commit 23e2d60): wall-colored island/tip repaints butted against the carved
  channels left a 1px antialiasing sliver. Sealed with a thin same-color stroke on the wall draws.
- **Perimeter wall + door gates** (commit 58a8634): grid was fit to the *board*, so outermost passages
  clipped the boundary (no rim). Now `gridFit()` fits the grid to the **boundary** inset by
  `wall+passage/2` (shared by `buildPreviewGrid`+`genOrtho`), leaving a full perimeter wall; the maze
  generates inside it. Doors ray-cast (`boundaryHit`) from the door cell through the new wall to the
  actual boundary edge, so entry/exit gates still reach the rim — canvas render + SVG export. Verified
  rect+hex perimeter, door notches, solve, square mode, SVG validity.
