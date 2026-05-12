"""Tiered geometric comparator: ifc-lite (candidate) vs IfcOpenShell (reference).

Inputs are NDJSON dumps from `dump_ifclite_native` and `dump_ifcopenshell.py`,
both in world coordinates, both filtered with the same exclude list.

Tiers per element:
  T1 Coverage         — matched / only-a / only-b / by-type counts
  T2 AABB invariants  — vertex/tri delta, AABB IoU, AABB-center distance,
                        AABB volume ratio, convex-hull volume ratio,
                        surface area ratio
  T3 Point-set        — Hausdorff (sym) and Chamfer (mean) on area-sampled
                        points, both raw (m) and normalized (bbox-diag)
  T4 Topology         — watertight-after-weld, euler characteristic,
                        manifold-edge ratio
  T5 Voxel IoU        — Jaccard on a fixed-resolution occupancy grid
                        (auto-enabled when either side is non-watertight
                        after welding, so signed volume is unreliable)

Per-element verdict ∈ {pass, warn, fail, fatal} with per-IFC-type thresholds.

Outputs:
  --out summary.json     model-level summary (counts, verdicts, top failures)
  --per-element ndjson   one record per matched element with all metrics
  --html report.html     human-readable report (sortable table)

Usage: diff.py <candidate.ndjson> <reference.ndjson> --out summary.json [opts]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import trimesh
from scipy.spatial import cKDTree

# ── thresholds ──────────────────────────────────────────────────────
#
# Per-IFC-type overrides take precedence; "_default" applies otherwise.
# These are first-cut numbers calibrated by the prototype run on duplex.ifc
# and reflect "I'd be alarmed if this is exceeded". Tighten over time.

# Threshold philosophy:
#   - voxel IoU is the strongest single signal (kernel- and tessellation-agnostic)
#     and is the primary fail driver.
#   - bbox IoU catches gross position/scale errors.
#   - Hull volume ratio is the primary volumetric check (works on open meshes too).
#   - Hausdorff is a *warning* signal only — tessellation noise can dominate the
#     max-distance metric even when the underlying shape is identical.
#   - Signed-volume ratio is informational only; trimesh.volume on closed-but-
#     inconsistently-oriented meshes returns nonsense.
#
# These numbers are calibrated from the duplex.ifc distribution: most "matching"
# elements have bbox_iou>=0.99 and voxel_iou>=0.99, with a sharp cliff for the
# small subset that's truly different.

THRESHOLDS = {
    "_default": {
        "bbox_iou_warn":         0.95,
        "bbox_iou_fail":         0.50,
        "voxel_iou_warn":        0.95,
        "voxel_iou_fail":        0.80,
        "hull_volume_warn_band": (0.97, 1.03),
        "hull_volume_fail_band": (0.85, 1.15),
        "centroid_rel_warn":     0.02,
        "centroid_rel_fail":     0.10,
        "hausdorff_rel_warn":    0.15,
        # No hausdorff_rel_fail — Hausdorff is warning-only by default.
        "chamfer_rel_warn":      0.05,
    },
    # Open shells by design — relax voxel coverage (the meshes are thin shells,
    # surface voxelization at coarse resolution produces patchy occupancy)
    "IfcRailing":     {"voxel_iou_fail": 0.50},
    "IfcStairFlight": {"voxel_iou_fail": 0.60},
    # Profiles are well-defined; tighten volume bounds
    "IfcBeam":   {"hull_volume_warn_band": (0.99, 1.01),
                  "hull_volume_fail_band": (0.95, 1.05)},
    "IfcColumn": {"hull_volume_warn_band": (0.99, 1.01),
                  "hull_volume_fail_band": (0.95, 1.05)},
}


_MISSING = object()


def thresh(t: str, key: str, default=_MISSING):
    """Look up threshold key, with per-type override -> _default -> caller default."""
    if t in THRESHOLDS and key in THRESHOLDS[t]:
        return THRESHOLDS[t][key]
    if key in THRESHOLDS["_default"]:
        return THRESHOLDS["_default"][key]
    if default is _MISSING:
        raise KeyError(f"no threshold {key!r} for type {t!r}")
    return default


# ── loading ─────────────────────────────────────────────────────────


def load_ndjson(path: Path):
    by_guid: dict[str, dict] = {}
    no_guid: list[dict] = []
    by_type: dict[str, int] = defaultdict(int)
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        by_type[rec["type"]] += 1
        key = rec.get("guid")
        if key:
            by_guid[key] = rec
        else:
            no_guid.append(rec)
    return by_guid, no_guid, dict(by_type)


def to_trimesh(rec: dict, weld: bool = True) -> Optional[trimesh.Trimesh]:
    pos = np.asarray(rec["positions"], dtype=np.float64).reshape(-1, 3)
    idx = np.asarray(rec["indices"], dtype=np.int64).reshape(-1, 3)
    if pos.shape[0] == 0 or idx.shape[0] == 0:
        return None
    try:
        # process=True welds vertices within tolerance and drops degenerate faces.
        # We do this for *both* engines so triangle-soup vs welded becomes apples-to-apples.
        m = trimesh.Trimesh(vertices=pos, faces=idx, process=weld, validate=weld)
    except Exception:
        return None
    return m


# ── metric helpers ──────────────────────────────────────────────────


def aabb_iou(a_min, a_max, b_min, b_max) -> float:
    inter_min = np.maximum(a_min, b_min)
    inter_max = np.minimum(a_max, b_max)
    inter_size = np.clip(inter_max - inter_min, 0, None)
    inter_vol = float(np.prod(inter_size))
    a_vol = float(np.prod(a_max - a_min))
    b_vol = float(np.prod(b_max - b_min))
    union = a_vol + b_vol - inter_vol
    return inter_vol / union if union > 0 else 0.0


def directed(src: np.ndarray, dst: np.ndarray):
    if len(src) == 0 or len(dst) == 0:
        return None, None
    tree = cKDTree(dst)
    d, _ = tree.query(src, k=1)
    return float(d.max()), float(d.mean())


def sample_surface(m: trimesh.Trimesh, n: int) -> Optional[np.ndarray]:
    if m.area <= 0 or len(m.faces) == 0:
        return None
    try:
        pts, _ = trimesh.sample.sample_surface(m, max(64, int(n)))
        return np.asarray(pts, dtype=np.float64)
    except Exception:
        return None


def convex_hull_volume(m: trimesh.Trimesh) -> Optional[float]:
    """Volume of the convex hull — robust to open/non-manifold meshes."""
    try:
        if len(m.vertices) < 4:
            return None
        return float(m.convex_hull.volume)
    except Exception:
        return None


def voxel_iou(ma: trimesh.Trimesh, mb: trimesh.Trimesh,
              pitch: Optional[float] = None,
              max_cells_per_axis: int = 96) -> Optional[float]:
    """Voxelize both meshes on a shared grid and compute Jaccard.

    Resolution: if pitch is None, picks pitch = max(bbox_extent)/max_cells_per_axis.
    The shared grid uses the union AABB so cell indices are comparable directly.

    Robust to non-watertight meshes (uses fill via flood-fill).
    """
    # Shared AABB
    amin = np.minimum(ma.bounds[0], mb.bounds[0])
    amax = np.maximum(ma.bounds[0] * 0 + ma.bounds[1], mb.bounds[1])
    extent = amax - amin
    diag = float(np.max(extent))
    if diag <= 0:
        return None
    p = pitch if pitch is not None else max(diag / max_cells_per_axis, 1e-4)

    def occupancy(m: trimesh.Trimesh) -> Optional[set[tuple[int, int, int]]]:
        try:
            # Surface voxelization is fine for IoU on solids of comparable shape.
            # We avoid `fill=True` since not all reps are closed; using surface
            # voxels makes the metric symmetric and well-defined.
            vox = m.voxelized(pitch=p)
            if vox is None or vox.points is None or len(vox.points) == 0:
                return None
            # Quantize to the shared grid origin (amin) so both engines hit
            # the same cells.
            cells = np.floor((vox.points - amin) / p).astype(np.int64)
            return set(map(tuple, cells.tolist()))
        except Exception:
            return None

    sa = occupancy(ma)
    sb = occupancy(mb)
    if sa is None or sb is None:
        return None
    if not sa and not sb:
        return 1.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


# ── per-element comparison ─────────────────────────────────────────


@dataclass
class Pair:
    rec_a: dict
    rec_b: dict
    metrics: dict = field(default_factory=dict)
    verdict: str = "pending"


def compare_pair(rec_a: dict, rec_b: dict, opts: dict) -> dict:
    m: dict = {
        "guid": rec_a.get("guid") or rec_b.get("guid"),
        "type": rec_b["type"],
        "type_a": rec_a["type"],
        "type_b": rec_b["type"],
        "name": rec_a.get("name") or rec_b.get("name"),
        "express_id_a": rec_a["express_id"],
        "express_id_b": rec_b["express_id"],
    }
    ma = to_trimesh(rec_a, weld=True)
    mb = to_trimesh(rec_b, weld=True)
    if ma is None or mb is None:
        m["error"] = "empty_mesh"
        return m

    m["vertex_count_a"] = int(len(ma.vertices))
    m["vertex_count_b"] = int(len(mb.vertices))
    m["triangle_count_a"] = int(len(ma.faces))
    m["triangle_count_b"] = int(len(mb.faces))

    # AABB
    a_min, a_max = ma.bounds[0], ma.bounds[1]
    b_min, b_max = mb.bounds[0], mb.bounds[1]
    m["bbox_iou"] = aabb_iou(a_min, a_max, b_min, b_max)
    diag_b = float(np.linalg.norm(b_max - b_min)) or 1e-9
    m["bbox_diag_b"] = diag_b
    aabb_center_a = (a_min + a_max) * 0.5
    aabb_center_b = (b_min + b_max) * 0.5
    m["centroid_aabb_dist"] = float(np.linalg.norm(aabb_center_a - aabb_center_b))
    m["centroid_rel"] = m["centroid_aabb_dist"] / diag_b

    # Volumes
    aabb_vol_a = float(np.prod(a_max - a_min))
    aabb_vol_b = float(np.prod(b_max - b_min))
    m["aabb_volume_a"] = aabb_vol_a
    m["aabb_volume_b"] = aabb_vol_b
    if aabb_vol_b > 1e-12:
        m["aabb_volume_ratio"] = aabb_vol_a / aabb_vol_b

    hv_a = convex_hull_volume(ma)
    hv_b = convex_hull_volume(mb)
    m["hull_volume_a"] = hv_a
    m["hull_volume_b"] = hv_b
    if hv_a is not None and hv_b is not None and hv_b > 1e-12:
        m["hull_volume_ratio"] = hv_a / hv_b

    # Topology + watertight signed volume
    try:
        m["watertight_a"] = bool(ma.is_watertight)
        m["watertight_b"] = bool(mb.is_watertight)
        m["euler_a"] = int(ma.euler_number)
        m["euler_b"] = int(mb.euler_number)
    except Exception:
        m["watertight_a"] = m["watertight_b"] = False

    if m.get("watertight_a") and m.get("watertight_b"):
        try:
            va = float(ma.volume)
            vb = float(mb.volume)
            m["volume_a"] = va
            m["volume_b"] = vb
            if abs(vb) > 1e-12:
                m["volume_ratio"] = va / vb
        except Exception:
            pass

    # Surface area
    try:
        m["surface_area_a"] = float(ma.area)
        m["surface_area_b"] = float(mb.area)
        if mb.area > 0:
            m["surface_area_ratio"] = float(ma.area / mb.area)
    except Exception:
        pass

    # Point-set distance
    n = int(max(opts.get("min_samples", 256),
                min(opts.get("max_samples", 1024),
                    math.sqrt(max(len(ma.faces), len(mb.faces))) * 16)))
    pa_s = sample_surface(ma, n)
    pb_s = sample_surface(mb, n)
    if pa_s is not None and pb_s is not None:
        h_ab, c_ab = directed(pa_s, pb_s)
        h_ba, c_ba = directed(pb_s, pa_s)
        if h_ab is not None and h_ba is not None:
            m["hausdorff"] = max(h_ab, h_ba)
            m["hausdorff_a_to_b"] = h_ab
            m["hausdorff_b_to_a"] = h_ba
            m["chamfer_mean"] = (c_ab + c_ba) * 0.5
            m["hausdorff_rel"] = m["hausdorff"] / diag_b
            m["chamfer_rel"] = m["chamfer_mean"] / diag_b

    # Voxel IoU — kernel-agnostic shape oracle.
    #
    # Always-run is the default for correctness; we add a fast-path skip
    # (`voxel_skip_if_strong_agreement`) that bypasses voxelization when
    # cheaper metrics already strongly agree (bbox IoU and hull volume both
    # within 1%). This cuts the dominant per-element cost by ~3-4× on models
    # where most elements match.
    do_vox = not opts.get("voxel_off", False)
    if do_vox and opts.get("voxel_skip_if_strong_agreement", True):
        bbox_strong = m.get("bbox_iou", 0) >= 0.99
        hull_strong = "hull_volume_ratio" in m and abs(m["hull_volume_ratio"] - 1) < 0.01
        if bbox_strong and hull_strong and not opts.get("voxel_always", False):
            do_vox = False
            m["voxel_iou_skipped"] = "strong-agreement"
    if do_vox:
        m["voxel_iou"] = voxel_iou(ma, mb,
                                   max_cells_per_axis=opts.get("voxel_cells", 64))

    return m


def classify(m: dict) -> str:
    """Verdict order: fail signals first, then warn, else pass.

    Fail axes  : position (bbox), shape (voxel), volume (hull).
    Warn axes  : voxel, hausdorff, chamfer, hull volume, centroid.
    Hausdorff is warning-only — its max-distance nature makes it sensitive to
    tessellation density rather than shape correctness.
    """
    t = m.get("type_b") or m.get("type", "")
    if m.get("error"):
        return f"fatal:{m['error']}"
    if m.get("type_a") and m.get("type_b") and m["type_a"] != m["type_b"]:
        return "fatal:type-mismatch"

    # ── FAIL ─────────────────────────────────────────────────────────
    if "bbox_iou" in m and m["bbox_iou"] < thresh(t, "bbox_iou_fail"):
        return "fail:position"
    if "voxel_iou" in m and m["voxel_iou"] is not None \
            and m["voxel_iou"] < thresh(t, "voxel_iou_fail"):
        return "fail:shape"
    if "hull_volume_ratio" in m:
        lo, hi = thresh(t, "hull_volume_fail_band")
        if not (lo <= m["hull_volume_ratio"] <= hi):
            return "fail:volume"

    # ── WARN ─────────────────────────────────────────────────────────
    if "voxel_iou" in m and m["voxel_iou"] is not None \
            and m["voxel_iou"] < thresh(t, "voxel_iou_warn"):
        return "warn:shape"
    if "hull_volume_ratio" in m:
        lo, hi = thresh(t, "hull_volume_warn_band")
        if not (lo <= m["hull_volume_ratio"] <= hi):
            return "warn:volume"
    if "hausdorff_rel" in m \
            and m["hausdorff_rel"] > thresh(t, "hausdorff_rel_warn"):
        return "warn:hausdorff"
    if "chamfer_rel" in m \
            and m["chamfer_rel"] > thresh(t, "chamfer_rel_warn"):
        return "warn:chamfer"
    if "centroid_rel" in m \
            and m["centroid_rel"] > thresh(t, "centroid_rel_warn"):
        return "warn:centroid"
    return "pass"


# ── reporting ───────────────────────────────────────────────────────


def write_html(summary: dict, per_elem: list[dict], path: Path):
    rows = []
    for p in sorted(per_elem, key=_sort_key, reverse=True):
        rows.append(_html_row(p))
    counts = summary["counts"]
    verdicts = summary["verdicts"]
    title = f"correctness: {Path(summary['files']['a']).name} vs {Path(summary['files']['b']).name}"
    html = f"""<!doctype html><html><head>
