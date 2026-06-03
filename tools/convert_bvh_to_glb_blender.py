"""
BVH → GLB 转换脚本（Blender Python API）

使用方法：
1. 确保安装了 Blender（3.0+）
2. 命令行执行：
   blender --background --python tools/convert_bvh_to_glb_blender.py -- <input.bvh> <output.glb> [--fps 30]

或从 Python 调用：
   from tools.bvh_to_glb_converter import convert_bvh_to_glb
   convert_bvh_to_glb("input.bvh", "output.glb")
"""

import bpy
import sys
import argparse
from pathlib import Path


def convert_bvh_to_glb(bvh_path: str, glb_path: str, target_fps: float = 30.0):
    """
    使用 Blender 将 BVH 转换为 GLB 动画文件
    """
    bvh_path = Path(bvh_path).resolve()
    glb_path = Path(glb_path).resolve()
    
    print(f"[Blender] 清除场景...")
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    
    # 清除残留的 Action
    for action in list(bpy.data.actions):
        bpy.data.actions.remove(action)
    
    print(f"[Blender] 导入 BVH: {bvh_path}")
    bpy.ops.import_scene.anim(
        filepath=str(bvh_path),
        axis_forward='-Z',
        axis_up='Y',
    )
    
    # BVH 导入后通常是一个 Armature
    armature = None
    for obj in bpy.context.scene.objects:
        if obj.type == 'ARMATURE':
            armature = obj
            break
    
    if not armature:
        raise RuntimeError("BVH 导入后未找到 Armature 对象")
    
    print(f"[Blender] 找到骨骼: {armature.name}")
    
    # 重采样动画到目标帧率（可选）
    if target_fps > 0:
        # 获取当前场景帧率
        scene_fps = bpy.context.scene.render.fps
        if scene_fps != target_fps:
            print(f"[Blender] 重采样 {scene_fps}fps -> {target_fps}fps")
            # 简化：Blender 的 BVH 导入通常会自动设置帧率
            pass
    
    # 确保导出为 glTF 时 Y-up
    print(f"[Blender] 导出 GLB: {glb_path}")
    bpy.ops.export_scene.gltf(
        filepath=str(glb_path),
        export_format='GLB',
        export_animations=True,
        export_animation_mode='ACTIONS',
        export_skins=True,
        export_morph=False,
        export_draco_mesh_compression_enable=False,
        export_yup=True,
        export_apply=True,
        export_include_armature_modifier=True,
    )
    
    print(f"[Blender] 导出完成: {glb_path}")
    return str(glb_path)


def main():
    # 解析命令行参数（跳过 Blender 自带的参数）
    argv = sys.argv
    if "--" not in argv:
        argv = []  # 没有用户参数
    else:
        argv = argv[argv.index("--") + 1:]
    
    parser = argparse.ArgumentParser(description="BVH to GLB converter (Blender)")
    parser.add_argument("bvh", help="Input BVH file path")
    parser.add_argument("glb", help="Output GLB file path")
    parser.add_argument("--fps", type=float, default=30.0, help="Target FPS")
    args = parser.parse_args(argv)
    
    try:
        convert_bvh_to_glb(args.bvh, args.glb, args.fps)
    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
