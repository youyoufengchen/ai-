"""
深度重建器 (Depth Reconstructor)

核心思想：
- 2D 视频没有真实深度 Z
- MediaPipe 给的 z 值是相对值，不可靠
- 需要用人体约束来推测合理的 Z

方法：
1. 骨长约束：人体骨长基本恒定，2D 投影缩短说明有 Z 分量
2. 地面约束：脚踩地时 y = 0
3. 连续性约束：Z 不能突变
4. 用户修正：用户在自动估计基础上手动微调

输入：关节点序列（x, y 来自视频，z 初始为 MediaPipe 或 0）
输出：修正后的关节点序列（x, y, z），其中 z 是重建后的深度
"""

import math
from typing import Dict, List, Optional, Tuple


# 标准人体骨长比例（以髋宽为1.0的相对比例）
STANDARD_BONE_LENGTH_RATIOS = {
    "leftUpperArm":  0.65,
    "leftLowerArm":  0.55,
    "rightUpperArm": 0.65,
    "rightLowerArm": 0.55,
    "leftUpperLeg":  0.90,
    "leftLowerLeg":  0.85,
    "rightUpperLeg": 0.90,
    "rightLowerLeg": 0.85,
    "spine":         0.35,
    "neck":          0.15,
    "leftShoulder":  0.25,  # 肩宽的一半
    "rightShoulder": 0.25,
}


def estimate_depth_from_bone_lengths(
    joints: Dict[str, Dict[str, float]],
    bone_connections: Dict[str, Tuple[str, str]],
    reference_lengths: Dict[str, float],
) -> Dict[str, Dict[str, float]]:
    """
    根据骨长约束推测缺失或修正 Z 深度

    思路：如果 2D 投影长度 < 参考骨长，说明有 Z 分量需要补
    real_length² = xy_length² + z_length²
    z = sqrt(real_length² - xy_length²) * sign

    返回：修正后的 joints
    """
    result = {k: dict(v) for k, v in joints.items()}

    for bone_name, (from_joint, to_joint) in bone_connections.items():
        ref_len = reference_lengths.get(bone_name)
        if ref_len is None:
            continue

        fj = result.get(from_joint)
        tj = result.get(to_joint)
        if not fj or not tj:
            continue

        dx = tj["x"] - fj["x"]
        dy = tj["y"] - fj["y"]
        dz = tj.get("z", 0) - fj.get("z", 0)

        xy_len = math.sqrt(dx*dx + dy*dy)
        current_3d_len = math.sqrt(dx*dx + dy*dy + dz*dz)

        if current_3d_len < 1e-6:
            continue

        # 如果当前 3D 长度已经大于等于参考长度，不需要补
        if current_3d_len >= ref_len * 0.95:
            continue

        # 需要补 Z：z_needed² = ref_len² - xy_len²
        z_needed_sq = ref_len*ref_len - xy_len*xy_len
        if z_needed_sq <= 0:
            continue

        z_needed = math.sqrt(z_needed_sq)

        # 确定 Z 方向符号：使用现有的 z 差值符号
        z_sign = 1.0 if dz >= 0 else -1.0

        # 平均分配 Z 到两个端点（保持中点不变）
        z_offset = (z_needed - abs(dz)) / 2 * z_sign
        if abs(z_offset) > 0.001:
            fj["z"] = fj.get("z", 0) - z_offset
            tj["z"] = tj.get("z", 0) + z_offset

    return result


def smooth_joint_z_sequence(
    joint_frames: List[Dict[str, Dict[str, float]]],
    joint_names: List[str],
    window_size: int = 5,
) -> List[Dict[str, Dict[str, float]]]:
    """
    对每个关节点的 Z 轴做时间平滑
    使用移动平均
    """
    if not joint_frames or window_size < 2:
        return joint_frames

    half = window_size // 2
    result = []

    for i in range(len(joint_frames)):
        frame = {}
        for joint_name in joint_names:
            # 收集窗口内的 Z 值
            z_values = []
            for j in range(max(0, i - half), min(len(joint_frames), i + half + 1)):
                jt = joint_frames[j].get(joint_name)
                if jt:
                    z_values.append(jt.get("z", 0))

            if not z_values:
                continue

            # 去掉异常值后平均（中位数更稳健）
            z_values.sort()
            median_z = z_values[len(z_values) // 2]

            # 只保留与 median 差距不太大的值
            filtered = [z for z in z_values if abs(z - median_z) < 0.5]
            avg_z = sum(filtered) / len(filtered) if filtered else median_z

            # 复制原关节点，但替换 Z
            orig = joint_frames[i].get(joint_name, {})
            frame[joint_name] = {
                "x": orig.get("x", 0),
                "y": orig.get("y", 0),
                "z": avg_z,
                "confidence": orig.get("confidence", 1.0),
            }
        result.append(frame)

    return result


def apply_ground_constraint(
    joint_frames: List[Dict[str, Dict[str, float]]],
    ground_y: float = 0.0,
    foot_joints: List[str] = None,
) -> List[Dict[str, Dict[str, float]]]:
    """
    地面约束：脚踩地时 ankle/foot y 不能低于地面
    同时整体抬升/降低 hips 使最低 foot 刚好触地
    """
    if foot_joints is None:
        foot_joints = ["leftFoot", "rightFoot", "leftAnkle", "rightAnkle"]

    result = []
    for joints in joint_frames:
        new_joints = {k: dict(v) for k, v in joints.items()}

        # 找最低点
        min_y = float('inf')
        for fj in foot_joints:
            j = new_joints.get(fj)
            if j:
                min_y = min(min_y, j["y"])

        if min_y < ground_y:
            # 整体抬高
            offset_y = ground_y - min_y
            for j in new_joints.values():
                j["y"] += offset_y

        # 确保脚不穿透地面
        for fj in foot_joints:
            j = new_joints.get(fj)
            if j and j["y"] < ground_y:
                j["y"] = ground_y

        result.append(new_joints)

    return result


def normalize_scale_by_hip_width(
    joint_frames: List[Dict[str, Dict[str, float]]],
    target_hip_width: float = 0.25,
) -> List[Dict[str, Dict[str, float]]]:
    """
    根据髋宽归一化尺度
    让不同身高的人在视频中尺度一致
    """
    if not joint_frames:
        return joint_frames

    result = []
    for joints in joint_frames:
        lh = joints.get("leftHip")
        rh = joints.get("rightHip")
        if not lh or not rh:
            result.append(joints)
            continue

        current_width = math.sqrt(
            (lh["x"] - rh["x"])**2 +
            (lh["y"] - rh["y"])**2 +
            (lh["z"] - rh["z"])**2
        )
        if current_width < 1e-6:
            result.append(joints)
            continue

        scale = target_hip_width / current_width
        new_joints = {}
        for name, j in joints.items():
            new_joints[name] = {
                "x": j["x"] * scale,
                "y": j["y"] * scale,
                "z": j.get("z", 0) * scale,
                "confidence": j.get("confidence", 1.0),
            }
        result.append(new_joints)

    return result


def apply_user_z_correction(
    joints: Dict[str, Dict[str, float]],
    correction_curves: Dict[str, List[float]],  # joint_name -> [z_offset_per_frame]
    frame_idx: int,
) -> Dict[str, Dict[str, float]]:
    """
    应用用户对 Z 轴的手动修正

    correction_curves: 用户在曲线编辑器中调整的 Z 偏移量
    """
    result = {k: dict(v) for k, v in joints.items()}
    for joint_name, curve in correction_curves.items():
        if frame_idx < len(curve) and joint_name in result:
            result[joint_name]["z"] += curve[frame_idx]
    return result
