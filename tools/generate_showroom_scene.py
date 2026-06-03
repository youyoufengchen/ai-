"""
现代商务展厅直播间场景生成器
带视频播放大屏，适合NPC产品介绍演示

核心功能:
- 主播讲解台（中央/前方）
- 后方大型LED视频屏（播放产品视频）
- 两侧商品展示区
- 明确的NPC停靠点和视线规划

使用方法:
    blender --background --python tools/generate_showroom_scene.py
"""

import bpy
import math
import os
import json
from mathutils import Vector

# ═══════════════════════════════════════════════════════════
# 配置参数
OUTPUT_PATH = "D:/新建文件夹 (2)/assets/scenes/modern_showroom"
SCENE_ID = "modern_showroom"
SCENE_NAME = "商务展厅"

# 商务配色（黑白金，高端简洁）
COLORS = {
    'floor_dark': (0.08, 0.08, 0.1),      # 深灰地板
    'wall_light': (0.95, 0.95, 0.97),     # 浅灰白墙
    'accent_gold': (0.9, 0.75, 0.3),      # 金色点缀
    'led_blue': (0.2, 0.6, 1.0),          # LED屏冷光
    'led_glow': (0.3, 0.7, 1.0),          # 屏幕发光
    'product_white': (0.98, 0.98, 0.99),  # 展示台
    'host_black': (0.1, 0.1, 0.12),       # 主播台
}

# 商品展示台配置（左右两侧）
DISPLAY_PODS = [
    # 左侧展示区
    {"pos": (-2.5, 1), "type": "tall", "sku": "product_01", "label": "爆款A"},
    {"pos": (-2.5, 3), "type": "wide", "sku": "product_02", "label": "新品B"},
    # 右侧展示区
    {"pos": (2.5, 1), "type": "tall", "sku": "product_03", "label": "经典C"},
    {"pos": (2.5, 3), "type": "wide", "sku": "product_04", "label": "限量D"},
]

# 视频播放屏配置
VIDEO_SCREEN = {
    "position": (0, 5.5, 2.5),  # 后方中央，高度2.5米
    "size": (4.5, 2.5),         # 宽4.5米，高2.5米
    "led_spacing": 0.02,        # LED点阵间距
}

# ═══════════════════════════════════════════════════════════
# 工具函数

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
    """创建PBR材质（兼容Blender 4.x/5.x）"""
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs['Base Color'].default_value = (*color, 1.0)
    bsdf.inputs['Roughness'].default_value = roughness
    bsdf.inputs['Metallic'].default_value = metallic
    if emit > 0:
        # Blender 4.x/5.x: Emission 改名为 Emission Color
        if 'Emission Color' in bsdf.inputs:
            bsdf.inputs['Emission Color'].default_value = (*color, 1.0)
        elif 'Emission' in bsdf.inputs:
            bsdf.inputs['Emission'].default_value = (*color, 1.0)
        # Emission Strength 始终存在
        if 'Emission Strength' in bsdf.inputs:
            bsdf.inputs['Emission Strength'].default_value = emit
    return mat

def create_led_screen_material(name, led_color, grid_size=0.02):
    """创建LED点阵屏幕材质（兼容Blender 4.x/5.x）"""
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    
    # 使用节点创建点阵效果
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    
    # 清除默认节点
    nodes.clear()
    
    # 输出节点
    output = nodes.new('ShaderNodeOutputMaterial')
    output.location = (400, 0)
    
    # 发光BSDF
    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.location = (100, 0)
    bsdf.inputs['Base Color'].default_value = (0.02, 0.02, 0.02, 1.0)  # 黑底
    bsdf.inputs['Roughness'].default_value = 0.1
    
    # 兼容不同版本的Emission输入名
    if 'Emission Color' in bsdf.inputs:
        bsdf.inputs['Emission Color'].default_value = (*led_color, 1.0)
    elif 'Emission' in bsdf.inputs:
        bsdf.inputs['Emission'].default_value = (*led_color, 1.0)
    
    if 'Emission Strength' in bsdf.inputs:
        bsdf.inputs['Emission Strength'].default_value = 3.0
    
    links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])
    
    return mat

