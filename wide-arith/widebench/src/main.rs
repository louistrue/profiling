// Native reference timing for the same bench functions.
use std::time::Instant;
use widebench::{bench_i256, bench_i512};

fn main() {
    let iters: u64 = std::env::args()
        .nth(1)
        .and_then(|s| s.parse().ok())
        .unwrap_or(5_000_000);
    for (name, f) in [
        ("i256", bench_i256 as extern "C" fn(u64, u64) -> i64),
        ("i512", bench_i512 as extern "C" fn(u64, u64) -> i64),
    ] {
        let t = Instant::now();
        let acc = f(iters, 0x9E3779B97F4A7C15);
        let ms = t.elapsed().as_secs_f64() * 1000.0;
        println!(
            "native {name}: {ms:.1} ms for {iters} iters ({:.1} ns/det, acc={acc})",
            ms * 1e6 / iters as f64
        );
    }
}
