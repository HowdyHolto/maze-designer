# Curvy Arc-Fillet Engine + Island/Tip Polish — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render the curvy maze's loop *islands* and dead-end *wall tips* as clean shapes (no teardrops), and rebuild corner smoothing on exact circular **arc-fillets** (replacing quad-Béziers as the default, Bézier parked).

**Architecture:** Single-file app (`index.html`, no build/deps). All changes are to `index.html`. Smoothing functions switch from quad-Bézier to `arcTo`/SVG-`A` arcs. After channels are drawn, a new pass detects wall-blobs disconnected from the boundary frame (connected components on the wall lattice) and dead-end wall tips, and repaints them as rounded shapes. Algorithms are already proven in committed prototypes `island-poc.html` (island/tip detection + render) and `smoothing-style.html` (arc-fillet).

**Tech Stack:** Vanilla JS, Canvas 2D, SVG string-building. Verification: `node --check`, headless geometry assertions, browser preview (pixel + visual). No unit-test framework — adapt accordingly.

**Branch:** `curvy`. **Prod backup:** tag `backup-prod-2026-06-07`. **Spec:** `docs/superpowers/specs/2026-06-07-curvy-polish-and-export-kit-design.md`.

**Out of scope (Phase 2, separate plan):** the Export Kit (raw/polished/info/zip). Phase 1 leaves `buildSVG` channels arc-based (free, via shared `smoothSvgD`) but does NOT add island geometry to the export — that's Phase 2.

