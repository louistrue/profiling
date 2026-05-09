"""Render the 4-panel benchmark chart.

Panels 1–3: Parse, Geometry, Total — six engine series:
  IfcOpenShell single core (Moult, his hardware)
  IfcOpenShell max threads  (Moult, his hardware)
  web-ifc                   (M4, OpenModel + StreamAllMeshes)
  ifc-lite (WASM)           (M4, scanEntities + parseMeshes)
  ifc-lite (native, 1 core) (M4, ifc-lite-processing crate, rayon=1)
  ifc-lite (native, max)    (M4, ifc-lite-processing crate, rayon=N)

Panel 4: Zero-copy / GPU-ready buffer (separate output category).
  ifc-lite parseZeroCopy
  web-ifc OpenModel + StreamAllMeshes + GetGeometry/Vertex/Index + JS concat

All ifc-lite series apply Dion's exclude list at product counting and produce
per-element output identical to IfcOpenShell iterator.

Inputs (../results/):
  ifclite-dion.json, webifc-dion.json
  ifclite-native-1c.json, ifclite-native-max.json
  ifclite-zerocopy.json, webifc-zerocopy.json

IOS numbers from Moult's findings.md.
"""
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"

IOS_SINGLE = {
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
    "ISSUE_098_R8_F1_MAB_AR_M3_XX_XXX_MO_7000.IFC":                    (3.34, 5.08),
    "ISSUE_053_20181220Holter_Tower_10.ifc":                           (8.68, 10.85),
}
IOS_MAX = {
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
    "ISSUE_098_R8_F1_MAB_AR_M3_XX_XXX_MO_7000.IFC":                    (4.23, 1.59),
    "ISSUE_053_20181220Holter_Tower_10.ifc":                          (10.29, 3.41),
}

with open(RESULTS / "ifclite-dion.json") as f:
    lite_wasm = {r["file"]: r for r in json.load(f)["results"]}
with open(RESULTS / "webifc-dion.json") as f:
    web = {r["file"]: r for r in json.load(f)["results"]}
with open(RESULTS / "ifclite-native-1c.json") as f:
    lite_n1 = {r["file"]: r for r in json.load(f)["results"]}
with open(RESULTS / "ifclite-native-max.json") as f:
    lite_nm = {r["file"]: r for r in json.load(f)["results"]}
zc_lite = {}
zc_web = {}
if (RESULTS / "ifclite-zerocopy.json").exists():
    zc_lite = {r["file"]: r for r in json.load(open(RESULTS / "ifclite-zerocopy.json"))["results"]}
if (RESULTS / "webifc-zerocopy.json").exists():
    zc_web = {r["file"]: r for r in json.load(open(RESULTS / "webifc-zerocopy.json"))["results"]}

NATIVE_THREADS = next(iter(lite_nm.values())).get("threads", "max") if lite_nm else "max"

files = [f for f in IOS_SINGLE if f in lite_wasm and f in web and f in lite_n1 and f in lite_nm]
files.sort(key=lambda f: lite_wasm[f]["sizeMb"])
x = np.arange(len(files))

ios_s_p   = [IOS_SINGLE[f][0] for f in files]
ios_s_g   = [IOS_SINGLE[f][1] for f in files]
ios_m_p   = [IOS_MAX[f][0] for f in files]
ios_m_g   = [IOS_MAX[f][1] for f in files]
web_p     = [web[f]["tParse"] for f in files]
web_g     = [web[f]["tGeom"] or float("nan") for f in files]
litew_p   = [lite_wasm[f]["tParse"] for f in files]
litew_g   = [lite_wasm[f]["tGeom"] or float("nan") for f in files]
liten1_p  = [lite_n1[f]["t_parse"] for f in files]
liten1_g  = [lite_n1[f]["t_geom"] for f in files]
litenm_p  = [lite_nm[f]["t_parse"] for f in files]
litenm_g  = [lite_nm[f]["t_geom"] for f in files]

ios_s_t   = [a + b for a, b in zip(ios_s_p, ios_s_g)]
ios_m_t   = [a + b for a, b in zip(ios_m_p, ios_m_g)]
web_t     = [a + (b if b == b else 0) for a, b in zip(web_p, web_g)]
litew_t   = [a + (b if b == b else 0) for a, b in zip(litew_p, litew_g)]
liten1_t  = [lite_n1[f]["t_total"] for f in files]
litenm_t  = [lite_nm[f]["t_total"] for f in files]

zc_l = [zc_lite.get(f, {}).get("tZeroCopy") or float("nan") for f in files]
zc_w = [zc_web.get(f, {}).get("tZeroCopyRef") or float("nan") for f in files]

labels = [
    f"{f.replace('.ifc','').replace('.IFC','')[:32]}\n({lite_wasm[f]['sizeMb']:.1f} MB)"
    for f in files
]

C_IOS_S    = "#1f4e9f"
C_IOS_M    = "#6fa8d8"
C_WEB      = "#ff7f0e"
C_LITE_W   = "#9ed99e"   # ifc-lite WASM — light green
C_LITE_N1  = "#2ca02c"   # ifc-lite native single — green
C_LITE_NM  = "#0a4f08"   # ifc-lite native max — dark green

