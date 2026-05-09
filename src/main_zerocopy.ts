/* ifc-lite Category 4 — zero-copy / GPU-ready geometry buffer.
 *
 * Output: single concatenated buffer accessible as Float32Array + Uint32Array
 * views into WASM memory. No per-element attribution, no exclude filter — by
 * design. This is what ifc-lite's own viewer uses for GPU upload.
 *
 * Not a faster Category 2; a separate category with a different output goal.
 */

import { readFile, readdir, stat } from 'node:fs/promises';
import { resolve, dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { writeFileSync } from 'node:fs';
import initWasm, { IfcAPI } from '@ifc-lite/wasm';

const __dirname = dirname(fileURLToPath(import.meta.url));
const MODELS_DIR = resolve(__dirname, '..', 'models');
const RESULTS_DIR = resolve(__dirname, '..', 'results');

const wasmPkgDir = dirname(fileURLToPath(import.meta.resolve('@ifc-lite/wasm')));
const wasmBytes = await readFile(join(wasmPkgDir, 'ifc-lite_bg.wasm'));
await initWasm({ module_or_path: wasmBytes });

const ifcFiles: { name: string; path: string; size: number }[] = [];
for (const name of await readdir(MODELS_DIR)) {
  if (!/\.ifc$/i.test(name)) continue;
  const path = join(MODELS_DIR, name);
  const s = await stat(path);
  ifcFiles.push({ name, path, size: s.size });
}
ifcFiles.sort((a, b) => a.size - b.size);

interface Result { file: string; sizeMb: number; tZeroCopy: number | null; vertices: number; triangles: number; }
const results: Result[] = [];

for (const { name, path, size } of ifcFiles) {
  const sizeMb = size / (1024 * 1024);
  const buffer = await readFile(path);
  const origLog = console.log, origWarn = console.warn;
  console.log = () => {}; console.warn = () => {};
  let t: number | null = null, verts = 0, tris = 0;
  try {
    const t0 = performance.now();
    const api = new IfcAPI();
    const content = new TextDecoder().decode(buffer);
    const r = api.parseZeroCopy(content);
    t = (performance.now() - t0) / 1000;
    verts = r.vertex_count;
    tris = r.triangle_count;
    r.free();
  } catch (e) {
    t = null;
  }
  console.log = origLog; console.warn = origWarn;
  console.log(`${name.padEnd(50)} ${sizeMb.toFixed(1).padStart(6)}M  parseZeroCopy: ${t !== null ? t.toFixed(3) + 's' : 'FAIL'}  (verts=${verts}, tris=${tris})`);
  results.push({ file: name, sizeMb, tZeroCopy: t, vertices: verts, triangles: tris });
}

writeFileSync(join(RESULTS_DIR, 'ifclite-zerocopy.json'),
  JSON.stringify({ engine: 'ifc-lite-zerocopy', date: new Date().toISOString(), results }, null, 2));
console.log(`\nJSON written to ${join(RESULTS_DIR, 'ifclite-zerocopy.json')}`);