**Working conventions for every task:**
- Serve for preview: `python3 -m http.server 4321` from repo root (or the session's node static server). Open `http://localhost:4321/index.html`.
- After each edit: extract the `<script>` and run `node --check` on it (see Task 0 helper). Validate any SVG via DOMParser/`xmllint`.
- The preview canvas can report a non-positive zoom when headless; set `S.vs=2;S.vx=20;S.vy=20` before driving generation via eval (see Task 3).
- Line numbers below are indicative — **Read the current function before editing**; match by function name.

---

### Task 0: Verification helpers (one-time)

**Files:**
- Create: `test/extract-check.sh`
- Create: `test/island-geom.test.js`

- [ ] **Step 1: Create the syntax-check helper**

`test/extract-check.sh`:
```bash
#!/usr/bin/env bash
# Extract the <script> body from index.html and node --check it.
set -e
node -e '
const fs=require("fs");
const html=fs.readFileSync("index.html","utf8");
const m=html.match(/<script>([\s\S]*?)<\/script>/);
if(!m){console.error("no <script> found");process.exit(2);}
fs.writeFileSync("/tmp/maze-script.js",m[1]);
'
node --check /tmp/maze-script.js && echo "node --check OK"
```

- [ ] **Step 2: Run it against the current file**

Run: `bash test/extract-check.sh`
Expected: `node --check OK`

- [ ] **Step 3: Commit**

```bash
git add test/extract-check.sh
git commit -m "test: add extract+node-check helper for index.html"
```

---

### Task 1: Arc-fillet canvas smoothing (replace Bézier default; park Bézier)

**Files:**
- Modify: `index.html` — function `smoothCanvasPath` (~line 249)

- [ ] **Step 1: Read the current `smoothCanvasPath`** and confirm it is the quad-Bézier version (uses `quadraticCurveTo`).

- [ ] **Step 2: Replace it with the arc-fillet version + a parked Bézier copy**

Replace the whole `smoothCanvasPath` function with:
```js
// Arc-fillet corner rounding (DEFAULT). Each turn becomes a circular arc tangent to both edges,
// radius r = min(d1,d2)*0.5*s. Collinear points stay straight. Closed under offset (CAM-clean).
function smoothCanvasPath(ctx,pts,s){
  if(pts.length<3||s<=0){ctx.moveTo(pts[0].x,pts[0].y);for(var i=1;i<pts.length;i++)ctx.lineTo(pts[i].x,pts[i].y);return;}
  ctx.moveTo(pts[0].x,pts[0].y);
  for(var i=1;i<pts.length-1;i++){
    var p0=pts[i-1],p1=pts[i],p2=pts[i+1];
    var d1=Math.hypot(p1.x-p0.x,p1.y-p0.y)||1,d2=Math.hypot(p2.x-p1.x,p2.y-p1.y)||1;
    var r=Math.min(d1,d2)*0.5*s;
    ctx.arcTo(p1.x,p1.y,p2.x,p2.y,r);
  }
  ctx.lineTo(pts[pts.length-1].x,pts[pts.length-1].y);
}
// PARKED: previous quad-Bézier smoother. Retained for a future "soft/organic" style; not wired in.
function smoothBezierPath(ctx,pts,s){
  if(pts.length<3||s<=0){ctx.moveTo(pts[0].x,pts[0].y);for(var i=1;i<pts.length;i++)ctx.lineTo(pts[i].x,pts[i].y);return;}
  ctx.moveTo(pts[0].x,pts[0].y);
  for(var i=1;i<pts.length-1;i++){var p0=pts[i-1],p1=pts[i],p2=pts[i+1];
    var d1=Math.hypot(p1.x-p0.x,p1.y-p0.y)||1,d2=Math.hypot(p2.x-p1.x,p2.y-p1.y)||1;var r=Math.min(d1,d2)*0.5*s;
    var a={x:p1.x+(p0.x-p1.x)/d1*r,y:p1.y+(p0.y-p1.y)/d1*r},b={x:p1.x+(p2.x-p1.x)/d2*r,y:p1.y+(p2.y-p1.y)/d2*r};
    ctx.lineTo(a.x,a.y);ctx.quadraticCurveTo(p1.x,p1.y,b.x,b.y);}
  ctx.lineTo(pts[pts.length-1].x,pts[pts.length-1].y);
}
```

- [ ] **Step 3: Syntax check**

Run: `bash test/extract-check.sh`
Expected: `node --check OK`

- [ ] **Step 4: Visual check in preview**

Generate a curvy maze (see Task 3 Step 2 for the eval setup), set `S.smoothing=1`, `draw()`, screenshot. Expected: curvy corridors look essentially identical to before (arc vs Bézier is a few-percent difference) — no broken/garbled corners.

- [ ] **Step 5: Commit**

```bash
git add index.html
git commit -m "feat(curvy): arc-fillet canvas smoothing (default), park Bezier smoother"
```

---

### Task 2: Arc-fillet SVG smoothing (replace Bézier default; park Bézier)

**Files:**
- Modify: `index.html` — function `smoothSvgD` (~line 251)

- [ ] **Step 1: Read the current `smoothSvgD`** (quad-Bézier, emits `Q`).

- [ ] **Step 2: Replace with the arc version + parked copy**

```js
// Arc-fillet SVG path (DEFAULT). Emits L + A (true circular arcs). Mirrors smoothCanvasPath/arcTo.
function smoothSvgD(pts,s){
  var f=function(p){return p.x.toFixed(2)+' '+p.y.toFixed(2);};
  if(pts.length<3||s<=0){var d='M '+f(pts[0]);for(var i=1;i<pts.length;i++)d+=' L '+f(pts[i]);return d;}
  var d='M '+f(pts[0]);
  for(var i=1;i<pts.length-1;i++){
    var p0=pts[i-1],p1=pts[i],p2=pts[i+1];
    var d1=Math.hypot(p1.x-p0.x,p1.y-p0.y)||1,d2=Math.hypot(p2.x-p1.x,p2.y-p1.y)||1;
    var r=Math.min(d1,d2)*0.5*s;
    var u1x=(p0.x-p1.x)/d1,u1y=(p0.y-p1.y)/d1,u2x=(p2.x-p1.x)/d2,u2y=(p2.y-p1.y)/d2;
    var dot=Math.max(-1,Math.min(1,u1x*u2x+u1y*u2y));
    var theta=Math.acos(dot);
    if(theta>=Math.PI-1e-6||r<1e-6){d+=' L '+f(p1);continue;}      // collinear -> straight
    var t=Math.min(r/Math.tan(theta/2),d1,d2);
    var rr=t*Math.tan(theta/2);                                    // radius consistent with clamped t
    var a={x:p1.x+u1x*t,y:p1.y+u1y*t},b={x:p1.x+u2x*t,y:p1.y+u2y*t};
    var cross=u1x*u2y-u1y*u2x;                                     // SVG y-down: cross<0 => CW turn
    var sweep=cross<0?1:0;
    d+=' L '+f(a)+' A '+rr.toFixed(2)+' '+rr.toFixed(2)+' 0 0 '+sweep+' '+f(b);
  }
  d+=' L '+f(pts[pts.length-1]);
  return d;
}
// PARKED: previous quad-Bézier SVG smoother.
function smoothBezierSvgD(pts,s){
  var f=function(p){return p.x.toFixed(2)+' '+p.y.toFixed(2);};
  if(pts.length<3||s<=0){var d='M '+f(pts[0]);for(var i=1;i<pts.length;i++)d+=' L '+f(pts[i]);return d;}
  var d='M '+f(pts[0]);
  for(var i=1;i<pts.length-1;i++){var p0=pts[i-1],p1=pts[i],p2=pts[i+1];
    var d1=Math.hypot(p1.x-p0.x,p1.y-p0.y)||1,d2=Math.hypot(p2.x-p1.x,p2.y-p1.y)||1;var r=Math.min(d1,d2)*0.5*s;
    var a={x:p1.x+(p0.x-p1.x)/d1*r,y:p1.y+(p0.y-p1.y)/d1*r},b={x:p1.x+(p2.x-p1.x)/d2*r,y:p1.y+(p2.y-p1.y)/d2*r};
    d+=' L '+f(a)+' Q '+f(p1)+' '+f(b);}
  d+=' L '+f(pts[pts.length-1]);return d;
}
```

- [ ] **Step 3: Syntax check** — `bash test/extract-check.sh` → `node --check OK`.

- [ ] **Step 4: SVG sweep-direction verification (the finicky bit)**

In the preview, generate a curvy maze, then eval:
```js
(function(){var svg=buildSVG();var ok=true;try{new DOMParser().parseFromString(svg,'image/svg+xml');}catch(e){ok=false;}
 // render the channels path into an <img> and compare visually to the canvas
 document.body.insertAdjacentHTML('beforeend','<div id=__t style="position:fixed;right:0;top:0;background:#fff">'+svg+'</div>');return {valid:ok};})()
```
Screenshot and confirm the SVG arcs **bulge the same way** as the canvas render (corners curve outward identically). If any corner bulges inward/wrong, flip the `sweep` flag rule and re-check. (Validated when SVG matches canvas.)

- [ ] **Step 5: Commit**

```bash
git add index.html
git commit -m "feat(curvy): arc-fillet SVG smoothing (default), park Bezier; channels now exact arcs"
```

---

### Task 3: Negative-zoom guard

**Files:**
- Modify: `index.html` — `drawCurvyFillets` (~line 282) and/or `drawCurvyMaze` (~line 258)

- [ ] **Step 1: Reproduce the crash** — fresh-load the app and immediately eval `doGenerate()` before the canvas is sized; observe `IndexSizeError: ... arc ... radius ... negative` (root cause: `vzFit` computes `S.vs<0` when `cvs.width` is ~0).

- [ ] **Step 2: Add a guard at the top of `drawCurvyMaze`**

After the existing `if(S.gridType!=='ortho'){...return;}` line in `drawCurvyMaze`, add:
```js
if(!(S.vs>0))return;   // canvas not sized yet (headless/early) — skip; avoids negative arc radius
```

- [ ] **Step 3: Syntax check** — `bash test/extract-check.sh` → OK.

- [ ] **Step 4: Verify no crash**

In a freshly-loaded preview, eval (without pre-setting `S.vs`):
```js
(function(){try{doGenerate();return 'no throw';}catch(e){return 'THREW: '+e.message;}})()
```
Expected: `"no throw"`.

- [ ] **Step 5: Commit**

```bash
git add index.html
git commit -m "fix(curvy): guard curvy draw against non-positive zoom (headless crash)"
```

---

### Task 4: Island + wall-tip detection (adapted to app coords) + headless test

**Files:**
- Modify: `index.html` — add `islandComponents()`, `wallTips()` near `buildChains` (~line 255)
- Create: `test/island-geom.test.js`

These generalize the prototype detectors to the app's `S.cmap`/`inside` model (arbitrary polygon boundary: frame = lattice vertex touching ≥1 inside and ≥1 outside/off-grid cell).

- [ ] **Step 1: Write the headless test fixture FIRST**

`test/island-geom.test.js`:
```js
// Headless assertions for islandComponents/wallTips logic (pure, no DOM).
// Mirrors the app's wall-lattice rules on a hand-built inside-cell grid.
function mkGrid(N){var cmap={};for(var r=0;r<N;r++)for(var c=0;c<N;c++)cmap[c+','+r]={col:c,row:r,inside:true,walls:{N:true,S:true,E:true,W:true}};return {cmap:cmap,N:N};}
function open(cmap,c,r,dir){var a=cmap[c+','+r];a.walls[dir]=false;var DV={N:[0,-1],S:[0,1],E:[1,0],W:[-1,0]},opp={N:'S',S:'N',E:'W',W:'E'};var b=cmap[(c+DV[dir][0])+','+(r+DV[dir][1])];if(b)b.walls[opp[dir]]=false;}
// ---- functions under test (copy of the app versions; keep in sync) ----
%%ISLAND_FNS%%
// ---- cases ----
function run(){
  // Case A: a 2x2 all-open pillar loop in the middle of a 5x5 -> exactly 1 island (1 vertex), 0 tips on it
  var g=mkGrid(5),cmap=g.cmap;
  open(cmap,1,1,'E');open(cmap,1,1,'S');open(cmap,2,1,'S');open(cmap,1,2,'E'); // ring c(1,1)
  // also open a path so the rest is connected-ish (not required for island detection)
  var comps=islandComponents(cmap,5);
  var pillars=comps.filter(function(c){return c.verts.length===1;});
  console.log('CASE A islands:',comps.length,'single-vertex:',pillars.length);
  if(pillars.length<1)throw new Error('expected a single-vertex pillar island');
  console.log('OK');
}
run();
```
Note: the test calls `islandComponents(cmap,N)` / `wallTips(cmap,N)` — write the app functions to accept `(cmap,N)` OR add thin wrappers; keep the test copy in sync with the app copy (documented limitation of a single-file app).

- [ ] **Step 2: Run it — it must FAIL (functions undefined)**

Run: `node test/island-geom.test.js`
Expected: `ReferenceError: islandComponents is not defined` (the `%%ISLAND_FNS%%` placeholder is literal until Step 3).

- [ ] **Step 3: Add the detectors to `index.html`** (and paste the same bodies over `%%ISLAND_FNS%%` in the test)

Insert after `buildChains` in `index.html`:
```js
// Wall lattice over inside cells. Vertex (i,j) = top-left corner of cell(i,j). A lattice edge is
// "wall" if the cell-boundary is closed, or it is an inside/outside boundary (frame). Islands =
// connected components of interior wall NOT reaching the frame. (cmap default S.cmap; N optional.)
function _wallH(cmap,i,j){var b=cmap[i+','+j],a=cmap[i+','+(j-1)];var bIn=b&&b.inside,aIn=a&&a.inside;if(!bIn&&!aIn)return false;if(bIn&&aIn)return b.walls.N;return true;}
function _wallV(cmap,i,j){var rt=cmap[i+','+j],lf=cmap[(i-1)+','+j];var rIn=rt&&rt.inside,lIn=lf&&lf.inside;if(!rIn&&!lIn)return false;if(rIn&&lIn)return rt.walls.W;return true;}
function _allIn(cmap,i,j){var k=[cmap[(i-1)+','+(j-1)],cmap[i+','+(j-1)],cmap[(i-1)+','+j],cmap[i+','+j]];for(var t=0;t<4;t++)if(!(k[t]&&k[t].inside))return false;return true;}
function _frameVtx(cmap,i,j){var k=[cmap[(i-1)+','+(j-1)],cmap[i+','+(j-1)],cmap[(i-1)+','+j],cmap[i+','+j]],anyIn=false,anyOut=false;for(var t=0;t<4;t++){if(k[t]&&k[t].inside)anyIn=true;else anyOut=true;}return anyIn&&anyOut;}
function _bounds(cmap){var c0=1e9,c1=-1e9,r0=1e9,r1=-1e9;for(var key in cmap){var cl=cmap[key];if(!cl.inside)continue;if(cl.col<c0)c0=cl.col;if(cl.col>c1)c1=cl.col;if(cl.row<r0)r0=cl.row;if(cl.row>r1)r1=cl.row;}return {I0:c0,I1:c1+1,J0:r0,J1:r1+1};}
function islandComponents(cmap,N){cmap=cmap||S.cmap;var b=_bounds(cmap),I0=b.I0,I1=b.I1,J0=b.J0,J1=b.J1;
  function nbrs(i,j){var a=[];if(_wallH(cmap,i,j))a.push([i+1,j]);if(_wallH(cmap,i-1,j))a.push([i-1,j]);if(_wallV(cmap,i,j))a.push([i,j+1]);if(_wallV(cmap,i,j-1))a.push([i,j-1]);return a;}
  var vid=function(i,j){return i+'_'+j;},comp={},st=[];
  for(var i=I0;i<=I1;i++)for(var j=J0;j<=J1;j++)if(_frameVtx(cmap,i,j))st.push([i,j]);
  while(st.length){var p=st.pop(),id=vid(p[0],p[1]);if(comp[id]!==undefined)continue;comp[id]=-1;var ns=nbrs(p[0],p[1]);for(var k=0;k<ns.length;k++)if(comp[vid(ns[k][0],ns[k][1])]===undefined)st.push(ns[k]);}
  var out=[];
  for(var i=I0;i<=I1;i++)for(var j=J0;j<=J1;j++){if(!_allIn(cmap,i,j)||comp[vid(i,j)]!==undefined)continue;
    var q=[[i,j]],verts=[],edges=[];comp[vid(i,j)]=out.length;
    while(q.length){var p=q.pop();verts.push(p);var cand=[];
      if(_wallH(cmap,p[0],p[1]))cand.push([p[0]+1,p[1]]);if(_wallH(cmap,p[0]-1,p[1]))cand.push([p[0]-1,p[1]]);
      if(_wallV(cmap,p[0],p[1]))cand.push([p[0],p[1]+1]);if(_wallV(cmap,p[0],p[1]-1))cand.push([p[0],p[1]-1]);
      for(var k=0;k<cand.length;k++){var nb=cand[k];edges.push([p,nb]);if(comp[vid(nb[0],nb[1])]===undefined){comp[vid(nb[0],nb[1])]=out.length;q.push(nb);}}}
    out.push({verts:verts,edges:edges});}
  return out;}
function wallTips(cmap){cmap=cmap||S.cmap;var b=_bounds(cmap),out=[];
  for(var i=b.I0;i<=b.I1;i++)for(var j=b.J0;j<=b.J1;j++){if(!_allIn(cmap,i,j))continue;
    var e=0;if(_wallH(cmap,i,j))e++;if(_wallH(cmap,i-1,j))e++;if(_wallV(cmap,i,j))e++;if(_wallV(cmap,i,j-1))e++;
    if(e===1)out.push([i,j]);}
  return out;}
```
Then replace `%%ISLAND_FNS%%` in `test/island-geom.test.js` with the same function bodies (drop the `cmap=cmap||S.cmap` default; the test passes cmap explicitly).

- [ ] **Step 4: Run the test — must PASS**

Run: `node test/island-geom.test.js`
Expected: `CASE A islands: ... single-vertex: 1` then `OK`.

- [ ] **Step 5: Syntax check the app** — `bash test/extract-check.sh` → OK.

- [ ] **Step 6: Sanity-check on a real maze in preview**

Eval (after generating a braided curvy maze): `islandComponents().length` and `wallTips().length` — expect small positive integers (not zero, not thousands).

- [ ] **Step 7: Commit**

```bash
git add index.html test/island-geom.test.js
git commit -m "feat(curvy): island + wall-tip detectors (wall-lattice components vs frame) + headless test"
```

---

### Task 5: Canvas island + tip rendering in `drawCurvyMaze`

**Files:**
- Modify: `index.html` — add `roundRectPath`, `drawCurvyIslands`, and call them inside `drawCurvyMaze`

- [ ] **Step 1: Add helpers near `drawCurvyMaze`**

```js
// world-space rounded-rect path on the canvas (uses w2s + S.vs).
function roundRectPath(x,y,w,h,r){var s0=w2s(x,y),sw=w*S.vs,sh=h*S.vs,rs=Math.min(r*S.vs,sw/2,sh/2);
  ctx.beginPath();ctx.moveTo(s0.x+rs,s0.y);
  ctx.arcTo(s0.x+sw,s0.y,s0.x+sw,s0.y+sh,rs);ctx.arcTo(s0.x+sw,s0.y+sh,s0.x,s0.y+sh,rs);
  ctx.arcTo(s0.x,s0.y+sh,s0.x,s0.y,rs);ctx.arcTo(s0.x,s0.y,s0.x+sw,s0.y,rs);ctx.closePath();}
// Repaint islands (erase blocky footprint to bg, redraw rounded) + additive rounded caps on wall tips.
function drawCurvyIslands(C){
  var cs=S.cellSize,passage=cs*(1-S.wallFrac),HALF=(cs-passage)/2,r=HALF*(S.smoothing||0);
  var ref=null;for(var i=0;i<S.cells.length;i++){if(S.cells[i].inside){ref=S.cells[i];break;}}if(!ref)return;
  var ox=ref.cx-cs/2-ref.col*cs, oy=ref.cy-cs/2-ref.row*cs;
  function X(i){return ox+i*cs;}function Y(j){return oy+j*cs;}
  var comps=islandComponents();
  // pass 0 erase (bg, square), pass 1 draw (wall, rounded)
  for(var pass=0;pass<2;pass++){
    ctx.fillStyle=pass?C.wall:C.bg;var rad=pass?r:0;
    for(var ci=0;ci<comps.length;ci++){var cp=comps[ci];
      for(var ei=0;ei<cp.edges.length;ei++){var a=cp.edges[ei][0],b=cp.edges[ei][1],ax=X(a[0]),ay=Y(a[1]),bx=X(b[0]),by=Y(b[1]);
        var rx,ry,rw,rh;
        if(Math.abs(ax-bx)<1e-6){rx=ax-HALF;ry=Math.min(ay,by);rw=2*HALF;rh=Math.abs(by-ay);}
        else{rx=Math.min(ax,bx);ry=ay-HALF;rw=Math.abs(bx-ax);rh=2*HALF;}
        var s0=w2s(rx,ry);ctx.fillRect(s0.x,s0.y,rw*S.vs,rh*S.vs);}
      for(var vi=0;vi<cp.verts.length;vi++){var vx=X(cp.verts[vi][0]),vy=Y(cp.verts[vi][1]);roundRectPath(vx-HALF,vy-HALF,2*HALF,2*HALF,rad);ctx.fill();}}
  }
  // wall-tip caps: additive rounded square (never redraw the edge)
  var tips=wallTips();ctx.fillStyle=C.wall;
  for(var ti=0;ti<tips.length;ti++){var tx=X(tips[ti][0]),ty=Y(tips[ti][1]);roundRectPath(tx-HALF,ty-HALF,2*HALF,2*HALF,r);ctx.fill();}
}
```
Note: uses `C.wall` (plate color) and `C.bg` (passage color) — confirm those keys exist in the `C` object built in `draw()`; in `drawCurvyMaze` the plate is filled with `C.wall` and channels carved with `C.bg`, so they match.

- [ ] **Step 2: Call it in `drawCurvyMaze`** — immediately **after** the existing `drawCurvyFillets(C);` line and **before** `ctx.restore();`:
```js
  drawCurvyIslands(C);
```

- [ ] **Step 3: Syntax check** — `bash test/extract-check.sh` → OK.

- [ ] **Step 4: Visual sweep verification (the acceptance test)**

In the preview, set a positive zoom and build a heavily-braided curvy maze:
```js
(function(){S.vs=2;S.vx=20;S.vy=20;S.bW=200;S.bH=200;buildPreset('rect');S.runnerMm=10;S.toolDiamMm=10;applyGeometry();
 S.braidPct=85;S.seed=42;S.doors.customPath=false;S.renderMode='curvy';S.smoothing=1;S.layers.solution=false;S.layers.dead=false;S.layers.alts=false;
 doGenerate();vzFit&&vzFit();draw();return {islands:islandComponents().length,tips:wallTips().length};})()
```
Screenshot at `S.smoothing=1`, `0.5`, `0`. **Expected:** islands render as clean circles (sm 1) / squircles (0.5) / squares (0); bars render as stadiums; **no teardrops, no comma artifacts, no thin seams**; wall-finger tips are rounded caps, not points. Compare against `island-poc.html` (same look). Also flip to `S.renderMode='square'` and confirm square mode is visually unchanged.

- [ ] **Step 5: Pixel spot-check** (optional but recommended) — sample a known island center across smoothing values to confirm it stays wall-colored and centered (per the `island-poc.html` pixel-check pattern).

- [ ] **Step 6: Commit**

```bash
git add index.html
git commit -m "feat(curvy): render islands as rounded shapes + wall-tip caps (no teardrops)"
```

---

### Task 6: Full verification, docs, deploy to preview

**Files:**
- Modify: `index.html` (version comment bump if present)
- Create: `docs/session-notes/2026-06-07-curvy-arc-polish.md`

- [ ] **Step 1: Full syntax + SVG validity pass**

Run: `bash test/extract-check.sh` (OK) and validate a generated curvy SVG:
```bash
# in preview eval: copy buildSVG() output to a file via the /save endpoint, then:
xmllint --noout /tmp/out.svg && echo VALID
```

- [ ] **Step 2: Cross-check the whole curvy sweep once more** (square / curvy-0 / curvy-1) on a non-rect boundary preset (e.g. `buildPreset('hex')`) to exercise the inside/outside frame logic, not just the rectangle. Confirm no islands are mis-detected at the angled boundary.

- [ ] **Step 3: Write the session note**

`docs/session-notes/2026-06-07-curvy-arc-polish.md` — summarize: arc-fillet default (Bézier parked as `smoothBezierPath`/`smoothBezierSvgD`), island/tip polish (`islandComponents`/`wallTips`/`drawCurvyIslands`), negative-zoom guard; note Phase 2 (Export Kit) is next.

- [ ] **Step 4: Commit + push to the `curvy` preview**

```bash
git add index.html docs/session-notes/2026-06-07-curvy-arc-polish.md
git commit -m "docs: session note for curvy arc-fillet + island polish (phase 1)"
git push origin curvy
```

- [ ] **Step 5: Verify on the deployed preview**

Open `https://curvy--maze-designer-v2.netlify.app`, generate a braided curvy maze, sweep smoothing — confirm clean islands/tips live. (Do NOT merge to `dev`/`main` yet — hold for user sign-off and Phase 2.)

---

## Self-review notes
- **Spec coverage:** 1a arc-fillet → Tasks 1–2; 1b island polish → Tasks 4–5; 1c tip caps → Tasks 4–5; 1d zoom guard → Task 3; Bézier parked → Tasks 1–2; square untouched → Task 5 Step 4. Export (Phase 2) intentionally excluded.
- **Naming consistency:** detectors `islandComponents(cmap,N)`/`wallTips(cmap)`; render `drawCurvyIslands(C)` + `roundRectPath`; parked `smoothBezierPath`/`smoothBezierSvgD`. Helpers `_wallH/_wallV/_allIn/_frameVtx/_bounds`.
- **Known single-file limitation:** the headless test keeps a *copy* of the detector bodies in sync with `index.html` (no module system to import from). Flagged in Task 4.
- **Finicky bit:** SVG arc `sweep` flag direction (Task 2 Step 4) — verify visually, flip if wrong.
