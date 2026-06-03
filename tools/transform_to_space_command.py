"""
科幻指挥舱改造脚本 - 方案 A
基于 Kenney Sci-Fi Interior 资产改造为直播间

运行前准备:
1. 导入 Kenney Sci-Fi Interior 的 floor.obj, wall.obj, console.obj
2. 导入 Poly Haven 星空 HDRI 作为环境
3. 选中所有导入的物体
4. 运行此脚本
"""

import bpy
import math
import os
import json

# ═══════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════
OUTPUT_DIR = "D:/新建文件夹 (2)/assets/scenes/space_command"
SCENE_ID = "space_command"
SCENE_NAME = "星际指挥舱"

# 科幻配色
COLORS = {
    'hologram_blue': (0, 0.8, 1.0),
    'hologram_orange': (1.0, 0.5, 0),
    'metal_dark': (0.15, 0.15, 0.18),
    'light_panel': (0.9, 0.95, 1.0),
}

# 商品展示全息屏位置（环绕主播控制台）
HOLO_SCREENS = [
    {"angle": 0, "radius": 2.5, "type": "tall", "sku": "sci_product_01"},
    {"angle": 60, "radius": 2.5, "type": "wide", "sku": "sci_product_02"},
    {"angle": 120, "radius": 2.5, "type": "tall", "sku": "sci_product_03"},
    {"angle": 180, "radius": 2.5, "type": "wide", "sku": "sci_product_04"},
    {"angle": 240, "radius": 2.5, "type": "tall", "sku": "sci_product_05"},
    {"angle": 300, "radius": 2.5, "type": "wide", "sku": "sci_product_06"},
]

# ═══════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════

def create_hologram_material(name, color, strength=5.0):
    """创建全息发光材质"""
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs['Base Color'].default_value = (0, 0, 0, 1)
    bsdf.inputs['Emission'].default_value = (*color, 1.0)
    bsdf.inputs['Emission Strength'].default_value = strength
    bsdf.inputs['Transmission'].default_value = 0.3
    return mat

def create_metal_material(name, color, roughness=0.3):
    """创建金属材质"""
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs['Base Color'].default_value = (*color, 1.0)
    bsdf.inputs['Roughness'].default_value = roughness
    bsdf.inputs['Metallic'].default_value = 0.8
    return mat

def add_holographic_screen(x, y, z, screen_type, sku):
    """添加全息商品展示屏"""
    if screen_type == "tall":
        scale = (0.8, 0.05, 1.2)
    else:  # wide
        scale = (1.2, 0.05, 0.8)
    
    # 屏幕主体
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(x, y, z))
    screen = bpy.context.active_object
    screen.name = f"HoloScreen_{sku}"
    screen.scale = scale
    
    # 全息材质
    color = COLORS['hologram_blue'] if hash(sku) % 2 == 0 else COLORS['hologram_orange']
    mat = create_hologram_material(f"Holo_{sku}", color, 8.0)
    screen.data.materials.append(mat)
    
    # 悬浮动画（上下浮动）
    screen["float_offset"] = z
    screen["float_speed"] = 1.0
    
    # 发光边框
    bpy.ops.mesh.primitive_cube_add(
        size=1.0, 
        location=(x, y, z)
    )
    frame = bpy.context.active_object
    frame.name = f"HoloFrame_{sku}"
    frame.scale = (scale[0] + 0.05, 0.02, scale[2] + 0.05)
    mat_frame = create_hologram_material(f"Frame_{sku}", color, 10.0)
    frame.data.materials.append(mat_frame)
    
    # 底部光柱（支撑感）
    bpy.ops.mesh.primitive_cylinder_add(
        radius=0.05,
        depth=z,
        location=(x, y, z/2)
    )
    beam = bpy.context.active_object
    beam.name = f"HoloBeam_{sku}"
    mat_beam = create_hologram_material(f"Beam_{sku}", color, 2.0)
    beam.data.materials.append(mat_beam)
    
    # 内部光源
    bpy.ops.object.light_add(type='POINT', location=(x, y, z))
    light = bpy.context.active_object
    light.name = f"HoloLight_{sku}"
    light.data.energy = 50
    light.data.color = color
    
    return screen

