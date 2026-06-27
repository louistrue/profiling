// End-to-end CSG bench: a real slab-minus-9-boxes void cut through the
// production kernel path (mesh_bridge::subtract_many), so the measurement
// includes arrangement + predicate cascade + retriangulation, not just the
// scalar predicate. Coordinates are multiples of 0.25 so they land exactly on
// the 2^16 grid and exercise the fixed-tier (I256/I512) exact predicates that
// wide-arithmetic accelerates.
use ifc_lite_geometry::kernel::mesh_bridge::subtract_many;
use ifc_lite_geometry::mesh::Mesh;

fn box_mesh(cx: f64, cy: f64, cz: f64, hx: f64, hy: f64, hz: f64) -> Mesh {
    let xs = [cx - hx, cx + hx];
    let ys = [cy - hy, cy + hy];
    let zs = [cz - hz, cz + hz];
    let mut positions = Vec::with_capacity(24);
    for i in 0..8usize {
        positions.push(xs[i & 1] as f32);
        positions.push(ys[(i >> 1) & 1] as f32);
        positions.push(zs[(i >> 2) & 1] as f32);
    }
    let faces: [[usize; 4]; 6] = [
        [0, 1, 3, 2],
        [4, 6, 7, 5],
        [0, 4, 5, 1],
        [2, 3, 7, 6],
        [0, 2, 6, 4],
        [1, 5, 7, 3],
    ];
    let mut indices = Vec::with_capacity(36);
    for f in faces {
        indices.extend_from_slice(&[
            f[0] as u32, f[1] as u32, f[2] as u32, f[0] as u32, f[2] as u32, f[3] as u32,
        ]);
    }
    let normals = vec![0.0f32; positions.len()];
    Mesh { positions, normals, indices, ..Default::default() }
}

fn scene() -> (Mesh, Vec<Mesh>) {
    // 12 x 0.5 x 12 slab centered at origin (thickness 0.5 in Y).
    let host = box_mesh(0.0, 0.0, 0.0, 6.0, 0.25, 6.0);
    // 3x3 grid of 0.5-cube cutters punching fully through the slab (Y half 0.5).
    let mut cutters = Vec::new();
    for gx in [-3.0, 0.0, 3.0] {
        for gz in [-3.0, 0.0, 3.0] {
            cutters.push(box_mesh(gx, 0.0, gz, 0.25, 0.5, 0.25));
        }
    }
    (host, cutters)
}

#[no_mangle]
pub extern "C" fn csg_bench(iters: u64) -> i64 {
    let (host, cutters) = scene();
    let refs: Vec<&Mesh> = cutters.iter().collect();
    let mut acc: i64 = 0;
    for _ in 0..iters {
        match subtract_many(&host, &refs) {
            Some(m) => acc = acc.wrapping_add(m.indices.len() as i64),
            None => acc = acc.wrapping_sub(1),
        }
    }
    acc
}
