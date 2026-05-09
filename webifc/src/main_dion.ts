/* web-ifc runner aligned with Dion's framework (Categories 1, 2, 3).
 *
 * Mirrors his main_simple.ts but with explicit phase split and the same
 * exclude filter applied at product counting (matches IOS).
 */

import { readFile, readdir, stat } from 'node:fs/promises';
import { resolve, dirname, join, basename } from 'node:path';
import { fileURLToPath } from 'node:url';
import { writeFileSync } from 'node:fs';
import * as WebIFC from 'web-ifc';

const __dirname = dirname(fileURLToPath(import.meta.url));
const MODELS_DIR = resolve(__dirname, '..', '..', 'models');
const RESULTS_DIR = resolve(__dirname, '..', '..', 'results');

const typeIdToName = new Map<number, string>();
for (const [key, value] of Object.entries(WebIFC)) {
  if (typeof value === 'number' && key.startsWith('IFC') && key === key.toUpperCase()) {
    typeIdToName.set(value, key);
  }
}

// Dion's exclude set, normalized to web-ifc's all-caps type names.
const EXCLUDE_NAMES = new Set([
  'IFCOPENINGELEMENT',
  'IFCOPENINGSTANDARDCASE',
  'IFCSPACE',
  'IFCBUILDING',
  'IFCBUILDINGSTOREY',
]);

const api = new WebIFC.IfcAPI();
await api.Init();
api.SetLogLevel(WebIFC.LogLevel.LOG_LEVEL_OFF);

const ifcFiles: { name: string; path: string; size: number }[] = [];
const target = process.argv[2];
if (target) {
  const p = resolve(target.includes('/') ? target : join(MODELS_DIR, target));
  const s = await stat(p);
  ifcFiles.push({ name: basename(p), path: p, size: s.size });
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
  byType: Record<string, number>;
}

const results: Result[] = [];

for (const { name, path, size } of ifcFiles) {
  const sizeMb = size / (1024 * 1024);
  console.log(`\n${'='.repeat(60)}\n${name} (${sizeMb.toFixed(1)} MB)\n${'='.repeat(60)}`);

  const buffer = await readFile(path);

  // Category 1 — Parse / Open
  let t0 = performance.now();
  const modelID = api.OpenModel(new Uint8Array(buffer));
  const tParse = (performance.now() - t0) / 1000;
  console.log(`  parse: ${tParse.toFixed(3)}s`);

  // Category 2 — Query (walls + slabs)
  t0 = performance.now();
  const ifcWall = (WebIFC as any).IFCWALL;
  const ifcWallStd = (WebIFC as any).IFCWALLSTANDARDCASE;
  const ifcWallElem = (WebIFC as any).IFCWALLELEMENTEDCASE;
  const ifcSlab = (WebIFC as any).IFCSLAB;
  const ifcSlabElem = (WebIFC as any).IFCSLABELEMENTEDCASE;
  const wallIds = api.GetLineIDsWithType(modelID, ifcWall, false);
  const wallStdIds = api.GetLineIDsWithType(modelID, ifcWallStd, false);
  const wallElemIds = ifcWallElem ? api.GetLineIDsWithType(modelID, ifcWallElem, false) : { size: () => 0 };
  const slabIds = api.GetLineIDsWithType(modelID, ifcSlab, false);
  const slabElemIds = ifcSlabElem ? api.GetLineIDsWithType(modelID, ifcSlabElem, false) : { size: () => 0 };
  const walls = wallIds.size() + wallStdIds.size() + wallElemIds.size();
  const slabs = slabIds.size() + slabElemIds.size();
  const tQuery = (performance.now() - t0) / 1000;
  console.log(`  IfcWall: ${walls}, IfcSlab: ${slabs} (query: ${tQuery.toFixed(3)}s)`);

  // Category 3 — Geometry: StreamAllMeshes with exclude filter
  let products = 0;
  const typeCounts: Record<string, number> = {};
  let tGeom: number | null = null;
  try {
    const tg0 = performance.now();
    api.StreamAllMeshes(modelID, (mesh) => {
      const typeId = api.GetLineType(modelID, mesh.expressID);
      const typeName = typeIdToName.get(typeId) ?? 'Unknown';
      if (EXCLUDE_NAMES.has(typeName)) return;
      products++;
      typeCounts[typeName] = (typeCounts[typeName] ?? 0) + 1;
    });
    tGeom = (performance.now() - tg0) / 1000;
    console.log(`  geometry (${products} products): ${tGeom.toFixed(3)}s`);
    for (const [t, c] of Object.entries(typeCounts).sort((a, b) => b[1] - a[1])) {
      console.log(`    ${t}: ${c}`);
    }
  } catch (e) {
    console.log(`  geometry: FAILED (${e})`);
  }
  api.CloseModel(modelID);

  results.push({ file: name, sizeMb, tParse, tQuery, tGeom, walls, slabs, products, byType: typeCounts });
}

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
  join(RESULTS_DIR, 'webifc-dion.json'),
  JSON.stringify({ engine: 'web-ifc', date: new Date().toISOString(), results }, null, 2)
);
console.log(`\nJSON written to ${join(RESULTS_DIR, 'webifc-dion.json')}`);
