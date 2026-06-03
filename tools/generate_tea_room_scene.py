#!/usr/bin/env python3
"""
生成基础茶室3D场景 (GLTF格式)

运行方式:
    cd "d:\新建文件夹 (2)"
    .venv\Scripts\python tools\generate_tea_room_scene.py

或直接在Blender中运行:
    1. 打开 Blender
    2. 切换到 Scripting 工作区
    3. 打开此文件并运行
"""

import json
import os
import struct
from pathlib import Path

# 配置
OUTPUT_DIR = Path(__file__).parent.parent / "assets" / "scenes" / "tea_room"
OUTPUT_FILE = OUTPUT_DIR / "scene.gltf"

# 确保输出目录存在
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# GLTF 数据结构
def generate_tea_room_gltf():
    """生成茶室场景的GLTF JSON数据"""
    
    # 基础 GLTF 结构
    gltf = {
        "asset": {
            "version": "2.0",
            "generator": "TeaRoomSceneGenerator"
        },
        "scene": 0,
        "scenes": [
            {
                "name": "Tea Room",
                "nodes": [0, 1, 2, 3, 4, 5, 6]  # floor, back_wall, shelf_01, shelf_02, shelf_03, table, light
            }
        ],
        "nodes": [],
        "meshes": [],
        "materials": [],
        "accessors": [],
        "bufferViews": [],
        "buffers": [],
        "buffer": bytes()
    }
    
    buffer_data = bytearray()
    accessor_index = 0
    buffer_view_index = 0
    mesh_index = 0
    material_index = 0
    
    def add_buffer_view(data, target):
        """添加 buffer view 并返回索引"""
        nonlocal buffer_view_index
        offset = len(buffer_data)
        buffer_data.extend(data)
        # 4字节对齐
        while len(buffer_data) % 4 != 0:
            buffer_data.append(0)
        gltf["bufferViews"].append({
            "buffer": 0,
            "byteOffset": offset,
            "byteLength": len(data)
        })
        idx = buffer_view_index
        buffer_view_index += 1
        return idx
    
    def add_accessor(buffer_view, component_type, count, type_name, max_val=None, min_val=None):
        """添加 accessor 并返回索引"""
        nonlocal accessor_index
        acc = {
            "bufferView": buffer_view,
            "componentType": component_type,
            "count": count,
            "type": type_name
        }
        if max_val:
            acc["max"] = max_val
        if min_val:
            acc["min"] = min_val
        gltf["accessors"].append(acc)
        idx = accessor_index
        accessor_index += 1
        return idx
    
    def create_plane_mesh(width, depth, y_pos=0, name="plane"):
        """创建平面网格"""
        nonlocal mesh_index
        
        # 顶点数据 (位置 + 法线 + UV)
        # 两个三角形组成一个平面
        w, d = width / 2, depth / 2
        vertices = [
            # 位置 (x, y, z)          法线 (0, 1, 0)      UV
            -w, y_pos, -d,            0, 1, 0,            0, 0,
             w, y_pos, -d,            0, 1, 0,            1, 0,
             w, y_pos,  d,            0, 1, 0,            1, 1,
            -w, y_pos,  d,            0, 1, 0,            0, 1,
        ]
        indices = [0, 1, 2, 0, 2, 3]
        
        # 转换为字节
        pos_data = struct.pack('<' + 'f' * len(vertices), *vertices)
        idx_data = struct.pack('<' + 'H' * len(indices), *indices)
        
        # 添加 buffer views
        pos_bv = add_buffer_view(pos_data, 34962)  # ARRAY_BUFFER
        idx_bv = add_buffer_view(idx_data, 34963)  # ELEMENT_ARRAY_BUFFER
        
        # 添加 accessors
        pos_acc = add_accessor(pos_bv, 5126, 4, "VEC3", [w, y_pos, d], [-w, y_pos, -d])
        normal_acc = add_accessor(pos_bv, 5126, 4, "VEC3")  # 共享 buffer view
        uv_acc = add_accessor(pos_bv, 5126, 4, "VEC2")  # 共享 buffer view
        idx_acc = add_accessor(idx_bv, 5123, 6, "SCALAR")
        
        # 创建 mesh
        gltf["meshes"].append({
            "name": name,
            "primitives": [{
                "attributes": {
                    "POSITION": pos_acc,
                    "NORMAL": normal_acc,
                    "TEXCOORD_0": uv_acc
                },
                "indices": idx_acc,
                "material": material_index
            }]
        })
        mesh_idx = mesh_index
        mesh_index += 1
        return mesh_idx
    
    def create_box_mesh(width, height, depth, name="box"):
        """创建盒子网格 (用于货架)"""
        nonlocal mesh_index
        
        w, h, d = width / 2, height / 2, depth / 2
        
        # 8个顶点
        vertices_pos = [
            -w, -h, -d,  # 0
             w, -h, -d,  # 1
             w,  h, -d,  # 2
            -w,  h, -d,  # 3
            -w, -h,  d,  # 4
             w, -h,  d,  # 5
             w,  h,  d,  # 6
            -w,  h,  d,  # 7
        ]
        
        # 6个面，每个面2个三角形
        indices = [
            0, 1, 2, 0, 2, 3,  # 前
            1, 5, 6, 1, 6, 2,  # 右
            5, 4, 7, 5, 7, 6,  # 后
            4, 0, 3, 4, 3, 7,  # 左
            3, 2, 6, 3, 6, 7,  # 上
            4, 5, 1, 4, 1, 0,  # 下
        ]
        
        # 每个顶点需要位置
        pos_data = struct.pack('<' + 'f' * len(vertices_pos), *vertices_pos)
        idx_data = struct.pack('<' + 'H' * len(indices), *indices)
        
        pos_bv = add_buffer_view(pos_data, 34962)
        idx_bv = add_buffer_view(idx_data, 34963)
        
        pos_acc = add_accessor(pos_bv, 5126, 8, "VEC3", [w, h, d], [-w, -h, -d])
        idx_acc = add_accessor(idx_bv, 5123, 36, "SCALAR")
        
        gltf["meshes"].append({
            "name": name,
            "primitives": [{
                "attributes": {"POSITION": pos_acc},
                "indices": idx_acc,
                "material": material_index
            }]
        })
        mesh_idx = mesh_index
        mesh_index += 1
        return mesh_idx
    
    # 创建材质
    # 0: 木质地板
    gltf["materials"].append({
        "name": "wood_floor",
        "pbrMetallicRoughness": {
            "baseColorFactor": [0.6, 0.4, 0.25, 1.0],  # 暖棕色
            "metallicFactor": 0.0,
            "roughnessFactor": 0.8
        }
    })
    
    # 1: 墙面
    gltf["materials"].append({
        "name": "wall",
        "pbrMetallicRoughness": {
            "baseColorFactor": [0.95, 0.9, 0.85, 1.0],  # 米白色
            "metallicFactor": 0.0,
            "roughnessFactor": 0.9
        }
    })
    
    # 2: 深色木质 (货架)
    gltf["materials"].append({
        "name": "dark_wood",
        "pbrMetallicRoughness": {
            "baseColorFactor": [0.35, 0.25, 0.15, 1.0],  # 深棕色
            "metallicFactor": 0.1,
            "roughnessFactor": 0.7
        }
    })
    
    # 3: 红木 (桌子)
    gltf["materials"].append({
        "name": "red_wood",
        "pbrMetallicRoughness": {
            "baseColorFactor": [0.5, 0.15, 0.1, 1.0],  # 红棕色
            "metallicFactor": 0.0,
            "roughnessFactor": 0.6
        }
    })
    
    # 创建节点和网格
    node_index = 0
    
    # 0: 地板 (10m x 10m)
    floor_mesh = create_plane_mesh(10, 10, 0, "floor")
    gltf["nodes"].append({
        "name": "floor",
        "mesh": floor_mesh,
        "translation": [0, 0, 0]
    })
    
    # 1: 后墙
    wall_mesh = create_box_mesh(10, 3, 0.2, "back_wall")
    gltf["nodes"].append({
        "name": "back_wall",
        "mesh": wall_mesh,
        "translation": [0, 1.5, -4.9]
    })
    
    # 2: 货架 01 (西湖龙井) - 左侧
    shelf_01_mesh = create_box_mesh(1.2, 1.8, 0.6, "shelf_01")
    gltf["nodes"].append({
        "name": "shelf_01_xihu_longjing",
        "mesh": shelf_01_mesh,
        "translation": [-2.2, 0.9, -2.5],
        "rotation": [0, 0.26, 0, 1]  # Y轴旋转约15度
    })
    
    # 3: 货架 02 (铁观音) - 中间
    shelf_02_mesh = create_box_mesh(1.2, 1.8, 0.6, "shelf_02")
    gltf["nodes"].append({
        "name": "shelf_02_tieguanyin",
        "mesh": shelf_02_mesh,
        "translation": [0, 0.9, -2.8]
    })
    
    # 4: 货架 03 (普洱) - 右侧
    shelf_03_mesh = create_box_mesh(1.2, 1.8, 0.6, "shelf_03")
    gltf["nodes"].append({
        "name": "shelf_03_puer",
        "mesh": shelf_03_mesh,
        "translation": [2.2, 0.9, -2.5],
        "rotation": [0, -0.26, 0, 1]  # Y轴旋转约-15度
    })
    
    # 5: 茶桌 (中间)
    table_mesh = create_box_mesh(1.5, 0.8, 0.8, "tea_table")
    gltf["nodes"].append({
        "name": "tea_table",
        "mesh": table_mesh,
        "translation": [0, 0.4, 0.5]
    })
    
    # 6: 环境光 (虚拟节点，用于光照信息)
    gltf["nodes"].append({
        "name": "ambient_light_info",
        "translation": [0, 5, 0]
    })
    
    # 添加 buffer
    gltf["buffers"].append({
        "byteLength": len(buffer_data)
    })
    
    gltf["buffer"] = bytes(buffer_data)
    
    return gltf


