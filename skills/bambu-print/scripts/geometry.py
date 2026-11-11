"""Blender-side audit of the exported meshes in their chosen print orientations."""

import json
import math
from pathlib import Path
import sys

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree


def check_bore(tree, bore, low, high):
    x, y = bore["center_xy_mm"]
    diameter = float(bore["diameter_mm"])
    if not all(math.isfinite(v) for v in (x, y, diameter)) or diameter <= 0.1:
        raise ValueError("Invalid bore dimensions")
    start = Vector((x, y, low - 1))
    if tree.ray_cast(start, Vector((0, 0, 1)), high - low + 2)[0] is not None:
        raise ValueError("Bore centreline is obstructed")
    distances = []
    for f in (0.05, 0.5, 0.95):
        origin = Vector((x, y, low + (high - low) * f))
        for i in range(16):
            # Offset rays from STL facet seams and vertices.
            a = math.tau * (i + 0.137) / 16
            distance = tree.ray_cast(origin, Vector((math.cos(a), math.sin(a), 0)))[3]
            if distance is None or abs(2 * distance - diameter) > 0.05:
                raise ValueError(f"Bore wall mismatch at height fraction {f}, angle {a:.3f}, radius {distance}")
            distances.append(2 * distance)
    return {"center_xy_mm": [x, y], "measured_diameter_range_mm": [min(distances), max(distances)]}


def inspect(file, spec):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.wm.stl_import(filepath=str(file))
    obj, = bpy.context.selected_objects
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.transform(obj.matrix_world)
    bm.normal_update()
    if not bm.faces or any(not e.is_manifold or not e.is_contiguous for e in bm.edges):
        raise ValueError("Open or inconsistently wound mesh")
    if any(face.calc_area() <= 0 for face in bm.faces) or bm.calc_volume(signed=True) <= 0:
        raise ValueError("Degenerate face or inward normals")
    first = next(iter(bm.verts))
    seen, todo = {first}, [first]
    while todo:
        v = todo.pop()
        for edge in v.link_edges:
            other = edge.other_vert(v)
            if other not in seen:
                todo.append(other)
                seen.add(other)
    if len(seen) != len(bm.verts):
        raise ValueError("Multiple shells in one part; inspect internal or disconnected surfaces")
    bm.faces.ensure_lookup_table()
    tree = BVHTree.FromBMesh(bm)
    for left, right in tree.overlap(tree):
        if left < right and set(bm.faces[left].verts).isdisjoint(bm.faces[right].verts):
            raise ValueError("Intersecting non-adjacent triangles")
    lo = [min(v.co[i] for v in bm.verts) for i in range(3)]
    hi = [max(v.co[i] for v in bm.verts) for i in range(3)]
    size = [b - a for a, b in zip(lo, hi)]
    if any(not math.isfinite(a) or not math.isfinite(b) or a <= 0 or abs(a - b) > 0.05
           for a, b in zip(spec["size_mm"], size, strict=True)):
        raise ValueError(f"Expected {spec['size_mm']} mm, measured {size}")
    contact = sum(f.calc_area() for f in bm.faces if all(abs(v.co.z) < 0.001 for v in f.verts))
    if abs(lo[2]) > 0.001 or not contact:
        raise ValueError("Part needs a flat contact face at Z=0 in the chosen print orientation")
    steep = sum(f.calc_area() for f in bm.faces if f.normal.z < -0.7071
                and max(v.co.z for v in f.verts) > 0.001)
    result = {"part": file.name, "size_mm": size, "triangles": len(bm.faces),
              "volume_mm3": bm.calc_volume(signed=True), "bed_contact_mm2": contact,
              "downward_area_over_45deg_mm2": steep,
              "vertical_bores": [check_bore(tree, b, lo[2], hi[2]) for b in spec.get("vertical_bores", [])]}
    bm.free()
    return result


if __name__ == "__main__":
    job, out = map(Path, sys.argv[sys.argv.index("--") + 1:])
    details = [inspect(job.parent / s["stl"], s) for s in json.loads(job.read_text("utf-8"))["parts"]]
    out.write_text(json.dumps(details, indent=2), encoding="utf-8")
