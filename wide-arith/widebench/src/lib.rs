// Faithful microbench of the ifc-lite exact-CSG predicate hot path: a 3x3
// determinant (orient3d core) over bnum fixed-width integers, with the same
// CheckedMul/CheckedSub/CheckedAdd ops the kernel uses (rust/geometry/src/kernel/fixed.rs).
// Pure compute, no std I/O, so it runs unchanged under wasm32 + wasmtime.
#![allow(clippy::needless_range_loop)]
use bnum::types::{I256, I512};
use num_traits::{CheckedAdd, CheckedMul, CheckedSub, FromPrimitive, Signed, Zero};

#[inline(always)]
fn det3<I: CheckedMul + CheckedSub + CheckedAdd + Copy>(u: &[I; 3], v: &[I; 3], w: &[I; 3]) -> Option<I> {
    let m0 = v[1].checked_mul(&w[2])?.checked_sub(&v[2].checked_mul(&w[1])?)?;
    let m1 = v[2].checked_mul(&w[0])?.checked_sub(&v[0].checked_mul(&w[2])?)?;
    let m2 = v[0].checked_mul(&w[1])?.checked_sub(&v[1].checked_mul(&w[0])?)?;
    u[0]
        .checked_mul(&m0)?
        .checked_add(&u[1].checked_mul(&m1)?)?
        .checked_add(&u[2].checked_mul(&m2)?)
}

#[inline(always)]
fn lcg(s: &mut u64) -> i64 {
    *s = s
        .wrapping_mul(6364136223846793005)
        .wrapping_add(1442695040888963407);
    // building-scale coords on a 2^16 grid land near 2^36; widen toward ~2^60
    // so each checked_mul spans multiple 64-bit limbs (the wide-arith regime).
    ((*s >> 4) as i64) >> 1
}

macro_rules! bench {
    ($name:ident, $T:ty) => {
        #[no_mangle]
        pub extern "C" fn $name(iters: u64, seed: u64) -> i64 {
            let mut s = seed | 1;
            let mut acc: i64 = 0;
            for _ in 0..iters {
                let u = [
                    <$T>::from_i64(lcg(&mut s)).unwrap(),
                    <$T>::from_i64(lcg(&mut s)).unwrap(),
                    <$T>::from_i64(lcg(&mut s)).unwrap(),
                ];
                let v = [
                    <$T>::from_i64(lcg(&mut s)).unwrap(),
                    <$T>::from_i64(lcg(&mut s)).unwrap(),
                    <$T>::from_i64(lcg(&mut s)).unwrap(),
                ];
                let w = [
                    <$T>::from_i64(lcg(&mut s)).unwrap(),
                    <$T>::from_i64(lcg(&mut s)).unwrap(),
                    <$T>::from_i64(lcg(&mut s)).unwrap(),
                ];
                if let Some(d) = det3::<$T>(&u, &v, &w) {
                    acc = acc.wrapping_add(if d.is_negative() {
                        -1
                    } else if d.is_zero() {
                        0
                    } else {
                        1
                    });
                }
            }
            acc
        }
    };
}

bench!(bench_i256, I256);
bench!(bench_i512, I512);