# ═══════════════════════════════════════════════════════════
# 场景构建

def build_floor():
    """创建深色地板 + 金色装饰线"""
    # 主地板
    bpy.ops.mesh.primitive_plane_add(size=1.0, location=(0, 2, 0))
    floor = bpy.context.active_object
    floor.name = "Floor_Main"
    floor.scale = (6, 7, 1)
    
    mat = create_material("Floor_Dark", COLORS['floor_dark'], roughness=0.2)
    floor.data.materials.append(mat)
    
    # 金色装饰线条（引导视线到视频屏）
    for x in [-1, 0, 1]:
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(x, 2, 0.01))
        line = bpy.context.active_object
        line.name = f"Floor_Guide_{x}"
        line.scale = (0.02, 7, 0.01)
        mat_line = create_material("Guide_Gold", COLORS['accent_gold'], metallic=0.8, emit=0.5)
        line.data.materials.append(mat_line)
    
    print("[1/6] 地板与引导线已创建")

def build_video_screen():
    """创建大型LED视频播放屏"""
    x, y, z = VIDEO_SCREEN["position"]
    width, height = VIDEO_SCREEN["size"]
    
    # 主屏幕
    bpy.ops.mesh.primitive_plane_add(size=1.0, location=(x, y, z))
    screen = bpy.context.active_object
    screen.name = "Video_Screen_Main"
    screen.scale = (width, height, 1)
    
    # LED点阵材质
    mat = create_led_screen_material("LED_Screen", COLORS['led_blue'])
    screen.data.materials.append(mat)
    
    # 屏幕边框（金属质感）
    border_thick = 0.1
    bpy.ops.mesh.primitive_cube_add(
        size=1.0, 
        location=(x, y - border_thick/2, z)
    )
    border = bpy.context.active_object
    border.name = "Screen_Border"
    border.scale = (width + border_thick, border_thick, height + border_thick)
    
    mat_border = create_material("Screen_Frame", (0.15, 0.15, 0.18), metallic=0.6)
    border.data.materials.append(mat_border)
    
    # 屏幕上方射灯（照亮主播位）
    bpy.ops.object.light_add(type='SPOT', location=(x, y - 1, z + 1))
    spot = bpy.context.active_object
    spot.name = "Screen_Spotlight"
    spot.data.energy = 150
    spot.data.spot_size = math.radians(45)
    spot.data.color = COLORS['led_blue']
    spot.rotation_euler = (math.radians(-30), 0, 0)
    
    # 屏幕下方状态灯条
    bpy.ops.mesh.primitive_cube_add(
        size=1.0,
        location=(x, y, z - height/2 - 0.05)
    )
    status = bpy.context.active_object
    status.name = "Screen_Status_LED"
    status.scale = (width, 0.05, 0.02)
    mat_status = create_material("Status_LED", COLORS['accent_gold'], emit=2.0)
    status.data.materials.append(mat_status)
    
    print("[2/6] 视频播放屏已创建")
    return screen

