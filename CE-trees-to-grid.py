\
bl_info = {
    "name": "Tree Grid Importer",
    "author": "Assistant",
    "version": (1, 5, 0),
    "blender": (4, 5, 0),
    "location": "View3D > Sidebar > Trees",
    "description": "Import tree GLBs into a grid with configurable labels (model, style, both), text size/offset/color. Centers models in cells and rests them on the grid.",
    "category": "Import-Export",
}

import bpy
import os
import re
from mathutils import Vector

ROOT_PATH = r"E:\Work\City Engine\Default Workspace\Adelaide\assets\Trees"
STYLES = ["Schematic","LowPoly","Fan","Realistic"]
STYLE_REGEX = re.compile(r"_LOD\d+", re.IGNORECASE)

# ------------ Helpers ------------
def grid_cell_center(x, y, s):
    return Vector((x*s + s/2, -y*s - s/2, 0))

def make_checkerboard(cols, rows, spacing):
    mat_light = bpy.data.materials.get("CheckerLight")
    if not mat_light:
        mat_light = bpy.data.materials.new("CheckerLight")
    mat_light.diffuse_color = (0.8,0.8,0.8,1)
    mat_dark = bpy.data.materials.get("CheckerDark")
    if not mat_dark:
        mat_dark = bpy.data.materials.new("CheckerDark")
    mat_dark.diffuse_color = (0.3,0.3,0.3,1)
    for cx in range(cols):
        for cy in range(rows):
            bpy.ops.mesh.primitive_plane_add(size=spacing, location=(cx*spacing+spacing/2, -cy*spacing-spacing/2, 0))
            plane = bpy.context.active_object
            plane.name = f"Cell_{cx}_{cy}"
            plane.data.materials.append(mat_light if (cx+cy)%2==0 else mat_dark)

def spaced_name(n: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])"," ", n)

def get_or_make_text_material(color, name="TreeTextMaterial"):
    m = bpy.data.materials.get(name)
    if not m:
        m = bpy.data.materials.new(name)
    if len(color) == 3:
        color = (color[0], color[1], color[2], 1.0)
    m.diffuse_color = color
    return m

def add_text(loc, text, size, mat):
    bpy.ops.object.text_add(location=loc)
    t = bpy.context.active_object
    t.data.body = text
    t.data.extrude = 0.05
    t.data.size = size
    t.name = f"Label_{text}"
    if t.data.materials:
        t.data.materials[0] = mat
    else:
        t.data.materials.append(mat)
    return t

def compute_world_bbox(objs):
    coords = []
    for obj in objs:
        try:
            bb = obj.bound_box
        except:
            bb = None
        if bb is None:
            continue
        for v in bb:
            coords.append(obj.matrix_world @ Vector(v))
    if not coords:
        return None, None, None
    min_corner = Vector((min(c.x for c in coords), min(c.y for c in coords), min(c.z for c in coords)))
    max_corner = Vector((max(c.x for c in coords), max(c.y for c in coords), max(c.z for c in coords)))
    center = (min_corner + max_corner) / 2.0
    return min_corner, max_corner, center

def align_group_with_empty(imported_objs, cell_x, cell_y, spacing, group_name, collection):
    if not imported_objs:
        return None
    empty = bpy.data.objects.new(group_name, None)
    collection.objects.link(empty)
    for obj in imported_objs:
        obj.parent = empty
    min_corner, max_corner, center = compute_world_bbox(imported_objs)
    if center is None:
        return empty
    target = grid_cell_center(cell_x, cell_y, spacing)
    offset = Vector((target.x - center.x, target.y - center.y, -min_corner.z))
    empty.location += offset
    return empty

def add_text_above_group(objs, text, size, offset, mat):
    min_corner, max_corner, center = compute_world_bbox(objs)
    if center is None:
        center = Vector((0,0,0))
        max_corner = Vector((0,0,0))
    loc = Vector((center.x, center.y, max_corner.z + offset))
    return add_text(loc, text, size, mat)

# ------------ Properties ------------
class TreeGridProperties(bpy.types.PropertyGroup):
    spacing: bpy.props.FloatProperty(name="Grid Spacing", default=50.0, min=10.0, soft_max=200.0)
    text_size: bpy.props.FloatProperty(name="Text Size", default=1.5, min=0.5, soft_max=10.0)
    text_offset: bpy.props.FloatProperty(name="Text Offset", default=1.0, min=0.1, soft_max=10.0)
    text_color: bpy.props.FloatVectorProperty(name="Text Color", subtype='COLOR', size=4, min=0.0, max=1.0, default=(0,0,0,1))
    label_mode: bpy.props.EnumProperty(name="Label Mode",
        items=[('MODEL',"Model Labels",""),('FOLDER',"Folder Labels",""),('BOTH',"Both","")],
        default='MODEL')

