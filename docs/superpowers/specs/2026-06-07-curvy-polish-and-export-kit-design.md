# Maze Designer — Curvy Polish + Export Kit (Design Spec)

**Date:** 2026-06-07 · **Branch:** `curvy` · **Status:** approved design, pre-implementation
**Prod backup tag:** `backup-prod-2026-06-07` (main @3d6ef4b)

## Goal
Make the curvy render's small loop **islands** and dead-end **wall tips** render as clean shapes (no
teardrops), rebuild the curvy smoothing on **arc-fillets** (exact, CAM-native), and add an **Export
Kit** that gives an editable "kit of parts" plus clean, Pathfinder-ready cut geometry plus an info
sheet — bundled. All curvy-only; square mode is untouched.

## Background / why (see also `docs/research/2026-06-07-curve-geometry-and-export.md`)
- Teardrop islands are a side-effect of carving smoothed channels and leaving the island as *negative
  space*; fix = detect islands explicitly and paint them as rounded shapes.
- Arcs+lines are **closed under offset** (exact cut outlines); Béziers aren't. So the smoothing engine
  moves to arc-fillets, which also unlocks exact export geometry.
- Working prototypes exist and are validated: `island-poc.html` (island/tip detection + rounded
  rendering), `smoothing-style.html` (arc-fillet vs Bézier), `export-examples.html` (raw / grooves /
  walls representations). The build ports proven code from these.

## Scope & phasing
- **Phase 1 — Curvy arc-fillet engine + island/tip polish** (on-screen render). Ships the visual fix.
- **Phase 2 — Export Kit** (raw + polished + info doc + zip), built on the arc engine.
- **Parked:** Bézier smoother retained, dormant (not deleted, not wired to clean export).
- **Future phase (not now):** "Organic" mode (coral/brain) via reaction-diffusion / differential
  growth / space colonization + spline rendering; app-side boolean union for non-vector users;
  full project save/load file.

---

## Phase 1 — Curvy arc-fillet engine + island/tip polish

### 1a. Arc-fillet smoothing (replace Bézier as default)
- New corner-rounding builds each turn as a **circular arc** tangent to both edges, radius
  `r = min(d1,d2) * 0.5 * smoothing` (same cut-back as today). Canvas: `ctx.arcTo(p1,p2,r)`. SVG: `A`
  command with computed tangent points + radius.
- Collinear points stay straight (no fillet). Straight runs stay straight; only real turns fillet.
- **Keep the existing quad-Bézier smoother** as a named, unused function (e.g. `smoothBezierPath` /
  `smoothBezierSvgD`) behind a style constant. Default path = arc.
- Smoothing slider semantics unchanged to the user (Round→Organic), now = corner radius 0…½ cell.

### 1b. Island polish (connected-component detection + rounded redraw)
Detect wall-blobs disconnected from the boundary frame, repaint each as a rounded shape.
- **Wall lattice:** vertices at cell corners; a lattice edge is "wall" when the cell-boundary it lies
  on is closed (or is an inside/outside boundary = frame). `wallH/wallV` from `S.cmap` + `cell.walls`,
  with inside/outside handling for arbitrary polygon boundaries (frame = any edge with exactly one
  inside neighbor).
- **Main structure** = flood-fill from all frame edges. **Islands** = every remaining connected
  component of interior wall vertices/edges (points, bars, L/T blobs).
- **Render per island:** erase its blocky footprint to passage, then repaint rounded — edges as plain
  bars (width = wall), vertices as rounded squares (corner radius `r = smoothing * (wall/2)`).
  → square (sm 0) → squircle → circle (sm 1) for pillars; rectangle → stadium for bars.
- Half-width `HALF = (cell - passage)/2 = wall/2`. (Reference impl: `islandComponents`, `drawIslands`
  in `island-poc.html`.)

### 1c. Wall-finger tip caps
- **Tips** = interior lattice vertices with exactly one incident wall edge (degree-1 dead-end walls).
- Render: **additive rounded cap only** (wall-colored rounded square, radius `r = smoothing*(wall/2)`)
  at the tip vertex. Never redraw the tip's edge (that fights the curved corridors and leaves seams).
  (Reference impl: `wallTips` + additive cap loop in `island-poc.html`.)