def build_host_station():
    """创建主播讲解台"""
    # 主播站立平台
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=16,
        radius=0.8,
        depth=0.15,
        location=(0, 0, 0.075)
    )
    platform = bpy.context.active_object
    platform.name = "Host_Platform"
    
    mat = create_material("Host_Platform", COLORS['host_black'], metallic=0.3)
    platform.data.materials.append(mat)
    
    # 主播讲台/控制台
    bpy.ops.mesh.primitive_cube_add(
        size=1.0,
        location=(0, -0.3, 0.5)
    )
    podium = bpy.context.active_object
    podium.name = "Host_Podium"
    podium.scale = (0.6, 0.4, 0.8)
    
    mat_podium = create_material("Podium", COLORS['product_white'], roughness=0.1)
    podium.data.materials.append(mat_podium)
    
    # 讲台上的话筒
    bpy.ops.mesh.primitive_cylinder_add(
        radius=0.02,
        depth=0.3,
        location=(0, -0.4, 1.0)
    )
    mic = bpy.context.active_object
    mic.name = "Microphone"
    mic.scale = (1, 1, 1)
    mat_mic = create_material("Mic_Metal", (0.3, 0.3, 0.35), metallic=0.8)
    mic.data.materials.append(mat_mic)
    
    # 话筒头
    bpy.ops.mesh.primitive_uv_sphere_add(
        radius=0.04,
        location=(0, -0.4, 1.18)
    )
    mic_head = bpy.context.active_object
    mic_head.name = "Mic_Head"
    mat_head = create_material("Mic_Foam", (0.1, 0.1, 0.12))
    mic_head.data.materials.append(mat_head)
    
    # 提词器（透明屏，对着主播）
    bpy.ops.mesh.primitive_plane_add(
        size=1.0,
        location=(0, 0.5, 0.8)
    )
    teleprompter = bpy.context.active_object
    teleprompter.name = "Teleprompter"
    teleprompter.scale = (0.4, 0.3, 1)
    teleprompter.rotation_euler = (math.radians(60), 0, 0)
    
    mat_tel = bpy.data.materials.new(name="Teleprompter_Glass")
    mat_tel.use_nodes = True
    bsdf = mat_tel.node_tree.nodes["Principled BSDF"]
    # 兼容不同版本的BSDF输入
    if 'Transmission' in bsdf.inputs:
        bsdf.inputs['Transmission'].default_value = 0.7
    elif 'Transmission Weight' in bsdf.inputs:
        bsdf.inputs['Transmission Weight'].default_value = 0.7
    bsdf.inputs['Base Color'].default_value = (0.9, 0.95, 1.0, 0.3)
    bsdf.inputs['Roughness'].default_value = 0.1
    teleprompter.data.materials.append(mat_tel)
    
    print("[3/6] 主播讲解台已创建")

def build_product_display(x, y, display_type, sku, label):
    """创建商品展示台"""
    pod_id = f"display_{sku}"
    
    if display_type == "tall":
        # 立式展示（适合高产品）
        bpy.ops.mesh.primitive_cylinder_add(
            radius=0.4,
            depth=1.2,
            location=(x, y, 0.6)
        )
        stand = bpy.context.active_object
        stand.name = f"{pod_id}_Stand"
        
        mat = create_material(f"Stand_{sku}", COLORS['product_white'], roughness=0.1)
        stand.data.materials.append(mat)
        
        # 顶部展示面
        bpy.ops.mesh.primitive_cylinder_add(
            radius=0.35,
            depth=0.05,
            location=(x, y, 1.22)
        )
        top = bpy.context.active_object
        top.name = f"{pod_id}_Top"
        mat_top = create_material(f"Top_{sku}", COLORS['accent_gold'], metallic=0.8)
        top.data.materials.append(mat_top)
        
        # 品牌标签
        bpy.ops.mesh.primitive_plane_add(
            size=1.0,
            location=(x, y - 0.35, 0.8)
        )
        label_obj = bpy.context.active_object
        label_obj.name = f"{pod_id}_Label"
        label_obj.scale = (0.3, 0.15, 1)
        label_obj.rotation_euler = (math.radians(90), 0, 0)
        
        mat_label = create_material(f"Label_{sku}", (0.2, 0.2, 0.25))
        label_obj.data.materials.append(mat_label)
        
        # 展示台射灯
        bpy.ops.object.light_add(type='SPOT', location=(x, y - 1, 2))
        spot = bpy.context.active_object
        spot.name = f"{pod_id}_Spot"
        spot.data.energy = 80
        spot.data.spot_size = math.radians(30)
        spot.data.color = COLORS['product_white'][:3]
        spot.rotation_euler = (math.radians(45), 0, 0)
        
    else:  # wide
        # 宽式展示（适合平放产品）
        bpy.ops.mesh.primitive_cube_add(
            size=1.0,
            location=(x, y, 0.4)
        )
        table = bpy.context.active_object
        table.name = f"{pod_id}_Table"
        table.scale = (0.8, 0.5, 0.08)
        
        mat = create_material(f"Table_{sku}", COLORS['product_white'], roughness=0.1)
        table.data.materials.append(mat)
        
        # 桌腿
        for dx in [-0.3, 0.3]:
            bpy.ops.mesh.primitive_cylinder_add(
                radius=0.03,
                depth=0.4,
                location=(x + dx, y, 0.2)
            )
            leg = bpy.context.active_object
            leg.name = f"{pod_id}_Leg_{dx}"
            mat_leg = create_material(f"Leg_{sku}", COLORS['host_black'])
            leg.data.materials.append(mat_leg)
        
        # 展示灯光
        bpy.ops.object.light_add(type='POINT', location=(x, y, 1.2))
        light = bpy.context.active_object
        light.name = f"{pod_id}_Light"
        light.data.energy = 50
        light.data.color = COLORS['accent_gold']
    
    # 计算停靠点（主播面向展示台）
    # 主播在 (0, 0)，展示台在 (x, y)
    # 停靠点在两者的中点附近
    stop_x = x * 0.6
    stop_y = y * 0.6
    
    return {
        "id": pod_id,
        "type": "product_display",
        "label": label,
        "position": {"x": x, "y": y, "z": 0},
        "sku_id": sku,
        "display_type": display_type,
        "visible": True,
        "npc_stop_point": {
            "position": [stop_x, 0, stop_y],
            "look_at": [x, 1.0, y]  # 看展示台
        }
    }

