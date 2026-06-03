"""
Retarget：从 Canonical Motion 到目标模型骨骼动画

目标：将标准人体动作重定向到具体模型（X Bot, VRM 等）
"""
import math
from typing import Dict, List, Optional, Any


def retarget_to_bones(
    canonical_frames: List[Dict],
    bone_mapping: Dict[str, str],
    model_rest_dirs: Dict[str, Dict[str, float]],
) -> List[Dict]:
    """
    重定向 canonical motion 到目标模型骨骼

    canonical_frames: [{time, bones: {"leftUpperArm": {dir: {...}}, ...}}, ...]
    bone_mapping: canonical bone -> model bone name
    model_rest_dirs: model bone -> {x, y, z} rest pose 方向

    返回: 同上，但 bones 键变为 model bone name，且包含 rotation 而非 dir
    """
    result = []
    for frame in canonical_frames:
        out_bones = {}
        for c_name, c_data in frame.get("bones", {}).items():
            m_name = bone_mapping.get(c_name)
            if not m_name:
                continue
            rest_dir = model_rest_dirs.get(m_name)
            if not rest_dir:
                continue

            if "dir" in c_data and rest_dir:
                # 计算从 restDir -> targetDir 的旋转
                rx, ry, rz = rest_dir["x"], rest_dir["y"], rest_dir["z"]
                tx, ty, tz = c_data["dir"]["x"], c_data["dir"]["y"], c_data["dir"]["z"]

                # setFromUnitVectors 等效计算
                dot = rx * tx + ry * ty + rz * tz
                dot = max(-1.0, min(1.0, dot))
                if dot > 0.99999:
                    qx, qy, qz, qw = 0.0, 0.0, 0.0, 1.0
                elif dot < -0.99999:
                    # 180度旋转
                    ax, ay, az = (1.0, 0.0, 0.0) if abs(rx) < 0.9 else (0.0, 1.0, 0.0)
                    qx, qy, qz, qw = ax, ay, az, 0.0
                else:
                    angle = math.acos(dot)
                    cross_x = ry * tz - rz * ty
                    cross_y = rz * tx - rx * tz
                    cross_z = rx * ty - ry * tx
                    axis_len = math.sqrt(cross_x ** 2 + cross_y ** 2 + cross_z ** 2)
                    if axis_len < 1e-6:
                        qx, qy, qz, qw = 0.0, 0.0, 0.0, 1.0
                    else:
                        half = angle / 2
                        s = math.sin(half) / axis_len
                        c = math.cos(half)
                        qx, qy, qz, qw = cross_x * s, cross_y * s, cross_z * s, c

                out_bones[m_name] = {
                    "rotation": {"x": qx, "y": qy, "z": qz, "w": qw},
                }

            if "position" in c_data:
                out_bones[m_name]["position"] = c_data["position"]

        result.append({
            "time": frame["time"],
            "bones": out_bones,
        })

    return result
