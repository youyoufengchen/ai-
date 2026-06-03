"""
生成古风舞台式直播间场景 (P4 - 文化展示型)
仿古建筑风格，博古架 + 表演台，适合文创/汉服/茶叶/国潮

使用方法:
    blender --background --python tools/generate_temple_scene.py
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
OUTPUT_PATH = "D:/新建文件夹 (2)/assets/scenes/temple_classical"
SCENE_ID = "temple_classical"
SCENE_NAME = "古风雅阁"

# 中国风配色
COLORS = {
    'floor_wood': (0.4, 0.25, 0.15),   # 深木色
    'floor_mat': (0.85, 0.75, 0.65),    # 草席色
    'pillar_red': (0.6, 0.15, 0.1),    # 朱红色柱子
    'pillar_gold': (0.9, 0.75, 0.3),    # 金色装饰
    'wall_paper': (0.9, 0.85, 0.75),    # 米黄墙纸
    'roof_tile': (0.3, 0.25, 0.2),     # 深灰瓦片
    'lantern': (0.95, 0.7, 0.3),        # 灯笼暖光
    'jade': (0.4, 0.7, 0.6),           # 玉石色点缀
}

# 展示架配置 - 博古架形式
DISPLAY_SHELVES = [
    # 左侧博古架
    {"pos": (-3, -1.5), "size": (0.4, 1.2, 2.0), "shelves": 4, "sku": "cultural_01"},
    {"pos": (-3, 1.0), "size": (0.4, 1.2, 2.0), "shelves": 4, "sku": "cultural_02"},
    # 右侧博古架
    {"pos": (3, -1.5), "size": (0.4, 1.2, 2.0), "shelves": 4, "sku": "cultural_03"},
    {"pos": (3, 1.0), "size": (0.4, 1.2, 2.0), "shelves": 4, "sku": "cultural_04"},
    # 后方矮架
    {"pos": (-1.5, 4), "size": (0.3, 0.8, 1.2), "shelves": 3, "sku": "cultural_05"},
    {"pos": (0, 4), "size": (0.3, 0.8, 1.2), "shelves": 3, "sku": "cultural_06"},
    {"pos": (1.5, 4), "size": (0.3, 0.8, 1.2), "shelves": 3, "sku": "cultural_07"},
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

def create_material(name, color, roughness=0.5, metallic=0.0):
    """创建材质"""
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs['Base Color'].default_value = (*color, 1.0)
        bsdf.inputs['Roughness'].default_value = roughness
        bsdf.inputs['Metallic'].default_value = metallic
    return mat

def create_wood_material(name, color, grain_scale=1.0):
    """创建木纹材质（带纹理坐标）"""
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    
    # 简化版 - 基础木纹色
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs['Base Color'].default_value = (*color, 1.0)
        bsdf.inputs['Roughness'].default_value = 0.6
        bsdf.inputs['Metallic'].default_value = 0.0
    
    return mat

def create_paper_screen_material():
    """创建宣纸/屏风材质"""
    mat = bpy.data.materials.new(name="Paper_Screen")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs['Base Color'].default_value = (0.92, 0.88, 0.78, 1.0)
        bsdf.inputs['Roughness'].default_value = 0.9
        bsdf.inputs['Subsurface'].default_value = 0.1
        bsdf.inputs['Subsurface Color'].default_value = (0.95, 0.9, 0.8, 1.0)
    return mat

# ═══════════════════════════════════════════════════════════
#  场景构建
# ═══════════════════════════════════════════════════════════

def build_floor():
    """创建木地板 + 草席区域"""
    # 主木地板
    bpy.ops.mesh.primitive_plane_add(
        size=1.0,
        location=(0, 1, 0)
    )
    floor = bpy.context.active_object
    floor.name = "Floor_Wood"
    floor.scale = (8, 8, 1)
    
    mat = create_wood_material("Wood_Floor", COLORS['floor_wood'])
    floor.data.materials.append(mat)
    
    # 中央草席区
    bpy.ops.mesh.primitive_plane_add(
        size=1.0,
        location=(0, 1, 0.01)
    )
    mat_area = bpy.context.active_object
    mat_area.name = "Floor_Mat"
    mat_area.scale = (3, 4, 1)
    
    mat = create_material("Straw_Mat", COLORS['floor_mat'], roughness=0.9)
    mat_area.data.materials.append(mat)
    
    # 边缘装饰线
    for x in [-3.8, 3.8]:
        bpy.ops.mesh.primitive_cube_add(
            size=1.0,
            location=(x, 1, 0.02)
        )
        edge = bpy.context.active_object
        edge.name = f"Floor_Edge_{x}"
        edge.scale = (0.1, 8, 0.02)
        mat_edge = create_wood_material("Dark_Wood_Edge", (0.25, 0.15, 0.1))
        edge.data.materials.append(mat_edge)

def build_pillars():
    """创建朱红柱子 + 金色装饰"""
    pillar_positions = [
        (-3.5, -3), (3.5, -3),
        (-3.5, 3), (3.5, 3),
    ]
    
    for i, (x, y) in enumerate(pillar_positions):
        # 主柱
        bpy.ops.mesh.primitive_cylinder_add(
            radius=0.15,
            depth=4.0,
            location=(x, y, 2)
        )
        pillar = bpy.context.active_object
        pillar.name = f"Pillar_{i}"
        
        mat = create_material("Pillar_Red", COLORS['pillar_red'], roughness=0.3)
        pillar.data.materials.append(mat)
        
        # 柱础（底部装饰）
        bpy.ops.mesh.primitive_cylinder_add(
            radius=0.25,
            depth=0.2,
            location=(x, y, 0.1)
        )
        base = bpy.context.active_object
        base.name = f"Pillar_Base_{i}"
        mat_base = create_material("Pillar_Gold", COLORS['pillar_gold'], roughness=0.2, metallic=0.8)
        base.data.materials.append(mat_base)
        
        # 柱头（顶部装饰）
        bpy.ops.mesh.primitive_cylinder_add(
            radius=0.22,
            depth=0.15,
            location=(x, y, 3.95)
        )
        top = bpy.context.active_object
        top.name = f"Pillar_Top_{i}"
        top.data.materials.append(mat_base)

def build_roof_structure():
    """创建屋顶框架 - 简化中式飞檐"""
    # 横梁
    for y in [-3, 3]:
        bpy.ops.mesh.primitive_cube_add(
            size=1.0,
            location=(0, y, 3.8)
        )
        beam = bpy.context.active_object
        beam.name = f"Beam_{y}"
        beam.scale = (8, 0.15, 0.2)
        
        mat = create_wood_material("Beam_Wood", (0.3, 0.2, 0.12))
        beam.data.materials.append(mat)
    
    # 纵梁
    for x in [-3.5, 3.5]:
        bpy.ops.mesh.primitive_cube_add(
            size=1.0,
            location=(x, 0, 3.8)
        )
        beam = bpy.context.active_object
        beam.name = f"Beam_V_{x}"
        beam.scale = (0.15, 7, 0.2)
        beam.data.materials.append(mat)
    
    # 中央藻井（天花板装饰）
    bpy.ops.mesh.primitive_plane_add(
        size=1.0,
        location=(0, 1, 3.9)
    )
    ceiling = bpy.context.active_object
    ceiling.name = "Ceiling_Center"
    ceiling.scale = (3, 3, 1)
    
    mat = create_material("Ceiling_Pattern", (0.7, 0.5, 0.3), roughness=0.4)
    ceiling.data.materials.append(mat)

def build_host_area():
    """创建主播位 - 茶席/案几"""
    # 主案几
    bpy.ops.mesh.primitive_cube_add(
        size=1.0,
        location=(0, 1, 0.4)
    )
    table = bpy.context.active_object
    table.name = "Host_Table"
    table.scale = (1.2, 0.6, 0.08)
    
    mat = create_wood_material("Table_Wood", (0.35, 0.22, 0.12))
    table.data.materials.append(mat)
    
    # 案几腿
    leg_positions = [
        (-0.5, -0.2), (0.5, -0.2),
        (-0.5, 0.2), (0.5, 0.2)
    ]
    for i, (lx, ly) in enumerate(leg_positions):
        bpy.ops.mesh.primitive_cylinder_add(
            radius=0.04,
            depth=0.4,
            location=(lx, 1 + ly, 0.2)
        )
        leg = bpy.context.active_object
        leg.name = f"Table_Leg_{i}"
        leg.data.materials.append(mat)
    
    # 坐垫（主播位标记）
    bpy.ops.mesh.primitive_cylinder_add(
        radius=0.35,
        depth=0.08,
        location=(0, 1, 0.04)
    )
    cushion = bpy.context.active_object
    cushion.name = "Host_Cushion"
    
    mat_cushion = create_material("Cushion_Red", (0.5, 0.1, 0.05), roughness=0.8)
    cushion.data.materials.append(mat_cushion)
    
    return {"position": {"x": 0, "y": 0.4, "z": 1}, "rotation": {"x": 0, "y": 0, "z": 0}}

def build_classical_shelf(x, y, width, depth, height, shelves, sku):
    """创建博古架 - 中式多宝格"""
    shelf_id = f"shelf_{int(x)}_{int(y)}"
    
    # 主体框架 - 外框
    bpy.ops.mesh.primitive_cube_add(
        size=1.0,
        location=(x, y, height/2)
    )
    frame = bpy.context.active_object
    frame.name = f"{shelf_id}_Frame"
    frame.scale = (width, depth, height)
    
    mat = create_wood_material("Shelf_Wood", (0.3, 0.18, 0.1))
    frame.data.materials.append(mat)
    
    # 内部层板
    for i in range(shelves):
        shelf_y_pos = 0.2 + (height - 0.4) * (i + 0.5) / shelves
        bpy.ops.mesh.primitive_cube_add(
            size=1.0,
            location=(x, y, shelf_y_pos)
        )
        shelf = bpy.context.active_object
        shelf.name = f"{shelf_id}_Level_{i}"
        shelf.scale = (width - 0.05, depth - 0.05, 0.02)
        shelf.data.materials.append(mat)
        
        # 每层放一个小展示台
        if i % 2 == 0:  # 隔层放
            bpy.ops.mesh.primitive_cylinder_add(
                radius=0.08,
                depth=0.05,
                location=(x, y, shelf_y_pos + 0.04)
            )
            stand = bpy.context.active_object
            stand.name = f"{shelf_id}_Stand_{i}"
            mat_stand = create_material("Jade_Stand", COLORS['jade'], roughness=0.2)
            stand.data.materials.append(mat_stand)
    
    # 计算停靠点 - 主播面向博古架
    stop_x = x * 0.6
    stop_y = 1 + (y - 1) * 0.4
    
    return {
        "id": shelf_id,
        "type": "classical_shelf",
        "label": f"博古架 {sku}",
        "position": {"x": x, "y": y, "z": 0},
        "rotation": {"x": 0, "y": 0, "z": 0},
        "scale": 1,
        "sku_id": sku,
        "visible": True,
        "npc_stop_point": {
            "position": [stop_x, 0, stop_y],
            "look_at": [x, 1.2, y]
        }
    }

def build_performance_stage():
    """创建表演台 - 小舞台区域"""
    # 舞台区域
    bpy.ops.mesh.primitive_cube_add(
        size=1.0,
        location=(0, -2.5, 0.15)
    )
    stage = bpy.context.active_object
    stage.name = "Performance_Stage"
    stage.scale = (2.5, 1.5, 0.1)
    
    mat = create_wood_material("Stage_Wood", (0.38, 0.24, 0.14))
    stage.data.materials.append(mat)
    
    # 舞台边缘装饰
    for x in [-1.2, 1.2]:
        bpy.ops.mesh.primitive_cylinder_add(
            radius=0.06,
            depth=0.12,
            location=(x, -2.5, 0.21)
        )
        post = bpy.context.active_object
        post.name = f"Stage_Post_{x}"
        mat_post = create_material("Stage_Gold", COLORS['pillar_gold'], roughness=0.3, metallic=0.8)
        post.data.materials.append(mat_post)
    
    return {"position": {"x": 0, "y": 0.2, "z": -2.5}, "rotation": {"x": 0, "y": 0, "z": 0}}

def build_lanterns():
    """创建悬挂灯笼"""
    lantern_positions = [
        (-2, 0, 3.2), (2, 0, 3.2),
        (-2, 2, 3.2), (2, 2, 3.2),
    ]
    
    for i, (x, y, z) in enumerate(lantern_positions):
        # 灯笼主体
        bpy.ops.mesh.primitive_uv_sphere_add(
            radius=0.25,
            segments=16,
            ring_count=12,
            location=(x, y, z)
        )
        lantern = bpy.context.active_object
        lantern.name = f"Lantern_{i}"
        lantern.scale = (1, 1, 1.3)
        
        mat = create_material("Lantern_Paper", COLORS['lantern'], roughness=0.8)
        lantern.data.materials.append(mat)
        
        # 灯笼穗
        bpy.ops.mesh.primitive_cylinder_add(
            radius=0.02,
            depth=0.4,
            location=(x, y, z - 0.4)
        )
            tassel = bpy.context.active_object
        tassel.name = f"Lantern_Tassel_{i}"
        mat_tassel = create_material("Tassel_Red", (0.6, 0.1, 0.05))
        tassel.data.materials.append(mat_tassel)
        
        # 点光源
        bpy.ops.object.light_add(type='POINT', location=(x, y, z))
        light = bpy.context.active_object
        light.name = f"Lantern_Light_{i}"
        light.data.energy = 30
        light.data.color = COLORS['lantern']

def build_robot_zone():
    """创建机器人隐蔽区 - 屏风后"""
    # 屏风
    bpy.ops.mesh.primitive_plane_add(
        size=1.0,
        location=(0, 5.5, 1.2)
    )
    screen = bpy.context.active_object
    screen.name = "Robot_Screen"
    screen.scale = (4, 2.4, 1)
    
    mat = create_paper_screen_material()
    screen.data.materials.append(mat)
    
    # 屏风架
    for x in [-2, 2]:
        bpy.ops.mesh.primitive_cube_add(
            size=1.0,
            location=(x, 5.5, 1.2)
        )
            frame = bpy.context.active_object
        frame.name = f"Screen_Frame_{x}"
        frame.scale = (0.08, 0.05, 2.4)
        mat_frame = create_wood_material("Screen_Frame_Wood", (0.25, 0.15, 0.08))
        frame.data.materials.append(mat_frame)

def build_backdrop():
    """创建背景屏风/画卷"""
    # 主背景画卷
    bpy.ops.mesh.primitive_plane_add(
        size=1.0,
        location=(0, 6.8, 2)
    )
    scroll = bpy.context.active_object
    scroll.name = "Backdrop_Scroll"
    scroll.scale = (6, 3, 1)
    scroll.rotation_euler = (math.radians(-5), 0, 0)
    
    mat = create_paper_screen_material()
    scroll.data.materials.append(mat)
    
    # 卷轴杆
    for y in [5.3, 8.3]:
        bpy.ops.mesh.primitive_cylinder_add(
            radius=0.08,
            depth=6.2,
            location=(0, y, 2 + (y - 6.8) * 0.1)
        )
        rod = bpy.context.active_object
        rod.name = f"Scroll_Rod_{y}"
        rod.rotation_euler = (0, 0, math.radians(90))
        mat_rod = create_wood_material("Scroll_Rod_Wood", (0.2, 0.12, 0.06))
        rod.data.materials.append(mat_rod)

def build_lighting():
    """设置古风暖光"""
    # 清除默认灯光
    for obj in bpy.data.objects:
        if obj.type == 'LIGHT':
            bpy.data.objects.remove(obj)
    
    # 主光源 - 暖色顶光
    bpy.ops.object.light_add(type='AREA', location=(0, 1, 5))
    main = bpy.context.active_object
    main.name = "Main_Light_Warm"
    main.data.energy = 120
    main.data.size = 5.0
    main.data.color = (1.0, 0.85, 0.7)  # 暖白光
    
    # 两侧灯笼补光
    for x in [-3, 3]:
        bpy.ops.object.light_add(type='AREA', location=(x, 1, 2.5))
        fill = bpy.context.active_object
        fill.name = f"Fill_Lantern_{x}"
        fill.data.energy = 50
        fill.data.size = 2.0
        fill.data.color = COLORS['lantern']

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
    print(f"[Temple] Exported to: {filepath}")
    return filepath

def generate_scene_config():
    """生成 scenes.json 配置片段"""
    objects = []
    
    # 构建所有博古架
    for shelf in DISPLAY_SHELVES:
        obj_data = build_classical_shelf(
            shelf['pos'][0],
            shelf['pos'][1],
            shelf['size'][0],
            shelf['size'][1],
            shelf['size'][2],
            shelf['shelves'],
            shelf['sku']
        )
        objects.append(obj_data)
    
    # 表演台配置
    objects.append({
        "id": "performance_stage",
        "type": "stage",
        "label": "表演台",
        "position": {"x": 0, "y": 0, "z": -2.5},
        "visible": True,
        "npc_stop_point": {
            "position": [0, 0, -1.5],
            "look_at": [0, 1.0, 0]
        }
    })
    
    # 机器人区
    objects.append({
        "id": "robot_standby",
        "type": "spawn_point",
        "label": "机器人隐藏区",
        "position": {"x": 0, "y": 0, "z": 0},
        "visible": False,
        "npc_stop_point": {
            "position": [0, 0, 6],
            "look_at": [0, 1.0, 1]
        }
    })
    
    scene_config = {
        "id": SCENE_ID,
        "name": SCENE_NAME,
        "description": "古风雅阁直播间，朱红柱子、博古架、茶席案几，适合文创/茶叶/汉服展示，含表演台",
        "environment": SCENE_ID,
        "host_position": {
            "x": 50,
            "y": 55,
            "scale": 1
        },
        "host_position_3d": {
            "x": 0,
            "y": 0.4,
            "z": 1
        },
        "objects": objects,
        "slots": [
            {"id": "slot_1", "x": 15, "y": 30, "width": 14, "height": 14, "sku_id": "cultural_01", "label": "文创1"},
            {"id": "slot_2", "x": 15, "y": 55, "width": 14, "height": 14, "sku_id": "cultural_02", "label": "文创2"},
            {"id": "slot_3", "x": 71, "y": 30, "width": 14, "height": 14, "sku_id": "cultural_03", "label": "文创3"},
            {"id": "slot_4", "x": 71, "y": 55, "width": 14, "height": 14, "sku_id": "cultural_04", "label": "文创4"},
            {"id": "slot_5", "x": 30, "y": 75, "width": 12, "height": 12, "sku_id": "cultural_05", "label": "茶叶1"},
            {"id": "slot_6", "x": 50, "y": 75, "width": 12, "height": 12, "sku_id": "cultural_06", "label": "茶叶2"},
            {"id": "slot_7", "x": 70, "y": 75, "width": 12, "height": 12, "sku_id": "cultural_07", "label": "茶叶3"},
        ]
    }
    
    config_path = os.path.join(OUTPUT_PATH, "scene_config.json")
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(scene_config, f, ensure_ascii=False, indent=2)
    print(f"[Temple] Config saved to: {config_path}")
    
    return scene_config

# ═══════════════════════════════════════════════════════════
#  主流程
# ═══════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("🏛️ 古风雅阁场景生成器")
    print("=" * 60)
    
    clear_scene()
    print("[1/8] 场景已清空")
    
    build_floor()
    print("[2/8] 木地板与草席已创建")
    
    build_pillars()
    print("[3/8] 朱红柱子已创建")
    
    build_roof_structure()
    print("[4/8] 屋顶框架已创建")
    
    build_host_area()
    print("[5/8] 茶席案几已创建")
    
    build_performance_stage()
    print("[6/8] 表演台已创建")
    
    build_lanterns()
    print("[7/8] 悬挂灯笼已创建")
    
    build_robot_zone()
    build_backdrop()
    print("[8/8] 屏风与背景已创建")
    
    print("[+] 创建7个博古架...")
    build_lighting()
    print("[+] 古风暖光系统已设置")
    
    export_gltf()
    generate_scene_config()
    
    print("=" * 60)
    print("✅ 古风雅阁场景生成完成!")
    print(f"📁 输出目录: {OUTPUT_PATH}")
    print("🎨 风格: 中式古典 / 朱红金饰 / 博古架茶席")
    print("=" * 60)

if __name__ == "__main__":
    main()