def add_host_command_center():
    """添加主播指挥控制台"""
    # 主控制台
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=16,
        radius=1.0,
        depth=0.1,
        location=(0, 0, 0.8)
    )
    console = bpy.context.active_object
    console.name = "HostConsole"
    
    mat = create_metal_material("ConsoleMetal", COLORS['metal_dark'], 0.2)
    console.data.materials.append(mat)
    
    # 指挥官座椅
    bpy.ops.mesh.primitive_cylinder_add(
        radius=0.4,
        depth=0.6,
        location=(0, -0.3, 0.5)
    )
    chair = bpy.context.active_object
    chair.name = "CommandChair"
    mat_chair = create_metal_material("ChairMetal", (0.2, 0.2, 0.25), 0.4)
    chair.data.materials.append(mat_chair)
    
    # 控制台面发光
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=16,
        radius=0.9,
        depth=0.02,
        location=(0, 0, 0.86)
    )
    panel = bpy.context.active_object
    panel.name = "ControlPanel"
    mat_panel = create_hologram_material("PanelGlow", COLORS['hologram_blue'], 3.0)
    panel.data.materials.append(mat_panel)
    
    return console

def add_robot_airlock():
    """添加机器人气闸门出生点"""
    # 气闸门框
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(4, 0, 1.5))
    door_frame = bpy.context.active_object
    door_frame.name = "RobotAirlock"
    door_frame.scale = (0.2, 1.5, 2)
    
    mat = create_metal_material("AirlockMetal", (0.3, 0.3, 0.35), 0.3)
    door_frame.data.materials.append(mat)
    
    # 门框发光边
    bpy.ops.mesh.primitive_torus_add(
        major_radius=1.0,
        minor_radius=0.05,
        location=(4, 0, 1.5)
    )
    ring = bpy.context.active_object
    ring.name = "AirlockRing"
    ring.scale = (0.2, 1.5, 2)
    mat_ring = create_hologram_material("AirlockRing", COLORS['hologram_orange'], 5.0)
    ring.data.materials.append(mat_ring)
    
    # 待命区标记
    bpy.ops.mesh.primitive_circle_add(
        radius=0.5,
        fill_type='NGON',
        location=(4.5, 0, 0.02)
    )
    mark = bpy.context.active_object
    mark.name = "RobotStandbyMark"
    mat_mark = create_hologram_material("StandbyMark", COLORS['hologram_orange'], 2.0)
    mark.data.materials.append(mat_mark)

def add_transformation_chamber():
    """添加变身舱（透明圆柱，用于变身/技能表演）"""
    # 透明舱体
    bpy.ops.mesh.primitive_cylinder_add(
        radius=1.2,
        depth=2.5,
        location=(0, -3.5, 1.25)
    )
    chamber = bpy.context.active_object
    chamber.name = "TransformationChamber"
    
    # 玻璃材质
    mat = bpy.data.materials.new(name="ChamberGlass")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs['Transmission'].default_value = 0.9
    bsdf.inputs['Roughness'].default_value = 0.05
    bsdf.inputs['IOR'].default_value = 1.45
    chamber.data.materials.append(mat)
    
    # 舱体发光环
    for y_offset in [-1, 0, 1]:
        bpy.ops.mesh.primitive_torus_add(
            major_radius=1.25,
            minor_radius=0.03,
            location=(0, -3.5, 1.25 + y_offset)
        )
        ring = bpy.context.active_object
        ring.name = f"ChamberRing_{y_offset}"
        mat_ring = create_hologram_material(f"ChamberRing_{y_offset}", COLORS['hologram_blue'], 8.0)
        ring.data.materials.append(mat_ring)
    
    # 舱内光源
    bpy.ops.object.light_add(type='AREA', location=(0, -3.5, 1.25))
    light = bpy.context.active_object
    light.name = "ChamberLight"
    light.data.energy = 100
    light.data.size = 1.5
    light.data.color = COLORS['hologram_blue']

def setup_space_lighting():
    """设置太空舱灯光"""
    # 清除现有灯光
    for obj in bpy.data.objects:
        if obj.type == 'LIGHT':
            bpy.data.objects.remove(obj)
    
    # 顶部指挥舱主光源
    bpy.ops.object.light_add(type='AREA', location=(0, 0, 4))
    main = bpy.context.active_object
    main.name = "CommandLight"
    main.data.energy = 150
    main.data.size = 3.0
    main.data.color = COLORS['light_panel']
    
    # 蓝色氛围光（左侧）
    bpy.ops.object.light_add(type='AREA', location=(-3, 2, 2))
    blue = bpy.context.active_object
    blue.name = "BlueAmbience"
    blue.data.energy = 80
    blue.data.size = 2.0
    blue.data.color = COLORS['hologram_blue']
    
    # 橙色氛围光（右侧）
    bpy.ops.object.light_add(type='AREA', location=(3, 2, 2))
    orange = bpy.context.active_object
    orange.name = "OrangeAmbience"
    orange.data.energy = 60
    orange.data.size = 2.0
    orange.data.color = COLORS['hologram_orange']

