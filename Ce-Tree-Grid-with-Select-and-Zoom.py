\
bl_info = {
    "name": "CE Tree Grid",
    "author": "Assistant",
    "version": (4, 2, 2),
    "blender": (4, 5, 0),
    "location": "View3D > Sidebar > CE Tools",
    "description": "Imports trees into a CE-aligned grid with Empties, labels, configurable folder path, validation, and a Tree Selector that frames the entire collection in the 3D view.",
    "category": "Import-Export",
}

import bpy
import os
import re
import sys
from collections import Counter
from mathutils import Vector

# --- Constants & Regex ---
STYLE_ORDER = ["Schematic", "LowPoly", "Fan", "Realistic"]
STYLE_REGEX = re.compile(r"(schematic|lowpoly|fan|realistic)", re.IGNORECASE)
LOD_REGEX = re.compile(r"_LOD\d+", re.IGNORECASE)


# --- Helpers ---
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
            bpy.ops.mesh.primitive_plane_add(
                size=spacing,
                location=(x * spacing + spacing / 2, -y * spacing - spacing / 2, 0),
            )
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
    return Counter(cleaned).most_common(1)[0][0]


def spaced_name(name):
    """Insert spaces before capital letters, except the first letter."""
    return re.sub(r"(?<!^)(?=[A-Z])", " ", name)


def align_group_with_empty(imported_objs, cell_x, cell_y, spacing, style_name, tree_collection):
    if not imported_objs:
        return
    style_empty = bpy.data.objects.new(style_name, None)  # an Empty
    tree_collection.objects.link(style_empty)
    for obj in imported_objs:
        obj.parent = style_empty

    # Compute group AABB in world
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


# --- Text / Labels ---
def get_text_material():
    """Return material for text using scene-defined color, create if missing."""
    mat_name = "TreeTextMaterial"
    mat = bpy.data.materials.get(mat_name)
    if not mat:
        mat = bpy.data.materials.new(mat_name)
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
    txt_obj.rotation_euler[2] = -0.785398  # -45°

    # Assign material
    mat = get_text_material()
    if txt_obj.data.materials:
        txt_obj.data.materials[0] = mat
    else:
        txt_obj.data.materials.append(mat)


def update_existing_text_colors(context):
    """Update all existing 3D text labels to match the current color picker value."""
    mat = get_text_material()
    for obj in bpy.data.objects:
        if obj.type == 'FONT' and obj.name.startswith("Label_"):
            if obj.data.materials:
                obj.data.materials[0] = mat
            else:
                obj.data.materials.append(mat)


# --- Detect CE Tree collections ---
def is_ce_tree_collection(coll: bpy.types.Collection) -> bool:
    # Prefer explicit tag, fallback to heuristic of having a Label_ FONT object inside
    if coll.get("ce_tree_grid", False):
        return True
    for obj in coll.objects:
        if obj.type == 'FONT' and obj.name.startswith("Label_"):
            return True
    return False


def get_all_objects_in_collection(coll: bpy.types.Collection, recursive=True):
    objs = list(coll.objects)
    if recursive:
        for child in coll.children:
            objs.extend(get_all_objects_in_collection(child, True))
    return objs


def focus_view_on_collection(coll: bpy.types.Collection):
    objs = get_all_objects_in_collection(coll, recursive=True)
    if not objs:
        return

    # Deselect all, then select everything in the collection
    try:
        bpy.ops.object.select_all(action='DESELECT')
    except Exception:
        pass

    # Choose a decent active object (prefer non-empty)
    active = None
    for obj in objs:
        try:
            obj.select_set(True)
        except Exception:
            pass
        if not active and obj.type != 'EMPTY':
            active = obj
    if not active:
        active = objs[0]

    bpy.context.view_layer.objects.active = active

    # Find a 3D View area and frame selected
    win = bpy.context.window
    if not win:
        return
    screen = win.screen
    for area in screen.areas:
        if area.type == 'VIEW_3D':
            space = area.spaces.active if area.spaces else None
            for region in area.regions:
                if region.type == 'WINDOW':
                    try:
                        with bpy.context.temp_override(area=area, region=region, space_data=space, active_object=active, selected_objects=objs):
                            bpy.ops.view3d.view_selected(use_all_regions=False)
                    except Exception:
                        pass
                    return


