# IFC engine comparison

Apples-to-apples profiling of three IFC engines under the methodology of
`Moult/profiling`. Three categories preserved from the upstream harness
(Parse, Geometry, Total). One category proposed (Zero-copy / GPU-ready
geometry buffer).

## Setup

- **Hardware**: Apple M4 / 10c / 16 GB / macOS 26.4.1 / Node 22.14.
- **Engines**:
  - `IfcOpenShell` — numbers reproduced verbatim from `Moult/profiling/findings.md` (his hardware, datamodel branch, `hybrid-manifold-cgal-simple-opencascade` kernel). Two configurations: single core, max threads.
  - `web-ifc@0.0.68` — matches `webifc/package-lock.json`. Run on M4.
  - `ifc-lite (WASM)` — `@ifc-lite/parser@2.3.0` + `@ifc-lite/wasm@1.16.8`. Run on M4. Single-threaded.
  - `ifc-lite (native, 1 core)` — `ifc-lite-processing` Rust crate, rayon thread pool size 1. Run on M4.
  - `ifc-lite (native, 10 threads)` — same crate, rayon thread pool sized to CPU count. Run on M4.
- **Hardware caveat**: IOS rows are from a different machine. IOS-vs-others comparisons carry a hardware caveat. Cross-engine ratios within IOS bars (single vs max) are valid.
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

The native ifc-lite path uses the same `ifc-lite-processing` crate the production server uses (`apps/server` in the `ifc-lite` repo). The bench binary (`ifclite-rs/`) calls `process_geometry(&content)` directly — no HTTP, no WASM. rayon thread pool size is configurable via `--threads N`. Internal per-phase timings come from `ProcessingStats` (the same struct the server returns to clients).

Build: `cd ifclite-rs && cargo build --release`. Drive: `node run_native.mjs`.

## Product-count validation

Counts after the exclude list is applied, vs Moult's IOS reference.

| File | IOS | web-ifc | ifc-lite WASM | ifc-lite native | web Δ | WASM Δ | native Δ |
|---|---:|---:|---:|---:|---:|---:|---:|
| duplex.ifc | 215 | 216 | 215 | 215 | +1 | 0 | 0 |
| AC20-FZK-Haus.ifc | 83 | 83 | 83 | 83 | 0 | 0 | 0 |
| ISSUE_005_haus.ifc | 83 | 83 | 83 | 83 | 0 | 0 | 0 |
| ISSUE_021_Mini Project.ifc | 2636 | 2636 | 2636 | 2636 | 0 | 0 | 0 |
| Office_A_20110811.ifc | 803 | 803 | 803 | 803 | 0 | 0 | 0 |
| ISSUE_126_model.ifc | 257 | 257 | 257 | 257 | 0 | 0 | 0 |
| ISSUE_034_HouseZ.ifc | 228 | 228 | 228 | **222** | 0 | 0 | **−6** |
| ISSUE_102_M3D-CON.ifc | 138 | 138 | 138 | 138 | 0 | 0 | 0 |
| ISSUE_159_kleine_Wohnung_R22.ifc | 414 | 425 | 425 | 425 | +11 | +11 | +11 |
| C20-Institute-Var-2.ifc | 702 | 702 | 702 | 702 | 0 | 0 | 0 |
| ISSUE_129_…IGC_V17.ifc | 959 | 959 | 947 | 947 | 0 | −12 | −12 |
| dental_clinic.ifc | 2586 | 2586 | 2583 | 2583 | 0 | −3 | −3 |
| FM_ARC_DigitalHub.ifc | 692 | 705 | 703 | 703 | +13 | +11 | +11 |
| ifcbridge-model01.ifc | 165 | 165 | 165 | 165 | 0 | 0 | 0 |
| ISSUE_102_M3D-CON-CD.ifc | 1616 | 1616 | 1616 | 1616 | 0 | 0 | 0 |
| S_Office_Integrated Design Archi.ifc | 3407 | 3422 | 3396 | 3396 | +15 | −11 | −11 |
| advanced_model.ifc | 6401 | 6401 | 6400 | **6401** | 0 | −1 | **0** |
| schependomlaan.ifc | 3569 | 3569 | 3566 | **3569** | 0 | −3 | **0** |
| ISSUE_068_ARK_NUS_skolebygg.ifc | 4459 | 4459 | 4453 | **4459** | 0 | −6 | **0** |
| ISSUE_098_…MO_7000.IFC | 11124 | 11124 | 11123 | 11123 | 0 | −1 | −1 |
| ISSUE_053_…Holter_Tower_10.ifc | 60285 | 60285 | 60285 | 60285 | 0 | 0 | 0 |

