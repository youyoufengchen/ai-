"""
生成玻璃展示柜直播间场景 (P1 - 高端展示型)
悬浮玻璃罩 + 发光底座，炫酷科幻感，适合精品展示

使用方法:
    blender --background --python tools/generate_showcase_scene.py
"""

import bpy
import bmesh
import math
import os
import json
from mathutils import Vector

# ═══════════════════════════════════════════════════════════
#  配置参数
# ═══════════════════════════════════════════════════════════
OUTPUT_PATH = "D:/新建文件夹 (2)/assets/scenes/showcase_luxury"
SCENE_ID = "showcase_luxury"
SCENE_NAME = "悬浮展示馆"

# 赛博朋克风格配色
COLORS = {
    'floor': (0.05, 0.05, 0.08),       # 深黑蓝地面
    'floor_glow': (0.1, 0.3, 0.5),    # 地面发光纹路
    'wall': (0.03, 0.03, 0.05),       # 近乎纯黑背景
    'accent': (0, 0.8, 1.0),          # 青色霓虹
    'accent_warm': (1.0, 0.4, 0),     # 橙色点缀
    'glass': (0.9, 0.95, 1.0),        # 冷白玻璃
    'glass_glow': (0, 0.9, 1.0),      # 玻璃发光边
    'pedestal': (0.1, 0.1, 0.12),     # 底座
}

# 8个悬浮展示罩配置 - 双列排布
DISPLAY_PODS = [
    # 左侧列
    {"pos": (-2.5, -2, 0), "height": 1.6, "type": "tall", "sku": "luxury_01", "light": "cyan"},
    {"pos": (-2.5, 0.5, 0), "height": 1.2, "type": "medium", "sku": "luxury_02", "light": "orange"},
    {"pos": (-2.5, 3, 0), "height": 1.4, "type": "tall", "sku": "luxury_03", "light": "cyan"},
    {"pos": (-2.5, 5.5, 0), "height": 1.0, "type": "short", "sku": "luxury_04", "light": "white"},
    # 右侧列
    {"pos": (2.5, -2, 0), "height": 1.6, "type": "tall", "sku": "luxury_05", "light": "orange"},
    {"pos": (2.5, 0.5, 0), "height": 1.2, "type": "medium", "sku": "luxury_06", "light": "cyan"},
    {"pos": (2.5, 3, 0), "height": 1.4, "type": "tall", "sku": "luxury_07", "light": "orange"},
    {"pos": (2.5, 5.5, 0), "height": 1.0, "type": "short", "sku": "luxury_08", "light": "white"},
]

# ═══════════════════════════════════════════════════════════
#  工具函数
# ═══════════════════════════════════════════════════════════

def clear_scene():
    """清空场景"""
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for mesh in bpy.data.meshes:
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    for mat in bpy.data.materials:
        if mat.users == 0:
            bpy.data.materials.remove(mat)

def create_material(name, color, roughness=0.5, metallic=0.0, emit=0.0):
    """创建材质"""
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs['Base Color'].default_value = (*color, 1.0)
        bsdf.inputs['Roughness'].default_value = roughness
        bsdf.inputs['Metallic'].default_value = metallic
        if emit > 0:
            bsdf.inputs['Emission'].default_value = (*color, 1.0)
            bsdf.inputs['Emission Strength'].default_value = emit
    return mat

def create_glass_material(name, tint=(0.9, 0.95, 1.0)):
    """创建有色玻璃材质"""
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs['Base Color'].default_value = (*tint, 0.3)
        bsdf.inputs['Roughness'].default_value = 0.05
        bsdf.inputs['Metallic'].default_value = 0.0
        bsdf.inputs['Transmission'].default_value = 0.9
        bsdf.inputs['IOR'].default_value = 1.5
    return mat

def create_neon_material(name, color, strength=10.0):
    """创建霓虹发光材质"""
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs['Base Color'].default_value = (0, 0, 0, 1.0)
        bsdf.inputs['Emission'].default_value = (*color, 1.0)
        bsdf.inputs['Emission Strength'].default_value = strength
    return mat

# ═══════════════════════════════════════════════════════════
#  场景构建
# ═══════════════════════════════════════════════════════════