### 1d. Defensive guard
- Guard `drawCurvyFillets` / curvy draw against non-positive zoom (`S.vs <= 0`) — observed crash
  ("arc radius negative") when the canvas is unsized. Skip/clamp rather than throw.

### Phase 1 integration points (`index.html`)
- `smoothCanvasPath` / `smoothSvgD` → arc default (+ parked bézier variants).
- `drawCurvyMaze`: after channels + existing fillets, run island pass + tip caps.
- `buildSVG` curvy branch: emit island + tip shapes (for on-screen-parity preview export; the *clean*
  cut export is Phase 2).

---

## Phase 2 — Export Kit

On **Export**, produce a `.zip` (hand-rolled **store-only** ZIP — preserves the no-dependency,
single-file rule) containing:

### 2a. `maze-raw.svg` — editable "kit of parts"
- Named layers/groups so a whole category is selectable: `boundary`, `channels` (editable smoothed
  centerlines), `doors`, `islands`, `solution`, `dead-ends`, `goal`.
- Path-based / editable. Honors the existing per-layer include toggles.

### 2b. `maze-polished.svg` — clean, Pathfinder-ready cut geometry
- Built on the **arc engine**: passage edges = centerline offset ±½ passage = exact arcs+lines;
  islands = circles/stadiums/rounded-rects.
- **Two labeled layers, both included** (they are inverses — same outline data, opposite side):
  - `cut-grooves` — passages as filled closed shapes (islands are clean holes).
  - `cut-walls` — boundary minus passages (islands are filled standing blobs).
- Pieces overlap correctly → **one Pathfinder ▸ Unite per layer** in the user's tool. (Option **B**:
  app does not compute the boolean union itself — yet. Arc geometry means the *pieces* are exact, so
  no Outline-Stroke step needed.)

### 2c. `maze-info.txt` — the data sheet
- Board size, runner ⌀, passage/wall, cell size, grid type, seed, render mode + smoothing, solution
  length, dead-end / loop / island counts, layer manifest.

### Phase 2 notes
- Square exports can reuse the same bundle/info wrapper later, but have no polish geometry problem;
  not a priority.

---

## Decisions (settled in brainstorming)
- **Export matches the preview** (whatever smoothing) — no separate forced "round" look. (Arc makes
  this exact + clean.)
- **Both groove + wall layers** shipped; user picks. No need to choose a cut convention up front.
- **Option B** for the union step (user runs one Unite) — app emits exact, correctly-overlapping
  pieces. App-side union is a documented future option for non-vector users.
- **Arc-fillets default; Bézier parked.** Visual difference is negligible; the win is exact offsets.

## Out of scope / future
- Organic (coral/brain) generators + spline rendering.
- App-computed boolean union / single merged outline (for users without vector tools).
- Full project save/load file (everything-editable + preview).
- Arc-fillet exposed as an explicit user-facing alt to Bézier (kept dormant for now).

## Verification plan
- Per the project's prototype-validation norm: serve locally, `node --check` the extracted `<script>`,
  validate SVG via DOMParser / `xmllint`.
- Visual: square / curvy-0 / curvy-1 sweep on a braided maze (islands clean, no teardrops, no seams);
  pixel-spot-check island/bar/tip connectivity + rounding (as done in the prototypes).
- Export: open `maze-raw.svg` and `maze-polished.svg` in Illustrator; confirm layers select cleanly
  and one Unite per polished layer yields clean cut geometry; validate the zip opens.
- Test on the `curvy` Netlify preview before any merge. Merge path: `curvy → dev → main`.

## Risks
- Arc offset inner-corner cases (fillet < ½ passage) — finite, handle explicitly.
- Inside/outside frame logic for arbitrary polygon boundaries (Phase 1b) — the prototype assumed a
  rect; generalize and test on a non-rect preset.
- Store-only ZIP correctness — validate the archive opens on macOS + extracts all three files.
