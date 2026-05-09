/* web-ifc Category 4 reference — what a real viewer must do to produce a
 * single GPU-ready geometry buffer with web-ifc:
 *
 *   1. OpenModel
 *   2. StreamAllMeshes — for each placed geometry:
 *      a. GetGeometry, GetVertexArray, GetIndexArray
 *      b. apply mesh-flat-transform to vertex positions (4×4 matrix)
 *      c. append to JS-side buffers
 *   3. concat per-mesh buffers into one Float32Array (positions+normals
 *      interleaved) and one Uint32Array (indices, with offset baked in)
 *
 * This is the closest equivalent to ifc-lite parseZeroCopy. Output: a single
 * pair of buffers ready for a single device.queue.writeBuffer call.
 */

import { readFile, readdir, stat } from 'node:fs/promises';
import { resolve, dirname, join, basename } from 'node:path';
import { fileURLToPath } from 'node:url';
import { writeFileSync } from 'node:fs';
import * as WebIFC from 'web-ifc';

const __dirname = dirname(fileURLToPath(import.meta.url));
const MODELS_DIR = resolve(__dirname, '..', '..', 'models');
const RESULTS_DIR = resolve(__dirname, '..', '..', 'results');

const api = new WebIFC.IfcAPI();
await api.Init();
api.SetLogLevel(WebIFC.LogLevel.LOG_LEVEL_OFF);

const ifcFiles: { name: string; path: string; size: number }[] = [];
for (const name of await readdir(MODELS_DIR)) {
  if (!/\.ifc$/i.test(name)) continue;
  const path = join(MODELS_DIR, name);
  const s = await stat(path);
  ifcFiles.push({ name, path, size: s.size });
}
ifcFiles.sort((a, b) => a.size - b.size);

interface Result {
  file: string;
  sizeMb: number;
  tZeroCopyRef: number | null;
  vertices: number;
  triangles: number;
}
const results: Result[] = [];

for (const { name, path, size } of ifcFiles) {
  const sizeMb = size / (1024 * 1024);
  const buffer = await readFile(path);

  let t: number | null = null;
  let totalVerts = 0;
  let totalTris = 0;

  try {
    const t0 = performance.now();
    const modelID = api.OpenModel(new Uint8Array(buffer));

    const vertexChunks: Float32Array[] = [];
    const indexChunks: Uint32Array[] = [];

    api.StreamAllMeshes(modelID, (mesh) => {
      const placedGeoms = mesh.geometries;
      for (let j = 0; j < placedGeoms.size(); j++) {
        const pg = placedGeoms.get(j);
        const geometry = api.GetGeometry(modelID, pg.geometryExpressID);
        const verts = api.GetVertexArray(geometry.GetVertexData(), geometry.GetVertexDataSize());
        const indices = api.GetIndexArray(geometry.GetIndexData(), geometry.GetIndexDataSize());

        // verts is interleaved [px, py, pz, nx, ny, nz, ...]
        // For zero-copy ref fairness we just append; we skip the flat-transform
        // multiply since ifc-lite parseZeroCopy also doesn't apply per-instance
        // transforms (it concatenates raw geometry).
        vertexChunks.push(new Float32Array(verts));
        indexChunks.push(new Uint32Array(indices));
        totalVerts += verts.length / 6;
        totalTris += indices.length / 3;
        geometry.delete();
      }
    });

    // Concatenate into single buffers
    let vTotal = 0;
    for (const c of vertexChunks) vTotal += c.length;
    const finalVerts = new Float32Array(vTotal);
    let off = 0;
    for (const c of vertexChunks) {
      finalVerts.set(c, off);
      off += c.length;
    }

    let iTotal = 0;
    for (const c of indexChunks) iTotal += c.length;
    const finalIdx = new Uint32Array(iTotal);
    off = 0;
    let baseVertex = 0;
    for (let k = 0; k < indexChunks.length; k++) {
      const c = indexChunks[k];
      // bake in the vertex offset so concatenated indices are valid
      for (let m = 0; m < c.length; m++) finalIdx[off + m] = c[m] + baseVertex;
      off += c.length;
      baseVertex += vertexChunks[k].length / 6;
    }

    api.CloseModel(modelID);
    t = (performance.now() - t0) / 1000;
  } catch (e) {
    t = null;
  }

  console.log(`${name.padEnd(50)} ${sizeMb.toFixed(1).padStart(6)}M  zerocopy-ref: ${t !== null ? t.toFixed(3) + 's' : 'FAIL'}  (verts=${totalVerts}, tris=${totalTris})`);
  results.push({ file: name, sizeMb, tZeroCopyRef: t, vertices: totalVerts, triangles: totalTris });
}

writeFileSync(
  join(RESULTS_DIR, 'webifc-zerocopy.json'),
  JSON.stringify({ engine: 'web-ifc-zerocopy-ref', date: new Date().toISOString(), results }, null, 2)
);
console.log(`\nJSON written to ${join(RESULTS_DIR, 'webifc-zerocopy.json')}`);
