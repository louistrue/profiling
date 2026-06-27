// Reproduce the VIEWER streaming path (GeometryProcessor.processStreaming),
// not the raw parseMeshes single-call path. Used to bisect the Holter
// "fine -> crawling" wasm/geometry regression between #1394 and main.
import { readFile } from 'node:fs/promises';
import { resolve, dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { GeometryProcessor } from '@ifc-lite/geometry';

const __dirname = dirname(fileURLToPath(import.meta.url));
const MODELS = resolve(__dirname, '..', 'models');
const target = process.argv[2] ?? 'ISSUE_053_20181220Holter_Tower_10.ifc';
const path = target.includes('/') ? target : join(MODELS, target);

// Report the installed versions so each run is self-labelling.
const gv = JSON.parse(await readFile(resolve(__dirname, '..', 'node_modules/@ifc-lite/geometry/package.json'), 'utf8')).version;
const wv = JSON.parse(await readFile(resolve(__dirname, '..', 'node_modules/@ifc-lite/wasm/package.json'), 'utf8')).version;

const bytes = new Uint8Array(await readFile(path));
const proc = new GeometryProcessor();
await proc.init();

const t0 = performance.now();
let meshes = 0, batches = 0, firstBatch = 0;
try {
  for await (const ev of proc.processStreaming(bytes)) {
    if (ev.type === 'batch') {
      if (!firstBatch) firstBatch = performance.now() - t0;
      meshes += ev.meshes.length; batches++;
    }
  }
  const ms = performance.now() - t0;
  console.log(`geometry=${gv} wasm=${wv} | ${target}: streaming TOTAL=${(ms/1000).toFixed(2)}s firstBatch=${(firstBatch/1000).toFixed(2)}s meshes=${meshes} batches=${batches}`);
} catch (e) {
  const ms = performance.now() - t0;
  console.log(`geometry=${gv} wasm=${wv} | ${target}: FAILED after ${(ms/1000).toFixed(2)}s -> ${e instanceof Error ? e.message : e}`);
}
