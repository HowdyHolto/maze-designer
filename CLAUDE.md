# Maze Designer — Claude Code Context

## What this is
A browser-based maze generator for fabrication use (CNC, laser, 3D print, ball mazes).
Single-file app: **`index.html`** contains all HTML, CSS, and JS — no build system, no dependencies.

## How to run
Open `index.html` in any browser. That's it.

## How to deploy
```bash
# Uses Netlify MCP CLI — run from the repo root
npx -y @netlify/mcp@latest --site-id 847127c4-be09-4427-a522-072e58ae0c1f \
  --proxy-path "$(netlify-mcp-proxy-path)"
```
Site: https://maze-designer-v2.netlify.app  
Netlify team ID: 68c826910e60b405e08b5303  
Site ID: `847127c4-be09-4427-a522-072e58ae0c1f`

In practice, get a fresh `--proxy-path` token by running the Netlify deploy-site tool
and copying the `npx` command it returns, then run it from this directory.

## 4-step UX flow
```
1 · Boundary  →  2 · Doors  →  3 · Generate  →  4 · Export
```
- **Boundary**: pick grid type (Square/Concentric), board size, preset shape or draw custom
- **Doors**: place entry (green) and exit (orange) on perimeter hotspots, or interior finish
- **Generate**: tool preset → cell size / wall fraction / braid / winding → Generate → auto-solves
- **Export**: SVG download with named layers (boundary, walls, solution, dead-end-N, alt-path-N)

## Architecture — State object `S`
Everything lives in a single global `S` object. Key fields:

```js
S = {
  // Boundary (step 1)
  gridType: 'ortho' | 'polar',
  bW, bH,           // board mm
  boundary: [],      // polygon points [{x,y}]
  bDone: false,

  // Doors (step 2)
  doors: {
    exitMode: 'perimeter' | 'interior',
    entries: [],    // [{col, row, dir, mx, my}]  ← ALWAYS use mx/my as source of truth
    exits: [],      // [{col, row, dir, mx, my}]  ← dir=null means interior exit
    placing: 'entry' | 'exit' | null,
    customPath: false,
    pathCells: [],  // [{col, row, cx, cy}]
  },
  _pg: null,  // preview grid {cells, cmap} — rebuilt on every doGenerate()
  _pf: [],    // perimeter faces [{col,row,dir,mx,my}]

  // Generation (step 3)
  cellSize: 12,      // mm
  wallFrac: 0.30,    // wall thickness as fraction of cell
  braidPct: 0,       // 0–100, % of dead ends to remove (creates loops)
  winding: 0.5,      // 0=winding DFS, 1=flowing (straight bias)
  bias: 'random' | 'N' | 'S' | 'E' | 'W',
  toolType: 'mill' | 'laser' | 'printer' | 'ball',
  toolSizeIdx: 1,
  toolDiamMm: 3.175,
  constraints: { minP, minW, minC },  // derived from tool preset

  // Maze data
  cells: [],   // all cell objects (inside + outside boundary)
  cmap: {},    // {cellKey: cell} where cellKey = "col,row"
  hasMaze: false,

  // Solve
  solution: [],       // array of cells forming solution path
  deadBranches: [],   // [{cells[], tip, length}]
  altPaths: [],       // up to 3 alternate paths (requires braidPct > 0)
  solveData: {},

  // Visibility layers (right panel)
  layers: { bnd, walls, doors, grid, solution, dead, alts },
}
```

## Cell structure (ortho)
```js
cell = {
  id: "col,row",     // cellKey format
  col, row,
  cx, cy,            // center position in mm (world coordinates)
  walls: { N: true, S: true, E: true, W: true },  // true = wall exists
  inside: bool,      // whether cell is inside the boundary polygon
  visited: bool,     // used during DFS generation
}
```

## Key functions

### `doGenerate()` — THE critical function
Handles all generation + door re-snapping. **Never call genOrtho directly.**
```
1. Save door mm-positions (mx/my) — grid-independent
2. Reset maze state
3. Rebuild preview grid + perimeter faces with CURRENT cellSize
4. Re-snap doors to new grid using mm-positions (snapFaceFromMm)
5. Run genOrtho() / genPolar()
6. Auto-solve if doors are set
```
**Critical rule**: doors are stored with both `col/row` AND `mx/my`. Always re-snap using `mx/my` on regeneration — col/row can become stale if cellSize changes.

### `solveMaze()` — BFS from entry to exit
- Uses plain objects `{}` for visited/dist/prev maps (not Map/Set — caused closure bugs)
- Explicit `for` loops throughout (no forEach — caused BFS traversal bugs)
- Uses `S.doors.entries[0]` as start, `S.doors.exits[0]` as fixed exit if reachable
- Falls back to topmost-leftmost cell (entry) and farthest reachable (exit) if no doors

### `isDoorWall(cell, dir)` — wall gap rendering
Returns true if this cell+direction is a door position.
Walls with `isDoorWall() === true` are skipped in both canvas draw and SVG export.

### `cellKey(col, row)` → `"col,row"`
Used consistently for all cmap lookups. Both col and row are always integers.

### `computePerimFaces(pg)` — perimeter hotspot detection
A cell face is a perimeter face if the neighbor in that direction is outside the boundary or off-grid. Returns array of `{col, row, dir, mx, my}` — the hotspot circles shown in the Doors step.

## Tool preset cascade
```
toolType + toolSizeIdx → toolDiamMm + constraints{minP, minW, minC} + wallFrac + cellSize + kerf
```
When a preset is applied, `cellSize` is raised to meet `minC` if needed. Sliders clamp at constraint floors.

## SVG export layers
Named groups for CAM software:
- `boundary` — profile cut (closed polygon)
- `walls` — pocket/engrave paths (door gaps omitted via isDoorWall)
- `solution` — primary route (purple)
- `alt-path-N` — alternate routes (light purple, requires braid > 0)
- `dead-end-N` — dead end branches (coral)

## Known issues / pending work
- [ ] Polar maze solve not implemented (alerts "v2")
- [ ] Door col/row display in Doors panel sometimes shows stale values after cellSize change (visual only, mx/my is correct)
- [ ] Custom path validation: should enforce start/end at door positions
- [ ] Multiple entry/exit points (architecture uses arrays, UI only exposes one each)
- [ ] DXF export
- [ ] G-code export with feed rates
- [ ] Tab/holding bridges for CNC through-cuts
- [ ] Hex grid type
- [ ] Voronoi grid type
- [ ] Unicursal labyrinth mode (Chartres algorithm)
- [ ] Weave/bridge crossings
- [ ] Wall click-to-edit individual walls

## Architecture notes for future multi-door support
`S.doors.entries` and `S.doors.exits` are already arrays — adding multiple doors is a UI
change, not an architecture change. The solver would need updating to handle multiple
entry/exit candidates (e.g., find the longest shortest-path among all entry→exit pairs).

## Session notes
See `docs/session-notes/` for full build history and decisions.
