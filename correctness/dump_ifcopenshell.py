"""IfcOpenShell per-element world-space mesh dump.

Writes NDJSON, one line per element:
  {"express_id": int, "guid": str, "type": str, "name": str|null,
   "positions": [x,y,z,...], "indices": [a,b,c,...]}

Coordinates are in world (model) space — USE_WORLD_COORDS=True bakes
ObjectPlacement into vertex positions, matching what ifc-lite emits.

Usage: python dump_ifcopenshell.py <model.ifc> <out.ndjson>
"""
import json
import os
import sys
import time

import ifcopenshell
import ifcopenshell.geom

EXCLUDE = ["IfcOpeningElement", "IfcOpeningStandardCase", "IfcSpace", "IfcBuilding", "IfcBuildingStorey"]


def main():
    if len(sys.argv) not in (3, 4):
        print("usage: dump_ifcopenshell.py <model.ifc> <out.ndjson> [origin.txt]", file=sys.stderr)
        sys.exit(2)
    model_path, out_path = sys.argv[1], sys.argv[2]

    # Optional local-frame anchor (georeferenced models). The ifc-lite dumper
    # writes the site translation it subtracted to a `<lite>.origin` sidecar so
    # both engines are compared in one near-origin frame — otherwise IOS's
    # national-grid world coordinates (1e6+) overflow f32 precision on the
    # ifc-lite side and fabricate shape failures. Subtract the SAME anchor here.
    anchor = (0.0, 0.0, 0.0)
    if len(sys.argv) == 4 and os.path.exists(sys.argv[3]):
        with open(sys.argv[3]) as fh:
            parts = fh.read().split()
            if len(parts) >= 3:
                anchor = (float(parts[0]), float(parts[1]), float(parts[2]))
    ax, ay, az = anchor

    t0 = time.perf_counter()
    f = ifcopenshell.open(model_path)
    t_open = time.perf_counter() - t0

    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    settings.set("weld-vertices", True)
    settings.set("apply-default-materials", True)
    # default tolerances; matches "fair" IOS run

    iterator = ifcopenshell.geom.iterator(settings, f, 1, exclude=EXCLUDE)

    t0 = time.perf_counter()
    count = 0
    skipped = 0
    with open(out_path, "w") as out:
        if iterator.initialize():
            while True:
                shape = iterator.get()
                eid = shape.id
                ent = f.by_id(eid)
                geo = shape.geometry
                verts = list(geo.verts)         # flat [x,y,z,...]
                faces = list(geo.faces)         # flat [i,j,k,...]
                if not verts or not faces:
                    skipped += 1
                    if not iterator.next():
                        break
                    continue
                if ax or ay or az:
                    verts = [
                        v - (ax, ay, az)[i % 3] for i, v in enumerate(verts)
                    ]
                rec = {
                    "express_id": eid,
                    "guid": getattr(shape, "guid", None) or getattr(ent, "GlobalId", None),
                    "type": ent.is_a(),
                    "name": getattr(ent, "Name", None),
                    "positions": verts,
                    "indices": faces,
                }
                out.write(json.dumps(rec, separators=(",", ":")) + "\n")
                count += 1
                if not iterator.next():
                    break
    t_iter = time.perf_counter() - t0

    print(f"ios dump: {count} elements ({skipped} empty), open={t_open:.2f}s iter={t_iter:.2f}s -> {out_path}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
