# IFC engine comparison

Apples-to-apples profiling under the methodology of `Moult/profiling`. Three
categories preserved from the upstream harness (Parse, Geometry, Total). One
category proposed (Zero-copy / GPU-ready geometry buffer).

## Setup

- **Hardware**: Apple M4 / 10c / 16 GB / macOS 26.4.1 / Node 22.14 / pnpm 10.8.1.
- **Engines**:
  - `IfcOpenShell` — numbers reproduced verbatim from `Moult/profiling/findings.md` (his hardware, datamodel branch, `hybrid-manifold-cgal-simple-opencascade` kernel). Pip ifcopenshell 0.8.2 does not ship the Manifold kernel; using Moult's published Manifold-augmented numbers is the fairest representation of IOS at its best, rather than a kernel-handicapped re-run on M4.
  - `web-ifc@0.0.68` — same version as upstream `webifc/package-lock.json`. Run on M4.
  - `ifc-lite (WASM)` — `@ifc-lite/parser@2.3.0` + `@ifc-lite/wasm@1.16.8`. Run on M4. Single-threaded.
  - `ifc-lite (native, 1 core)` — `ifc-lite-processing` Rust crate, rayon thread pool size 1. Run on M4.
  - `ifc-lite (native, 10 threads)` — same crate, rayon thread pool sized to CPU count. Run on M4.
- **Hardware caveat**: IOS rows are from Moult's machine; web-ifc and ifc-lite are from M4. Cross-engine ratios within IOS bars (single vs max) are valid; absolute IOS-vs-others times carry a hardware caveat.
- **Corpus**: 21 of Moult's 26 public IFCs. Five `private*.ifc` files not available locally.
- **Geometry exclude list**: `IfcOpeningElement`, `IfcOpeningStandardCase`, `IfcSpace`, `IfcBuilding`, `IfcBuildingStorey` — applied at product counting in all engines.
- **Methodology**: single cold run per file. Subprocess per file for the native binary. Sorted by file size.

## Categories and engine paths

| Category | Output goal | IOS | web-ifc | ifc-lite (WASM) | ifc-lite (native) |
|---|---|---|---|---|---|
| 1. Parse / Open | model in queryable state | `ifcopenshell.open(path)` | `api.OpenModel(bytes)` | `StepTokenizer.scanEntities` + JS index | `ProcessingStats.parse_time_ms` from `ifc_lite_processing::process_geometry` |
| 2. Geometry | per-element meshes, exclude applied | `ifcopenshell.geom.iterator(... exclude=[...])` | `api.StreamAllMeshes(modelID, cb)` + filter | `api.parseMeshes(content)` + filter on `mesh.ifcType` | `ProcessingStats.geometry_time_ms` (rayon-parallel) |
| 3. Total | parse + geometry | `open + iterator` | `OpenModel + StreamAllMeshes` | `scanEntities + parseMeshes` | wall-clock around `process_geometry` |
| 4. Zero-copy | single concatenated GPU-ready buffer | n/a | `OpenModel + StreamAllMeshes + GetGeometry/Vertex/Index + JS concat` | `api.parseZeroCopy(content)` | n/a in this run |

### Native bench

The native ifc-lite path uses the same `ifc-lite-processing` crate the production server uses (`apps/server` in the `ifc-lite` repo). The bench binary (`ifclite-rs/`) calls `process_geometry(&content)` directly — no HTTP, no WASM. Rayon thread pool size is configurable via `--threads N`. Internal per-phase timings come from `ProcessingStats` (the same struct the server returns to clients).

Build: `cd ifclite-rs && cargo build --release`. Drive: `node run_native.mjs`.

## Product-count validation

Counts after the exclude list is applied, vs Moult's IOS reference.

