// Native ifc-lite bench binary aligned with Dion's framework.
//
// Calls `ifc_lite_processing::process_geometry` (the same code the server uses),
// reads timing from the returned ProcessingStats, applies Dion's exclude list
// at product counting, and prints a JSON row to stdout.
//
// Usage:
//   ifclite-bench <file> [--threads N] [--label TAG]
//
// Wires up rayon's global thread pool with the requested thread count, so this
// gives us the "max threads" equivalent of IOS's iterator(... cpu_count, ...).

use ifc_lite_processing::{process_geometry, ProcessingResult};
use serde::Serialize;
use std::collections::BTreeMap;
use std::env;
use std::fs;
use std::path::Path;
use std::time::Instant;

#[derive(Serialize)]
struct BenchRow {
    file: String,
    size_mb: f64,
    threads: usize,
    label: String,
    t_parse: f64,
    t_geom: f64,
    t_total: f64,
    t_wallclock: f64,
    products: usize,
    walls: usize,
    slabs: usize,
    by_type: BTreeMap<String, u32>,
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 2 {
        eprintln!("usage: ifclite-bench <file> [--threads N] [--label TAG]");
        std::process::exit(2);
    }

    let path = args[1].clone();
    let threads: usize = arg_value(&args, "--threads")
        .and_then(|s| s.parse().ok())
        .unwrap_or_else(num_cpus::get);
    let label = arg_value(&args, "--label").unwrap_or_else(|| {
        if threads == 1 {
            "single-thread".into()
        } else {
            format!("{}-threads", threads)
        }
    });

    rayon::ThreadPoolBuilder::new()
        .num_threads(threads)
        .build_global()
        .ok();

    let bytes = fs::read(&path).expect("read file");
    let size_mb = bytes.len() as f64 / 1024.0 / 1024.0;
    let content = String::from_utf8(bytes).expect("utf8");

    let t0 = Instant::now();
    let result: ProcessingResult = process_geometry(&content);
    let wallclock_ms = t0.elapsed().as_secs_f64() * 1000.0;

    // Dion's exclude set — verbatim from profile_ifc.py + main.ts
    let exclude: std::collections::HashSet<&str> = [
        "IfcOpeningElement",
        "IfcOpeningStandardCase",
        "IfcSpace",
        "IfcBuilding",
        "IfcBuildingStorey",
    ]
    .into_iter()
    .collect();

    let mut by_type: BTreeMap<String, u32> = BTreeMap::new();
    let mut products = 0usize;
    let mut walls = 0usize;
    let mut slabs = 0usize;
    let mut seen = std::collections::HashSet::new();
    for m in &result.meshes {
        if exclude.contains(m.ifc_type.as_str()) {
            continue;
        }
        if !seen.insert(m.express_id) {
            continue;
        }
        *by_type.entry(m.ifc_type.clone()).or_default() += 1;
        products += 1;
        match m.ifc_type.as_str() {
            "IfcWall" | "IfcWallStandardCase" | "IfcWallElementedCase" => walls += 1,
            "IfcSlab" | "IfcSlabElementedCase" => slabs += 1,
            _ => {}
        }
    }

    let stats = &result.stats;
    let row = BenchRow {
        file: Path::new(&path)
            .file_name()
            .and_then(|s| s.to_str())
            .unwrap_or(&path)
            .to_string(),
        size_mb,
        threads,
        label,
        // parse_time_ms is the full parse phase (scan + lookup + preprocess).
        // entity_scan_time_ms is a sub-phase inside parse and must not be summed.
        // geometry_time_ms is the rayon-parallel meshing phase, sequential w.r.t. parse.
        t_parse: stats.parse_time_ms as f64 / 1000.0,
        t_geom: stats.geometry_time_ms as f64 / 1000.0,
        // External wall-clock around process_geometry is the authoritative Total
        // (matches what an external timer would observe). total_time_ms is
        // an internal stat that may exclude the very last finalize step.
        t_total: wallclock_ms / 1000.0,
        t_wallclock: wallclock_ms / 1000.0,
        products,
        walls,
        slabs,
        by_type,
    };

    println!("{}", serde_json::to_string(&row).expect("json"));
}

fn arg_value<'a>(args: &'a [String], flag: &str) -> Option<String> {
    let pos = args.iter().position(|a| a == flag)?;
    args.get(pos + 1).cloned()
}