def build_floor():
    """创建发光地板 - 网格纹理"""
    # 主地板
    bpy.ops.mesh.primitive_plane_add(
        size=1.0,
        location=(0, 2, 0)
    )
    floor = bpy.context.active_object
    floor.name = "Floor_Main"
    floor.scale = (6, 8, 1)
    
    mat = create_material("Floor_Dark", COLORS['floor'], roughness=0.2, metallic=0.1)
    floor.data.materials.append(mat)
    
    # 发光网格线
    for i in range(-5, 6, 2):
        # 纵向线
        bpy.ops.mesh.primitive_cube_add(
            size=1.0,
            location=(i * 0.5, 2, 0.01)
        )
        line = bpy.context.active_object
        line.name = f"Floor_Line_V_{i}"
        line.scale = (0.02, 8, 0.01)
        mat_line = create_neon_material("Floor_Line_Cyan", COLORS['floor_glow'], 2.0)
        line.data.materials.append(mat_line)

def build_walls():
    """创建深邃背景"""
    # 后墙
    bpy.ops.mesh.primitive_plane_add(
        size=1.0,
        location=(0, 10, 3)
    )
    wall = bpy.context.active_object
    wall.name = "Back_Wall"
    wall.scale = (8, 6, 1)
    wall.rotation_euler = (math.radians(90), 0, 0)
    
    mat = create_material("Wall_Void", COLORS['wall'], roughness=1.0)
    wall.data.materials.append(mat)

def build_host_platform():
    """创建主播位 - 中央悬浮平台"""
    # 主平台
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=32,
        radius=1.0,
        depth=0.2,
        location=(0, 2, 0.15)
    )
    platform = bpy.context.active_object
    platform.name = "Host_Platform"
    
    mat = create_material("Platform_Neon", COLORS['pedestal'], roughness=0.3, metallic=0.5)
    platform.data.materials.append(mat)
    
    # 霓虹边框
    bpy.ops.mesh.primitive_torus_add(
        major_radius=1.0,
        minor_radius=0.03,
        major_segments=32,
        minor_segments=8,
        location=(0, 2, 0.26)
    )
    ring = bpy.context.active_object
    ring.name = "Platform_Neon_Ring"
    mat_ring = create_neon_material("Neon_Cyan", COLORS['accent'], 8.0)
    ring.data.materials.append(mat_ring)
    
    # 下方发光柱（悬浮感）
    bpy.ops.mesh.primitive_cylinder_add(
        radius=0.3,
        depth=0.8,
        location=(0, 2, -0.4)
    )
    glow = bpy.context.active_object
    glow.name = "Platform_Support_Glow"
    mat_glow = create_neon_material("Support_Glow", COLORS['accent'], 5.0)
    glow.data.materials.append(mat_glow)
    
    return {"position": {"x": 0, "y": 0.25, "z": 2}, "rotation": {"x": 0, "y": 0, "z": 0}}

def build_display_pod(x, y, z, height, pod_type, sku, light_color):
    """创建悬浮玻璃展示罩"""
    pod_id = f"pod_{int(x)}_{int(y)}"
    
    # 底座 - 发光
    base_height = 0.15
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=24,
        radius=0.5,
        depth=base_height,
        location=(x, y, z + base_height/2)
    )
    base = bpy.context.active_object
    base.name = f"{pod_id}_Base"
    
    # 底座发光材质
    if light_color == "cyan":
        base_color = COLORS['accent']
    elif light_color == "orange":
        base_color = COLORS['accent_warm']
    else:
        base_color = (0.9, 0.9, 0.9)
    
    mat_base = create_neon_material(f"Base_{pod_id}", base_color, 3.0)
    base.data.materials.append(mat_base)
    
    # 玻璃罩 - 胶囊形状
    glass_height = height - base_height - 0.2
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=16,
        radius=0.45,
        depth=glass_height,
        location=(x, y, z + base_height + glass_height/2 + 0.1)
    )
    glass = bpy.context.active_object
    glass.name = f"{pod_id}_Glass"
    
    # 玻璃顶半球
    bpy.ops.mesh.primitive_uv_sphere_add(
        radius=0.45,
        segments=16,
        ring_count=8,
        location=(x, y, z + base_height + glass_height + 0.1)
    )
    dome = bpy.context.active_object
    dome.name = f"{pod_id}_Dome"
    dome.scale = (1, 1, 0.5)
    
    # 玻璃材质
    mat_glass = create_glass_material(f"Glass_{pod_id}", tint=(*base_color, 0.9))
    glass.data.materials.append(mat_glass)
    dome.data.materials.append(mat_glass)
    
    # 内部悬浮展示台
    bpy.ops.mesh.primitive_cylinder_add(
        radius=0.25,
        depth=0.05,
        location=(x, y, z + base_height + glass_height * 0.4)
    )
    stage = bpy.context.active_object
    stage.name = f"{pod_id}_Stage"
    mat_stage = create_material(f"Stage_{pod_id}", (0.95, 0.95, 0.95), metallic=0.8, roughness=0.2)
    stage.data.materials.append(mat_stage)
    
    # 内部光源
    bpy.ops.object.light_add(type='POINT', location=(x, y, z + height - 0.3))
    inner_light = bpy.context.active_object
    inner_light.name = f"{pod_id}_Inner_Light"
    inner_light.data.energy = 20
    inner_light.data.color = base_color
    
    # 停靠点 - 主播面向展示罩
    stop_x = x * 0.5  # 主播在中央(0)，向展示罩走一半
    stop_y = 2 + (y - 2) * 0.4  # 主播在y=2
    
    return {
        "id": pod_id,
        "type": "display_pod",
        "label": f"展示罩 {sku}",
        "position": {"x": x, "y": y, "z": z},
        "rotation": {"x": 0, "y": 0, "z": 0},
        "scale": 1,
        "sku_id": sku,
        "visible": True,
        "npc_stop_point": {
            "position": [stop_x, 0, stop_y],
            "look_at": [x, 1.0, y]
        },
        "pod_type": pod_type,
        "light_color": light_color
    }

