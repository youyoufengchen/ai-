"""
BVH → GLB 转换器（后端模块）

尝试以下方式，按优先级排序：
1. Blender Python API（bpy）—— 如果 Blender 已安装
2. 命令行调用 blender --background --python ...
3. 生成最小化 glTF（纯 Python，无外部依赖）—— 兜底方案

用法：
    from modules.bvh_to_glb_converter import convert_bvh_to_glb
    glb_path = convert_bvh_to_glb("input.bvh", "output.glb")
"""

import json
import struct
import math
import logging
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple, Dict, List

logger = logging.getLogger("bvh_to_glb")

# 项目根目录
ROOT_DIR = Path(__file__).parent.parent


def convert_bvh_to_glb(
    bvh_path: str,
    glb_path: str,
    fps: float = 30.0,
    use_blender: bool = True
) -> Optional[str]:
    """
    将 BVH 转换为 GLB
    
    Returns:
        GLB 文件路径，或 None（失败时）
    """
    bvh_path = Path(bvh_path)
    glb_path = Path(glb_path)
    
    if not bvh_path.exists():
        logger.error(f"BVH 文件不存在: {bvh_path}")
        return None
    
    # 方案1：尝试使用 Blender 命令行
    if use_blender:
        result = _try_blender_cli(bvh_path, glb_path, fps)
        if result:
            return result
    
    # 方案2：尝试使用 bpy（如果在 Blender 内部运行）
    try:
        import bpy
        # 在 Blender 内部
        from tools.convert_bvh_to_glb_blender import convert_bvh_to_glb as blender_convert
        return blender_convert(str(bvh_path), str(glb_path), fps)
    except ImportError:
        pass
    
    # 方案3：最小化 glTF 生成器（兜底）
    logger.warning("Blender 不可用，使用最小化 glTF 生成器（无 mesh，仅有骨骼动画）")
    return _generate_minimal_glb(bvh_path, glb_path)