def export_scene():
    """导出场景和配置"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # 导出 GLTF
    filepath = os.path.join(OUTPUT_DIR, "scene.gltf")
    bpy.ops.export_scene.gltf(
        filepath=filepath,
        export_format='GLTF_SEPARATE',
        export_materials='EXPORT',
        export_yup=True,
        export_apply=True,
    )
    
    # 生成配置
    objects = []
    
    # 全息屏配置
    for screen in HOLO_SCREENS:
        angle_rad = math.radians(screen['angle'])
        x = screen['radius'] * math.sin(angle_rad)
        y = -screen['radius'] * math.cos(angle_rad)
        z = 1.5
        
        # 停靠点在主播和屏之间
        stop_x = x * 0.5
        stop_y = y * 0.5
        
        objects.append({
            "id": f"holo_screen_{screen['angle']}",
            "type": "holographic_display",
            "label": f"全息屏 {screen['sku']}",
            "position": {"x": x, "y": y, "z": z},
            "sku_id": screen['sku'],
            "visible": True,
            "npc_stop_point": {
                "position": [stop_x, 0, stop_y],
                "look_at": [x, 1.2, y]
            }
        })
    
    # 变身舱配置
    objects.append({
        "id": "transformation_chamber",
        "type": "special_zone",
        "label": "变身舱",
        "position": {"x": 0, "y": -3.5, "z": 0},
        "visible": True,
        "npc_stop_point": {
            "position": [0, 0, -2.5],
            "look_at": [0, 1.5, -3.5]
        },
        "tags": ["transformation", "special_skill"]
    })
    
    # 机器人气闸
    objects.append({
        "id": "robot_airlock",
        "type": "spawn_point",
        "label": "机器人气闸门",
        "position": {"x": 4, "y": 0, "z": 0},
        "visible": True,
        "npc_stop_point": {
            "position": [4.5, 0, 0],
            "look_at": [0, 1.0, 0]
        }
    })
    
    config = {
        "id": SCENE_ID,
        "name": SCENE_NAME,
        "description": "星际指挥舱直播间，全息商品展示屏环绕主播控制台，含变身舱和机器人气闸门",
        "environment": SCENE_ID,
        "host_position_3d": {"x": 0, "y": 0.8, "z": 0},
        "objects": objects,
        "slots": [
            {"id": f"slot_{i+1}", "x": 20 + (i % 3) * 25, "y": 20 + (i // 3) * 30,
             "width": 15, "height": 15, "sku_id": screen['sku'], "label": f"全息商品{i+1}"}
            for i, screen in enumerate(HOLO_SCREENS)
        ]
    }
    
    config_path = os.path.join(OUTPUT_DIR, "scene_config.json")
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    
    return filepath, config_path

def main():
    print("=" * 60)
    print("🚀 星际指挥舱场景改造")
    print("=" * 60)
    
    # 检查是否有导入的资产
    imported_objects = [obj for obj in bpy.data.objects if obj.type == 'MESH']
    if len(imported_objects) < 3:
        print("⚠️ 警告: 导入的物体较少，建议先导入 Kenney Sci-Fi Interior 资产")
        print("继续生成基础结构...")
    
    print("[1/5] 添加主播指挥控制台...")
    add_host_command_center()
    
    print("[2/5] 添加环绕全息商品屏...")
    for screen in HOLO_SCREENS:
        angle_rad = math.radians(screen['angle'])
        x = screen['radius'] * math.sin(angle_rad)
        y = -screen['radius'] * math.cos(angle_rad)
        add_holographic_screen(x, y, 1.5, screen['type'], screen['sku'])
    
    print("[3/5] 添加变身舱...")
    add_transformation_chamber()
    
    print("[4/5] 添加机器人气闸门...")
    add_robot_airlock()
    
    print("[5/5] 设置灯光并导出...")
    setup_space_lighting()
    gltf_path, config_path = export_scene()
    
    print("=" * 60)
    print("✅ 星际指挥舱生成完成!")
    print(f"📁 场景: {gltf_path}")
    print(f"📁 配置: {config_path}")
    print("=" * 60)
    print("\n功能区域:")
    print("  🎮 中央: 主播指挥控制台")
    print("  🖥️  环绕: 6个全息商品展示屏")
    print("  🌀 后方: 变身舱（技能/变身表演）")
    print("  🤖 侧方: 机器人气闸门出生点")

if __name__ == "__main__":
    main()
