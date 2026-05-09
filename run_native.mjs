// Driver: spawns the native Rust bench binary across all 21 files at two
// thread counts (1 and max), aggregates per-file JSON rows into two output files.

import { readdir, stat, writeFile } from 'node:fs/promises';
import { resolve, dirname, join, basename } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { cpus } from 'node:os';

const __dirname = dirname(fileURLToPath(import.meta.url));
const MODELS_DIR = resolve(__dirname, 'models');
const RESULTS_DIR = resolve(__dirname, 'results');
const BIN = resolve(__dirname, 'ifclite-rs/target/release/ifclite-bench');

const MAX = cpus().length;
const RUNS = [
  { threads: 1,    label: 'single-thread', outFile: 'ifclite-native-1c.json' },
  { threads: MAX,  label: `${MAX}-threads`, outFile: 'ifclite-native-max.json' },
];

const files = (await readdir(MODELS_DIR))
  .filter((n) => /\.ifc$/i.test(n));
const sized = await Promise.all(files.map(async (n) => {
  const path = join(MODELS_DIR, n);
  const s = await stat(path);
  return { name: n, path, size: s.size };
}));
sized.sort((a, b) => a.size - b.size);

for (const run of RUNS) {
  const results = [];
  console.log(`\n=== ${run.label} (threads=${run.threads}) ===`);
  for (const f of sized) {
    process.stdout.write(`  ${f.name.padEnd(60)} (${(f.size / 1e6).toFixed(1).padStart(6)} MB) ... `);
    const out = spawnSync(BIN, [f.path, '--threads', String(run.threads), '--label', run.label], {
      encoding: 'utf8',
      maxBuffer: 1 << 28,
    });
    if (out.status !== 0) {
      console.log(`FAIL (status=${out.status})`);
      console.error(out.stderr);
      continue;
    }
    const row = JSON.parse(out.stdout.trim());
    results.push(row);
    console.log(`parse=${row.t_parse.toFixed(2)}s geom=${row.t_geom.toFixed(2)}s total=${row.t_total.toFixed(2)}s prods=${row.products}`);
  }
  const outPath = join(RESULTS_DIR, run.outFile);
  await writeFile(outPath, JSON.stringify({
    engine: 'ifc-lite-native',
    label: run.label,
    threads: run.threads,
    date: new Date().toISOString(),
    results,
  }, null, 2));
  console.log(`  wrote ${outPath}`);
}
