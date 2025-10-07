import bpy
import mathutils
import random
import bmesh

# ------------------------------
# ADDON METADATA
# ------------------------------
bl_info = {
    "name": "Edit Large LOD Model - Final Solution",
    "description": "Tools for isolating and editing large LOD models far from origin",
    "author": "Josh & ChatGPT",
    "version": (1, 5),
    "blender": (3, 0, 0),
    "location": "3D Viewport Sidebar > Edit Large LOD Model",
    "doc_url": "",
    "tracker_url": "",
    "category": "Object",
}

# ------------------------------
# GLOBAL STORAGE
# ------------------------------
original_positions_store = []
original_geometry_store = {}
selected_reference_name = None
scene_offset_vector = mathutils.Vector((0, 0, 0))

# ------------------------------
# OPERATORS
# ------------------------------

class OBJECT_OT_SelectRandomModel(bpy.types.Operator):
    """Randomly select one mesh object to serve as the reference point for the new scene origin."""
    bl_idname = "object.select_random_model_final"
    bl_label = "Select Random Model"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        mesh_objects = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
        if not mesh_objects:
            self.report({'WARNING'}, "No mesh objects in scene.")
            return {'CANCELLED'}

        ref_obj = random.choice(mesh_objects)
        bpy.ops.object.select_all(action='DESELECT')
        ref_obj.select_set(True)
        bpy.context.view_layer.objects.active = ref_obj

        global selected_reference_name
        selected_reference_name = ref_obj.name

        self.report({'INFO'}, f"Selected random model: {ref_obj.name}")
        return {'FINISHED'}


class OBJECT_OT_MoveReferenceToOrigin(bpy.types.Operator):
    """Moves the selected reference model's origin to the scene center and repositions all other meshes relative to it."""
    bl_idname = "object.move_reference_to_origin_final"
    bl_label = "Move Reference to Origin"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        global original_positions_store, original_geometry_store, selected_reference_name

        if not selected_reference_name:
            self.report({'WARNING'}, "No reference object selected. Run 'Select Random Model' first.")
            return {'CANCELLED'}

        ref_obj = bpy.data.objects.get(selected_reference_name)
        if not ref_obj:
            self.report({'WARNING'}, f"Reference object '{selected_reference_name}' not found.")
            return {'CANCELLED'}

        # Clear previous stored data
        original_positions_store.clear()
        original_geometry_store.clear()

        # Store original positions of all mesh objects
        for obj in bpy.context.scene.objects:
            if obj.type == 'MESH':
                original_positions_store.append((obj.name, obj.location.copy()))

        # Store original geometry data for the reference object
        if ref_obj.data:
            original_mesh = ref_obj.data.copy()
            original_geometry_store[ref_obj.name] = original_mesh

        # Calculate geometry center of the reference object
        bpy.context.view_layer.objects.active = ref_obj
        bpy.ops.object.select_all(action='DESELECT')
        ref_obj.select_set(True)

        bm = bmesh.new()
        bm.from_mesh(ref_obj.data)
        if bm.verts:
            geometry_center = sum((v.co for v in bm.verts), mathutils.Vector()) / len(bm.verts)
        else:
            geometry_center = mathutils.Vector((0, 0, 0))
        geometry_center_world = ref_obj.matrix_world @ geometry_center

        for v in bm.verts:
            v.co -= geometry_center
        bm.to_mesh(ref_obj.data)
        bm.free()
        ref_obj.data.update()
        ref_obj.location = mathutils.Vector((0, 0, 0))

        offset_vector = -geometry_center_world
        global scene_offset_vector
        scene_offset_vector = offset_vector

        for obj in bpy.context.scene.objects:
            if obj.type == 'MESH' and obj != ref_obj:
                obj.location += offset_vector

        self.report({'INFO'}, f"Centered {ref_obj.name} at origin and repositioned {len([o for o in bpy.context.scene.objects if o.type == 'MESH'])} mesh objects.")
        return {'FINISHED'}


