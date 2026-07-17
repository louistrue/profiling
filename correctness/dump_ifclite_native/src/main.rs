//! Per-element world-space mesh dump from ifc-lite native.
//!
//! Writes NDJSON to stdout (one line per mesh):
//!   {"express_id":u32,"guid":str|null,"type":str,"name":str|null,
//!    "positions":[f32,...],"indices":[u32,...]}
//!
//! IMPORTANT — coordinate alignment with IfcOpenShell:
//! `process_geometry` emits meshes in `raw_ifc` space, which has element
//! placements baked in but NOT the IfcSite placement. IfcOpenShell with
//! `use-world-coords=True` bakes the full chain (incl. site). To make the
//! two outputs comparable, this dumper applies `result.site_transform` to
//! every vertex before serialization when it's present and non-identity.
//!
//! Same exclude list as the bench so the comparison matches.

use ifc_lite_processing::process_geometry;
use serde::Serialize;
use std::collections::HashSet;
use std::env;
use std::fs;
use std::io::{BufWriter, Write};

#[derive(Serialize)]
struct Record<'a> {
    express_id: u32,
    #[serde(skip_serializing_if = "Option::is_none")]
    guid: Option<&'a str>,
    #[serde(rename = "type")]
    ty: &'a str,
    #[serde(skip_serializing_if = "Option::is_none")]
    name: Option<&'a str>,
    positions: Vec<f32>,
    indices: &'a [u32],
}

/// Apply a column-major 4x4 transform to flat [x,y,z,...] vertex data, then
/// subtract `anchor` — all in f64 before the single f32 store, so the result
/// stays precise even when the transform lands vertices at national-grid
/// coordinates (subtracting the anchor brings them back near the origin).
/// Treats the matrix as homogeneous; the w component of the output is dropped.
fn transform_in_place(positions: &mut [f64], m: &[f64], anchor: &[f64; 3]) {
    debug_assert!(m.len() >= 16);
    // Column-major: m[col*4 + row]
    let m00 = m[0]; let m10 = m[1]; let m20 = m[2];  // first column
    let m01 = m[4]; let m11 = m[5]; let m21 = m[6];  // second column
    let m02 = m[8]; let m12 = m[9]; let m22 = m[10]; // third column
    let m03 = m[12]; let m13 = m[13]; let m23 = m[14]; // translation
    for chunk in positions.chunks_exact_mut(3) {
        let x = chunk[0];
        let y = chunk[1];
        let z = chunk[2];
        chunk[0] = m00 * x + m01 * y + m02 * z + m03 - anchor[0];
        chunk[1] = m10 * x + m11 * y + m12 * z + m13 - anchor[1];
        chunk[2] = m20 * x + m21 * y + m22 * z + m23 - anchor[2];
    }
}

const IDENTITY_EPS: f64 = 1e-9;

