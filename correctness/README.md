# Geometry correctness framework

Companion to the speed bench (`profile_ifc.py`, `src/main_dion.ts`, etc.). Where
the bench answers "how fast?", this answers **"does ifc-lite produce the same
geometry as IfcOpenShell?"** — per element, in world coordinates, with
graduated metrics so we don't drown in tessellation noise.

## Layout

```
correctness/
├── dump_ifclite_native/   ← Rust binary, dumps per-element world-coord meshes
│   ├── Cargo.toml
│   └── src/main.rs
├── dump_ifcopenshell.py   ← IOS iterator dump (USE_WORLD_COORDS, weld vertices)
├── diff.py                ← tiered comparator (T1 coverage → T5 voxel IoU)
├── run.sh                 ← one-shot driver: build, dump both, diff
└── results/               ← outputs (gitignored)
    └── <model>.{ifclite,ios}.ndjson, .summary.json, .per-element.ndjson, .report.html
```

## What's checked

| Tier | Metric | Catches |
|---|---|---|
| T1 Coverage | matched / only-a / only-b by GlobalId, grouped by IFC type | missing or extra elements |
| T2 AABB invariants | vertex/tri count, AABB IoU, AABB-center distance, AABB volume | gross position or scale error |
| T3 Point-set | symmetric Hausdorff + mean (Chamfer-style) on area-sampled points, normalized by element bbox diagonal | shape drift, tessellation mismatch |
| T4 Topology | watertight-after-weld, Euler number, surface area | non-manifold output, missing faces |
| T5 Voxel IoU | Jaccard on a shared occupancy grid | kernel-agnostic shape correctness; works on open meshes |

Per-IFC-type thresholds (in `THRESHOLDS` at the top of `diff.py`). Verdict
priority: `fail:position` (bbox) → `fail:shape` (voxel) → `fail:volume` (hull)
→ warning axes → `pass`. Hausdorff is warning-only because its max-distance
nature is dominated by tessellation density, not shape correctness.

## Usage

```sh
# One-shot on a model
correctness/run.sh duplex.ifc

# Outputs land in correctness/results/<name>.{ndjson,html,json}
open correctness/results/duplex.report.html
```

Requires Python with `trimesh`, `numpy`, `scipy`, `ifcopenshell` (pip 0.8.2 is
the validated reference), and Cargo (only on first run — builds the native
dumper).

## Coordinate alignment

ifc-lite's `process_geometry` emits meshes in `raw_ifc` space — element
placements baked in, but **not** the `IfcSite` placement. IfcOpenShell with
`use-world-coords=True` bakes the full chain. The dumper applies
`result.site_transform` (column-major 4×4) to every vertex when present and
non-identity, so both engines feed the diff in the same frame.

## Knobs

```sh
python3 correctness/diff.py <candidate.ndjson> <reference.ndjson> \
  --out summary.json \
  --per-element per-elem.ndjson \
  --html report.html \
  [--voxel-cells 64]   # max cells per longest axis (default 64; 96 = ~3.4× slower)
  [--voxel-always]     # don't skip voxel even when bbox+hull strongly agree
  [--voxel-off]        # skip T5 entirely
  [--voxel-no-skip]    # disable the bbox+hull strong-agreement fast path
```

## Calibration results

| Model | Elements | Pass | Fail | Warn | Wall-clock |
|---|---:|---:|---:|---:|---:|
| duplex.ifc | 215 | 174 (81%) | 38 | 3 | ~23s |
| AC20-FZK-Haus.ifc | 83 | 65 (78%) | 13 | 5 | ~30s |
| advanced_model.ifc | 6,401 | 6,255 (98%) | 131 | 15 | ~128s |

Defects surfaced (today's bench can't see these):
- Revit `M_Fixed` window + `M_Single-Flush` door families: missing frame
  geometry in ifc-lite (vertex count ratio 0.17 vs IOS).
- German `Drehflügel/Türelement` doors in advanced_model: same defect class,
  cross-tool confirmation.
- ArchiCAD `EG-Fenster`: ifc-lite produces 68% of IOS window volume,
  deterministic across all instances.
- `Muro básico` walls with openings: bbox matches but voxel IoU 0.46–0.65 →
  opening cuts differ between engines.