class OBJECT_OT_RegisterNewMeshes(bpy.types.Operator):
    """Registers any new mesh objects that have been added to the scene after moving the scene to the origin."""
    bl_idname = "object.register_new_meshes_final"
    bl_label = "Register New Meshes"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        global original_positions_store, scene_offset_vector

        if not original_positions_store:
            self.report({'WARNING'}, "No active session. Move reference to origin first.")
            return {'CANCELLED'}

        stored_names = {name for name, _ in original_positions_store}
        new_meshes = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH' and obj.name not in stored_names]

        if not new_meshes:
            self.report({'INFO'}, "No new mesh objects found.")
            return {'FINISHED'}

        new_count = 0
        for obj in new_meshes:
            original_location = obj.location.copy() - scene_offset_vector
            original_positions_store.append((obj.name, original_location))
            new_count += 1
            self.report({'INFO'}, f"Registered new mesh {obj.name} for restore.")

        self.report({'INFO'}, f"Registered {new_count} new mesh objects for restore.")
        return {'FINISHED'}


class OBJECT_OT_RestoreOriginalPosition(bpy.types.Operator):
    """Restores all mesh objects to their original positions and geometry."""
    bl_idname = "object.restore_original_position_final"
    bl_label = "Restore Original Position"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        global original_positions_store, original_geometry_store

        if not original_positions_store:
            self.report({'WARNING'}, "No stored positions found. Move reference to origin first.")
            return {'CANCELLED'}

        restored_count = 0
        for name, orig_loc in original_positions_store:
            obj = bpy.data.objects.get(name)
            if obj:
                obj.location = orig_loc
                restored_count += 1

        for obj_name, original_mesh in original_geometry_store.items():
            obj = bpy.data.objects.get(obj_name)
            if obj and obj.data:
                old_mesh = obj.data
                obj.data = original_mesh
                bpy.data.meshes.remove(old_mesh)

        original_positions_store.clear()
        original_geometry_store.clear()
        global scene_offset_vector
        scene_offset_vector = mathutils.Vector((0, 0, 0))

        self.report({'INFO'}, f"Restored {restored_count} objects to original positions and geometry.")
        return {'FINISHED'}


class OBJECT_OT_ClearSession(bpy.types.Operator):
    """Clears all stored data for the LOD editing session (safe)."""
    bl_idname = "object.clear_lod_session_final"
    bl_label = "Clear Session Data"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        global original_positions_store, original_geometry_store, scene_offset_vector
        original_positions_store.clear()
        original_geometry_store.clear()
        scene_offset_vector = mathutils.Vector((0, 0, 0))
        self.report({'INFO'}, "Cleared all stored LOD model data.")
        return {'FINISHED'}


# ------------------------------
# PANEL
# ------------------------------

class VIEW3D_PT_EditLargeLODModelPanel(bpy.types.Panel):
    """Panel in 3D View sidebar"""
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Edit Large LOD Model'
    bl_label = "Edit Large LOD Model"

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def draw(self, context):
        layout = self.layout
        global selected_reference_name

        if selected_reference_name:
            box = layout.box()
            box.label(text=f"Reference: {selected_reference_name}", icon='OBJECT_DATA')

        layout.operator("object.select_random_model_final")
        layout.operator("object.move_reference_to_origin_final")

        if original_positions_store:
            layout.separator()
            box = layout.box()
            box.label(text="After Adding New Meshes:", icon='INFO')
            box.operator("object.register_new_meshes_final")

        layout.operator("object.restore_original_position_final")
        layout.separator()
        layout.operator("object.clear_lod_session_final")


# ------------------------------
# REGISTER / UNREGISTER
# ------------------------------

classes = (
    OBJECT_OT_SelectRandomModel,
    OBJECT_OT_MoveReferenceToOrigin,
    OBJECT_OT_RegisterNewMeshes,
    OBJECT_OT_RestoreOriginalPosition,
    OBJECT_OT_ClearSession,
    VIEW3D_PT_EditLargeLODModelPanel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