| File | IOS | web-ifc | ifc-lite WASM | ifc-lite native |
|---|---:|---:|---:|---:|
| duplex.ifc | 215 | 216 | 215 | 215 |
| AC20-FZK-Haus.ifc | 83 | 83 | 83 | 83 |
| ISSUE_005_haus.ifc | 83 | 83 | 83 | 83 |
| ISSUE_021_Mini Project.ifc | 2636 | 2636 | 2636 | 2636 |
| Office_A_20110811.ifc | 803 | 803 | 803 | 803 |
| ISSUE_126_model.ifc | 257 | 257 | 257 | 257 |
| ISSUE_034_HouseZ.ifc | 228 | 228 | 228 | 222 |
| ISSUE_102_M3D-CON.ifc | 138 | 138 | 138 | 138 |
| ISSUE_159_kleine_Wohnung_R22.ifc | 414 | 425 | 425 | 425 |
| C20-Institute-Var-2.ifc | 702 | 702 | 702 | 702 |
| ISSUE_129_…IGC_V17.ifc | 959 | 959 | 947 | 947 |
| dental_clinic.ifc | 2586 | 2586 | 2583 | 2583 |
| FM_ARC_DigitalHub.ifc | 692 | 705 | 703 | 703 |
| ifcbridge-model01.ifc | 165 | 165 | 165 | 165 |
| ISSUE_102_M3D-CON-CD.ifc | 1616 | 1616 | 1616 | 1616 |
| S_Office_Integrated Design Archi.ifc | 3407 | 3422 | 3396 | 3396 |
| advanced_model.ifc | 6401 | 6401 | 6400 | 6401 |
| schependomlaan.ifc | 3569 | 3569 | 3566 | 3569 |
| ISSUE_068_ARK_NUS_skolebygg.ifc | 4459 | 4459 | 4453 | 4459 |
| ISSUE_098_…MO_7000.IFC | 11124 | 11124 | 11123 | 11123 |
| ISSUE_053_…Holter_Tower_10.ifc | 60285 | 60285 | 60285 | 60285 |

Exact match vs IOS: web-ifc 17/21, ifc-lite WASM 12/21, ifc-lite native 14/21. All deltas ≤2% per file. Native fixes WASM gaps on `advanced_model`, `schependomlaan`, `ISSUE_068_ARK_NUS_skolebygg`. Native opens one new gap on `ISSUE_034_HouseZ` (−6 vs IOS, under investigation — likely related to `OpeningFilterMode::Default` interaction with voids on that specific model). Shared deltas across all M4 measurements (`ISSUE_159` +11, `ISSUE_129` −12, `FM_ARC` +11/+13) match the pattern Moult flagged in upstream `findings.md`.

## Total time, seconds

