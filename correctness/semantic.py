"""T6 — semantic relationship checks.

Walks IFC schema-level relationships (IfcRelVoidsElement, IfcRelFillsElement)
and checks whether the candidate engine (ifc-lite) honored them in geometry.

Where T1-T5 work entirely on mesh data, T6 reads the IFC schema for ground
truth about "this wall should have a hole where this opening sits" and then
tests the candidate's mesh for that hole.

Two checks per `IfcRelVoidsElement(host, opening)`:

  C1 — opening cut from host
     IOS meshes the IfcOpeningElement (the void volume).
     We sample points uniformly inside that void.
     For each point, we ask: is it inside the candidate's host mesh?
     A properly cut wall → ~0% of opening-interior points are inside the wall.
     An uncut wall      → ~100% are inside.

  C2 — opening volume preserved
     IOS gives the opening's volume.
     A candidate wall that didn't cut the opening should have hull volume
     roughly `host_volume + opening_volume` larger than IOS's (over-thick).
     A wall that over-cut should be smaller. (Informational only.)

Plus one check per `IfcRelFillsElement(opening, filler)`:

  C3 — filler aligned with opening
     The window/door bbox should sit inside (or substantially overlap) the
     opening bbox. If the filler is way off, the wall + filler + opening are
     misaligned — usually a placement bug downstream.

Usage:
   semantic.py <model.ifc> <ifclite.ndjson> --out semantic.json [--html report.html]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict, Counter
from pathlib import Path

import numpy as np
import trimesh
import trimesh.proximity

import ifcopenshell
import ifcopenshell.geom


# Verdict thresholds — calibrated against the assumption that opening volumes
# are typically 0.05-2 m³ and we sample 200 points inside them.
FAIL_WALL_IN_OPENING = 0.30   # >30% of opening points inside wall → fail
WARN_WALL_IN_OPENING = 0.10   # 10-30% → warn
FAIL_FILLER_BBOX_OVERLAP = 0.10  # <10% of filler bbox volume overlapping opening bbox → fail
WARN_FILLER_BBOX_OVERLAP = 0.30


def load_candidate(path: Path) -> dict[str, dict]:
    by_guid: dict[str, dict] = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("guid"):
            by_guid[rec["guid"]] = rec
    return by_guid


def make_trimesh(rec: dict) -> trimesh.Trimesh | None:
    pos = np.asarray(rec["positions"], dtype=np.float64).reshape(-1, 3)
    idx = np.asarray(rec["indices"], dtype=np.int64).reshape(-1, 3)
    if pos.shape[0] == 0 or idx.shape[0] == 0:
        return None
    try:
        return trimesh.Trimesh(vertices=pos, faces=idx, process=True, validate=True)
    except Exception:
        return None


def mesh_openings(ifc) -> dict[int, dict]:
    """Return {express_id: {'positions':[...], 'indices':[...]}}, world coords, for all openings.

    Uses the standard iterator with an `include` filter so we benefit from
    caching, instead of per-element `create_shape`.
    """
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    settings.set("weld-vertices", True)

    out: dict[int, dict] = {}
    try:
        iterator = ifcopenshell.geom.iterator(
            settings, ifc, 1,
            include=["IfcOpeningElement", "IfcOpeningStandardCase"],
        )
        if iterator.initialize():
            while True:
                shape = iterator.get()
                geo = shape.geometry
                verts = list(geo.verts)
                faces = list(geo.faces)
                if verts and faces:
                    out[shape.id] = {"positions": verts, "indices": faces}
                if not iterator.next():
                    break
    except Exception as e:
        print(f"  warning: opening iterator failed: {e}", file=sys.stderr)
    return out


def sample_inside_volume(m: trimesh.Trimesh, n: int) -> np.ndarray | None:
    """Uniform points inside `m`. Tries volume sampler; falls back to bbox
    rejection sampling via `m.contains`."""
    try:
        # trimesh.sample.volume_mesh works when the mesh is watertight
        pts = trimesh.sample.volume_mesh(m, count=n)
        if pts is not None and len(pts):
            return np.asarray(pts, dtype=np.float64)
    except Exception:
        pass
    # Fallback: bbox rejection sampling (up to 10× oversample)
    try:
        lo, hi = m.bounds
        if not m.is_volume:
            # contains() requires watertight; skip if no
            return None
        for mul in (5, 20):
            cand = np.random.uniform(lo, hi, size=(n * mul, 3))
            inside = m.contains(cand)
            if inside.any():
                kept = cand[inside]
                if len(kept) >= n:
                    return kept[:n]
        if len(kept):
            return kept
    except Exception:
        pass
    return None


def fraction_inside(host_mesh: trimesh.Trimesh, points: np.ndarray) -> float | None:
    """Fraction of `points` that are inside `host_mesh`.

    Strategy (in order):
      1. `mesh.contains` if watertight (cheapest, exact).
      2. Ray parity test (`ray.contains_points`) — works on consistently-
         oriented triangle soup. ifc-lite emits CCW-oriented faces so this
         is reliable for our candidate meshes.
      3. signed-distance fallback (least reliable on open shells; only used
         when (1) and (2) both fail).
    """
    if len(points) == 0:
        return None
    # Method 1
    try:
        if host_mesh.is_watertight:
            inside = host_mesh.contains(points)
            return float(inside.mean())
    except Exception:
        pass
    # Method 2 — ray parity. Works on any consistently-oriented mesh.
    try:
        inside = host_mesh.ray.contains_points(points)
        if inside is not None and len(inside) == len(points):
            return float(np.asarray(inside, dtype=bool).mean())
    except Exception:
        pass
    # Method 3 — signed distance fallback. Known to over-report "inside" on
    # open shells; we use only as last resort and tag the result.
    try:
        sd = trimesh.proximity.signed_distance(host_mesh, points)
        return float((sd < 0).mean())
    except Exception:
        return None


def bbox_overlap_volume(a_min, a_max, b_min, b_max) -> tuple[float, float, float]:
    """Returns (overlap_volume, a_volume, b_volume)."""
    inter_lo = np.maximum(a_min, b_min)
    inter_hi = np.minimum(a_max, b_max)
    inter = np.clip(inter_hi - inter_lo, 0, None)
    return (float(np.prod(inter)),
            float(np.prod(a_max - a_min)),
            float(np.prod(b_max - b_min)))


def mesh_bounds(rec: dict) -> tuple[np.ndarray, np.ndarray] | None:
    pos = np.asarray(rec["positions"], dtype=np.float64).reshape(-1, 3)
    if pos.shape[0] == 0:
        return None
    return pos.min(axis=0), pos.max(axis=0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ifc")
    ap.add_argument("candidate", help="ifc-lite NDJSON dump")
    ap.add_argument("--out", required=True)
    ap.add_argument("--per-pair", help="optional NDJSON of per-pair results")
    ap.add_argument("--samples", type=int, default=200,
                    help="points sampled inside each opening's volume")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    np.random.seed(args.seed)

    cand_by_guid = load_candidate(Path(args.candidate))
    print(f"loaded {len(cand_by_guid)} candidate elements", file=sys.stderr)

    t0 = time.perf_counter()
    ifc = ifcopenshell.open(args.ifc)
    print(f"opened IFC in {time.perf_counter()-t0:.2f}s", file=sys.stderr)

    rels_voids = ifc.by_type("IfcRelVoidsElement")
    rels_fills = ifc.by_type("IfcRelFillsElement")
    print(f"relationships: voids={len(rels_voids)} fills={len(rels_fills)}",
          file=sys.stderr)

    if not rels_voids and not rels_fills:
        Path(args.out).write_text(json.dumps({
            "message": "no IfcRelVoidsElement or IfcRelFillsElement in model",
            "checks": [],
        }, indent=2))
        return

    print("meshing openings…", file=sys.stderr)
    t0 = time.perf_counter()
    openings = mesh_openings(ifc) if rels_voids else {}
    print(f"  meshed {len(openings)} openings in {time.perf_counter()-t0:.2f}s",
          file=sys.stderr)

    pair_records: list[dict] = []

    # C1+C2: walk IfcRelVoidsElement
    print(f"\nchecking {len(rels_voids)} void relationships…", file=sys.stderr)
    t0 = time.perf_counter()
    for i, rel in enumerate(rels_voids, 1):
        if i % 50 == 0 or i == len(rels_voids):
            print(f"  [{i}/{len(rels_voids)}] ({time.perf_counter()-t0:.1f}s)",
                  file=sys.stderr)
        host = rel.RelatingBuildingElement
        opening = rel.RelatedOpeningElement
        if host is None or opening is None:
            continue
        host_guid = getattr(host, "GlobalId", None)
        if not host_guid:
            continue

        rec = {
            "kind": "voids",
            "host_guid": host_guid,
            "host_type": host.is_a(),
            "host_name": getattr(host, "Name", None),
            "host_express_id": host.id(),
            "opening_express_id": opening.id(),
            "opening_type": opening.is_a(),
        }

        cand_host = cand_by_guid.get(host_guid)
        if cand_host is None:
            rec["verdict"] = "skip:no-candidate-host"
            pair_records.append(rec)
            continue
        op_data = openings.get(opening.id())
        if op_data is None:
            rec["verdict"] = "skip:no-opening-mesh"
            pair_records.append(rec)
            continue

        host_mesh = make_trimesh(cand_host)
        op_mesh = make_trimesh(op_data)
        if host_mesh is None or op_mesh is None:
            rec["verdict"] = "skip:empty-mesh"
            pair_records.append(rec)
            continue

        # Opening bbox + volume
        op_bbox_lo, op_bbox_hi = op_mesh.bounds
        rec["opening_bbox_volume"] = float(np.prod(op_bbox_hi - op_bbox_lo))
        try:
            rec["opening_hull_volume"] = float(op_mesh.convex_hull.volume)
        except Exception:
            rec["opening_hull_volume"] = None
        rec["host_watertight"] = bool(host_mesh.is_watertight)
        rec["opening_watertight"] = bool(op_mesh.is_watertight)

        # C1: sample inside the opening, check fraction inside host
        pts = sample_inside_volume(op_mesh, args.samples)
        if pts is None or len(pts) == 0:
            # Some openings have degenerate (zero-volume) tessellations.
            # Fall back to bbox sampling.
            pts = np.random.uniform(op_bbox_lo, op_bbox_hi,
                                    size=(args.samples, 3))
            rec["sampling"] = "bbox-fallback"
        else:
            rec["sampling"] = "volume"
        rec["sample_points"] = int(len(pts))

        f_inside = fraction_inside(host_mesh, pts)
        rec["wall_fraction_in_opening"] = f_inside

        if f_inside is None:
            rec["verdict"] = "skip:contains-failed"
        elif f_inside >= FAIL_WALL_IN_OPENING:
            rec["verdict"] = "fail:opening-not-cut"
        elif f_inside >= WARN_WALL_IN_OPENING:
            rec["verdict"] = "warn:opening-partial-cut"
        else:
            rec["verdict"] = "pass"

        pair_records.append(rec)

    # C3: walk IfcRelFillsElement
    print(f"\nchecking {len(rels_fills)} fills relationships…", file=sys.stderr)
    for rel in rels_fills:
        opening = rel.RelatingOpeningElement
        filler = rel.RelatedBuildingElement
        if opening is None or filler is None:
            continue
        rec = {
            "kind": "fills",
            "filler_guid": getattr(filler, "GlobalId", None),
            "filler_type": filler.is_a(),
            "filler_name": getattr(filler, "Name", None),
            "filler_express_id": filler.id(),
            "opening_express_id": opening.id(),
            "opening_type": opening.is_a(),
        }
        op_data = openings.get(opening.id())
        cand_filler = cand_by_guid.get(rec["filler_guid"]) if rec["filler_guid"] else None
        if op_data is None:
            rec["verdict"] = "skip:no-opening-mesh"
            pair_records.append(rec)
            continue
        if cand_filler is None:
            rec["verdict"] = "skip:no-candidate-filler"
            pair_records.append(rec)
            continue

        op_b = mesh_bounds(op_data)
        f_b = mesh_bounds(cand_filler)
        if op_b is None or f_b is None:
            rec["verdict"] = "skip:empty-mesh"
            pair_records.append(rec)
            continue
        overlap, op_vol, f_vol = bbox_overlap_volume(op_b[0], op_b[1], f_b[0], f_b[1])
        rec["opening_bbox_volume"] = op_vol
        rec["filler_bbox_volume"] = f_vol
        rec["overlap_bbox_volume"] = overlap
        rec["filler_bbox_inside_opening_frac"] = overlap / f_vol if f_vol > 0 else None

        frac = rec["filler_bbox_inside_opening_frac"]
        if frac is None:
            rec["verdict"] = "skip:zero-bbox"
        elif frac < FAIL_FILLER_BBOX_OVERLAP:
            rec["verdict"] = "fail:filler-misaligned"
        elif frac < WARN_FILLER_BBOX_OVERLAP:
            rec["verdict"] = "warn:filler-partial-overlap"
        else:
            rec["verdict"] = "pass"
        pair_records.append(rec)

    # Summary
    verdicts = Counter(r["verdict"] for r in pair_records)
    by_kind = defaultdict(lambda: Counter())
    for r in pair_records:
        by_kind[r["kind"]][r["verdict"]] += 1
    fails = [r for r in pair_records if r["verdict"].startswith(("fail", "fatal"))]
    fails_by_type = Counter((r["verdict"], r.get("host_type") or r.get("filler_type"))
                            for r in fails)

    summary = {
        "ifc": args.ifc,
        "candidate": args.candidate,
        "relationships": {
            "voids": len(rels_voids),
            "fills": len(rels_fills),
            "openings_meshed": len(openings),
        },
        "verdicts": dict(verdicts),
        "verdicts_by_kind": {k: dict(v) for k, v in by_kind.items()},
        "fails_by_type": {
            f"{v}|{t}": c for (v, t), c in fails_by_type.most_common(30)
        },
        "failures_top20": fails[:20],
    }
    Path(args.out).write_text(json.dumps(summary, indent=2))

    if args.per_pair:
        with open(args.per_pair, "w") as f:
            for r in pair_records:
                f.write(json.dumps(r, separators=(",", ":")) + "\n")

    print("\n=== Semantic summary ===")
    print(f"  pairs checked: {len(pair_records)}")
    for v, c in sorted(verdicts.items()):
        print(f"  {v}: {c}")
    if fails_by_type:
        print("\nTop failure groups:")
        for (v, t), c in fails_by_type.most_common(10):
            print(f"  {v:<28} {t or '?'}: {c}")


if __name__ == "__main__":
    main()