def save_gltf(gltf_data, output_path):
    """保存GLTF文件 (嵌入buffer的格式)"""
    # 分离 buffer 数据
    buffer_bytes = gltf_data.pop("buffer")
    
    # 将 buffer 编码为 base64
    import base64
    buffer_b64 = base64.b64encode(buffer_bytes).decode('ascii')
    gltf_data["buffers"][0]["uri"] = f"data:application/octet-stream;base64,{buffer_b64}"
    
    # 保存 JSON
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(gltf_data, f, indent=2, ensure_ascii=False)
    
    print(f"✅ GLTF 场景已保存: {output_path}")
    print(f"   文件大小: {len(buffer_bytes)} 字节 (buffer)")
    print(f"   节点数: {len(gltf_data['nodes'])}")
    print(f"   网格数: {len(gltf_data['meshes'])}")


def main():
    print("🍵 生成茶室3D场景...")
    gltf_data = generate_tea_room_gltf()
    save_gltf(gltf_data, OUTPUT_FILE)
    print(f"\n📍 场景位置: {OUTPUT_FILE}")
    print("\n场景包含:")
    print("  - 木质地板 (10x10m)")
    print("  - 后墙")
    print("  - 3个货架 (对应西湖龙井、铁观音、普洱)")
    print("  - 1个茶桌")


if __name__ == "__main__":
    main()