# --- Properties ---
def enum_tree_items(self, context):
    items = []
    # Scan all collections and include only ones recognized as CE Tree collections
    for coll in bpy.data.collections:
        if is_ce_tree_collection(coll):
            items.append((coll.name, coll.name, "CE Tree Grid collection"))
    if not items:
        items = [("none","<no CE trees found>","")]
    return items


def on_tree_selected(self, context):
    name = self.tree_selector
    if not name or name == "none":
        return
    coll = bpy.data.collections.get(name)
    if not coll:
        return
    focus_view_on_collection(coll)


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
    tree_selector: bpy.props.EnumProperty(
        name="Jump to Tree",
        description="Frames the selected CE Tree Grid collection in the 3D view",
        items=enum_tree_items,
        update=on_tree_selected
    )


# --- Operators ---
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

        # Build dictionary of files per index across styles
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
        rows = len(styles) + 3  # 4 style rows + 1 label row + 2 buffer rows
        make_checkerboard(cols, rows, spacing)

        # Import each tree across style rows into its own collection
        for tree_index, style_dict in tree_files.items():
            col = tree_index
            base_name = clean_base_name(list(style_dict.values()))
            tree_collection = bpy.data.collections.new(base_name)
            tree_collection["ce_tree_grid"] = True  # tag for detection
            context.scene.collection.children.link(tree_collection)

            for row_index, style in enumerate(styles):
                if style not in style_dict:
                    continue
                filepath = style_dict[style]
                try:
                    bpy.ops.import_scene.gltf(filepath=filepath)
                    imported_objs = list(context.selected_objects)

                    # Relink to our tree collection only
                    for obj in imported_objs:
                        for c in obj.users_collection:
                            if c != tree_collection:
                                c.objects.unlink(obj)
                        tree_collection.objects.link(obj)

                    align_group_with_empty(imported_objs, col, row_index, spacing, style, tree_collection)
                except Exception as e:
                    self.report({'ERROR'}, f"Failed {filepath}: {e}")

            # Add spaced name label on the 5th row (index len(styles))
            add_text_to_cell(spaced_name(base_name), col, len(styles), spacing)

        return {'FINISHED'}


class CE_OT_uninstall(bpy.types.Operator):
    bl_idname = "ce.uninstall"
    bl_label = "Uninstall CE Tree Grid"
    bl_options = {'REGISTER'}

    def execute(self, context):
        addon_name = __name__
        addon_file = os.path.realpath(__file__)
        # Attempt to cleanly unregister and remove the file
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


# --- Panel ---
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

        # Help text
        layout.label(text="Expected folder structure under 'assets':")
        layout.label(text="   assets/")
        layout.label(text="   └── Trees/")
        layout.label(text="       ├── Schematic/")
        layout.label(text="       ├── LowPoly/")
        layout.label(text="       ├── Fan/")
        layout.label(text="       └── Realistic/")
        layout.separator()

        # Folder path
        layout.prop(props, "trees_folder")

        # Missing folder warning
        missing = [s for s in STYLE_ORDER if not os.path.exists(os.path.join(root_path, s))]
        if missing:
            col = layout.column()
            col.label(text="⚠ Missing required subfolders:", icon='ERROR')
            for s in missing:
                col.label(text=f"   - {s}")
            col.label(text="Please ensure structure matches above.", icon='INFO')

        layout.separator()

        # Controls
        layout.prop(props, "spacing")
        layout.prop(props, "reverse_rows")
        layout.prop(props, "text_color", text="Text Color")
        layout.operator(CE_OT_import_grid.bl_idname, icon="IMPORT")

        layout.separator()

        # Tree Selector (auto-refresh via dynamic items callback)
        layout.prop(props, "tree_selector", text="Jump to Tree")

        layout.separator()

        layout.operator(CE_OT_uninstall.bl_idname, icon="TRASH")


# --- Registration ---
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
