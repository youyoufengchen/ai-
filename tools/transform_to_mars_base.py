"""
火星基地直播间改造脚本 - 方案 C
基于 NASA Mars 地形 + Kenney Space Kit 改造
"""

import bpy
import math
import os
import json

OUTPUT_DIR = "D:/新建文件夹 (2)/assets/scenes/mars_base"
SCENE_ID = "mars_base"
SCENE_NAME = "火星基地"

COLORS = {
    'mars_orange': (0.8, 0.3, 0.1),
    'mars_dust': (0.9, 0.5, 0.2),
    'base_metal': (0.6, 0.6, 0.65),
    'light_white': (1.0, 0.98, 0.95),
    'hazard_yellow': (0.9, 0.7, 0.1),
}

# 岩石展示台位置（融入地形）
ROCK_DISPLAYS = [
    {"pos": (-2, -1), "height": 0.8, "sku": "mars_product_01"},
    {"pos": (2, -1), "height": 0.6, "sku": "mars_product_02"},
    {"pos": (-1.5, 2), "height": 0.5, "sku": "mars_product_03"},
    {"pos": (1.5, 2), "height": 0.7, "sku": "mars_product_04"},
]

def create_dust_material(name):
    """创建火星尘埃材质"""
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs['Base Color'].default_value = (*COLORS['mars_orange'], 1.0)
    bsdf.inputs['Roughness'].default_value = 0.9
    return mat

def create_rock_display(x, y, z, sku):
    """创建岩石展示台"""
    # 岩石基座
    bpy.ops.mesh.primitive_ico_sphere_add(
        subdivisions=2,
        radius=0.6,
        location=(x, y, z/2)
    )
    rock = bpy.context.active_object
    rock.name = f"RockBase_{sku}"
    rock.scale = (1, 0.8, z/1.2)
    
    # 随机变形让岩石更自然
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.transform.vertex_random(offset=0.1, uniform=0.5, normal=0.2)
    bpy.ops.object.mode_set(mode='OBJECT')
    
    mat = create_dust_material(f"Rock_{sku}")
    rock.data.materials.append(mat)
    
    # 玻璃罩（保护商品）
    bpy.ops.mesh.primitive_ico_sphere_add(
        subdivisions=3,
        radius=0.4,
        location=(x, y, z + 0.3)
    )
    dome = bpy.context.active_object
    dome.name = f"Dome_{sku}"
    
    mat_glass = bpy.data.materials.new(name=f"DomeGlass_{sku}")
    mat_glass.use_nodes = True
    bsdf = mat_glass.node_tree.nodes["Principled BSDF"]
    bsdf.inputs['Transmission'].default_value = 0.95
    bsdf.inputs['Roughness'].default_value = 0.02
    bsdf.inputs['IOR'].default_value = 1.45
    dome.data.materials.append(mat_glass)
    
    # 发光边框
    bpy.ops.mesh.primitive_torus_add(
        major_radius=0.42,
        minor_radius=0.02,
        location=(x, y, z + 0.05)
    )
    ring = bpy.context.active_object
    ring.name = f"DomeRing_{sku}"
    mat_ring = bpy.data.materials.new(name=f"Ring_{sku}")
    mat_ring.use_nodes = True
    mat_ring.node_tree.nodes["Principled BSDF"].inputs['Emission'].default_value = (*COLORS['hazard_yellow'], 1.0)
    mat_ring.node_tree.nodes["Principled BSDF"].inputs['Emission Strength'].default_value = 3.0
    ring.data.materials.append(mat_ring)
    
    # 停靠点
    stop_x = x * 0.7
    stop_y = y * 0.7
    
    return {
        "id": f"rock_display_{sku}",
        "type": "rock_display",
        "label": f"岩石展台 {sku}",
        "position": {"x": x, "y": y, "z": z},
        "sku_id": sku,
        "visible": True,
        "npc_stop_point": {
            "position": [stop_x, 0, stop_y],
            "look_at": [x, z + 0.5, y]
        }
    }