def build_robot_zone():
    """创建机器人待命区（侧后方）"""
    x, y = 4.5, 4
    
    # 待命平台
    bpy.ops.mesh.primitive_circle_add(
        radius=0.6,
        fill_type='NGON',
        location=(x, y, 0.02)
    )
    zone = bpy.context.active_object
    zone.name = "Robot_Standby_Zone"
    
    mat = create_material("Robot_Zone", COLORS['accent_gold'], emit=1.0)
    zone.data.materials.append(mat)
    
    # 指示柱
    bpy.ops.mesh.primitive_cylinder_add(
        radius=0.05,
        depth=1.5,
        location=(x, y, 0.75)
    )
    pillar = bpy.context.active_object
    pillar.name = "Robot_Pillar"
    mat_pillar = create_material("Pillar", COLORS['led_blue'], emit=2.0)
    pillar.data.materials.append(mat_pillar)

def build_lighting():
    """设置专业演播室灯光"""
    # 清除默认灯光
    for obj in bpy.data.objects:
        if obj.type == 'LIGHT':
            bpy.data.objects.remove(obj)
    
    # 主播主光源（前方45度）
    bpy.ops.object.light_add(type='AREA', location=(-2, -2, 3))
    key = bpy.context.active_object
    key.name = "Key_Light"
    key.data.energy = 150
    key.data.size = 2.0
    key.data.color = (1.0, 0.98, 0.95)
    key.rotation_euler = (math.radians(45), 0, math.radians(-30))
    
    # 补光（另一侧）
    bpy.ops.object.light_add(type='AREA', location=(2, -2, 2.5))
    fill = bpy.context.active_object
    fill.name = "Fill_Light"
    fill.data.energy = 80
    fill.data.size = 1.5
    fill.data.color = (0.9, 0.95, 1.0)
    
    # 背景光（照亮视频屏区域）
    bpy.ops.object.light_add(type='AREA', location=(0, 6, 4))
    back = bpy.context.active_object
    back.name = "Back_Light"
    back.data.energy = 100
    back.data.size = 4.0
    back.data.color = COLORS['led_blue']
    
    print("[4/6] 灯光系统已设置")

