/* ifc-lite runner aligned with Dion's framework (Categories 1, 2, 3).
 *
 * Category 1 — Parse / Open: StepTokenizer.scanEntities + JS-side byType / byId index.
 *   Output goal: model in queryable state (by_type works, attributes lazy).
 *   Equivalent to web-ifc OpenModel (tokenized, lazy attributes) and IOS open()
 *   (semantically; IOS's open is more eager).
 *
 * Category 2 — Geometry: api.parseMeshes(content) with exclude filter on mesh.ifcType.
 *   Output goal: per-element meshes, exclude list applied, comparable product counts.
 *
 * Category 3 — Total: tParse + tQuery + tGeom (additive per Dion's rule).
 *
 * JSON schema matches profile_ifc.py / webifc main.ts row shape:
 *   { file, sizeMb, tParse, tQuery, tGeom, walls, slabs, products, byType }
 */

import { readFile, readdir, stat } from 'node:fs/promises';
import { resolve, dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { writeFileSync } from 'node:fs';

import { StepTokenizer } from '@ifc-lite/parser';
import initWasm, { IfcAPI } from '@ifc-lite/wasm';

const __dirname = dirname(fileURLToPath(import.meta.url));
const MODELS_DIR = resolve(__dirname, '..', 'models');
const RESULTS_DIR = resolve(__dirname, '..', 'results');

const wasmPkgDir = dirname(fileURLToPath(import.meta.resolve('@ifc-lite/wasm')));
const wasmBytes = await readFile(join(wasmPkgDir, 'ifc-lite_bg.wasm'));
await initWasm({ module_or_path: wasmBytes });

// Dion's exclude set (verbatim from profile_ifc.py + main.ts).
const EXCLUDE_TYPES = new Set([
  'IfcOpeningElement',
  'IfcOpeningStandardCase',
  'IfcSpace',
  'IfcBuilding',
  'IfcBuildingStorey',
]);

const ifcFiles: { name: string; path: string; size: number }[] = [];
const target = process.argv[2];
if (target) {
  const p = resolve(target.includes('/') ? target : join(MODELS_DIR, target));
  const s = await stat(p);
  ifcFiles.push({ name: p.split('/').pop()!, path: p, size: s.size });
} else {
  for (const name of await readdir(MODELS_DIR)) {
    if (!/\.ifc$/i.test(name)) continue;
    const path = join(MODELS_DIR, name);
    const s = await stat(path);
    ifcFiles.push({ name, path, size: s.size });
  }
  ifcFiles.sort((a, b) => a.size - b.size);
}

interface Result {
  file: string;
  sizeMb: number;
  tParse: number;
  tQuery: number;
  tGeom: number | null;
  walls: number;
  slabs: number;
  products: number;
  vertices: number;
  triangles: number;
  byType: Record<string, number>;
}

const results: Result[] = [];

for (const { name, path, size } of ifcFiles) {
  const sizeMb = size / (1024 * 1024);
  console.log(`\n${'='.repeat(60)}\n${name} (${sizeMb.toFixed(1)} MB)\n${'='.repeat(60)}`);

  const buffer = await readFile(path);

  // Category 1 — Parse / Open
  let t0 = performance.now();
  const tokenizer = new StepTokenizer(buffer);
  const byType = new Map<string, number[]>();        // upper-case STEP type → expressIds
  const byId = new Map<number, { type: string; offset: number; length: number }>();
  for (const ref of tokenizer.scanEntities()) {
    let arr = byType.get(ref.type);
    if (!arr) {
      arr = [];
      byType.set(ref.type, arr);
    }
    arr.push(ref.expressId);
    byId.set(ref.expressId, { type: ref.type, offset: ref.offset, length: ref.length });
  }
  const tParse = (performance.now() - t0) / 1000;
  console.log(`  parse: ${tParse.toFixed(3)}s`);

  // Category 2 — Query (count walls + slabs)
  t0 = performance.now();
  const walls =
    (byType.get('IFCWALL')?.length ?? 0) +
    (byType.get('IFCWALLSTANDARDCASE')?.length ?? 0) +
    (byType.get('IFCWALLELEMENTEDCASE')?.length ?? 0);
  const slabs =
    (byType.get('IFCSLAB')?.length ?? 0) +
    (byType.get('IFCSLABELEMENTEDCASE')?.length ?? 0);
  const tQuery = (performance.now() - t0) / 1000;
  console.log(`  IfcWall: ${walls}, IfcSlab: ${slabs} (query: ${tQuery.toFixed(3)}s)`);

  // Category 3 — Geometry: parseMeshes + exclude filter on ifcType
  let tGeom: number | null = null;
  let products = 0;
  let totalVerts = 0;
  let totalTris = 0;
  const typeCounts: Record<string, number> = {};
  const origLog = console.log;
  const origWarn = console.warn;
  console.log = () => {};
  console.warn = () => {};
  try {
    const tg0 = performance.now();
    const api = new IfcAPI();
    const content = new TextDecoder().decode(buffer);
    const collection = api.parseMeshes(content);
    const seen = new Set<number>();
    for (let i = 0; i < collection.length; i++) {
      const mesh = collection.get(i);
      if (!mesh) continue;
      if (seen.has(mesh.expressId)) continue;
      const t = mesh.ifcType || 'Unknown';
      if (EXCLUDE_TYPES.has(t)) continue;
      seen.add(mesh.expressId);
      typeCounts[t] = (typeCounts[t] ?? 0) + 1;
      totalVerts += mesh.positions.length / 3;
      totalTris += mesh.indices.length / 3;
    }
    products = seen.size;
    tGeom = (performance.now() - tg0) / 1000;
  } catch (e) {
    console.log = origLog;
    console.warn = origWarn;
    console.log(`  geometry: FAILED (${e})`);
  }
  console.log = origLog;
  console.warn = origWarn;
  if (tGeom !== null) {
    console.log(`  geometry (${products} products, ${totalVerts} verts, ${totalTris} tris): ${tGeom.toFixed(3)}s`);
    for (const [t, c] of Object.entries(typeCounts).sort((a, b) => b[1] - a[1])) {
      console.log(`    ${t}: ${c}`);
    }
  }

  results.push({
    file: name, sizeMb, tParse, tQuery, tGeom, walls, slabs, products,
    vertices: totalVerts, triangles: totalTris, byType: typeCounts,
  });
}

// Summary table (matches Dion's profile_ifc.py format)
const w = Math.max(...results.map((r) => r.file.length)) + 2;
const total = w + 50;
console.log(`\n\n${'='.repeat(total)}`);
console.log(
  `${'FILE'.padEnd(w)} ${'SIZE'.padStart(7)} ${'PARSE'.padStart(7)} ${'QUERY'.padStart(7)} ${'GEOM'.padStart(7)} ${'PRODS'.padStart(6)}`
);
console.log('-'.repeat(total));
for (const r of results) {
  const geom = r.tGeom !== null ? `${r.tGeom.toFixed(2)}s` : 'FAIL';
  console.log(
    `${r.file.padEnd(w)} ${(r.sizeMb.toFixed(1) + 'M').padStart(7)} ${(r.tParse.toFixed(2) + 's').padStart(7)} ${(r.tQuery.toFixed(3) + 's').padStart(7)} ${geom.padStart(7)} ${String(r.products).padStart(6)}`
  );
}
console.log('='.repeat(total));

writeFileSync(
  join(RESULTS_DIR, 'ifclite-dion.json'),
  JSON.stringify({ engine: 'ifc-lite', date: new Date().toISOString(), results }, null, 2)
);
console.log(`\nJSON written to ${join(RESULTS_DIR, 'ifclite-dion.json')}`);
