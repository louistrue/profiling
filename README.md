# IFC Profiling

Benchmarks for comparing IFC parsing, querying, and geometry processing across IFC engines. Forked from [Moult/profiling](https://github.com/Moult/profiling). This branch (`apples-to-apples-with-native`) adds ifc-lite's native Rust deployment alongside the existing WASM and IOS series, plus a Zero-copy / GPU-ready buffer category.

See [`results/RESULTS.md`](./results/RESULTS.md) for the full numbers, methodology, and disclosures, and [`results/comparison.png`](./results/comparison.png) for the chart.

## Engines

| Path | Engine | Geometry |
|---|---|---|
| `profile_ifc.py` | IfcOpenShell (C++/Python) | Hybrid CGAL / OpenCASCADE / Manifold, multiprocessed |
| `src/main_dion.ts` | ifc-lite WASM (Rust → WASM) | WASM single-threaded |
| `src/main_zerocopy.ts` | ifc-lite WASM zero-copy fast path | WASM single-threaded |
| `webifc/src/main_simple.ts` | web-ifc (C++/WASM) | WASM single-threaded |
| `webifc/src/main_dion.ts` | web-ifc with explicit Parse phase | WASM single-threaded |
| `webifc/src/main_zerocopy_ref.ts` | web-ifc full-extract reference for Category 4 | WASM single-threaded |
| `ifclite-rs/src/main.rs` | ifc-lite **native** (Rust crate, rayon) | Native multi-threaded |

The native ifc-lite path uses the same `ifc-lite-processing` crate the production server uses (`@ifc-lite/server-bin`). The bench binary calls `process_geometry(&content)` directly — no HTTP, no WASM. Rayon thread pool size is configurable via `--threads N`.

## Models

IFC test files live in `models/`. Sourced from [ifc-lite/tests/models/ara3d](https://github.com/louistrue/ifc-lite/tree/main/tests/models/ara3d), files under 1MB removed. 21 of Moult's 26 public files; 5 `private*.ifc` not available.

## Usage

### Setup

```sh
pnpm install
cd webifc && npm install && cd ..
cd ifclite-rs && cargo build --release && cd ..
python3 -m pip install matplotlib       # for the chart
```

### Run all engines

```sh
# ifc-lite WASM (Categories 1, 2, 3)
pnpm start

# ifc-lite WASM zero-copy (Category 4)
pnpm zerocopy

# web-ifc (Categories 1, 2, 3)
cd webifc && pnpm start && cd ..

# web-ifc zero-copy reference (Category 4)
cd webifc && pnpm zerocopy && cd ..

# ifc-lite native (1 thread + max threads), produces ifclite-native-{1c,max}.json
node run_native.mjs

# Render chart
python3 compare/render_dion.py
```

### Single file

All scripts accept an optional filename argument to target one model.

```sh
pnpm start duplex.ifc
cd webifc && pnpm start duplex.ifc
ifclite-rs/target/release/ifclite-bench models/duplex.ifc --threads 10
```

### IfcOpenShell (upstream's path)

The IOS rows in our chart come from Moult's published `findings.md` (his hardware, datamodel branch, `hybrid-manifold-cgal-simple-opencascade` kernel). Pip ifcopenshell 0.8.2 does not ship the Manifold kernel, so re-running `profile_ifc.py` on a different machine with pip-installed IOS will produce slower numbers. Using Moult's published Manifold-augmented numbers represents IOS at its best.

```sh
python profile_ifc.py                  # all models (uses kernel hardcoded in script)
python profile_ifc.py duplex.ifc       # single model
```

## Per-object profiling (upstream's tooling, kept as-is)

```sh
python profile_ifc_per_object.py                # IOS
pnpm tsx src/profile_per_object.ts              # ifc-lite
cd webifc && pnpm tsx src/profile_per_object.ts # web-ifc
```

## Output

Each summary script prints per-file timings and a per-type product breakdown, followed by a summary table. JSON outputs land in `results/`. The renderer reads those JSONs and produces the 4-panel comparison PNG.
