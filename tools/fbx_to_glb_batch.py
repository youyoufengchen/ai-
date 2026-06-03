"""
FBX 批量转换为 GLB 脚本
使用方法：
1. 打开 Blender
2. 切换到 Scripting 工作区
3. 打开此文件并运行
"""

import bpy
import os
from pathlib import Path

# 配置路径
INPUT_DIR = Path("D:/新建文件夹 (2)/assets/动作库")  # FBX 所在目录
OUTPUT_DIR = INPUT_DIR  # GLB 输出到相同目录

# 遍历所有 FBX 文件
def convert_fbx_to_glb():
    fbx_files = list(INPUT_DIR.rglob("*.fbx"))
    
    print(f"找到 {len(fbx_files)} 个 FBX 文件")
    
    for fbx_path in fbx_files:
        # 构建输出路径（相同目录，改后缀）
        relative_path = fbx_path.relative_to(INPUT_DIR)
        glb_path = OUTPUT_DIR / relative_path.with_suffix('.glb')
        
        print(f"\n转换: {relative_path}")
        
        # 清除当前场景（对象 + 动画 + 孤立数据）
        bpy.ops.object.select_all(action='SELECT')
        bpy.ops.object.delete(use_global=False)
        
        # 关键：清除所有残留的 Action，否则会累积到后续GLB
        for action in list(bpy.data.actions):
            bpy.data.actions.remove(action)
        # 清除孤立数据块
        for armature in list(bpy.data.armatures):
            if armature.users == 0:
                bpy.data.armatures.remove(armature)
        
        # 导入 FBX
        try:
            bpy.ops.import_scene.fbx(
                filepath=str(fbx_path),
                use_anim=True,
                anim_offset=0,
                use_subsurf=False,
                use_custom_props=True
            )
            print(f"  导入成功")
        except Exception as e:
            print(f"  ❌ 导入失败: {e}")
            continue
        
        # 导出 GLB
        try:
            bpy.ops.export_scene.gltf(
                filepath=str(glb_path),
                export_format='GLB',
                export_animations=True,
                export_animation_mode='ACTIONS',
                export_skins=True,
                export_morph=True,
                export_draco_mesh_compression_enable=False,
                export_yup=True,
                export_apply=True
            )
            print(f"  ✅ 导出成功: {glb_path.name}")
        except Exception as e:
            print(f"  ❌ 导出失败: {e}")

# 执行转换
if __name__ == "__main__":
    print("=" * 50)
    print("FBX → GLB 批量转换开始")
    print("=" * 50)
    convert_fbx_to_glb()
    print("\n" + "=" * 50)
    print("转换完成！")
    print("=" * 50)
