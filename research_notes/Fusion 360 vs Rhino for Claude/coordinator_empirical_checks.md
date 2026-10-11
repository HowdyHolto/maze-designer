# Coordinator empirical checks (run in this session's Linux container, 2026-10-11)

These are direct test results, not web research. Container: Linux x86_64, no Rhino and no Fusion installed, Python 3 venv, outbound HTTPS via proxy.

## Check 1 — write a Rhino .3dm with rhino3dm (no Rhino installed)
- `pip install rhino3dm` succeeded; version installed: **8.35.0** (PyPI). `npm view rhino3dm` reports **8.35.0**, last modified 2026-09-15.
- Script created: `File3dm` with `ModelUnitSystem = Millimeters`; three named layers (`boundary`, `walls`, `solution`) with colors; a closed 100×80 mm boundary polyline (named object); four wall `LineCurve`s on the walls layer with object names; an `Arc` on the solution layer; a capped `Extrusion` (10 mm) from the boundary curve.
- `File3dm.Write("maze_test.3dm", 8)` returned `True` (Rhino 8 file version). File size 10,049 bytes.
- Read-back with `File3dm.Read`: 7 objects, layers `['boundary','walls','solution']`; geometry types round-tripped as `PolylineCurve`, 4×`LineCurve`, `NurbsCurve` (the arc), `Extrusion`; layer indices and object names preserved.
- Venv footprint for rhino3dm alone: a few MB. Wall-clock for install + write: well under a minute.
- Implication: Claude Code can produce native, layered Rhino files from any environment, including this cloud container and (via the npm/WASM build) from inside the user's single-file browser maze app.

## Check 2 — write a STEP solid with build123d (for Fusion or Rhino import)
- `pip install build123d` succeeded (pulls the OpenCascade `cadquery-ocp` wheel). Script: 100×80 mm rectangle sketch with a 4×40 mm subtracted slot, extruded 10 mm, `export_step(...)`.
- Output `maze_test.step`: 28,938 bytes; generation time ≈0.0 s after import.
- Venv footprint after build123d: **~1.0 GB** (vs a few MB for rhino3dm).
- Implication: a headless STEP path exists for Fusion, but it is a third-party kernel, far heavier to install, and produces generic solids rather than a Fusion-native parametric design. Rhino imports the same STEP, so this path is neutral between the two programs.

## Check 3 — proxy constraint affecting all researchers
- The container's egress proxy denied CONNECT to autodesk.com, aps.autodesk.com, help.autodesk.com, forums.autodesk.com, rhino3d.com, developer.rhino3d.com, discourse.mcneel.com, food4rhino.com, mecsoft.com and most third-party blogs; github.com, raw.githubusercontent.com, PyPI and npm registries were reachable. Researchers therefore relied on search-engine extracts for vendor pages and read McNeel docs from their public GitHub source repo. Vendor-page facts should be treated as "needs spot-check on the live page".