def add_mars_rover_host():
    """添加火星车主播位"""
    # 车体平台
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, 0.4))
    body = bpy.context.active_object
    body.name = "RoverBody"
    body.scale = (1.2, 0.8, 0.3)
    
    mat = bpy.data.materials.new(name="RoverMetal")
    mat.use_nodes = True
    mat.node_tree.nodes["Principled BSDF"].inputs['Base Color'].default_value = (*COLORS['base_metal'], 1.0)
    mat.node_tree.nodes["Principled BSDF"].inputs['Metallic'].default_value = 0.6
    body.data.materials.append(mat)
    
    # 驾驶舱（主播站立区）
    bpy.ops.mesh.primitive_cylinder_add(
        radius=0.5,
        depth=0.8,
        location=(0, -0.2, 0.9)
    )
    cabin = bpy.context.active_object
    cabin.name = "RoverCabin"
    
    # 透明穹顶
    mat_dome = bpy.data.materials.new(name="CabinDome")
    mat_dome.use_nodes = True
    bsdf = mat_dome.node_tree.nodes["Principled BSDF"]
    bsdf.inputs['Transmission'].default_value = 0.9
    bsdf.inputs['Base Color'].default_value = (0.9, 0.95, 1.0, 0.3)
    cabin.data.materials.append(mat_dome)
    
    # 危险警示条纹
    for x in [-0.6, 0.6]:
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(x, 0, 0.25))
        stripe = bpy.context.active_object
        stripe.name = f"HazardStripe_{x}"
        stripe.scale = (0.1, 0.9, 0.05)
        mat_stripe = bpy.data.materials.new(name=f"Stripe_{x}")
        mat_stripe.use_nodes = True
        mat_stripe.node_tree.nodes["Principled BSDF"].inputs['Emission'].default_value = (*COLORS['hazard_yellow'], 1.0)
        mat_stripe.node_tree.nodes["Principled BSDF"].inputs['Emission Strength'].default_value = 2.0
        stripe.data.materials.append(mat_stripe)
    
    # 探照灯
    bpy.ops.object.light_add(type='SPOT', location=(0, 0.5, 1.5))
    spot = bpy.context.active_object
    spot.name = "RoverSpotlight"
    spot.data.energy = 200
    spot.data.spot_size = math.radians(60)
    spot.data.color = COLORS['light_white']
    spot.rotation_euler = (math.radians(45), 0, 0)

def add_dust_storm_zone():
    """添加尘暴特效触发区（表演用）"""
    bpy.ops.mesh.primitive_circle_add(
        radius=1.5,
        fill_type='NGON',
        location=(0, -4, 0.02)
    )
    zone = bpy.context.active_object
    zone.name = "DustStormZone"
    
    mat = bpy.data.materials.new(name="DustZone")
    mat.use_nodes = True
    mat.node_tree.nodes["Principled BSDF"].inputs['Emission'].default_value = (*COLORS['mars_dust'], 0.5)
    mat.node_tree.nodes["Principled BSDF"].inputs['Emission Strength'].default_value = 1.0
    zone.data.materials.append(mat)
    
    return {
        "id": "dust_storm_zone",
        "type": "effect_zone",
        "label": "尘暴特效区",
        "position": {"x": 0, "y": -4, "z": 0},
        "visible": True,
        "npc_stop_point": {
            "position": [0, 0, -3],
            "look_at": [0, 1.0, -4]
        },
        "tags": ["special_skill", "effect", "transformation"]
    }

def add_rover_drone():
    """添加无人机/火星车机器人出生点"""
    bpy.ops.mesh.primitive_cylinder_add(
        radius=0.3,
        depth=0.1,
        location=(3, 3, 0.05)
    )
    pad = bpy.context.active_object
    pad.name = "DronePad"
    
    mat = bpy.data.materials.new(name="DronePad")
    mat.use_nodes = True
    mat.node_tree.nodes["Principled BSDF"].inputs['Emission'].default_value = (*COLORS['hazard_yellow'], 1.0)
    mat.node_tree.nodes["Principled BSDF"].inputs['Emission Strength'].default_value = 3.0
    pad.data.materials.append(mat)
    
    # 着陆灯
    bpy.ops.object.light_add(type='POINT', location=(3, 3, 0.5))
    light = bpy.context.active_object
    light.name = "DronePadLight"
    light.data.energy = 50
    light.data.color = COLORS['hazard_yellow']