def build_robot_zone():
    """创建机器人隐藏通道"""
    # 地面引导线
    bpy.ops.mesh.primitive_cube_add(
        size=1.0,
        location=(0, -4, 0.01)
    )
    path = bpy.context.active_object
    path.name = "Robot_Path"
    path.scale = (1, 3, 0.02)
    
    mat = create_neon_material("Path_Glow", (0.5, 0.5, 0.5), 1.0)
    path.data.materials.append(mat)
    
    # 待命点标记
    bpy.ops.mesh.primitive_circle_add(
        vertices=16,
        radius=0.4,
        fill_type='NGON',
        location=(0, -5, 0.02)
    )
    mark = bpy.context.active_object
    mark.name = "Robot_Standby_Mark"
    
    mat_mark = create_neon_material("Standby_Mark", COLORS['accent'], 2.0)
    mark.data.materials.append(mat_mark)

def build_holographic_screen():
    """创建全息投影屏"""
    # 主屏幕
    bpy.ops.mesh.primitive_plane_add(
        size=1.0,
        location=(0, 9, 3.5)
    )
    screen = bpy.context.active_object
    screen.name = "Holo_Screen"
    screen.scale = (5, 3, 1)
    screen.rotation_euler = (math.radians(-10), 0, 0)
    
    # 半透明发光材质
    mat = bpy.data.materials.new(name="Holo_Mat")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs['Base Color'].default_value = (0, 0.9, 1.0, 0.3)
        bsdf.inputs['Roughness'].default_value = 0.0
        bsdf.inputs['Transmission'].default_value = 0.7
        bsdf.inputs['Emission'].default_value = (0, 0.5, 0.6, 1.0)
        bsdf.inputs['Emission Strength'].default_value = 2.0
    screen.data.materials.append(mat)
    
    # 屏幕边框发光
    for offset in [(-2.6, 0), (2.6, 0), (0, -1.6), (0, 1.6)]:
        bpy.ops.mesh.primitive_cube_add(
            size=1.0,
            location=(offset[0], 9 + offset[1] * 0.1, 3.5)
        )
        edge = bpy.context.active_object
        edge.name = f"Screen_Edge_{offset}"
        edge.scale = (0.05, 1.6 if abs(offset[1]) > 1 else 2.6, 0.05)
        mat_edge = create_neon_material("Edge_Cyan", COLORS['accent'], 10.0)
        edge.data.materials.append(mat_edge)

def build_lighting():
    """设置赛博朋克灯光"""
    # 清除默认灯光
    for obj in bpy.data.objects:
        if obj.type == 'LIGHT':
            bpy.data.objects.remove(obj)
    
    # 顶部主光源 - 冷色
    bpy.ops.object.light_add(type='AREA', location=(0, 2, 6))
    main = bpy.context.active_object
    main.name = "Main_Light_Cold"
    main.data.energy = 150
    main.data.size = 4.0
    main.data.color = (0.8, 0.9, 1.0)
    
    # 两侧氛围光
    for x in [-4, 4]:
        bpy.ops.object.light_add(type='AREA', location=(x, 2, 4))
        rim = bpy.context.active_object
        rim.name = f"Rim_Light_{x}"
        rim.data.energy = 80
        rim.data.size = 2.0
        rim.data.color = COLORS['accent'] if x < 0 else COLORS['accent_warm']

