# Session Notes — 2026-06-07 — Feature pass + Curvy render mode

Extended session continuing from the 2026-06-06 migration. Two big arcs: (1) a broad UX/feature
pass shipped to `main`, and (2) the **curvy render mode** prototyped and integrated on the `curvy`
branch (not yet merged). Captures the decisions + rationale; see `CLAUDE.md` for the live
architecture.

## Infra / workflow established
- **Git-based CD** (Netlify deploy-key + push webhook — not the GitHub App, not `npx @netlify/mcp`).
  Push a branch → that branch deploys. `allowed_branches: [main, dev, curvy]`.
  - `main` → prod (maze-designer-v2.netlify.app); `dev`/`curvy` → `<branch>--maze-designer-v2.netlify.app`.
- **Workflow:** build/test on a branch → check its Netlify preview → merge up (`curvy → dev → main`).
  Pushing `main` ships to prod, so always test on the branch preview first.
- Verify loop: static-serve `python3 -m http.server 4321`; `node --check` the extracted `<script>`;
  validate SVG with `DOMParser`. The Claude-Preview MCP was flaky (reloaded mid-session) — re-navigate
  and rebuild state via eval when it drops.

## Feature pass (shipped to `main`, commit 3d6ef4b)
- **Resolution = "mazerunner size"**: one stepper (the ball/bit/nozzle ⌀) + a Clearance tweak slider
  derive passage/wall/cell. Replaced the manufacturing tool-preset dropdowns (decision: simpler mental
  model — the maze is sized to whatever runs it; clearance keeps passages > runner so it never pinches).
- **Boundary step** absorbed goal type + resolution (so they're set before doors/path). Boundary source:
  Choose-template vs Draw-myself; freehand removed (it "didn't work well"); polygon gets **Shift→45° snap**.
  Board-resize re-fits the active preset.
- **Goal types:** Exit goal (perimeter) vs Inner goal (interior target marker, canvas + SVG).
- **Custom path = grid painting** (drag paints BFS-connected cells; de-looped to a simple corridor;
  must connect entry→exit or generation is blocked). Decision: the drawn path IS the solution — pin it
  (`solveMaze` returns the drawn path) so the Solve button and auto-solve agree.
- **Branch anchors:** click the path to drop dead-end (coral) or loop (blue) nodes; carved with varied
  length/type. Decision: hand-designed branches replace random auto-features.
- **Maze complexity** slider (custom-path mode): 0 = path+anchors in open space → 100 = dense filler.
  Auto-braid off in custom mode (loops come from loop-anchors). Open area cells tagged `_open`.
- **Seeded generation** (mulberry32) so a seed+settings reproduces a maze.
- **Dead-ends list:** every branch is an inline row with an always-visible color box + editable name;
  drawn in color, exported as named/colored SVG layers. (Earlier expand-on-select version caused a
  panel-rebuild-mid-click collapse bug — fixed by updating swatch/label in place, no full re-render.)
- **Export step:** per-layer include toggles.
- **Bug fixes that mattered:** SVG was invalid XML (a `--` inside the `<!-- -->` comment → rejected by
  Illustrator/Affinity/eufyMake) — fixed. Open-space fill was punching stray perimeter holes ("bays")
  — fixed so only the real entry/exit breach the boundary. Winding-slider freeze + dead-ends collapse
  were the same "rebuild panel during interaction" anti-pattern — both moved to in-place DOM updates.

## Curvy render mode (curvy branch — NOT merged)
The key reframe: **stop thinking in walls, render the passage graph.** Curvy is a *pure render +
export choice — the maze data (grid/walls) is unchanged.*

Decisions & why:
- **Round-stroke channels are squeeze-free by construction.** Stroke the passage centerlines with a
  constant width = passage and round joins/caps; rounding only ever *adds* clearance on the outside of a
  turn, so a passage can never pinch below the runner ⌀. This directly answered the "no squeeze points
  on a grid" worry.
- **Two levels:** Level 1 = round-corner channels (grid); Level 2 = organic, by smoothing the
  centerlines into splines. The Smoothing slider (Round→Organic) morphs between them. Cut distance is
  capped at ½ cell so a curve's inner radius stays > ½ passage and it never bows past a neighbor wall.
- Prototyped first in a throwaway **`curvy-poc.html`** (square vs curvy side-by-side, sliders) before
  touching the app — validated the look + squeeze-free claim with zero risk.
- **Integration internals (index.html):** `buildChains()` decomposes the ortho passage graph into
  corridor chains (cached `S._chains`); `smoothCanvasPath()`/`smoothSvgD()` quad-bezier corner rounding;
  `drawCurvyMaze()` = wall plate clipped to boundary + carved smoothed channels + door stubs;
  `cellsSvgD()` smooths the solution/dead overlays. SVG emits `<g id="channels">` smoothed paths.
- **Open chambers** (complexity < 100%, `_open` cells) exploded the chain builder into thousands of
  tiny edges and rendered as a polka-dot grid → fix: skip chamber-internal edges and render chambers as
  solid open regions (passage-inset rects), keeping perimeter/corridor walls.
- **Junction inside corners** (T/+) stayed sharp because chains *end* at junctions so smoothing can't
  reach them → `drawCurvyFillets()` carves a small radiused fillet at each perpendicular open pair
  (canvas + SVG arc paths). The fillet **radius scales with the smoothing slider** so it adjusts in
  lockstep with the rest (at smoothing 0 it matches the regular sharp-inside corners; at 1 it's fully
  organic).
- Square mode and polar are untouched (polar falls back to square; curvy is ortho-only).

## Open / next
- Curvy is feature-complete and live on its preview; remaining is taste-tuning, then **merge
  curvy → dev → main** (drop or keep `curvy-poc.html`).
- Possible future: organic boundary breaches at doors (currently the boundary outline crosses the door
  gap, same as square); SVG open-chamber rects could be merged into one path to shrink file size.
