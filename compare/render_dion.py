"""5-panel benchmark chart, all engines on M4.

Panels:
  1. Parse / Open time
  2. Geometry time (per-element output, exclude IfcOpeningElement / IfcSpace / IfcBuilding / IfcBuildingStorey / IfcOpeningStandardCase)
  3. Total (parse + geometry)
  4. Geometric output — total triangles per file (sanity check that engines produce comparable geometry)
  5. Zero-copy / GPU-ready buffer (separate output category — single concatenated buffer, no per-element attribution)

Six engine series in panels 1-3, four in panel 4 (no zero-copy), two in panel 5.
"""
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"


def load(name: str) -> dict:
    return {r["file"]: r for r in json.load(open(RESULTS / name))["results"]}


lite_wasm = load("ifclite-dion.json")
web        = load("webifc-dion.json")
lite_n1    = load("ifclite-native-1c.json")
lite_nm    = load("ifclite-native-max.json")
zc_lite    = load("ifclite-zerocopy.json") if (RESULTS / "ifclite-zerocopy.json").exists() else {}
zc_web     = load("webifc-zerocopy.json") if (RESULTS / "webifc-zerocopy.json").exists() else {}

# IfcOpenShell numbers from Moult/profiling/findings.md (his hardware,
# datamodel branch, hybrid-manifold-cgal-simple-opencascade kernel).
# Pip ifcopenshell 0.8.2 does not ship the Manifold kernel, so the fairest
# IOS column is Moult's published Manifold-augmented run rather than a
# kernel-handicapped re-run on this M4. Hardware caveat noted in RESULTS.md.
IOS_KERNEL = "hybrid-manifold-cgal-simple-opencascade"
_IOS_SINGLE_RAW = {
    "duplex.ifc":                                                      (0.07, 0.12),
    "AC20-FZK-Haus.ifc":                                               (0.09, 0.13),
    "ISSUE_005_haus.ifc":                                              (0.08, 0.13),
    "ISSUE_021_Mini Project.ifc":                                      (0.10, 0.43),
    "Office_A_20110811.ifc":                                           (0.13, 0.16),
    "ISSUE_126_model.ifc":                                             (0.18, 0.28),
    "ISSUE_034_HouseZ.ifc":                                            (0.15, 0.56),
    "ISSUE_102_M3D-CON.ifc":                                           (0.21, 0.41),
    "ISSUE_159_kleine_Wohnung_R22.ifc":                                (0.46, 1.19),
    "C20-Institute-Var-2.ifc":                                         (0.40, 0.31),
    "ISSUE_129_N1540_17_EXE_MOD_448200_02_09_11SMC_IGC_V17.ifc":       (0.55, 0.97),
    "dental_clinic.ifc":                                               (0.53, 0.72),
    "FM_ARC_DigitalHub.ifc":                                           (0.72, 1.71),
    "ifcbridge-model01.ifc":                                           (0.81, 1.24),
    "ISSUE_102_M3D-CON-CD.ifc":                                        (1.10, 2.92),
    "S_Office_Integrated Design Archi.ifc":                            (1.42, 2.62),
    "advanced_model.ifc":                                              (1.58, 2.34),
    "schependomlaan.ifc":                                              (1.84, 1.51),
    "ISSUE_068_ARK_NUS_skolebygg.ifc":                                 (2.67, 3.05),
    "ISSUE_098_R8_F1_MAB_AR_M3_XX_XXX_MO_7000.IFC":                   (3.34, 5.08),
    "ISSUE_053_20181220Holter_Tower_10.ifc":                           (8.68, 10.85),
}
_IOS_MAX_RAW = {
    "duplex.ifc":                                                      (0.08, 0.04),
    "AC20-FZK-Haus.ifc":                                               (0.10, 0.05),
    "ISSUE_005_haus.ifc":                                              (0.09, 0.04),
    "ISSUE_021_Mini Project.ifc":                                      (0.13, 0.16),
    "Office_A_20110811.ifc":                                           (0.16, 0.09),
    "ISSUE_126_model.ifc":                                             (0.24, 0.08),
    "ISSUE_034_HouseZ.ifc":                                            (0.21, 0.17),
    "ISSUE_102_M3D-CON.ifc":                                           (0.28, 0.21),
    "ISSUE_159_kleine_Wohnung_R22.ifc":                                (0.57, 0.34),
    "C20-Institute-Var-2.ifc":                                         (0.53, 0.14),
    "ISSUE_129_N1540_17_EXE_MOD_448200_02_09_11SMC_IGC_V17.ifc":       (0.67, 0.22),
    "dental_clinic.ifc":                                               (0.72, 0.27),
    "FM_ARC_DigitalHub.ifc":                                           (0.93, 0.61),
    "ifcbridge-model01.ifc":                                           (1.04, 0.28),
    "ISSUE_102_M3D-CON-CD.ifc":                                        (1.38, 1.28),
    "S_Office_Integrated Design Archi.ifc":                            (1.83, 1.11),
    "advanced_model.ifc":                                              (2.17, 0.83),
    "schependomlaan.ifc":                                              (2.39, 0.46),
    "ISSUE_068_ARK_NUS_skolebygg.ifc":                                 (3.43, 0.68),
    "ISSUE_098_R8_F1_MAB_AR_M3_XX_XXX_MO_7000.IFC":                   (4.23, 1.59),
    "ISSUE_053_20181220Holter_Tower_10.ifc":                          (10.29, 3.41),
}
ios_1c = {f: {"t_open": p, "t_geom": g, "t_total": p + g} for f, (p, g) in _IOS_SINGLE_RAW.items()}
ios_mx = {f: {"t_open": p, "t_geom": g, "t_total": p + g} for f, (p, g) in _IOS_MAX_RAW.items()}