# ═══════════════════════════════════════════════════════════
#  导出与配置
# ═══════════════════════════════════════════════════════════

def export_gltf():
    """导出 GLTF 文件"""
    os.makedirs(OUTPUT_PATH, exist_ok=True)
    filepath = os.path.join(OUTPUT_PATH, "scene.gltf")
    
    bpy.ops.export_scene.gltf(
        filepath=filepath,
        export_format='GLTF_SEPARATE',
        export_materials='EXPORT',
        export_textures=True,
        export_yup=True,
        export_apply=True,
    )
    print(f"[Showcase] Exported to: {filepath}")
    return filepath

def generate_scene_config():
    """生成 scenes.json 配置片段"""
    objects = []
    
    # 构建所有展示罩
    for pod in DISPLAY_PODS:
        obj_data = build_display_pod(
            pod['pos'][0],
            pod['pos'][1],
            pod['pos'][2],
            pod['height'],
            pod['type'],
            pod['sku'],
            pod['light']
        )
        objects.append(obj_data)
    
    # 机器人区
    objects.append({
        "id": "robot_standby",
        "type": "spawn_point",
        "label": "机器人待命区",
        "position": {"x": 0, "y": 0, "z": 0},
        "visible": False,
        "npc_stop_point": {
            "position": [0, 0, -5],
            "look_at": [0, 1.0, 2]
        }
    })
    
    scene_config = {
        "id": SCENE_ID,
        "name": SCENE_NAME,
        "description": "赛博朋克风格悬浮玻璃展示罩直播间，8个独立发光展示舱，适合高端精品展示",
        "environment": SCENE_ID,
        "host_position": {
            "x": 50,
            "y": 50,
            "scale": 1
        },
        "host_position_3d": {
            "x": 0,
            "y": 0.25,
            "z": 2
        },
        "objects": objects,
        "slots": [
            {"id": "slot_1", "x": 20, "y": 15, "width": 12, "height": 12, "sku_id": "luxury_01", "label": "精品1"},
            {"id": "slot_2", "x": 20, "y": 35, "width": 12, "height": 12, "sku_id": "luxury_02", "label": "精品2"},
            {"id": "slot_3", "x": 20, "y": 55, "width": 12, "height": 12, "sku_id": "luxury_03", "label": "精品3"},
            {"id": "slot_4", "x": 20, "y": 75, "width": 12, "height": 12, "sku_id": "luxury_04", "label": "精品4"},
            {"id": "slot_5", "x": 68, "y": 15, "width": 12, "height": 12, "sku_id": "luxury_05", "label": "精品5"},
            {"id": "slot_6", "x": 68, "y": 35, "width": 12, "height": 12, "sku_id": "luxury_06", "label": "精品6"},
            {"id": "slot_7", "x": 68, "y": 55, "width": 12, "height": 12, "sku_id": "luxury_07", "label": "精品7"},
            {"id": "slot_8", "x": 68, "y": 75, "width": 12, "height": 12, "sku_id": "luxury_08", "label": "精品8"},
        ]
    }
    
    config_path = os.path.join(OUTPUT_PATH, "scene_config.json")
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(scene_config, f, ensure_ascii=False, indent=2)
    print(f"[Showcase] Config saved to: {config_path}")
    
    return scene_config

# ═══════════════════════════════════════════════════════════
#  主流程
# ═══════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("🌃 悬浮展示馆场景生成器")
    print("=" * 60)
    
    clear_scene()
    print("[1/6] 场景已清空")
    
    build_floor()
    print("[2/6] 发光地板已创建")
    
    build_walls()
    print("[3/6] 深邃背景已创建")
    
    build_host_platform()
    print("[4/6] 悬浮主播位已创建")
    
    build_robot_zone()
    print("[5/6] 机器人通道已创建")
    
    build_holographic_screen()
    print("[6/6] 全息屏已创建")
    
    print("[+] 创建8个悬浮玻璃展示罩...")
    build_lighting()
    print("[+] 赛博朋克灯光系统已设置")
    
    export_gltf()
    generate_scene_config()
    
    print("=" * 60)
    print("✅ 悬浮展示馆场景生成完成!")
    print(f"📁 输出目录: {OUTPUT_PATH}")
    print("🎨 风格: 赛博朋克 / 青橙霓虹 / 悬浮玻璃罩")
    print("=" * 60)

if __name__ == "__main__":
    main()