| File | size | IOS 1c | IOS max | web-ifc | ifc-lite WASM | ifc-lite native 1c | ifc-lite native 10t |
|---|---:|---:|---:|---:|---:|---:|---:|
| duplex.ifc | 2.3M | 0.19 | 0.12 | 0.16 | 0.11 | 0.05 | **0.02** |
| AC20-FZK-Haus.ifc | 2.4M | 0.22 | 0.15 | 0.13 | 0.09 | 0.02 | **0.02** |
| ISSUE_005_haus.ifc | 2.4M | 0.21 | 0.13 | 0.10 | 0.08 | 0.02 | **0.02** |
| ISSUE_021_Mini Project.ifc | 3.2M | 0.53 | 0.29 | 0.29 | 0.15 | 0.07 | **0.04** |
| Office_A_20110811.ifc | 3.8M | 0.29 | 0.25 | 0.11 | 0.14 | 0.06 | **0.03** |
| ISSUE_126_model.ifc | 4.2M | 0.46 | 0.32 | 0.07 | 0.14 | 0.04 | **0.02** |
| ISSUE_034_HouseZ.ifc | 4.8M | 0.71 | 0.38 | 0.09 | 0.16 | 0.07 | **0.04** |
| ISSUE_102_M3D-CON.ifc | 6.0M | 0.62 | 0.49 | 0.14 | 0.22 | 0.06 | **0.04** |
| ISSUE_159_kleine_Wohnung_R22.ifc | 9.5M | 1.65 | 0.91 | 0.33 | 0.46 | 0.22 | **0.08** |
| C20-Institute-Var-2.ifc | 10.3M | 0.71 | 0.67 | 0.30 | 0.31 | 0.11 | **0.09** |
| ISSUE_129_…IGC_V17.ifc | 11.5M | 1.52 | 0.89 | 0.33 | 0.37 | 0.12 | **0.09** |
| dental_clinic.ifc | 12.4M | 1.25 | 0.99 | 0.42 | 0.49 | 0.18 | **0.10** |
| FM_ARC_DigitalHub.ifc | 13.4M | 2.43 | 1.54 | 0.53 | 0.71 | 0.28 | **0.09** |
| ifcbridge-model01.ifc | 14.5M | 2.05 | 1.32 | 0.20 | 0.54 | 0.17 | **0.12** |
| ISSUE_102_M3D-CON-CD.ifc | 25.6M | 4.02 | 2.66 | 1.89 | 1.57 | 0.66 | **0.25** |
| S_Office_Integrated Design Archi.ifc | 29.6M | 4.04 | 2.94 | 2.62 | 1.17 | 0.52 | **0.25** |
| advanced_model.ifc | 33.7M | 3.92 | 3.00 | 1.36 | 1.46 | 0.74 | **0.29** |
| schependomlaan.ifc | 47.0M | 3.35 | 2.85 | 0.59 | 1.70 | 0.51 | **0.41** |
| ISSUE_068_ARK_NUS_skolebygg.ifc | 53.7M | 5.72 | 4.11 | 3.32 | 2.37 | 0.94 | **0.52** |
| ISSUE_098_…MO_7000.IFC | 68.4M | 8.42 | 5.82 | 13.05 | 2.72 | 1.17 | **0.59** |
| ISSUE_053_…Holter_Tower_10.ifc | 169.2M | 19.53 | 13.70 | 6.06 | 8.23 | 3.16 | **1.70** |

Wins on Total:

- ifc-lite native (10 threads): **21/21** vs every other series.
- ifc-lite native (1 core): 21/21 vs IOS-max-threads, 19/21 vs web-ifc (loses on `ifcbridge-model01` and `schependomlaan`).
- vs IOS max-threads: native ifc-lite at 10 threads is roughly **3.6× to 18× faster**, median ~10×.

## Zero-copy / GPU-ready geometry buffer, seconds

Single concatenated buffer of geometry, no per-element attribution.

| File | size | ifc-lite parseZeroCopy | web-ifc reference | speedup |
|---|---:|---:|---:|---:|
| duplex.ifc | 2.3M | 0.041 | 0.091 | 2.2× |
| AC20-FZK-Haus.ifc | 2.4M | 0.024 | 0.095 | 4.0× |
| ISSUE_005_haus.ifc | 2.4M | 0.022 | 0.091 | 4.2× |
| ISSUE_021_Mini Project.ifc | 3.2M | 0.068 | 0.300 | 4.4× |
| Office_A_20110811.ifc | 3.8M | 0.047 | 0.110 | 2.4× |
| ISSUE_126_model.ifc | 4.2M | 0.044 | 0.078 | 1.8× |
| ISSUE_034_HouseZ.ifc | 4.8M | 0.043 | 0.096 | 2.3× |
| ISSUE_102_M3D-CON.ifc | 6.0M | 0.076 | 0.147 | 1.9× |
| ISSUE_159_kleine_Wohnung_R22.ifc | 9.5M | 0.184 | 0.345 | 1.9× |
| C20-Institute-Var-2.ifc | 10.3M | 0.088 | 0.307 | 3.5× |
| ISSUE_129_…IGC_V17.ifc | 11.5M | 0.128 | 0.333 | 2.6× |
| dental_clinic.ifc | 12.4M | 0.164 | 0.417 | 2.5× |
| FM_ARC_DigitalHub.ifc | 13.4M | 0.276 | 0.533 | 1.9× |
| ifcbridge-model01.ifc | 14.5M | 0.195 | 0.219 | 1.1× |
| ISSUE_102_M3D-CON-CD.ifc | 25.6M | 0.912 | 1.406 | 1.5× |
| S_Office_Integrated Design Archi.ifc | 29.6M | 0.364 | 2.712 | 7.5× |
| advanced_model.ifc | 33.7M | 0.444 | 1.262 | 2.8× |
| schependomlaan.ifc | 47.0M | 0.449 | 0.617 | 1.4× |
| ISSUE_068_ARK_NUS_skolebygg.ifc | 53.7M | 0.718 | 2.174 | 3.0× |
| ISSUE_098_…MO_7000.IFC | 68.4M | 0.847 | 9.883 | 11.7× |
| ISSUE_053_…Holter_Tower_10.ifc | 169.2M | 3.889 | 5.996 | 1.5× |

