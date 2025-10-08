bl_info = {
    "name": "CE Tree Grid",
    "author": "Assistant",
    "version": (4, 1, 2),
    "blender": (4, 5, 0),
    "location": "View3D > Sidebar > CE Tools",
    "description": "Imports trees into a CE-aligned grid with Empties, labels, configurable folder path, and validation.",
    "category": "Import-Export",
}

import bpy
import os
import re
from mathutils import Vector

STYLE_ORDER = ["Schematic", "LowPoly", "Fan", "Realistic"]
STYLE_REGEX = re.compile(r"(schematic|lowpoly|fan|realistic)", re.IGNORECASE)
LOD_REGEX = re.compile(r"_LOD\d+", re.IGNORECASE)

def grid_cell_center(cell_x, cell_y, spacing):
    return Vector((cell_x * spacing + spacing / 2, -cell_y * spacing - spacing / 2, 0))

def make_checkerboard(cols, rows, spacing):
    mat_light = bpy.data.materials.get("CheckerLight")
    mat_dark = bpy.data.materials.get("CheckerDark")
    if not mat_light:
        mat_light = bpy.data.materials.new("CheckerLight")
        mat_light.diffuse_color = (0.8, 0.8, 0.8, 1)
    if not mat_dark:
        mat_dark = bpy.data.materials.new("CheckerDark")
        mat_dark.diffuse_color = (0.3, 0.3, 0.3, 1)
    for x in range(cols):
        for y in range(rows):
            bpy.ops.mesh.primitive_plane_add(size=spacing, location=(x * spacing + spacing / 2, -y * spacing - spacing / 2, 0))
            plane = bpy.context.active_object
            plane.name = f"Cell_{x}_{y}"
            plane.data.materials.append(mat_light if (x + y) % 2 == 0 else mat_dark)

def clean_base_name(filenames):
    cleaned = []
    for fn in filenames:
        name = os.path.splitext(os.path.basename(fn))[0]
        name = STYLE_REGEX.sub("", name)
        name = LOD_REGEX.sub("", name)
        name = re.sub(r"[_\-\s]+", "", name)
        cleaned.append(name)
    if not cleaned:
        return "UnknownTree"
    from collections import Counter
    return Counter(cleaned).most_common(1)[0][0]

def spaced_name(name):
    return re.sub(r"(?<!^)(?=[A-Z])", " ", name)

def align_group_with_empty(imported_objs, cell_x, cell_y, spacing, style_name, tree_collection):
    if not imported_objs:
        return
    style_empty = bpy.data.objects.new(style_name, None)
    tree_collection.objects.link(style_empty)
    for obj in imported_objs:
        obj.parent = style_empty
    all_coords = []
    for obj in imported_objs:
        for v in obj.bound_box:
            all_coords.append(obj.matrix_world @ Vector(v))
    if all_coords:
        min_corner = Vector((min(v.x for v in all_coords),
                             min(v.y for v in all_coords),
                             min(v.z for v in all_coords)))
        max_corner = Vector((max(v.x for v in all_coords),
                             max(v.y for v in all_coords),
                             max(v.z for v in all_coords)))
        center = (min_corner + max_corner) / 2.0
        target = grid_cell_center(cell_x, cell_y, spacing)
        offset = Vector((target.x - center.x, target.y - center.y, -min_corner.z))
        style_empty.location += offset

def get_text_material():
    mat_name = "TreeTextMaterial"
    mat = bpy.data.materials.get(mat_name)
    if not mat:
        mat = bpy.data.materials.new("TreeTextMaterial")
    scene = bpy.context.scene
    color = (0, 0, 0, 1)
    if hasattr(scene, "ce_tree_props"):
        color = (*scene.ce_tree_props.text_color, 1)
    mat.diffuse_color = color
    return mat

def add_text_to_cell(text, cell_x, cell_y, spacing):
    bpy.ops.object.text_add(location=grid_cell_center(cell_x, cell_y, spacing))
    txt_obj = bpy.context.active_object
    txt_obj.data.body = text
    txt_obj.name = f"Label_{text}"
    txt_obj.data.extrude = 0.05
    txt_obj.data.size = spacing / 5
    txt_obj.location.z = 1.0
    txt_obj.rotation_euler[2] = -0.785398
    mat = get_text_material()
    if txt_obj.data.materials:
        txt_obj.data.materials[0] = mat
    else:
        txt_obj.data.materials.append(mat)

def update_existing_text_colors(context):
    mat = get_text_material()
    for obj in bpy.data.objects:
        if obj.type == "FONT" and obj.name.startswith("Label_"):
            if obj.data.materials:
                obj.data.materials[0] = mat
            else:
                obj.data.materials.append(mat)