NATIVE_THREADS = next(iter(lite_nm.values())).get("threads", "max") if lite_nm else "max"

files = [f for f in lite_wasm if f in web and f in lite_n1 and f in lite_nm]
files.sort(key=lambda f: lite_wasm[f]["sizeMb"])
x = np.arange(len(files))


def get(d: dict, f: str, key: str):
    """Safe getter — file may be absent (engine FAILed on it). Returns NaN."""
    if f not in d:
        return float("nan")
    return safe(d[f].get(key))


def safe(v):
    return float("nan") if v is None else v


def t_total(row, parse_key="t_parse", geom_key="t_geom"):
    p = safe(row.get(parse_key))
    g = safe(row.get(geom_key))
    if p != p:  # NaN
        return float("nan")
    if g != g:
        return float("nan")
    return p + g


def t_total_native(row):
    # native bench reports an authoritative total from wallclock
    return safe(row.get("t_total"))


def t_total_ios(row):
    return safe(row.get("t_total"))


# Per-engine series. IOS may have FAIL rows (CGAL crashes on a couple of files)
# — use safe getters that return NaN for missing files.
ios_1c_p   = [get(ios_1c, f, "t_open") for f in files]
ios_1c_g   = [get(ios_1c, f, "t_geom") for f in files]
ios_mx_p   = [get(ios_mx, f, "t_open") for f in files]
ios_mx_g   = [get(ios_mx, f, "t_geom") for f in files]
web_p      = [web[f]["tParse"] for f in files]
web_g      = [safe(web[f]["tGeom"]) for f in files]
litew_p    = [lite_wasm[f]["tParse"] for f in files]
litew_g    = [safe(lite_wasm[f]["tGeom"]) for f in files]
liten1_p   = [lite_n1[f]["t_parse"] for f in files]
liten1_g   = [lite_n1[f]["t_geom"] for f in files]
litenm_p   = [lite_nm[f]["t_parse"] for f in files]
litenm_g   = [lite_nm[f]["t_geom"] for f in files]

ios_1c_t   = [t_total_ios(ios_1c[f]) if f in ios_1c else float("nan") for f in files]
ios_mx_t   = [t_total_ios(ios_mx[f]) if f in ios_mx else float("nan") for f in files]
web_t      = [t_total(web[f], "tParse", "tGeom") for f in files]
litew_t    = [t_total(lite_wasm[f], "tParse", "tGeom") for f in files]
liten1_t   = [t_total_native(lite_n1[f]) for f in files]
litenm_t   = [t_total_native(lite_nm[f]) for f in files]

# Triangle counts per file (may be 0 / missing if engine doesn't track yet)
ios_1c_tri = [get(ios_1c, f, "triangles") for f in files]
web_tri    = [get(web, f, "triangles") for f in files]
litew_tri  = [get(lite_wasm, f, "triangles") for f in files]
litenm_tri = [get(lite_nm, f, "triangles") for f in files]

# Zero-copy
zc_l = [safe(zc_lite.get(f, {}).get("tZeroCopy")) for f in files]
zc_w = [safe(zc_web.get(f, {}).get("tZeroCopyRef")) for f in files]

labels = [
    f"{f.replace('.ifc','').replace('.IFC','')[:32]}\n({lite_wasm[f]['sizeMb']:.1f} MB)"
    for f in files
]

# Colors
C_IOS_S    = "#1f4e9f"
C_IOS_M    = "#6fa8d8"
C_WEB      = "#ff7f0e"
C_LITE_W   = "#9ed99e"
C_LITE_N1  = "#2ca02c"
C_LITE_NM  = "#0a4f08"

fig, axes = plt.subplots(4, 1, figsize=(22, 18), sharex=True)
plt.subplots_adjust(hspace=0.13)

w = 0.13
positions = [-2.5*w, -1.5*w, -0.5*w, 0.5*w, 1.5*w, 2.5*w]


