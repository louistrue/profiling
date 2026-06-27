# WASM wide-arithmetic measurement (2026-06-27)

Two standalone benches proving the wasm wide-arithmetic win on ifc-lite's exact CSG.
- `widebench/`  predicate microbench (bnum I256/I512 det3 = orient3d core)
- `csgbench/`   end-to-end real void cut via `ifc_lite_geometry::kernel::mesh_bridge::subtract_many`
  (edit the `ifc-lite-geometry` path dep to your checkout)

Each: build baseline + `RUSTFLAGS=-C target-feature=+wide-arithmetic` (separate --target-dir),
then `wasmtime run -W wide-arithmetic=y --invoke <fn> <wide.wasm> <args>`.

Measured (M4): predicate 1.9x (I256) / 3.1x (I512); end-to-end CSG 1.71x (23.2->13.6 ms/cut),
wasm 2.26x->1.33x of native. See ifc-lite docs/architecture/wasm-wide-arithmetic.md.