# ------------ Operators ------------
class TREE_OT_import_grid(bpy.types.Operator):
    bl_idname = "tree.import_grid"
    bl_label = "Import Tree Grid"
    bl_options = {'REGISTER','UNDO'}
    def execute(self, ctx):
        p = ctx.scene.tree_grid_props
        s, ts, to, mode = p.spacing, p.text_size, p.text_offset, p.label_mode
        tmat = get_or_make_text_material(p.text_color, "TreeTextMaterial")

        # Gather files per style
        allf = {}
        for style in STYLES:
            folder = os.path.join(ROOT_PATH, style)
            if os.path.isdir(folder):
                allf[style] = [os.path.join(folder, f) for f in sorted(os.listdir(folder)) if f.lower().endswith(".glb")]

        if not allf:
            self.report({'WARNING'}, "No style folders found.")
            return {'CANCELLED'}

        cols = len(STYLES)
        extra_row = 1 if mode in ['FOLDER','BOTH'] else 0
        rows = max((len(files) for files in allf.values()), default=0) + extra_row
        make_checkerboard(cols, rows, s)

        total = 0
        for col, style in enumerate(STYLES):
            files = allf.get(style, [])
            coll = bpy.data.collections.new(style)
            ctx.scene.collection.children.link(coll)

            for r, fpath in enumerate(files):
                try:
                    bpy.ops.import_scene.gltf(filepath=fpath)
                    imported = list(ctx.selected_objects)

                    for o in imported:
                        for c in list(o.users_collection):
                            if c != coll:
                                c.objects.unlink(o)
                        if o.name not in coll.objects:
                            coll.objects.link(o)

                    align_group_with_empty(imported, col, r, s, os.path.basename(fpath), coll)

                    if imported and mode in ['MODEL','BOTH']:
                        name = os.path.splitext(os.path.basename(fpath))[0]
                        add_text_above_group(imported, spaced_name(name), ts, to, tmat)

                    total += 1
                except Exception as e:
                    self.report({'ERROR'}, f"Failed {fpath}: {e}")

            if mode in ['FOLDER','BOTH']:
                loc = grid_cell_center(col, len(files), s); loc.z = to
                add_text(loc, spaced_name(style), ts, tmat)

        self.report({'INFO'}, f"Imported {total} models.")
        return {'FINISHED'}

class TREE_OT_uninstall(bpy.types.Operator):
    bl_idname = "tree.uninstall"
    bl_label = "Uninstall Tree Grid Importer"
    bl_options = {'REGISTER'}
    def execute(self, ctx):
        fp = __file__
        try:
            unregister()
        except Exception:
            pass
        try:
            os.remove(fp)
            self.report({'INFO'}, f"Removed: {fp}")
        except Exception as e:
            self.report({'ERROR'}, f"Could not delete: {e}")
        return {'FINISHED'}

# ------------ Panel ------------
class VIEW3D_PT_tree_panel(bpy.types.Panel):
    bl_label = "Tree Tools"
    bl_idname = "VIEW3D_PT_tree_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Trees'
    def draw(self, ctx):
        p = ctx.scene.tree_grid_props
        l = self.layout
        l.prop(p, "spacing")
        l.prop(p, "text_size")
        l.prop(p, "text_offset")
        l.prop(p, "text_color")
        l.prop(p, "label_mode")
        l.operator(TREE_OT_import_grid.bl_idname, icon="IMPORT")
        l.separator()
        l.operator(TREE_OT_uninstall.bl_idname, icon="TRASH")

# ------------ Registration ------------
classes = (
    TreeGridProperties,
    TREE_OT_import_grid,
    TREE_OT_uninstall,
    VIEW3D_PT_tree_panel,
)

def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.tree_grid_props = bpy.props.PointerProperty(type=TreeGridProperties)
    print("✅ Tree Grid Importer loaded.")

def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
    if hasattr(bpy.types, "Scene") and hasattr(bpy.types.Scene, "tree_grid_props"):
        del bpy.types.Scene.tree_grid_props

if __name__ == "__main__":
    register()