def panel6(ax, title, ios_s, ios_m, webv, litew, liten1, litenm):
    ax.bar(x + positions[0], ios_s,  w, label=f"IfcOpenShell (single core, {IOS_KERNEL})", color=C_IOS_S)
    ax.bar(x + positions[1], ios_m,  w, label=f"IfcOpenShell (max threads, {IOS_KERNEL})", color=C_IOS_M)
    ax.bar(x + positions[2], webv,   w, label="web-ifc (StreamAllMeshes)", color=C_WEB)
    ax.bar(x + positions[3], litew,  w, label="ifc-lite (WASM, parseMeshes)", color=C_LITE_W)
    ax.bar(x + positions[4], liten1, w, label="ifc-lite (native, 1 core)", color=C_LITE_N1)
    ax.bar(x + positions[5], litenm, w, label=f"ifc-lite (native, {NATIVE_THREADS} threads)", color=C_LITE_NM)
    ax.set_yscale("log")
    ax.set_ylabel("seconds (log)")
    ax.set_title(title)
    ax.legend(loc="upper left", fontsize=8, ncol=3)
    ax.grid(True, axis="y", which="both", linestyle="--", alpha=0.3)


panel6(axes[0], "1. Parse / Open time", ios_1c_p, ios_mx_p, web_p, litew_p, liten1_p, litenm_p)
panel6(axes[1], "2. Geometry time (per-element output, IfcOpeningElement / IfcSpace / IfcBuilding / IfcBuildingStorey / IfcOpeningStandardCase excluded)",
       ios_1c_g, ios_mx_g, web_g, litew_g, liten1_g, litenm_g)
panel6(axes[2], "3. Total (parse + geometry)", ios_1c_t, ios_mx_t, web_t, litew_t, liten1_t, litenm_t)

# Panel 4 — zero-copy
ax = axes[3]
w5 = 0.35
ax.bar(x - w5/2, zc_l, w5, label="ifc-lite parseZeroCopy", color=C_LITE_N1)
ax.bar(x + w5/2, zc_w, w5, label="web-ifc OpenModel + StreamAllMeshes + per-mesh extract + JS concat", color=C_WEB)
ax.set_yscale("log")
ax.set_ylabel("seconds (log)")
ax.set_title("4. Zero-copy / GPU-ready geometry buffer (separate output category, single concatenated buffer, no per-element attribution)")
ax.legend(loc="upper left", fontsize=9)
ax.grid(True, axis="y", which="both", linestyle="--", alpha=0.3)

axes[3].set_xticks(x)
axes[3].set_xticklabels(labels, rotation=45, ha="right", fontsize=8)

out = RESULTS / "comparison.png"
plt.savefig(out, dpi=140, bbox_inches="tight")
print(f"wrote {out}")

# Summary
print(f"\n=== Total (parse + geometry), seconds — all on M4 ===")
print(f"{'FILE':<48} {'IOS-1c':>7} {'IOS-mx':>7} {'WEB':>7} {'L-WASM':>7} {'L-N1':>7} {'L-Nmx':>7}")
print('-' * 100)
for f, a, b, w_, lw, l1, lm in zip(files, ios_1c_t, ios_mx_t, web_t, litew_t, liten1_t, litenm_t):
    def fmt(v): return f"{v:>7.2f}" if v == v else f"{'FAIL':>7}"
    print(f"{f:<48} {fmt(a)} {fmt(b)} {fmt(w_)} {fmt(lw)} {fmt(l1)} {fmt(lm)}")

# Wins
print(f"\n=== Best M4 series per file (Total) ===")
ranks = {"IOS-1c":0, "IOS-mx":0, "web-ifc":0, "lite-WASM":0, "lite-N1":0, "lite-Nmx":0}
for f, a, b, w_, lw, l1, lm in zip(files, ios_1c_t, ios_mx_t, web_t, litew_t, liten1_t, litenm_t):
    pairs = [("IOS-1c", a), ("IOS-mx", b), ("web-ifc", w_), ("lite-WASM", lw), ("lite-N1", l1), ("lite-Nmx", lm)]
    pairs = [(k, v) for k, v in pairs if v == v]
    if not pairs: continue
    pairs.sort(key=lambda kv: kv[1])
    ranks[pairs[0][0]] += 1
for k, v in ranks.items():
    print(f"  {k}: {v}")

print(f"\n=== Triangle counts (post-exclude) ===")
print(f"{'FILE':<48} {'IOS-1c':>10} {'WEB':>10} {'L-WASM':>10} {'L-Nmx':>10}")
for f, a, w_, lw, ln in zip(files, ios_1c_tri, web_tri, litew_tri, litenm_tri):
    def fmt(v): return f"{v:>10.0f}" if v == v else f"{'FAIL':>10}"
    print(f"{f:<48} {fmt(a)} {fmt(w_)} {fmt(lw)} {fmt(ln)}")