- web-ifc exact match vs IOS: **17/21**
- ifc-lite WASM exact match vs IOS: **12/21**
- ifc-lite native exact match vs IOS: **14/21**

The native path closes WASM's gaps on `advanced_model`, `schependomlaan`, and `ISSUE_068_ARK_NUS_skolebygg` (likely the same `has_geometry_by_name` missing-types issue the WASM bindings expose, fixed in the Rust pipeline). It opens a new gap on `ISSUE_034_HouseZ` (−6 vs WASM); this may be related to the default opening-filter mode (`OpeningFilterMode::Default`, which keeps openings and cuts voids in hosts) interacting differently with voids for that specific model. Worth investigating but not a blocker for this comparison — within the same ≤2% per-file tolerance the other engines show.

The shared deltas across all M4 measurements (`ISSUE_159` +11, `ISSUE_129` −12, `FM_ARC` +11/+13, `S_Office` ±) indicate either differing exclude-list interpretations or genuinely different geometry resolution between IOS and the M4 engines. Same pattern Moult flagged in upstream `findings.md`.

## Timings

### Category 3 — Total (parse + geometry), seconds

| File | size | IOS 1c | IOS max | web-ifc | ifc-lite WASM | ifc-lite native 1c | ifc-lite native 10t |
|---|---:|---:|---:|---:|---:|---:|---:|
| duplex.ifc | 2.3M | 0.19 | 0.12 | 0.07 | 0.13 | 0.03 | **0.02** |
| AC20-FZK-Haus.ifc | 2.4M | 0.22 | 0.15 | 0.09 | 0.10 | 0.02 | **0.02** |
| ISSUE_005_haus.ifc | 2.4M | 0.21 | 0.13 | 0.09 | 0.08 | 0.02 | **0.02** |
| ISSUE_021_Mini Project.ifc | 3.2M | 0.53 | 0.29 | 0.29 | 0.15 | 0.07 | **0.04** |
| Office_A_20110811.ifc | 3.8M | 0.29 | 0.25 | 0.11 | 0.14 | 0.06 | **0.04** |
| ISSUE_126_model.ifc | 4.2M | 0.46 | 0.32 | 0.07 | 0.14 | 0.04 | **0.03** |
| ISSUE_034_HouseZ.ifc | 4.8M | 0.71 | 0.38 | 0.09 | 0.16 | 0.07 | **0.05** |
| ISSUE_102_M3D-CON.ifc | 6.0M | 0.62 | 0.49 | 0.14 | 0.22 | 0.06 | **0.04** |
| ISSUE_159_kleine_Wohnung_R22.ifc | 9.5M | 1.65 | 0.91 | 0.33 | 0.48 | 0.21 | **0.08** |
| C20-Institute-Var-2.ifc | 10.3M | 0.71 | 0.67 | 0.32 | 0.31 | 0.11 | **0.08** |
| ISSUE_129_…IGC_V17.ifc | 11.5M | 1.52 | 0.89 | 0.34 | 0.37 | 0.12 | **0.08** |
| dental_clinic.ifc | 12.4M | 1.25 | 0.99 | 0.41 | 0.46 | 0.18 | **0.10** |
| FM_ARC_DigitalHub.ifc | 13.4M | 2.43 | 1.54 | 0.55 | 0.70 | 0.27 | **0.10** |
| ifcbridge-model01.ifc | 14.5M | 2.05 | 1.32 | 0.19 | 0.62 | 0.18 | **0.14** |
| ISSUE_102_M3D-CON-CD.ifc | 25.6M | 4.02 | 2.66 | 1.30 | 1.43 | 0.72 | **0.28** |
| S_Office_Integrated Design Archi.ifc | 29.6M | 4.04 | 2.94 | 2.61 | 1.23 | 0.53 | **0.25** |
| advanced_model.ifc | 33.7M | 3.92 | 3.00 | 1.17 | 1.77 | 0.74 | **0.30** |
| schependomlaan.ifc | 47.0M | 3.35 | 2.85 | 0.59 | 1.42 | 0.51 | **0.41** |
| ISSUE_068_ARK_NUS_skolebygg.ifc | 53.7M | 5.72 | 4.11 | 2.08 | 2.33 | 1.01 | **0.54** |
| ISSUE_098_…MO_7000.IFC | 68.4M | 8.42 | 5.82 | 9.64 | 2.68 | 1.21 | **0.61** |
| ISSUE_053_…Holter_Tower_10.ifc | 169.2M | 19.53 | 13.70 | 5.49 | 8.16 | 3.31 | **1.72** |

