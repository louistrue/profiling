//! Raw-mesh thickness/degeneracy audit straight from `process_geometry`
//! (Manifold kernel), bypassing the diff harness entirely.
//!
//! For every element it unions all sub-meshes into the element-level AABB the
//! GLB node will carry (EX-6 one-node-per-element), and separately tracks the
//! thinnest individual sub-mesh. Reports:
//!   - non-finite (NaN/Inf) positions  -> §5.1.1 "finite" warranty
//!   - degenerate elements (min element AABB dim < 0.1 mm) -> "zero-thickness"
//!   - thin elements (min dim < 20 mm)
//! plus a per-type breakdown and any GUIDs matching a prefix filter.
//!
//! Usage: thickness <model.ifc> [guid_prefix,guid_prefix,...]

use ifc_lite_processing::process_geometry;
use std::collections::HashMap;
use std::env;
use std::fs;

#[derive(Default)]
struct Agg {
    ty: String,
    guid: Option<String>,
    name: Option<String>,
    submeshes: u32,
    verts: usize,
    // element-level union AABB
    min: [f64; 3],
    max: [f64; 3],
    // thinnest single sub-mesh (min over submeshes of that submesh's smallest dim)
    thinnest_submesh_dim: f64,
    nonfinite: usize,
}

fn dims(a: &Agg) -> [f64; 3] {
    [a.max[0] - a.min[0], a.max[1] - a.min[1], a.max[2] - a.min[2]]
}
fn min_dim(d: &[f64; 3]) -> f64 {
    d[0].min(d[1]).min(d[2])
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 2 {
        eprintln!("usage: thickness <model.ifc> [guid_prefix,...]");
        std::process::exit(2);
    }
    let prefixes: Vec<String> = args
        .get(2)
        .map(|s| s.split(',').map(|x| x.trim().to_string()).collect())
        .unwrap_or_default();

    let content = fs::read_to_string(&args[1]).expect("read ifc");
    let result = process_geometry(&content);

    let mut by_el: HashMap<u32, Agg> = HashMap::new();
    for m in &result.meshes {
        if m.positions.is_empty() {
            continue;
        }
        let e = by_el.entry(m.express_id).or_insert_with(|| Agg {
            ty: m.ifc_type.clone(),
            guid: m.global_id.clone(),
            name: m.name.clone(),
            min: [f64::INFINITY; 3],
            max: [f64::NEG_INFINITY; 3],
            thinnest_submesh_dim: f64::INFINITY,
            ..Default::default()
        });
        e.submeshes += 1;
        e.verts += m.positions.len() / 3;
        let mut smin = [f64::INFINITY; 3];
        let mut smax = [f64::NEG_INFINITY; 3];
        for p in m.positions.chunks_exact(3) {
            for k in 0..3 {
                let v = p[k] as f64;
                if !v.is_finite() {
                    e.nonfinite += 1;
                    continue;
                }
                if v < e.min[k] {
                    e.min[k] = v;
                }
                if v > e.max[k] {
                    e.max[k] = v;
                }
                if v < smin[k] {
                    smin[k] = v;
                }
                if v > smax[k] {
                    smax[k] = v;
                }
            }
        }
        let sdim = [smax[0] - smin[0], smax[1] - smin[1], smax[2] - smin[2]];
        let sm = min_dim(&sdim);
        if sm.is_finite() && sm < e.thinnest_submesh_dim {
            e.thinnest_submesh_dim = sm;
        }
    }

    const DEGEN: f64 = 1.0e-4; // 0.1 mm
    const THIN: f64 = 0.02; // 20 mm

    let mut elems: Vec<(&u32, &Agg)> = by_el.iter().collect();
    elems.sort_by(|a, b| min_dim(&dims(a.1)).partial_cmp(&min_dim(&dims(b.1))).unwrap());

    let total = elems.len();
    let mut nonfinite_els = 0usize;
    let mut degen_els = 0usize;
    let mut thin_els = 0usize;
    let mut by_type: HashMap<&str, (usize, usize, usize)> = HashMap::new(); // (count, degen, thin)
    for (_, a) in &elems {
        let d = dims(a);
        let md = min_dim(&d);
        let t = by_type.entry(a.ty.as_str()).or_default();
        t.0 += 1;
        if a.nonfinite > 0 {
            nonfinite_els += 1;
        }
        if md < DEGEN {
            degen_els += 1;
            t.1 += 1;
        } else if md < THIN {
            thin_els += 1;
            t.2 += 1;
        }
    }

    println!("== RAW process_geometry audit (Manifold kernel) ==");
    println!("file: {}", args[1]);
    println!(
        "coord_space={:?}  site_transform_present={}",
        result.mesh_coordinate_space.as_deref().unwrap_or("?"),
        result.site_transform.is_some()
    );
    println!(
        "elements_with_geometry={}  nonfinite={}  degenerate(<0.1mm)={}  thin(<20mm)={}",
        total, nonfinite_els, degen_els, thin_els
    );

    println!("\n-- per-type (count / degenerate / thin) --");
    let mut types: Vec<(&&str, &(usize, usize, usize))> = by_type.iter().collect();
    types.sort_by(|a, b| b.1 .0.cmp(&a.1 .0));
    for (ty, (c, dg, th)) in types {
        if *dg > 0 || *th > 0 || c > &0 {
            println!("  {:<28} n={:<4} degen={:<3} thin={}", ty, c, dg, th);
        }
    }

    println!("\n-- 15 thinnest elements (element-union AABB) --");
    println!(
        "  {:<10} {:<20} {:<8} {:>6} {:>5}  {:>10} {:>10} {:>10}   {:>11}",
        "guid", "type", "express", "subs", "verts", "dx", "dy", "dz", "thin_submesh"
    );
    for (id, a) in elems.iter().take(15) {
        let d = dims(a);
        println!(
            "  {:<10} {:<20} {:<8} {:>6} {:>5}  {:>10.4} {:>10.4} {:>10.4}   {:>11.4}",
            a.guid.as_deref().unwrap_or("-").chars().take(10).collect::<String>(),
            a.ty,
            id,
            a.submeshes,
            a.verts,
            d[0],
            d[1],
            d[2],
            a.thinnest_submesh_dim,
        );
    }

    if !prefixes.is_empty() {
        println!("\n-- elements matching prefixes {:?} --", prefixes);
        for (id, a) in &elems {
            let g = a.guid.as_deref().unwrap_or("");
            if prefixes.iter().any(|p| !p.is_empty() && g.starts_with(p.as_str())) {
                let d = dims(a);
                println!(
                    "  {:<24} {:<20} express={:<6} subs={} verts={} dims=[{:.4},{:.4},{:.4}] thin_submesh={:.4} nonfinite={}",
                    g, a.ty, id, a.submeshes, a.verts, d[0], d[1], d[2], a.thinnest_submesh_dim, a.nonfinite
                );
            }
        }
    }
}