fig, axes = plt.subplots(4, 1, figsize=(22, 18), sharex=True)
plt.subplots_adjust(hspace=0.13)

w = 0.13
positions = [-2.5*w, -1.5*w, -0.5*w, 0.5*w, 1.5*w, 2.5*w]

def panel6(ax, title, ios_s, ios_m, webv, litew, liten1, litenm):
    ax.bar(x + positions[0], ios_s,  w, label="IfcOpenShell (single core)", color=C_IOS_S)
    ax.bar(x + positions[1], ios_m,  w, label="IfcOpenShell (max threads)", color=C_IOS_M)
    ax.bar(x + positions[2], webv,   w, label="web-ifc (StreamAllMeshes)", color=C_WEB)
    ax.bar(x + positions[3], litew,  w, label="ifc-lite (WASM, parseMeshes)", color=C_LITE_W)
    ax.bar(x + positions[4], liten1, w, label="ifc-lite (native, 1 core)", color=C_LITE_N1)
    ax.bar(x + positions[5], litenm, w, label=f"ifc-lite (native, {NATIVE_THREADS} threads)", color=C_LITE_NM)
    ax.set_yscale("log")
    ax.set_ylabel("seconds (log)")
    ax.set_title(title)
    ax.legend(loc="upper left", fontsize=8, ncol=2)
    ax.grid(True, axis="y", which="both", linestyle="--", alpha=0.3)

panel6(axes[0], "1. Parse / Open time", ios_s_p, ios_m_p, web_p, litew_p, liten1_p, litenm_p)
panel6(axes[1], "2. Geometry time (per-element output, exclude IfcOpeningElement / IfcSpace / IfcBuilding / IfcBuildingStorey)",
       ios_s_g, ios_m_g, web_g, litew_g, liten1_g, litenm_g)
panel6(axes[2], "3. Total (parse + geometry)", ios_s_t, ios_m_t, web_t, litew_t, liten1_t, litenm_t)

# Panel 4 — zero-copy
ax = axes[3]
w4 = 0.35
ax.bar(x - w4/2, zc_l, w4, label="ifc-lite parseZeroCopy", color=C_LITE_N1)
ax.bar(x + w4/2, zc_w, w4, label="web-ifc OpenModel + StreamAllMeshes + per-mesh extract + JS concat", color=C_WEB)
ax.set_yscale("log")
ax.set_ylabel("seconds (log)")
ax.set_title("4. Zero-copy / GPU-ready geometry buffer  (separate output category — single concatenated buffer, no per-element attribution)")
ax.legend(loc="upper left", fontsize=9)
ax.grid(True, axis="y", which="both", linestyle="--", alpha=0.3)

axes[3].set_xticks(x)
axes[3].set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
fig.suptitle("IFC engine comparison — IfcOpenShell vs web-ifc vs ifc-lite (WASM and native)",
             fontsize=14, y=0.995)

out = RESULTS / "comparison.png"
plt.savefig(out, dpi=140, bbox_inches="tight")
print(f"wrote {out}")

# Numeric summary
print(f"\n=== Total (parse + geometry), seconds ===")
print(f"{'FILE':<48} {'IOS-1c':>7} {'IOS-mx':>7} {'WEB':>7} {'L-WASM':>7} {'L-N1':>7} {'L-Nmx':>7}")
print('-' * 100)
for f, a, b, w_, lw, l1, lm in zip(files, ios_s_t, ios_m_t, web_t, litew_t, liten1_t, litenm_t):
    print(f"{f:<48} {a:>7.2f} {b:>7.2f} {w_:>7.2f} {lw:>7.2f} {l1:>7.2f} {lm:>7.2f}")

# Wins under apples-to-apples (excluding hardware-caveat IOS rows)
print(f"\n=== Best M4 series per file (Total) ===")
ranks = {"web-ifc":0, "ifc-lite WASM":0, "ifc-lite native 1c":0, "ifc-lite native max":0}
for f, w_, lw, l1, lm in zip(files, web_t, litew_t, liten1_t, litenm_t):
    vals = [("web-ifc", w_), ("ifc-lite WASM", lw), ("ifc-lite native 1c", l1), ("ifc-lite native max", lm)]
    vals.sort(key=lambda kv: kv[1])
    ranks[vals[0][0]] += 1
print("  fastest series wins per file:")
for k, v in ranks.items():
    print(f"    {k}: {v}")

# Native multi-thread vs IOS max
print(f"\n=== ifc-lite native max vs IOS max (Total) ===")
n_lite_w = n_ios_w = 0
for f, ios_m_v, lm in zip(files, ios_m_t, litenm_t):
    if lm < ios_m_v: n_lite_w += 1
    else: n_ios_w += 1
print(f"  ifc-lite native max wins: {n_lite_w}/{len(files)}, IOS max wins: {n_ios_w}/{len(files)}")