def export_scene():
    """导出GLTF和配置"""
    os.makedirs(OUTPUT_PATH, exist_ok=True)
    
    # 导出GLTF
    filepath = os.path.join(OUTPUT_PATH, "scene.gltf")
    bpy.ops.export_scene.gltf(
        filepath=filepath,
        export_format='GLTF_SEPARATE',
        export_materials='EXPORT',
        export_yup=True,
        export_apply=True,
    )
    
    # 构建配置
    objects = []
    
    # 视频播放屏配置
    objects.append({
        "id": "video_screen_main",
        "type": "video_screen",
        "label": "产品视频大屏",
        "position": {"x": 0, "y": 5.5, "z": 2.5},
        "screen_size": {"width": 4.5, "height": 2.5},
        "visible": True,
        "npc_stop_point": {
            "position": [0, 0, 3.5],  # 主播转身看屏幕的位置
            "look_at": [0, 2.5, 5.5]  # 看屏幕中心
        },
        "tags": ["video", "presentation"]
    })
    
    # 商品展示台
    for display in DISPLAY_PODS:
        obj_data = build_product_display(
            display['pos'][0],
            display['pos'][1],
            display['type'],
            display['sku'],
            display['label']
        )
        objects.append(obj_data)
    
    # 机器人区
    objects.append({
        "id": "robot_standby",
        "type": "spawn_point",
        "label": "机器人待命区",
        "position": {"x": 4.5, "y": 4, "z": 0},
        "visible": False,
        "npc_stop_point": {
            "position": [4, 0, 3.5],
            "look_at": [0, 1.0, 0]
        }
    })
    
    config = {
        "id": SCENE_ID,
        "name": SCENE_NAME,
        "description": "现代商务展厅直播间，带大型LED视频播放屏，主播讲解台，两侧商品展示区，适合NPC产品介绍演示",
        "environment": SCENE_ID,
        "host_position_3d": {"x": 0, "y": 0.1, "z": 0},
        "objects": objects,
        "slots": [
            {"id": "slot_1", "x": 15, "y": 25, "width": 15, "height": 20, "sku_id": "product_01", "label": "爆款A"},
            {"id": "slot_2", "x": 15, "y": 55, "width": 15, "height": 20, "sku_id": "product_02", "label": "新品B"},
            {"id": "slot_3", "x": 70, "y": 25, "width": 15, "height": 20, "sku_id": "product_03", "label": "经典C"},
            {"id": "slot_4", "x": 70, "y": 55, "width": 15, "height": 20, "sku_id": "product_04", "label": "限量D"},
        ],
        "video_screen": {
            "id": "video_screen_main",
            "video_url": "/assets/videos/product_demo.mp4",
            "trigger": "npc_present",  # NPC展示产品时触发
            "auto_play": False
        }
    }
    
    config_path = os.path.join(OUTPUT_PATH, "scene_config.json")
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    
    print("[5/6] 场景已导出")
    print(f"    GLTF: {filepath}")
    print(f"    配置: {config_path}")
    
    return filepath, config_path

# ═══════════════════════════════════════════════════════════
# 主流程

def main():
    print("=" * 60)
    print("🏢 现代商务展厅直播间生成器")
    print("=" * 60)
    
    clear_scene()
    print("[0/6] 场景已清空")
    
    build_floor()
    build_video_screen()
    build_host_station()
    
    print("[3/6] 创建商品展示区...")
    for display in DISPLAY_PODS:
        build_product_display(
            display['pos'][0],
            display['pos'][1],
            display['type'],
            display['sku'],
            display['label']
        )
    
    build_robot_zone()
    build_lighting()
    
    gltf_path, config_path = export_scene()
    
    print("=" * 60)
    print("✅ 商务展厅生成完成!")
    print(f"📁 输出目录: {OUTPUT_PATH}")
    print("=" * 60)
    print("\n🎬 场景功能:")
    print("  📺 后方: 4.5×2.5米 LED视频播放屏")
    print("  🎤 中央: 主播讲解台（带话筒+提词器）")
    print("  🏷️ 两侧: 4个商品展示台（立式+宽式）")
    print("  🤖 侧后: 机器人待命区")
    print("\n🎯 NPC动作路径:")
    print("  主播位 → 展示台（取货）→ 屏幕前（看视频讲解）→ 观众位（展示）")

if __name__ == "__main__":
    main()