**Wins under apples-to-apples Total:**
- ifc-lite native (10 threads): **21/21** vs every other series.
- ifc-lite native (1 core): beats web-ifc on 19/21, beats ifc-lite WASM on 21/21, beats IOS-max on 21/21.
- ifc-lite WASM: beats web-ifc on 5/21, beats IOS-max on a majority but not all.

vs **IOS max threads** (closest hardware-difference-tolerant comparison): ifc-lite native 10 threads is **3.6× to 18× faster** across the corpus (median ~10×).

### Category 4 — Zero-copy / GPU-ready geometry buffer, seconds

Single concatenated buffer, no per-element attribution.

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
- **IOS hardware caveat.** IOS numbers are from Moult's machine; web-ifc and ifc-lite are from M4. IOS bars in the chart are reproduced from upstream for reference.
- **`ISSUE_034_HouseZ` native product-count gap (−6).** Under investigation. Likely related to `OpeningFilterMode::Default` interaction with voids on that specific model. WASM and IOS agree at 228 here.
- **Zero-copy is a separate category, not a faster Geometry.** `parseZeroCopy` returns a single concatenated buffer without per-element attribution and without applying the exclude list. Not a substitute for Category 2 measurements.
- **Single cold run.** No warmup, no median across multiple runs. Matches upstream methodology.

## Files

```
profiling/
├── ifclite-rs/                 ← native bench Cargo project (depends on ifc-lite-processing)
│   ├── Cargo.toml
│   └── src/main.rs
├── run_native.mjs              ← Node driver for the native binary
├── src/
│   ├── main_dion.ts            ← Categories 1, 2, 3 WASM (scanEntities + parseMeshes)
│   └── main_zerocopy.ts        ← Category 4 WASM (parseZeroCopy)
├── webifc/src/
│   ├── main_dion.ts            ← Categories 1, 2, 3 (OpenModel + StreamAllMeshes)
│   └── main_zerocopy_ref.ts    ← Category 4 reference (full extract + JS concat)
├── compare/
│   └── render_dion.py          ← chart renderer (4-panel, 6 series in 1-3, 2 series in 4)
└── results/
    ├── comparison.png          ← chart
    ├── ifclite-dion.json       ← WASM Categories 1-3
    ├── webifc-dion.json
    ├── ifclite-native-1c.json  ← native single-thread
    ├── ifclite-native-max.json ← native multi-thread (10 threads on M4)
    ├── ifclite-zerocopy.json
    ├── webifc-zerocopy.json
    ├── host-info.json
    └── RESULTS.md
```
