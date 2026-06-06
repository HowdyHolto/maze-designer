# Maze Designer

A browser-based maze generator for fabrication — CNC routing, laser cutting, 3D printing, and physical ball/marble mazes.

**Live:** https://maze-designer-v2.netlify.app

## What it is

A single, self-contained `index.html` — all HTML, CSS, and JS in one file. **No build system, no dependencies, no npm.** This is deliberate; keep it that way.

## Run it

Open [`index.html`](index.html) in any browser. That's it.

## The 4-step flow

```
1 · Boundary  →  2 · Doors & Path  →  3 · Generate  →  4 · Export
```

1. **Boundary** — pick grid type (Square/Concentric), board size, a preset shape, or draw custom.
2. **Doors** — place entry (green) and exit (orange) on perimeter hotspots, or an interior finish.
3. **Generate** — choose a tool preset, tune cell size / wall fraction / braid / winding, then Generate (auto-solves).
4. **Export** — download SVG with named layers (boundary, walls, solution, dead-ends, alt-paths) ready for CAM software.

See [`examples/maze-2.svg`](examples/maze-2.svg) for a sample export.

## Deploy

Hosted on Netlify (static site, publishes the repo root — see [`netlify.toml`](netlify.toml)).

```bash
# Get a fresh --proxy-path token from the Netlify deploy-site tool, then run from repo root:
npx -y @netlify/mcp@latest --site-id 847127c4-be09-4427-a522-072e58ae0c1f \
  --proxy-path "<fresh token>"
```

## Project context

- [`CLAUDE.md`](CLAUDE.md) — architecture, the global `S` state model, key functions, tool-preset cascade, and the backlog.
- [`docs/session-notes/`](docs/session-notes/) — full build history and design decisions.
