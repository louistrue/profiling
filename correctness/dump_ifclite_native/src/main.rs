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

/// Apply a column-major 4x4 transform to flat [x,y,z,...] vertex data.
/// Treats the matrix as homogeneous; the w component of the output is dropped.
fn transform_in_place(positions: &mut [f32], m: &[f64]) {
    debug_assert!(m.len() >= 16);
    // Column-major: m[col*4 + row]
    let m00 = m[0]; let m10 = m[1]; let m20 = m[2];  // first column
    let m01 = m[4]; let m11 = m[5]; let m21 = m[6];  // second column
    let m02 = m[8]; let m12 = m[9]; let m22 = m[10]; // third column
    let m03 = m[12]; let m13 = m[13]; let m23 = m[14]; // translation
    for chunk in positions.chunks_exact_mut(3) {
        let x = chunk[0] as f64;
        let y = chunk[1] as f64;
        let z = chunk[2] as f64;
        chunk[0] = (m00 * x + m01 * y + m02 * z + m03) as f32;
        chunk[1] = (m10 * x + m11 * y + m12 * z + m13) as f32;
        chunk[2] = (m20 * x + m21 * y + m22 * z + m23) as f32;
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
    let apply_site = site
        .map(|m| !is_identity_transform(m))
        .unwrap_or(false);

    let out = fs::File::create(out_path).expect("create out");
    let mut w = BufWriter::new(out);

    let mut emitted = 0usize;
    let mut seen = HashSet::new();
    for m in &result.meshes {
        if exclude.contains(m.ifc_type.as_str()) {
            continue;
        }
        if m.positions.is_empty() || m.indices.is_empty() {
            continue;
        }
        if !seen.insert(m.express_id) {
            continue;
        }
        let mut positions = m.positions.clone();
        if apply_site {
            if let Some(s) = site {
                transform_in_place(&mut positions, s);
            }
        }
        let rec = Record {
            express_id: m.express_id,
            guid: m.global_id.as_deref(),
            ty: m.ifc_type.as_str(),
            name: m.name.as_deref(),
            positions,
            indices: &m.indices,
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
