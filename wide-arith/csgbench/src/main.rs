use csgbench::csg_bench;
use std::time::Instant;

fn main() {
    let iters: u64 = std::env::args().nth(1).and_then(|s| s.parse().ok()).unwrap_or(300);
    let t = Instant::now();
    let acc = csg_bench(iters);
    let ms = t.elapsed().as_secs_f64() * 1000.0;
    println!(
        "native csg: {ms:.1} ms for {iters} cuts ({:.2} ms/cut, acc={acc})",
        ms / iters as f64
    );
}