def _try_blender_cli(bvh_path: Path, glb_path: Path, fps: float) -> Optional[str]:
    """尝试通过命令行调用 Blender"""
    # 搜索常见的 Blender 路径
    blender_cmds = [
        "blender",
        "blender.exe",
        "C:/Program Files/Blender Foundation/Blender 4.2/blender.exe",
        "C:/Program Files/Blender Foundation/Blender 4.1/blender.exe",
        "C:/Program Files/Blender Foundation/Blender 4.0/blender.exe",
        "C:/Program Files/Blender Foundation/Blender 3.6/blender.exe",
        "C:/Program Files/Blender Foundation/Blender 3.0/blender.exe",
    ]
    
    script_path = ROOT_DIR / "tools" / "convert_bvh_to_glb_blender.py"
    
    for blender in blender_cmds:
        try:
            result = subprocess.run(
                [blender, "--background", "--python", str(script_path), "--", str(bvh_path), str(glb_path), "--fps", str(fps)],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0 and glb_path.exists():
                logger.info(f"Blender 转换成功: {blender}")
                return str(glb_path)
            else:
                logger.debug(f"Blender 失败 ({blender}): {result.stderr[:200]}")
        except FileNotFoundError:
            continue
        except subprocess.TimeoutExpired:
            logger.warning(f"Blender 转换超时: {blender}")
        except Exception as e:
            logger.debug(f"Blender 异常 ({blender}): {e}")
    
    return None


def _generate_minimal_glb(bvh_path: Path, glb_path: Path) -> Optional[str]:
    """
    生成最小化的 glTF GLB（无 mesh，仅有骨骼层级 + 旋转动画）
    
    这是兜底方案，确保即使没有 Blender 也能产出可播放的 GLB。
    Three.js 的 AnimationMixer 可以播放这种"纯动画"GLB。
    """
    try:
        sys.path.insert(0, str(ROOT_DIR))
        from tools.bvh_parser import BVHParser
        
        bvh = BVHParser.load(str(bvh_path))
        rotations = bvh.compute_local_rotations()
        
        if not rotations:
            logger.error("BVH 没有动画数据")
            return None
        
        # 构建 glTF
        gltf = _build_minimal_gltf(bvh, rotations)
        
        # 写入 GLB
        _write_glb(gltf, glb_path)
        
        logger.info(f"最小化 GLB 生成成功: {glb_path}")
        return str(glb_path)
    except Exception as e:
        logger.error(f"最小化 GLB 生成失败: {e}", exc_info=True)
        return None


def _build_minimal_gltf(bvh, rotations: List[Dict[str, Tuple[float, float, float, float]]]) -> dict:
    """构建最小化 glTF JSON（无 mesh，有骨骼层级 + 动画）"""
    
    nodes = []
    node_indices = {}
    
    def add_joint_to_nodes(joint, parent_idx=None):
        idx = len(nodes)
        node = {
            "name": joint.name,
            "translation": [joint.offset[0], joint.offset[1], joint.offset[2]],
            "rotation": [0.0, 0.0, 0.0, 1.0],
        }
        if parent_idx is not None:
            node["parent"] = parent_idx  # 注意：glTF 用 scene.children 层级，不是 parent 字段
        nodes.append(node)
        node_indices[joint.name] = idx
        
        for child in joint.children:
            add_joint_to_nodes(child, idx)
        return idx
    
    # glTF 用 children 数组表示层级，不用 parent 指针
    # 重新组织
    nodes = []
    node_indices = {}
    
    def build_gltf_nodes(joint, parent_idx=None):
        idx = len(nodes)
        node = {
            "name": joint.name,
            "translation": list(joint.offset),
            "rotation": [0.0, 0.0, 0.0, 1.0],
            "scale": [1.0, 1.0, 1.0],
        }
        nodes.append(node)
        node_indices[joint.name] = idx
        
        # 处理子节点
        child_indices = []
        for child in joint.children:
            child_idx = build_gltf_nodes(child, idx)
            child_indices.append(child_idx)
        
        if child_indices:
            nodes[idx]["children"] = child_indices
        
        return idx
    
    root_idx = build_gltf_nodes(bvh.root)
    
    # 创建 accessor / bufferView / buffer
    # 每个关节每帧一个 rotation quaternion
    num_joints = len(node_indices)
    num_frames = bvh.frame_count
    
    # 收集所有关键帧旋转数据
    # 我们需要每个关节每帧的旋转
    # 但只有非 EndSite 的关节才有旋转通道
    animated_joints = []
    for name, joint in bvh.joints.items():
        if not joint.is_end_site and joint.channels:
            animated_joints.append(name)
    
    # 对每个关节，收集所有帧的旋转四元数
    # 格式：float[4] per keyframe -> 扁平数组
    rotation_data = []  # 所有关节的所有帧的四元数
    time_data = []      # 时间戳
    
    for frame_i in range(num_frames):
        time_data.append(frame_i / bvh.fps)
        frame_rots = rotations[frame_i]
        for joint_name in animated_joints:
            q = frame_rots.get(joint_name, (1.0, 0.0, 0.0, 0.0))
            rotation_data.extend([q[1], q[2], q[3], q[0]])  # glTF: x,y,z,w
    
    # 构建 binary buffer
    # 布局：[时间数据 (float)] [旋转数据 (float)]
    time_bytes = struct.pack(f"<{len(time_data)}f", *time_data)
    rot_bytes = struct.pack(f"<{len(rotation_data)}f", *rotation_data)
    
    buffer_data = time_bytes + rot_bytes
    # 4字节对齐
    padding = (4 - len(buffer_data) % 4) % 4
    buffer_data += b"\x00" * padding
    
    # glTF JSON
    gltf = {
        "asset": {"version": "2.0", "generator": "MoCapAnything-Minimal-GLB"},
        "scene": 0,
        "scenes": [{"nodes": [root_idx]}],
        "nodes": nodes,
        "animations": [],
        "accessors": [],
        "bufferViews": [],
        "buffers": [{"byteLength": len(buffer_data)}],
    }
    
    # 时间 accessor
    time_bv_idx = 0
    time_acc_idx = 0
    gltf["bufferViews"].append({
        "buffer": 0,
        "byteOffset": 0,
        "byteLength": len(time_bytes),
        "target": 34962,  # ARRAY_BUFFER
    })
    gltf["accessors"].append({
        "bufferView": time_bv_idx,
        "componentType": 5126,  # FLOAT
        "count": len(time_data),
        "type": "SCALAR",
        "min": [min(time_data)],
        "max": [max(time_data)],
    })
    
    # 旋转 accessor
    rot_bv_idx = 1
    rot_acc_idx = 1
    gltf["bufferViews"].append({
        "buffer": 0,
        "byteOffset": len(time_bytes),
        "byteLength": len(rot_bytes),
        "target": 34962,
    })
    gltf["accessors"].append({
        "bufferView": rot_bv_idx,
        "componentType": 5126,
        "count": len(rotation_data) // 4,
        "type": "VEC4",
    })
    
    # Animation samplers & channels
    # 为每个动画关节创建一个 sampler
    samplers = []
    channels = []
    
    for joint_i, joint_name in enumerate(animated_joints):
        sampler_idx = len(samplers)
        # 每个关节的旋转数据在 buffer 中的偏移
        joint_rot_offset = joint_i * num_frames * 4
        joint_rot_count = num_frames * 4
        
        # 为每个关节创建独立的 bufferView 和 accessor（简化处理）
        # 实际上可以共用，但为简化，我们用统一的数据，通过 stride 来区分
        # glTF 动画 sampler 要求 input/output 各一个 accessor
        # 这里简化：所有关节共用 input（时间），每个关节有自己 output 的 sub-view
        
        # 由于 glTF 不支持 sub-range accessor，我们需要为每个关节创建单独的 bufferView
        pass  # 这会让文件很大... 让我换一种方式
    
    # 简化方案：所有关节的旋转打包到一个大的 output accessor 中
    # 但 glTF 动画 channel 要求每个 target 对应一个 sampler
    # 我们可以用插值器从大的 output 中取数据... 不行
    
    # 让我换一种更实际的方式：每个关节每帧的数据在 output accessor 中连续排列
    # 然后每个 sampler 使用相同的 input，但 output 是总体数据
    # 但这意味着每个 sampler 的 output 是相同的巨大数组... Three.js 会全读
    
    # 实际上正确的方式是：每个 sampler 有自己的 output accessor（或至少独立的 bufferView）
    # 但这会导致 buffer 巨大重复
    
    # 更好的方式：使用一个 buffer，多个 bufferView（不同的 byteOffset）
    # 这正是 glTF 设计的初衷
    
    base_rot_offset = len(time_bytes)
    bytes_per_frame_per_joint = 4 * 4  # 4 floats * 4 bytes
    bytes_per_joint_total = bytes_per_frame_per_joint * num_frames
    
    for joint_i, joint_name in enumerate(animated_joints):
        sampler_idx = len(samplers)
        joint_rot_offset = base_rot_offset + joint_i * bytes_per_joint_total
        
        # 为这个关节创建 bufferView
        bv_idx = len(gltf["bufferViews"])
        gltf["bufferViews"].append({
            "buffer": 0,
            "byteOffset": joint_rot_offset,
            "byteLength": bytes_per_joint_total,
            "target": 34962,
        })
        
        # output accessor
        out_acc_idx = len(gltf["accessors"])
        gltf["accessors"].append({
            "bufferView": bv_idx,
            "componentType": 5126,
            "count": num_frames,
            "type": "VEC4",
        })
        
        samplers.append({
            "input": time_acc_idx,
            "output": out_acc_idx,
            "interpolation": "LINEAR",
        })
        
        node_idx = node_indices.get(joint_name)
        if node_idx is not None:
            channels.append({
                "sampler": sampler_idx,
                "target": {
                    "node": node_idx,
                    "path": "rotation",
                },
            })
    
    gltf["animations"] = [{
        "name": "Action",
        "samplers": samplers,
        "channels": channels,
    }]
    
    return {"json": gltf, "bin": buffer_data}


def _write_glb(gltf_data: dict, glb_path: Path):
    """将 glTF JSON + bin 写入 GLB 文件"""
    json_bytes = json.dumps(gltf_data["json"], separators=(",", ":")).encode("utf-8")
    bin_bytes = gltf_data["bin"]
    
    # 4字节对齐 JSON
    json_padding = (4 - len(json_bytes) % 4) % 4
    json_bytes += b" " * json_padding
    
    # 4字节对齐 BIN
    bin_padding = (4 - len(bin_bytes) % 4) % 4
    bin_bytes += b"\x00" * bin_padding
    
    # GLB header
    header = struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(json_bytes) + 8 + len(bin_bytes))
    
    # JSON chunk
    json_chunk = struct.pack("<II", len(json_bytes), 0x4E4F534A) + json_bytes
    
    # BIN chunk
    bin_chunk = struct.pack("<II", len(bin_bytes), 0x004E4942) + bin_bytes
    
    glb_path.parent.mkdir(parents=True, exist_ok=True)
    with open(glb_path, "wb") as f:
        f.write(header)
        f.write(json_chunk)
        f.write(bin_chunk)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python -m modules.bvh_to_glb_converter <input.bvh> <output.glb>")
        sys.exit(1)
    
    result = convert_bvh_to_glb(sys.argv[1], sys.argv[2])
    if result:
        print(f"[OK] 输出: {result}")
    else:
        print("[FAIL] 转换失败")
        sys.exit(1)
