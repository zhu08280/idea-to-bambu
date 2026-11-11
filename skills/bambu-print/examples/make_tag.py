"""Run inside Blender. Numeric coordinates are millimetres in the exported STL."""

from pathlib import Path
import sys

import bpy

out = Path(sys.argv[sys.argv.index("--") + 1])
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 1.5))
tag = bpy.context.object
tag.name = "Cable tag"
tag.dimensions = (30, 20, 3)
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
edge = tag.modifiers.new("Rounded edges", "BEVEL")
edge.width, edge.segments = 0.8, 6
bpy.ops.object.modifier_apply(modifier=edge.name)

bpy.ops.mesh.primitive_cylinder_add(vertices=96, radius=2.5, depth=6, location=(-10, 0, 1.5))
cutter = bpy.context.object
hole = tag.modifiers.new("Cord hole", "BOOLEAN")
hole.operation, hole.object = "DIFFERENCE", cutter
bpy.context.view_layer.objects.active = tag
bpy.ops.object.modifier_apply(modifier=hole.name)
bpy.data.objects.remove(cutter, do_unlink=True)
tag.select_set(True)
bpy.ops.wm.save_as_mainfile(filepath=str(out / "tag.blend"))
bpy.ops.wm.stl_export(filepath=str(out / "tag.stl"), export_selected_objects=True)
