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
    vertices: usize,
    triangles: usize,
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
    let mut total_verts = 0usize;
    let mut total_tris = 0usize;
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
        total_verts += m.positions.len() / 3;
        total_tris += m.indices.len() / 3;
        match m.ifc_type.as_str() {
            "IfcWall" | "IfcWallStandardCase" | "IfcWallElementedCase" => walls += 1,
            "IfcSlab" | "IfcSlabElementedCase" => slabs += 1,
            _ => {}
        }
    }

    // LOCAL-FRAME VERIFY (IFCLT_CRACK_DIAG=1): measure catastrophic collapse
    // (aspect>1e5) on (a) the stored LOCAL positions and (b) the f64 WORLD
    // reconstruction (origin + position). Both should be 0 after the per-element
    // local-origin fix. Also report the origin span (should cover the building).
    if env::var("IFCLT_CRACK_DIAG").is_ok() {
        let aspect = |p: &[[f64; 3]; 3]| -> f64 {
            let d = |a: [f64; 3], b: [f64; 3]| {
                ((a[0] - b[0]).powi(2) + (a[1] - b[1]).powi(2) + (a[2] - b[2]).powi(2)).sqrt()
            };
            let (e0, e1, e2) = (d(p[0], p[1]), d(p[1], p[2]), d(p[2], p[0]));
            let mn = e0.min(e1).min(e2);
            let mx = e0.max(e1).max(e2);
            if mn > 1e-12 {
                mx / mn
            } else {
                f64::INFINITY
            }
        };
        let max_edge = |p: &[[f64; 3]; 3]| -> f64 {
            let d = |a: [f64; 3], b: [f64; 3]| {
                ((a[0] - b[0]).powi(2) + (a[1] - b[1]).powi(2) + (a[2] - b[2]).powi(2)).sqrt()
            };
            d(p[0], p[1]).max(d(p[1], p[2])).max(d(p[2], p[0]))
        };
        // VISIBLE-fan characterization, over ALL meshes (NO express_id dedup —
        // opening-cut fans live in sub-meshes). A visible fan = a long triangle
        // (max edge spans the wall) with a near-zero short edge (high aspect).
        let mut a1e3 = 0i64; // aspect>1e3
        let mut a1e5 = 0i64; // aspect>1e5  (what the backstop drops)
        // visible = big edge AND fan-shaped, split by aspect band:
        let mut vis_1e3_1e5 = 0i64; // edge>0.5m, 1e3<aspect<=1e5  (SURVIVES the backstop)
        let mut vis_gt1e5 = 0i64; // edge>0.5m, aspect>1e5         (backstop drops these)
        let mut tri_total = 0i64;
        for m in &result.meshes {
            for tri in m.indices.chunks_exact(3) {
                let lp = |i: u32| {
                    let i = i as usize;
                    [
                        m.positions[i * 3] as f64,
                        m.positions[i * 3 + 1] as f64,
                        m.positions[i * 3 + 2] as f64,
                    ]
                };
                let p = [lp(tri[0]), lp(tri[1]), lp(tri[2])];
                tri_total += 1;
                let asp = aspect(&p);
                let edge = max_edge(&p);
                if asp > 1e3 {
                    a1e3 += 1;
                }
                if asp > 1e5 {
                    a1e5 += 1;
                }
                if edge > 0.5 && asp > 1e3 {
                    if asp > 1e5 {
                        vis_gt1e5 += 1;
                    } else {
                        vis_1e3_1e5 += 1;
                    }
                }
            }
        }
        eprintln!(
            "FANPROFILE tris={} aspect>1e3={} aspect>1e5={} | VISIBLE(edge>0.5m): aspect>1e5={} (backstop drops) 1e3<aspect<=1e5={} (SURVIVES backstop)",
            tri_total, a1e3, a1e5, vis_gt1e5, vis_1e3_1e5
        );
        // Height-based sliver rule calibration: a triangle that is LONG
        // (longest edge > 0.1m, so visible) but THIN (perpendicular height < H)
        // is a spanning sliver. height = 2*area/longest_edge. Count drops at
        // several H to pick a threshold that nukes the fans but spares real geom.
        let height = |p: &[[f64; 3]; 3]| -> (f64, f64) {
            let d = |a: [f64; 3], b: [f64; 3]| {
                ((a[0] - b[0]).powi(2) + (a[1] - b[1]).powi(2) + (a[2] - b[2]).powi(2)).sqrt()
            };
            let (e0, e1, e2) = (d(p[0], p[1]), d(p[1], p[2]), d(p[2], p[0]));
            let longest = e0.max(e1).max(e2);
            // area via cross product
            let u = [p[1][0]-p[0][0], p[1][1]-p[0][1], p[1][2]-p[0][2]];
            let v = [p[2][0]-p[0][0], p[2][1]-p[0][1], p[2][2]-p[0][2]];
            let cr = [u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0]];
            let area = 0.5 * (cr[0]*cr[0]+cr[1]*cr[1]+cr[2]*cr[2]).sqrt();
            let h = if longest > 0.0 { 2.0 * area / longest } else { 0.0 };
            (longest, h)
        };
        // Scale-aware f32-damage (the real metric): a triangle is f32 NOISE when
        // its perpendicular height is below the f32 ULP AT ITS OWN COORDINATE
        // MAGNITUDE. Captures BOTH collapse and JITTER — a thin CSG triangle
        // thinner than the local f32 grid distorts into a visible fan. The
        // aspect>1e5 backstop misses the jitter band entirely. Deterministic.
        let ulp_f32 = |v: f64| -> f64 {
            let a = (v.abs() as f32).max(f32::MIN_POSITIVE);
            (f32::from_bits(a.to_bits() + 1) - a) as f64
        };
        let mut damaged = 0i64;
        let mut damaged_visible = 0i64;
        // LOCAL-FRAME control: same metric but each mesh recentred to its own
        // centroid first. If damaged_local ≈ 0 while damaged_visible > 0, the
        // residual is pure f32 WORLD-STORAGE collapse (real thin triangles at
        // large georef coords) — an RTC/local-frame render problem, NOT a
        // degenerate-geometry problem. If both are >0, real sub-grid slivers
        // survived the drop (a hygiene problem).
        let mut damaged_local_visible = 0i64;
        let mut max_world_coord = 0.0f64;
        for m in &result.meshes {
            // mesh centroid (f64) for the local-frame control
            let mut cx = 0.0f64; let mut cy = 0.0f64; let mut cz = 0.0f64;
            let n = (m.positions.len() / 3).max(1) as f64;
            for c in m.positions.chunks_exact(3) {
                cx += c[0] as f64; cy += c[1] as f64; cz += c[2] as f64;
            }
            cx /= n; cy /= n; cz /= n;
            for tri in m.indices.chunks_exact(3) {
                let lp = |i: u32| {
                    let i = i as usize;
                    [m.positions[i * 3] as f64, m.positions[i * 3 + 1] as f64, m.positions[i * 3 + 2] as f64]
                };
                let p = [lp(tri[0]), lp(tri[1]), lp(tri[2])];
                let (longest, h) = height(&p);
                let maxc = p.iter().flat_map(|q| q.iter()).fold(0.0f64, |m, &c| m.max(c.abs()));
                max_world_coord = max_world_coord.max(maxc);
                if h < ulp_f32(maxc) {
                    damaged += 1;
                    if longest > 0.1 {
                        damaged_visible += 1;
                    }
                }
                // local-frame control: recentre, then re-test
                let pl = [
                    [p[0][0]-cx, p[0][1]-cy, p[0][2]-cz],
                    [p[1][0]-cx, p[1][1]-cy, p[1][2]-cz],
                    [p[2][0]-cx, p[2][1]-cy, p[2][2]-cz],
                ];
                let maxc_l = pl.iter().flat_map(|q| q.iter()).fold(0.0f64, |m, &c| m.max(c.abs()));
                if h < ulp_f32(maxc_l) && longest > 0.1 {
                    damaged_local_visible += 1;
                }
            }
        }
        eprintln!(
            "F32DAMAGE damaged(h<ULP@coord)={} damaged_VISIBLE(edge>0.1m)={} | LOCAL-FRAME damaged_VISIBLE={} | max_world_coord={:.1}m",
            damaged, damaged_visible, damaged_local_visible, max_world_coord
        );
        // (cell/tess/sliver diagnostics removed: those report fns exist only on
        // the local-frame WIP branch, not on published `main`, which this bench
        // now builds against.)
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
        vertices: total_verts,
        triangles: total_tris,
        by_type,
    };

    println!("{}", serde_json::to_string(&row).expect("json"));
}

fn arg_value<'a>(args: &'a [String], flag: &str) -> Option<String> {
    let pos = args.iter().position(|a| a == flag)?;
    args.get(pos + 1).cloned()
}