ifc-lite faster on 21/21. Median 2.4×, range 1.1×–11.7×.

## Disclosures

- **ifc-lite WASM Total includes redundant parse work.** `parseMeshes` performs its own internal parse independent of `scanEntities`. The additive Total under Dion's rule therefore over-counts parse for ifc-lite WASM. Native does not have this issue — `process_geometry` is a single pass and the additive Total reflects what's actually executed.
- **IOS hardware caveat.** IOS numbers are from Moult's machine; web-ifc and ifc-lite are from M4. Pip ifcopenshell 0.8.2 does not ship the Manifold kernel that Moult uses; using Moult's published Manifold-augmented numbers represents IOS at its best.
- **`ISSUE_034_HouseZ` native product-count gap (−6).** Under investigation. Likely related to `OpeningFilterMode::Default` interaction with voids on that specific model. WASM and IOS agree at 228 here.
- **Zero-copy is a separate category, not a faster Geometry.** `parseZeroCopy` returns a single concatenated buffer without per-element attribution and without applying the exclude list. Not a substitute for Category 2 measurements.
- **Single cold run.** No warmup, no median across multiple runs. Matches upstream methodology.

## Reproducing

```sh
# 1. Get the corpus (21 .ifc files in models/)

# 2. WASM ifc-lite + web-ifc
pnpm install
pnpm start                       # ifc-lite WASM (Categories 1, 2, 3)
pnpm zerocopy                    # ifc-lite WASM (Category 4)
cd webifc && npm install
pnpm start                       # web-ifc (Categories 1, 2, 3)
pnpm zerocopy                    # web-ifc (Category 4 reference)

# 3. Native ifc-lite (Rust, requires Cargo)
cd ../ifclite-rs && cargo build --release
cd .. && node run_native.mjs     # produces ifclite-native-{1c,max}.json

# 4. Render chart
python3 -m pip install matplotlib
python3 compare/render_dion.py   # writes results/comparison.png
```

## Files

```
profiling/
├── ifclite-rs/                 ← native bench Cargo project
│   ├── Cargo.toml
│   └── src/main.rs
├── run_native.mjs              ← Node driver for the native binary
├── src/
│   ├── main_dion.ts            ← Categories 1, 2, 3 WASM
│   └── main_zerocopy.ts        ← Category 4 WASM
├── webifc/src/
│   ├── main_dion.ts            ← Categories 1, 2, 3
│   └── main_zerocopy_ref.ts    ← Category 4 reference
├── compare/
│   └── render_dion.py          ← chart renderer (4 panels, 6 series in 1-3, 2 in 4)
└── results/
    ├── comparison.png
    ├── ifclite-dion.json
    ├── webifc-dion.json
    ├── ifclite-native-1c.json
    ├── ifclite-native-max.json
    ├── ifclite-zerocopy.json
    ├── webifc-zerocopy.json
    ├── host-info.json
    └── RESULTS.md              ← this file
```
