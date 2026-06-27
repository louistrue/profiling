# ifc-lite vs ThatOpen — what the load-speed numbers actually say

Response to the IFClite-vs-ThatOpen benchmark (github.com/Blogbotana/IFClite-vs-ThatOpen).
All ifc-lite/web-ifc numbers below are same-machine (Apple M4), engine-only (headless,
no renderer), via this profiling harness. ifc-lite native = built from latest `main`;
ifc-lite WASM = latest published `@ifc-lite/wasm`; web-ifc = 0.0.77.

## TL;DR: it is not the parser

The benchmark's headline ("ThatOpen up to 3x faster") is on **total open time**, which is
dominated by **geometry** (boolean/void CSG + mesh generation), not parsing. The
benchmark's own **Parse / convert** row shows ifc-lite faster in every architectural
model plus Tekla and Revit (x2.7 to x13). The parser is ifc-lite's strongest dimension,
not its weakness.

Where ThatOpen wins is the geometry stage on CSG/brep-heavy models, and that gap is
**specific to the in-browser WASM path**, not the engine.

## The Tekla model (the case ThatOpen "won"), same machine, engine-only

| engine | total open | triangles | notes |
|---|---:|---:|---|
| ifc-lite **native** (main, 10 threads) | **2.9s** | 3.0M | fastest; rayon over one heap |
| web-ifc 0.0.77 (1 core) | 4.9s | 2.5M | approximate booleans, coarse curve tessellation |
| ifc-lite native (main, 1 core) | 14.2s | 3.0M | per-core slower than web-ifc on exact CSG |
| ifc-lite **WASM** (latest published) | ~30s | 7.9M | exact CSG + no dedup in this path = the real gap |

Parse alone: ifc-lite ~0.1s vs web-ifc ~0.14s.

The same Rust kernel does this model in **2.9s natively (faster than web-ifc) but ~30s in
WASM**. So the algorithm is not the problem; the WASM execution of exact CSG is.

## Why WASM is slow here (the actual root cause)

ifc-lite uses an **exact, robust pure-Rust CSG kernel** (deterministic, no over-cutting).
Its predicate cascade uses wide fixed-width integers (i256/i512/...). Native CPUs do that
in stack-allocated arithmetic; **wasm32 has no wide-integer hardware**, so it emulates with
u64 limbs and, on hard cases, falls back to heap-allocated big-rationals (~ms per
predicate). That is the 6-20x gap on brep/CSG-heavy models. web-ifc sidesteps it with
faster approximate booleans; ThatOpen's fragments format also instances repeated geometry
(steel detailers emit thousands of byte-identical parts), so it meshes each unique part
once.

## Benchmark fairness notes (to make it apples-to-apples)

The harness handicaps ifc-lite in ways unrelated to engine speed:
- **`enableInstancing: false`** — every repeated steel part is meshed individually instead
  of once-and-instanced. ThatOpen fragments instance by design.
- **Parquet/BOS export with geometry runs inside the timed path** for ifc-lite; ThatOpen
  exports a lighter `.frag` buffer.
- ifc-lite geometry runs on the **main thread** (the documented happy-path), not the
  production worker pool.
- "ThatOpen" here is `@thatopen/fragments`, which is heavier than raw `web-ifc` but
  instanced — not the same thing as the web-ifc core.

## What this means

- ifc-lite's parser and its native geometry are already best-in-class (native wins the
  full Moult corpus 21/21 on total time; see RESULTS.md).
- The one real, honest gap is **in-browser WASM exact-CSG on brep/CSG-heavy models**. The
  levers are: dedup/instancing on that path, and the WASM wide-arithmetic proposal (a
  big-int workload went from ~120% slower-than-native to ~9% on x86_64 with it) -- the only
  no-install lever that attacks the root cause.

Reproduce: `./scripts/refresh-engines.sh` then `pnpm native`, `pnpm start`, and
`cd webifc && pnpm start`.
