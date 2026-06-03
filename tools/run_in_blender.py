import bpy
import sys
import os

# 强制刷新 API
bpy.ops.wm.read_factory_settings()

# 清除现有物体
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)

print("=" * 50)
print("🎬 开始生成环形剧场场景")
print("=" * 50)

# ═══════════════════════════════════════════════════════════
# 颜色定义
floor_color = (0.12, 0.10, 0.08, 1.0)  # 深木色
accent_color = (0.85, 0.65, 0.25, 1.0)  # 金色
light_color = (1.0, 0.95, 0.8, 1.0)    # 暖光

# ═══════════════════════════════════════════════════════════
# 创建地板
bpy.ops.mesh.primitive_circle_add(vertices=64, radius=6.0, fill_type='NGON', location=(0, 0, 0))
floor = bpy.context.active_object
floor.name = "Floor"

# 地板材质
mat_floor = bpy.data.materials.new(name="FloorMat")
mat_floor.use_nodes = True
mat_floor.node_tree.nodes["Principled BSDF"].inputs['Base Color'].default_value = floor_color
floor.data.materials.append(mat_floor)

print("[1/6] 地板已创建")

# ═══════════════════════════════════════════════════════════
# 创建主播位（中央平台）
bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=1.2, depth=0.15, location=(0, 0, 0.075))
platform = bpy.context.active_object
platform.name = "HostPlatform"

mat_platform = bpy.data.materials.new(name="PlatformMat")
mat_platform.use_nodes = True
mat_platform.node_tree.nodes["Principled BSDF"].inputs['Base Color'].default_value = accent_color
mat_platform.node_tree.nodes["Principled BSDF"].inputs['Metallic'].default_value = 0.8
platform.data.materials.append(mat_platform)

# 平台发光环
bpy.ops.mesh.primitive_torus_add(major_radius=1.0, minor_radius=0.03, location=(0, 0, 0.16))
ring = bpy.context.active_object
ring.name = "PlatformRing"
mat_ring = bpy.data.materials.new(name="RingMat")
mat_ring.use_nodes = True
bsdf = mat_ring.node_tree.nodes["Principled BSDF"]
bsdf.inputs['Emission'].default_value = light_color
bsdf.inputs['Emission Strength'].default_value = 3.0
ring.data.materials.append(mat_ring)

print("[2/6] 主播位已创建")

# ═══════════════════════════════════════════════════════════
# 创建展示柜（6个环形排列）
import math

cabinets = []
for i in range(6):
    angle = math.radians(i * 60)
    x = 3.5 * math.sin(angle)
    y = -3.5 * math.cos(angle)
    
    # 玻璃罩
    bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=0.6, depth=1.8, location=(x, y, 1.0))
    cabinet = bpy.context.active_object
    cabinet.name = f"Cabinet_{i}"
    cabinet.scale = (1, 1, 1)
    
    # 玻璃材质
    mat_glass = bpy.data.materials.new(name=f"Glass_{i}")
    mat_glass.use_nodes = True
    bsdf = mat_glass.node_tree.nodes["Principled BSDF"]
    bsdf.inputs['Transmission'].default_value = 0.9
    bsdf.inputs['Roughness'].default_value = 0.05
    bsdf.inputs['IOR'].default_value = 1.45
    cabinet.data.materials.append(mat_glass)
    
    # 底座发光
    bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=0.65, depth=0.1, location=(x, y, 0.05))
    base = bpy.context.active_object
    base.name = f"CabinetBase_{i}"
    mat_base = bpy.data.materials.new(name=f"Base_{i}")
    mat_base.use_nodes = True
    mat_base.node_tree.nodes["Principled BSDF"].inputs['Emission'].default_value = accent_color
    mat_base.node_tree.nodes["Principled BSDF"].inputs['Emission Strength'].default_value = 2.0
    base.data.materials.append(mat_base)
    
    # 内部光源
    bpy.ops.object.light_add(type='POINT', location=(x, y, 1.6))
    light = bpy.context.active_object
    light.name = f"CabinetLight_{i}"
    light.data.energy = 30
    light.data.color = light_color[:3]
    
    cabinets.append(cabinet)

print("[3/6] 6个展示柜已创建")

# ═══════════════════════════════════════════════════════════
# 创建背景墙
bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=8, depth=4, location=(0, 0, 2))
wall = bpy.context.active_object
wall.name = "BackWall"

# 删除前半部分（只留后墙）
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='DESELECT')
bm = bmesh.from_mesh(wall.data)
for vert in bm.verts:
    if vert.co.y > 0:
        vert.select = True
bm.to_mesh(wall.data)
bm.free()
bpy.ops.mesh.delete(type='VERT')
bpy.ops.object.mode_set(mode='OBJECT')

mat_wall = bpy.data.materials.new(name="WallMat")
mat_wall.use_nodes = True
mat_wall.node_tree.nodes["Principled BSDF"].inputs['Base Color'].default_value = (0.05, 0.04, 0.03, 1.0)
wall.data.materials.append(mat_wall)

print("[4/6] 背景墙已创建")

# ═══════════════════════════════════════════════════════════
# 设置灯光
# 清除默认灯光
for obj in bpy.data.objects:
    if obj.type == 'LIGHT':
        bpy.data.objects.remove(obj)

# 主光源
bpy.ops.object.light_add(type='AREA', location=(0, 0, 5))
main = bpy.context.active_object
main.name = "MainLight"
main.data.energy = 200
main.data.size = 3.0
main.data.color = light_color[:3]

print("[5/6] 灯光已设置")

# ═══════════════════════════════════════════════════════════
# 导出GLTF
import json

output_dir = "D:/新建文件夹 (2)/assets/scenes/theater_ring_fast"
os.makedirs(output_dir, exist_ok=True)
filepath = os.path.join(output_dir, "scene.gltf")

bpy.ops.export_scene.gltf(
    filepath=filepath,
    export_format='GLTF_SEPARATE',
    export_materials='EXPORT',
    export_yup=True,
    export_apply=True,
)

print("[6/6] 场景已导出到:", filepath)

# 生成配置
config = {
    "id": "theater_ring_fast",
    "name": "环形剧场(快速版)",
    "environment": "theater_ring_fast",
    "host_position_3d": {"x": 0, "y": 0.15, "z": 0},
    "objects": []
}

for i in range(6):
    angle = math.radians(i * 60)
    x = 3.5 * math.sin(angle)
    y = -3.5 * math.cos(angle)
    stop_x = 2.3 * math.sin(angle)
    stop_y = -2.3 * math.cos(angle)
    
    config["objects"].append({
        "id": f"cabinet_{i}",
        "type": "display_cabinet",
        "position": {"x": x, "y": 0, "z": y},
        "sku_id": f"product_{i+1:02d}",
        "npc_stop_point": {
            "position": [stop_x, 0, stop_y],
            "look_at": [x, 1.0, y]
        }
    })

config_path = os.path.join(output_dir, "scene_config.json")
with open(config_path, 'w', encoding='utf-8') as f:
    json.dump(config, f, ensure_ascii=False, indent=2)

print("=" * 50)
print("✅ 生成完成!")
print(f"📁 场景文件: {filepath}")
print(f"📁 配置文件: {config_path}")
print("=" * 50)