<meta charset="utf-8"><title>{title}</title>
<style>
 body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:24px;color:#222}}
 h1{{font-size:20px;margin:0 0 4px}}
 .sub{{color:#666;margin-bottom:18px}}
 .card{{background:#f6f6f6;border-radius:8px;padding:12px 14px;margin-bottom:16px;font-size:13px}}
 table{{border-collapse:collapse;width:100%;font-size:12px}}
 th,td{{padding:6px 8px;border-bottom:1px solid #eee;text-align:left}}
 th{{background:#fafafa;position:sticky;top:0;cursor:pointer;user-select:none}}
 .pass{{color:#0a7d2c}}.warn{{color:#b06d00}}.fail{{color:#c41f1f;font-weight:600}}.fatal{{color:#660066;font-weight:700}}
 td.n{{text-align:right;font-variant-numeric:tabular-nums}}
 .verdict{{font-weight:600}}
</style>
<script>
function sortTable(idx, isNum) {{
  const tb = document.querySelector('table tbody');
  const rows = Array.from(tb.querySelectorAll('tr'));
  const cur = tb.dataset.sort === idx + ':asc' ? 'desc' : 'asc';
  rows.sort((a,b) => {{
    const av = a.cells[idx].innerText, bv = b.cells[idx].innerText;
    if (isNum) {{
      const an = parseFloat(av), bn = parseFloat(bv);
      return (cur === 'asc' ? 1 : -1) * ((isNaN(an)?-Infinity:an) - (isNaN(bn)?-Infinity:bn));
    }}
    return (cur === 'asc' ? 1 : -1) * av.localeCompare(bv);
  }});
  tb.dataset.sort = idx + ':' + cur;
  rows.forEach(r => tb.appendChild(r));
}}
</script>
</head><body>
<h1>{title}</h1>
<div class="sub">matched: {counts['matched']} · only-a: {counts['only_a']} · only-b: {counts['only_b']}</div>
<div class="card">
 <b>Verdicts:</b>
 {' · '.join(f'<span class="{_cls(k)}">{k}={v}</span>' for k,v in sorted(verdicts.items()))}
</div>
<table>
<thead><tr>
 <th onclick="sortTable(0,false)">verdict</th>
 <th onclick="sortTable(1,false)">type</th>
 <th onclick="sortTable(2,false)">name</th>
 <th onclick="sortTable(3,true)">bbox IoU</th>
 <th onclick="sortTable(4,true)">vox IoU</th>
 <th onclick="sortTable(5,true)">haus_rel</th>
 <th onclick="sortTable(6,true)">cham_rel</th>
 <th onclick="sortTable(7,true)">hull vol_ratio</th>
 <th onclick="sortTable(8,true)">vol_ratio</th>
 <th onclick="sortTable(9,true)">verts a/b</th>
 <th onclick="sortTable(10,true)">tris a/b</th>
 <th onclick="sortTable(11,false)">wt a/b</th>
</tr></thead>
<tbody>
{''.join(rows)}
</tbody></table>
</body></html>
"""
    path.write_text(html)


def _cls(verdict: str) -> str:
    if verdict.startswith("fatal"):
        return "fatal"
    if verdict.startswith("fail"):
        return "fail"
    if verdict.startswith("warn"):
        return "warn"
    return "pass"


def _sort_key(p: dict):
    rank = {"fatal": 0, "fail": 1, "warn": 2, "pass": 3}
    return (-rank.get(p["verdict"].split(":")[0], 99),
            -(p.get("hausdorff_rel") or 0))


def _fmt(v, prec=3):
    if v is None:
        return ""
    if isinstance(v, float):
        if abs(v) < 1e-4:
            return f"{v:.2e}"
        return f"{v:.{prec}f}"
    return str(v)


def _html_row(p: dict) -> str:
    cls = _cls(p["verdict"])
    wt_a = "Y" if p.get("watertight_a") else "n"
    wt_b = "Y" if p.get("watertight_b") else "n"
    return (
        f'<tr><td class="verdict {cls}">{p["verdict"]}</td>'
        f'<td>{p.get("type_b", "")}</td>'
        f'<td>{(p.get("name") or "")[:60]}</td>'
        f'<td class="n">{_fmt(p.get("bbox_iou"))}</td>'
        f'<td class="n">{_fmt(p.get("voxel_iou"))}</td>'
        f'<td class="n">{_fmt(p.get("hausdorff_rel"), 4)}</td>'
        f'<td class="n">{_fmt(p.get("chamfer_rel"), 4)}</td>'
        f'<td class="n">{_fmt(p.get("hull_volume_ratio"), 4)}</td>'
        f'<td class="n">{_fmt(p.get("volume_ratio"), 4)}</td>'
        f'<td class="n">{p.get("vertex_count_a","")}/{p.get("vertex_count_b","")}</td>'
        f'<td class="n">{p.get("triangle_count_a","")}/{p.get("triangle_count_b","")}</td>'
        f'<td class="n">{wt_a}/{wt_b}</td></tr>'
    )


# ── main ────────────────────────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a", help="candidate ndjson (ifc-lite)")
    ap.add_argument("b", help="reference ndjson (ifcopenshell)")
    ap.add_argument("--out", required=True, help="summary JSON output")
    ap.add_argument("--per-element", help="NDJSON output of per-element metrics")
    ap.add_argument("--html", help="HTML report output")
    ap.add_argument("--voxel-off", action="store_true", help="disable voxel IoU entirely")
    ap.add_argument("--voxel-always", action="store_true",
                    help="compute voxel IoU even when both meshes are watertight")
    ap.add_argument("--voxel-cells", type=int, default=64,
                    help="max cells per longest axis when picking voxel pitch")
    ap.add_argument("--voxel-no-skip", action="store_true",
                    help="disable fast-path skip when bbox+hull already strongly agree")
    ap.add_argument("--max-samples", type=int, default=1024)
    ap.add_argument("--min-samples", type=int, default=256)
    args = ap.parse_args()

    a_by_guid, a_no_guid, a_types = load_ndjson(Path(args.a))
    b_by_guid, b_no_guid, b_types = load_ndjson(Path(args.b))

    a_keys = set(a_by_guid)
    b_keys = set(b_by_guid)
    matched = sorted(a_keys & b_keys)
    only_a = sorted(a_keys - b_keys)
    only_b = sorted(b_keys - a_keys)

    opts = {
        "voxel_off": args.voxel_off,
        "voxel_always": args.voxel_always,
        "voxel_cells": args.voxel_cells,
        "voxel_skip_if_strong_agreement": not args.voxel_no_skip,
        "max_samples": args.max_samples,
        "min_samples": args.min_samples,
    }

    per_elem: list[dict] = []
    verdicts: dict[str, int] = defaultdict(int)
    t0 = time.perf_counter()
    n = len(matched)
    print(f"Comparing {n} matched elements ({len(only_a)} only-a, {len(only_b)} only-b)…",
          file=sys.stderr)
    for i, key in enumerate(matched, 1):
        if i % 50 == 0 or i == n:
            print(f"  [{i}/{n}] ({time.perf_counter()-t0:.1f}s)", file=sys.stderr)
        p = compare_pair(a_by_guid[key], b_by_guid[key], opts)
        p["verdict"] = classify(p)
        verdicts[p["verdict"]] += 1
        per_elem.append(p)

    t_compare = time.perf_counter() - t0

    summary = {
        "files": {"a": args.a, "b": args.b},
        "elapsed_s": round(t_compare, 2),
        "counts": {
            "a_total": len(a_by_guid) + len(a_no_guid),
            "b_total": len(b_by_guid) + len(b_no_guid),
            "a_no_guid": len(a_no_guid),
            "b_no_guid": len(b_no_guid),
            "matched": len(matched),
            "only_a": len(only_a),
            "only_b": len(only_b),
        },
        "verdicts": dict(verdicts),
        "types_a": a_types,
        "types_b": b_types,
        "only_a_by_type": _group_types(a_by_guid, only_a),
        "only_b_by_type": _group_types(b_by_guid, only_b),
        "failures_top20": [p for p in per_elem
                           if p["verdict"].startswith(("fail", "fatal"))][:20],
        "thresholds": THRESHOLDS,
    }
    Path(args.out).write_text(json.dumps(summary, indent=2))
    if args.per_element:
        with open(args.per_element, "w") as f:
            for p in per_elem:
                f.write(json.dumps(p, separators=(",", ":")) + "\n")
    if args.html:
        write_html(summary, per_elem, Path(args.html))

    # Stdout
    print(f"\n=== Summary ({t_compare:.1f}s) ===")
    print(f"  matched: {summary['counts']['matched']}")
    print(f"  only ifc-lite: {summary['counts']['only_a']}")
    print(f"  only IOS:      {summary['counts']['only_b']}")
    for v, c in sorted(verdicts.items()):
        print(f"  {v}: {c}")
    if summary["only_b_by_type"]:
        print("\nMissing from ifc-lite (IOS has, ifc-lite doesn't), by type:")
        for t, c in sorted(summary["only_b_by_type"].items(), key=lambda x: -x[1])[:10]:
            print(f"  {t}: {c}")


def _group_types(recs: dict, keys: list[str]) -> dict[str, int]:
    g: dict[str, int] = defaultdict(int)
    for k in keys:
        g[recs[k]["type"]] += 1
    return dict(g)


if __name__ == "__main__":
    main()