fn is_identity_transform(m: &[f64]) -> bool {
    if m.len() < 16 {
        return true;
    }
    let expected = [
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ];
    m.iter().zip(expected.iter()).all(|(a, b)| (a - b).abs() < IDENTITY_EPS)
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() != 3 {
        eprintln!("usage: ifclite-dump <model.ifc> <out.ndjson>");
        std::process::exit(2);
    }
    let path = &args[1];
    let out_path = &args[2];

    let bytes = fs::read(path).expect("read file");
    let content = String::from_utf8(bytes).expect("utf8");

    let exclude: HashSet<&str> = [
        "IfcOpeningElement",
        "IfcOpeningStandardCase",
        "IfcSpace",
        "IfcBuilding",
        "IfcBuildingStorey",
    ]
    .into_iter()
    .collect();

    let result = process_geometry(&content);

    // Site placement alignment with IOS USE_WORLD_COORDS.
    // We apply site_transform if present and non-identity; building_transform
    // is intentionally not applied since IOS's world coords are at site level.
    let site = result.site_transform.as_ref();
    let mut apply_site = site
        .map(|m| !is_identity_transform(m))
        .unwrap_or(false);
    if env::var("NO_SITE").is_ok() {
        apply_site = false;
    }
    if env::var("SITE_DEBUG").is_ok() {
        if let Some(m) = site {
            // Column-major 4x4: print the 3x3 rotation columns to check
            // orthonormality (non-orthonormal => the site transform shears).
            eprintln!("SITE_DEBUG col0=({:.5},{:.5},{:.5}) col1=({:.5},{:.5},{:.5}) col2=({:.5},{:.5},{:.5})",
                m[0], m[1], m[2], m[4], m[5], m[6], m[8], m[9], m[10]);
            let dot01 = m[0]*m[4] + m[1]*m[5] + m[2]*m[6];
            let n0 = (m[0]*m[0]+m[1]*m[1]+m[2]*m[2]).sqrt();
            let n1 = (m[4]*m[4]+m[5]*m[5]+m[6]*m[6]).sqrt();
            eprintln!("SITE_DEBUG |col0|={:.5} |col1|={:.5} col0·col1={:.6} (orthonormal => ~1,~1,~0)", n0, n1, dot01);
        } else {
            eprintln!("SITE_DEBUG: no site_transform");
        }
    }

    // Local-frame anchor for georeferenced models.
    //
    // For `site_local` / georeferenced models the site translation lands
    // vertices at national-grid coordinates (e.g. 1.66e6 easting, 8.18e6
    // northing). f32 resolution there is 0.125–0.5 m, which quantizes a
    // column's ±0.5 m cross-section into garbage — fabricating "shape"
    // failures that have nothing to do with ifc-lite's geometry (its raw
    // output and the orthonormal site rotation are both exact). Production
    // keeps vertices in a local/RTC frame for exactly this reason.
    //
    // So we apply the site ROTATION (to match IOS world orientation) but
    // subtract the site TRANSLATION, keeping vertices near the origin and
    // f32-safe. The subtracted anchor is written to `<out>.origin` so the
    // IfcOpenShell dumper can subtract the SAME anchor and both engines are
    // compared in one local frame.
    //
    // Gate on GEOREF scale: only true georeferenced models (national-grid
    // translations, 1e5+) lose f32 precision. Ordinary building-site offsets
    // (a few metres, e.g. advanced_model's 12 m) are sub-millimetre in f32, so
    // anchoring them is unnecessary and would only break apples-to-apples with
    // un-anchored reference dumps. Threshold 5e4: f32 step there is ~4 mm.
    const GEOREF_ANCHOR_THRESHOLD: f64 = 5.0e4;
    let anchor: [f64; 3] = match site {
        Some(m) if apply_site => {
            let t = [m[12], m[13], m[14]];
            if t.iter().any(|c| c.abs() > GEOREF_ANCHOR_THRESHOLD) {
                t
            } else {
                [0.0, 0.0, 0.0]
            }
        }
        _ => [0.0, 0.0, 0.0],
    };
    if anchor != [0.0, 0.0, 0.0] {
        let origin_path = format!("{}.origin", out_path);
        let _ = fs::write(
            &origin_path,
            format!("{} {} {}\n", anchor[0], anchor[1], anchor[2]),
        );
    } else {
        // Remove any stale anchor from a previous run so the IOS dumper
        // doesn't subtract an origin we no longer use.
        let _ = fs::remove_file(format!("{}.origin", out_path));
    }

    let out = fs::File::create(out_path).expect("create out");
    let mut w = BufWriter::new(out);

    // Merge all sub-meshes that share an express_id into one record.
    //
    // ifc-lite emits ONE mesh per geometry sub-part: a window/door with a
    // frame + glazing (or 4 extruded frame members) produces several
    // `MeshData` records, all keyed by the *element's* express_id. IfcOpenShell
    // emits a single welded mesh per element. To compare apples-to-apples we
    // concatenate every sub-mesh of an element here, offsetting the index base
    // by the running vertex count. (Previously this dumper kept only the first
    // sub-mesh per express_id, which dropped 3 of 4 window-frame members and
    // ~⅔ of door geometry — fabricating "missing geometry" failures that don't
    // exist in ifc-lite's actual output.)
    struct Merged<'a> {
        guid: Option<&'a str>,
        ty: &'a str,
        name: Option<&'a str>,
        /// f64, with the per-mesh local-frame `origin` already folded in
        /// (world = origin + position); f32 would collapse georef-scale sums.
        positions: Vec<f64>,
        indices: Vec<u32>,
    }
    let mut order: Vec<u32> = Vec::new();
    let mut merged: std::collections::HashMap<u32, Merged> = std::collections::HashMap::new();
    for m in &result.meshes {
        if exclude.contains(m.ifc_type.as_str()) {
            continue;
        }
        if m.positions.is_empty() || m.indices.is_empty() {
            continue;
        }
        let entry = merged.entry(m.express_id).or_insert_with(|| {
            order.push(m.express_id);
            Merged {
                guid: m.global_id.as_deref(),
                ty: m.ifc_type.as_str(),
                name: m.name.as_deref(),
                positions: Vec::new(),
                indices: Vec::new(),
            }
        });
        let base = (entry.positions.len() / 3) as u32;
        // Fold the per-mesh local-frame origin: `positions` are RELATIVE to
        // `m.origin` (world = origin + position). Elements that get a local
        // frame (large placements) would otherwise dump centred on (0,0,0) —
        // fabricating fail:position verdicts against IOS world coords.
        let o = m.origin;
        entry.positions.reserve(m.positions.len());
        for chunk in m.positions.chunks_exact(3) {
            entry.positions.push(chunk[0] as f64 + o[0]);
            entry.positions.push(chunk[1] as f64 + o[1]);
            entry.positions.push(chunk[2] as f64 + o[2]);
        }
        entry.indices.extend(m.indices.iter().map(|&i| i + base));
    }

    let mut emitted = 0usize;
    for id in &order {
        let entry = &merged[id];
        let mut positions_f64 = entry.positions.clone();
        if apply_site {
            if let Some(s) = site {
                // Apply the site transform and re-base into the local frame
                // (world-oriented, near-origin) in one f64 pass — keeps f32
                // storage precise for georeferenced models. `anchor` is (0,0,0)
                // for non-georef models, making this the plain site transform.
                transform_in_place(&mut positions_f64, s, &anchor);
            }
        }
        let positions: Vec<f32> = positions_f64.iter().map(|&v| v as f32).collect();
        let rec = Record {
            express_id: *id,
            guid: entry.guid,
            ty: entry.ty,
            name: entry.name,
            positions,
            indices: &entry.indices,
        };
        let line = serde_json::to_string(&rec).expect("json");
        writeln!(w, "{}", line).expect("write");
        emitted += 1;
    }
    w.flush().expect("flush");

    eprintln!(
        "ifc-lite dump: {} elements -> {}  (coord_space={:?}, site_applied={})",
        emitted,
        out_path,
        result.mesh_coordinate_space.as_deref().unwrap_or("?"),
        apply_site,
    );
}
