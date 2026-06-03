"""
生成环形剧场式直播间场景 (P0 - 最通用)
玻璃展示柜环绕中央主播位，适合多 SKU 展示

使用方法:
    blender --background --python tools/generate_theater_scene.py
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
OUTPUT_PATH = "D:/新建文件夹 (2)/assets/scenes/theater_ring"
SCENE_ID = "theater_ring"
SCENE_NAME = "环形剧场"

# 颜色配置 - 暖色调奢华风格
COLORS = {
    'floor': (0.12, 0.10, 0.08),      # 深木色地板
    'wall': (0.08, 0.06, 0.05),       # 深褐色背景墙
    'accent': (0.85, 0.65, 0.25),     # 金色装饰
    'glass': (0.95, 0.97, 0.98),      # 玻璃
    'light_glow': (1.0, 0.95, 0.8),   # 暖白灯光
    'pillar': (0.15, 0.12, 0.10),     # 柱子
}

# 环形展示柜配置
DISPLAY_CABINETS = [
    # 6个玻璃展示柜，环形排列
    {"angle": 0, "radius": 3.5, "height": 1.8, "shelves": 3, "sku": "product_01"},
    {"angle": 60, "radius": 3.5, "height": 1.8, "shelves": 3, "sku": "product_02"},
    {"angle": 120, "radius": 3.5, "height": 1.8, "shelves": 3, "sku": "product_03"},
    {"angle": 180, "radius": 3.5, "height": 1.8, "shelves": 3, "sku": "product_04"},
    {"angle": 240, "radius": 3.5, "height": 1.8, "shelves": 3, "sku": "product_05"},
    {"angle": 300, "radius": 3.5, "height": 1.8, "shelves": 3, "sku": "product_06"},
]

# ═══════════════════════════════════════════════════════════
#  工具函数
# ═══════════════════════════════════════════════════════════

def clear_scene():
    """清空场景"""
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    # 清除数据块
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

def create_glass_material(name):
    """创建玻璃材质"""
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs['Base Color'].default_value = (0.95, 0.97, 0.98, 1.0)
        bsdf.inputs['Roughness'].default_value = 0.02
        bsdf.inputs['Metallic'].default_value = 0.0
        bsdf.inputs['Transmission'].default_value = 0.95
        bsdf.inputs['IOR'].default_value = 1.45
    return mat

def create_light_material(name, color, strength=5.0):
    """创建发光材质"""
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs['Base Color'].default_value = (*color, 1.0)
        bsdf.inputs['Emission'].default_value = (*color, 1.0)
        bsdf.inputs['Emission Strength'].default_value = strength
    return mat

# ═══════════════════════════════════════════════════════════
#  场景构建
# ═══════════════════════════════════════════════════════════

def build_floor():
    """创建圆形地板 - 带装饰边缘"""
    # 主地板
    bpy.ops.mesh.primitive_circle_add(
        vertices=64,
        radius=6.0,
        fill_type='NGON',
        location=(0, 0, 0)
    )
    floor = bpy.context.active_object
    floor.name = "Floor_Main"
    
    # 挤出厚度
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.extrude_region_move(TRANSFORM_OT_translate={"value":(0, 0, -0.1)})
    bpy.ops.object.mode_set(mode='OBJECT')
    
    mat = create_material("Floor_Mat", COLORS['floor'], roughness=0.3)
    floor.data.materials.append(mat)
    
    # 金色装饰环
    bpy.ops.mesh.primitive_torus_add(
        major_radius=5.8,
        minor_radius=0.05,
        major_segments=64,
        minor_segments=8,
        location=(0, 0, 0.02)
    )
    ring = bpy.context.active_object
    ring.name = "Floor_Decoration_Ring"
    mat_ring = create_material("Gold_Rim", COLORS['accent'], roughness=0.2, metallic=0.9)
    ring.data.materials.append(mat_ring)

def build_walls():
    """创建弧形背景墙"""
    # 使用圆柱体切片作为背景墙
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=64,
        radius=8.0,
        depth=4.0,
        location=(0, 0, 2)
    )
    wall = bpy.context.active_object
    wall.name = "Back_Wall"
    
    # 删除前半部分，只保留后半圆
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='DESELECT')
    bm = bmesh.from_mesh(wall.data)
    for vert in bm.verts:
        if vert.co.y > 0:  # 删除前半部分
            vert.select = True
    bm.to_mesh(wall.data)
    bm.free()
    bpy.ops.mesh.delete(type='VERT')
    bpy.ops.object.mode_set(mode='OBJECT')
    
    mat = create_material("Wall_Mat", COLORS['wall'], roughness=0.8)
    wall.data.materials.append(mat)

def build_host_platform():
    """创建主播位 - 中央圆形站台"""
    # 主站台
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=32,
        radius=1.2,
        depth=0.15,
        location=(0, 0, 0.075)
    )
    platform = bpy.context.active_object
    platform.name = "Host_Platform"
    
    mat = create_material("Platform_Mat", COLORS['accent'], roughness=0.3, metallic=0.8)
    platform.data.materials.append(mat)
    
    # 内嵌发光环
    bpy.ops.mesh.primitive_torus_add(
        major_radius=1.0,
        minor_radius=0.03,
        major_segments=32,
        minor_segments=8,
        location=(0, 0, 0.16)
    )
    glow = bpy.context.active_object
    glow.name = "Platform_Glow"
    mat_glow = create_light_material("Platform_Glow_Mat", COLORS['light_glow'], 3.0)
    glow.data.materials.append(mat_glow)
    
    return {"position": {"x": 0, "y": 0, "z": 0.15}, "rotation": {"x": 0, "y": 0, "z": 0}}

def build_glass_cabinet(angle_deg, radius, height, shelves, sku):
    """创建单个玻璃展示柜"""
    angle_rad = math.radians(angle_deg)
    x = radius * math.sin(angle_rad)
    y = -radius * math.cos(angle_rad)  # 负Y朝向中心
    
    cabinet_name = f"Cabinet_{angle_deg}"
    
    # 柜体外框 - 玻璃柱
    bpy.ops.mesh.primitive_cube_add(
        size=1.0,
        location=(x, y, height/2 + 0.1)
    )
    cabinet = bpy.context.active_object
    cabinet.name = cabinet_name
    cabinet.scale = (0.8, 0.8, height)
    
    # 玻璃材质
    mat_glass = create_glass_material(f"Glass_{angle_deg}")
    cabinet.data.materials.append(mat_glass)
    
    # 金属框架 - 4条立柱
    frame_positions = [
        (x - 0.35, y - 0.35), (x + 0.35, y - 0.35),
        (x - 0.35, y + 0.35), (x + 0.35, y + 0.35)
    ]
    for i, (fx, fy) in enumerate(frame_positions):
        bpy.ops.mesh.primitive_cylinder_add(
            radius=0.02,
            depth=height,
            location=(fx, fy, height/2 + 0.1)
        )
        pillar = bpy.context.active_object
        pillar.name = f"{cabinet_name}_Pillar_{i}"
        mat_frame = create_material(f"Frame_{angle_deg}", COLORS['accent'], roughness=0.2, metallic=0.9)
        pillar.data.materials.append(mat_frame)
    
    # 内部展示层板 - 发光
    for i in range(shelves):
        shelf_y = 0.4 + (height - 0.8) * (i + 1) / (shelves + 1)
        bpy.ops.mesh.primitive_cube_add(
            size=1.0,
            location=(x, y, shelf_y)
        )
        shelf = bpy.context.active_object
        shelf.name = f"{cabinet_name}_Shelf_{i}"
        shelf.scale = (0.7, 0.7, 0.02)
        mat_shelf = create_light_material(f"Shelf_Light_{angle_deg}_{i}", COLORS['light_glow'], 2.0)
        shelf.data.materials.append(mat_shelf)
    
    # 计算停靠点 - 主播面向展示柜的位置
    stop_x = (radius - 1.2) * math.sin(angle_rad)
    stop_y = -(radius - 1.2) * math.cos(angle_rad)
    look_x = x
    look_y = y
    
    return {
        "id": f"cabinet_{angle_deg}",
        "type": "display_cabinet",
        "label": f"展示柜 {angle_deg}°",
        "position": {"x": x, "y": y, "z": 0},
        "rotation": {"x": 0, "y": 0, "z": angle_rad},
        "scale": 1,
        "sku_id": sku,
        "visible": True,
        "npc_stop_point": {
            "position": [stop_x, 0, stop_y],
            "look_at": [look_x, 1.0, look_y]
        }
    }

def build_robot_zone():
    """创建机器人待命区"""
    # 后方待命位置
    bpy.ops.mesh.primitive_cylinder_add(
        radius=0.5,
        depth=0.05,
        location=(0, -5.5, 0.025)
    )
    zone = bpy.context.active_object
    zone.name = "Robot_Standby_Zone"
    
    mat = create_material("Robot_Zone", (0.2, 0.25, 0.3), roughness=0.5)
    zone.data.materials.append(mat)

def build_lighting():
    """设置灯光系统"""
    # 清除默认灯光
    for obj in bpy.data.objects:
        if obj.type == 'LIGHT':
            bpy.data.objects.remove(obj)
    
    # 主光源 - 顶部暖光
    bpy.ops.object.light_add(type='AREA', location=(0, 0, 5))
    main_light = bpy.context.active_object
    main_light.name = "Main_Light"
    main_light.data.energy = 200
    main_light.data.size = 3.0
    main_light.data.color = COLORS['light_glow']
    
    # 环形补光
    for angle in [0, 90, 180, 270]:
        rad = math.radians(angle)
        x = 4 * math.cos(rad)
        y = 4 * math.sin(rad)
        bpy.ops.object.light_add(type='POINT', location=(x, y, 3))
        light = bpy.context.active_object
        light.name = f"Fill_Light_{angle}"
        light.data.energy = 50
        light.data.color = COLORS['light_glow']
    
    # 展示柜内部光源
    for cabinet in DISPLAY_CABINETS:
        rad = math.radians(cabinet['angle'])
        x = cabinet['radius'] * math.sin(rad)
        y = -cabinet['radius'] * math.cos(rad)
        bpy.ops.object.light_add(type='POINT', location=(x, y, cabinet['height'] - 0.2))
        light = bpy.context.active_object
        light.name = f"Cabinet_Light_{cabinet['angle']}"
        light.data.energy = 30
        light.data.color = COLORS['light_glow']

def build_video_screen():
    """创建背景视频屏"""
    bpy.ops.mesh.primitive_plane_add(
        size=1.0,
        location=(0, -7.8, 2.5)
    )
    screen = bpy.context.active_object
    screen.name = "Video_Screen"
    screen.scale = (4, 2.5, 1)
    
    # 发光材质模拟屏幕
    mat = create_light_material("Screen_Mat", (0.9, 0.9, 0.95), 1.0)
    screen.data.materials.append(mat)

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
    print(f"[Theater] Exported to: {filepath}")
    return filepath

def generate_scene_config():
    """生成 scenes.json 配置片段"""
    objects = []
    
    # 构建所有展示柜
    for cabinet in DISPLAY_CABINETS:
        obj_data = build_glass_cabinet(
            cabinet['angle'],
            cabinet['radius'],
            cabinet['height'],
            cabinet['shelves'],
            cabinet['sku']
        )
        objects.append(obj_data)
    
    # 机器人待命区（虚拟对象，用于配置）
    objects.append({
        "id": "robot_standby",
        "type": "spawn_point",
        "label": "机器人待命区",
        "position": {"x": 0, "y": 0, "z": 0},
        "visible": False,
        "npc_stop_point": {
            "position": [0, 0, -5.5],
            "look_at": [0, 1.0, 0]
        }
    })
    
    scene_config = {
        "id": SCENE_ID,
        "name": SCENE_NAME,
        "description": "环形玻璃展示柜直播间，中央主播位，6个发光展示柜环绕，适合多SKU展示",
        "environment": SCENE_ID,
        "host_position": {
            "x": 50,
            "y": 75,
            "scale": 1
        },
        "host_position_3d": {
            "x": 0,
            "y": 0.15,
            "z": 0
        },
        "objects": objects,
        "slots": [
            {"id": "slot_1", "x": 20, "y": 20, "width": 15, "height": 15, "sku_id": "product_01", "label": "产品1"},
            {"id": "slot_2", "x": 70, "y": 20, "width": 15, "height": 15, "sku_id": "product_02", "label": "产品2"},
            {"id": "slot_3", "x": 85, "y": 50, "width": 15, "height": 15, "sku_id": "product_03", "label": "产品3"},
            {"id": "slot_4", "x": 70, "y": 80, "width": 15, "height": 15, "sku_id": "product_04", "label": "产品4"},
            {"id": "slot_5", "x": 20, "y": 80, "width": 15, "height": 15, "sku_id": "product_05", "label": "产品5"},
            {"id": "slot_6", "x": 5, "y": 50, "width": 15, "height": 15, "sku_id": "product_06", "label": "产品6"},
        ]
    }
    
    # 保存配置片段
    config_path = os.path.join(OUTPUT_PATH, "scene_config.json")
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(scene_config, f, ensure_ascii=False, indent=2)
    print(f"[Theater] Config saved to: {config_path}")
    
    return scene_config

# ═══════════════════════════════════════════════════════════
#  主流程
# ═══════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("🏛️  环形剧场式直播间场景生成器")
    print("=" * 60)
    
    # 清空场景
    clear_scene()
    print("[1/6] 场景已清空")
    
    # 构建场景
    build_floor()
    print("[2/6] 地板已创建")
    
    build_walls()
    print("[3/6] 背景墙已创建")
    
    build_host_platform()
    print("[4/6] 主播位已创建")
    
    build_robot_zone()
    print("[5/6] 机器人区已创建")
    
    build_video_screen()
    print("[6/6] 视频屏已创建")
    
    # 展示柜在循环中创建并收集配置
    print("[+] 创建玻璃展示柜...")
    
    # 设置灯光
    build_lighting()
    print("[+] 灯光系统已设置")
    
    # 导出
    export_gltf()
    
    # 生成配置
    generate_scene_config()
    
    print("=" * 60)
    print("✅ 环形剧场场景生成完成!")
    print(f"📁 输出目录: {OUTPUT_PATH}")
    print("=" * 60)

if __name__ == "__main__":
    main()