def setup_mars_lighting():
    """设置火星光照（暖色、方向性）"""
    for obj in bpy.data.objects:
        if obj.type == 'LIGHT':
            bpy.data.objects.remove(obj)
    
    # 主光源（模拟火星日落）
    bpy.ops.object.light_add(type='SUN', location=(5, -5, 8))
    sun = bpy.context.active_object
    sun.name = "MarsSun"
    sun.data.energy = 3
    sun.data.color = (1.0, 0.7, 0.5)  # 橙色阳光
    sun.rotation_euler = (math.radians(45), 0, math.radians(45))
    
    # 补光（模拟地面反射）
    bpy.ops.object.light_add(type='AREA', location=(0, 0, 3))
    fill = bpy.context.active_object
    fill.name = "MarsFill"
    fill.data.energy = 50
    fill.data.size = 5.0
    fill.data.color = COLORS['mars_orange']

def export_scene():
    """导出场景"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    filepath = os.path.join(OUTPUT_DIR, "scene.gltf")
    bpy.ops.export_scene.gltf(
        filepath=filepath,
        export_format='GLTF_SEPARATE',
        export_materials='EXPORT',
        export_yup=True,
        export_apply=True,
    )
    
    # 配置
    objects = []
    
    # 岩石展示台
    for display in ROCK_DISPLAYS:
        obj_data = create_rock_display(display['pos'][0], display['pos'][1], display['height'], display['sku'])
        objects.append(obj_data)
    
    # 尘暴区
    objects.append(add_dust_storm_zone())
    
    # 无人机停机坪
    objects.append({
        "id": "drone_pad",
        "type": "spawn_point",
        "label": "无人机停机坪",
        "position": {"x": 3, "y": 3, "z": 0},
        "visible": True,
        "npc_stop_point": {
            "position": [3, 0, 2.5],
            "look_at": [0, 1.0, 0]
        }
    })
    
    config = {
        "id": SCENE_ID,
        "name": SCENE_NAME,
        "description": "火星基地直播间，火星车驾驶舱主播位，岩石展示台，尘暴特效区",
        "environment": SCENE_ID,
        "host_position_3d": {"x": 0, "y": 0.9, "z": -0.2},
        "objects": objects,
        "slots": [
            {"id": f"slot_{i+1}", "x": 15 + (i % 2) * 35, "y": 20 + (i // 2) * 30,
             "width": 18, "height": 18, "sku_id": display['sku'], "label": f"火星商品{i+1}"}
            for i, display in enumerate(ROCK_DISPLAYS)
        ]
    }
    
    config_path = os.path.join(OUTPUT_DIR, "scene_config.json")
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    
    return filepath, config_path

def main():
    print("=" * 60)
    print("🪐 火星基地场景改造")
    print("=" * 60)
    
    print("[1/5] 添加火星车主播位...")
    add_mars_rover_host()
    
    print("[2/5] 添加岩石展示台...")
    for display in ROCK_DISPLAYS:
        create_rock_display(display['pos'][0], display['pos'][1], display['height'], display['sku'])
    
    print("[3/5] 添加尘暴特效区...")
    add_dust_storm_zone()
    
    print("[4/5] 添加无人机停机坪...")
    add_rover_drone()
    
    print("[5/5] 设置火星光照并导出...")
    setup_mars_lighting()
    gltf_path, config_path = export_scene()
    
    print("=" * 60)
    print("✅ 火星基地生成完成!")
    print(f"📁 场景: {gltf_path}")
    print(f"📁 配置: {config_path}")
    print("=" * 60)
    print("\n功能区域:")
    print("  🚗 中央: 火星车驾驶舱主播位")
    print("  🪨 四周: 4个岩石展示台（玻璃罩保护）")
    print("  🌪️ 后方: 尘暴特效区（变身/技能表演）")
    print("  🚁 侧方: 无人机停机坪（机器人出生点）")

if __name__ == "__main__":
    main()
