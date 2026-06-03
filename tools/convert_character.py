import bpy
import os
from pathlib import Path

fbx_path = Path("D:/新建文件夹 (2)/assets/角色/X Bot.fbx")
glb_path = Path("D:/新建文件夹 (2)/assets/角色/X Bot.glb")

print(f"导入: {fbx_path}")

bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)

bpy.ops.import_scene.fbx(
    filepath=str(fbx_path),
    use_anim=True,
    anim_offset=0,
    use_subsurf=False,
    use_custom_props=True
)
print("导入成功")

bpy.ops.export_scene.gltf(
    filepath=str(glb_path),
    export_format='GLB',
    export_animations=True,
    export_skins=True,
    export_morph=True,
    export_yup=True,
    export_apply=False
)
print(f"导出成功: {glb_path}")