class CETreeProperties(bpy.types.PropertyGroup):
    trees_folder: bpy.props.StringProperty(
        name="Trees Folder Path",
        description="Path to folder containing subfolders: Schematic, LowPoly, Fan, Realistic.",
        subtype='DIR_PATH',
        default=r"E:\Work\City Engine\Default Workspace\Adelaide\assets\Trees"
    )
    spacing: bpy.props.FloatProperty(
        name="Grid Spacing",
        description="Distance between grid cells",
        default=50.0,
        min=10.0,
        soft_max=200.0
    )
    reverse_rows: bpy.props.BoolProperty(
        name="Reverse Row Order",
        description="Reverse the order of style rows",
        default=False
    )
    text_color: bpy.props.FloatVectorProperty(
        name="Text Color",
        description="Color for label text",
        subtype='COLOR',
        default=(0.0, 0.0, 0.0),
        min=0.0,
        max=1.0,
        update=lambda self, context: update_existing_text_colors(context)
    )

class CE_OT_import_grid(bpy.types.Operator):
    bl_idname = "ce.import_grid"
    bl_label = "Import CE Tree Grid"
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        props = context.scene.ce_tree_props
        root_path = bpy.path.abspath(props.trees_folder)
        spacing = props.spacing
        reverse = props.reverse_rows
        styles = list(STYLE_ORDER)
        if reverse:
            styles.reverse()

        tree_files = {}
        for style in STYLE_ORDER:
            folder = os.path.join(root_path, style)
            if not os.path.exists(folder):
                self.report({'WARNING'}, f"Missing style folder: {folder}")
                continue
            files = sorted(f for f in os.listdir(folder) if f.lower().endswith(".glb"))
            for i, f in enumerate(files):
                if i not in tree_files:
                    tree_files[i] = {}
                tree_files[i][style] = os.path.join(folder, f)

        cols = len(tree_files)
        rows = len(styles) + 3
        make_checkerboard(cols, rows, spacing)

        for tree_index, style_dict in tree_files.items():
            col = tree_index
            base_name = clean_base_name(list(style_dict.values()))
            tree_collection = bpy.data.collections.new(base_name)
            context.scene.collection.children.link(tree_collection)
            for row_index, style in enumerate(styles):
                if style not in style_dict:
                    continue
                filepath = style_dict[style]
                try:
                    bpy.ops.import_scene.gltf(filepath=filepath)
                    imported_objs = list(context.selected_objects)
                    for obj in imported_objs:
                        for c in obj.users_collection:
                            if c != tree_collection:
                                c.objects.unlink(obj)
                        tree_collection.objects.link(obj)
                    align_group_with_empty(imported_objs, col, row_index, spacing, style, tree_collection)
                except Exception as e:
                    self.report({'ERROR'}, f"Failed {filepath}: {e}")
            add_text_to_cell(spaced_name(base_name), col, len(styles), spacing)
        return {'FINISHED'}

class CE_OT_uninstall(bpy.types.Operator):
    bl_idname = "ce.uninstall"
    bl_label = "Uninstall CE Tree Grid"
    bl_options = {'REGISTER'}
    def execute(self, context):
        addon_name = __name__
        addon_file = os.path.realpath(__file__)
        try:
            unregister()
        except Exception:
            pass
        if addon_name in sys.modules:
            del sys.modules[addon_name]
        try:
            os.remove(addon_file)
            self.report({'INFO'}, f"Addon removed: {addon_file}")
        except Exception as e:
            self.report({'ERROR'}, f"Could not delete file: {e}")
        return {'FINISHED'}

class VIEW3D_PT_ce_panel(bpy.types.Panel):
    bl_label = "CE Tree Grid"
    bl_idname = "VIEW3D_PT_ce_tree_grid"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "CE Tools"
    def draw(self, context):
        layout = self.layout
        props = context.scene.ce_tree_props
        root_path = bpy.path.abspath(props.trees_folder)
        layout.label(text="Expected folder structure under 'assets':")
        layout.label(text="   assets/")
        layout.label(text="   └── Trees/")
        layout.label(text="       ├── Schematic/")
        layout.label(text="       ├── LowPoly/")
        layout.label(text="       ├── Fan/")
        layout.label(text="       └── Realistic/")
        layout.separator()
        layout.prop(props, "trees_folder")
        missing = [s for s in STYLE_ORDER if not os.path.exists(os.path.join(root_path, s))]
        if missing:
            col = layout.column()
            col.label(text="⚠ Missing required subfolders:", icon='ERROR')
            for s in missing:
                col.label(text=f"   - {s}")
            col.label(text="Please ensure structure matches above.", icon='INFO')
        layout.separator()
        layout.prop(props, "spacing")
        layout.prop(props, "reverse_rows")
        layout.prop(props, "text_color", text="Text Color")
        layout.operator(CE_OT_import_grid.bl_idname, icon="IMPORT")
        layout.separator()
        layout.operator(CE_OT_uninstall.bl_idname, icon="TRASH")

classes = (
    CETreeProperties,
    CE_OT_import_grid,
    CE_OT_uninstall,
    VIEW3D_PT_ce_panel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.ce_tree_props = bpy.props.PointerProperty(type=CETreeProperties)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.ce_tree_props

if __name__ == "__main__":
    register()
