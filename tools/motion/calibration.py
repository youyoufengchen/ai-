"""
校准帧机制 (Calibration Frame)

核心思想：
- 用户选择视频中一帧作为“基准姿态”（通常是站直姿势）
- 系统记录视频人物在这一帧的关节点坐标
- 系统记录角色模型在 Rest Pose 下的关节点坐标
- 后续动作 = 视频当前帧相对于校准帧的变化量 + 角色 Rest Pose

这样无论视频人物初始站姿如何，角色都不会扭曲。
"""

import math
from typing import Dict, List, Optional, Tuple


def calculate_joint_offsets(
    calibration_video_joints: Dict[str, Dict[str, float]],
    calibration_model_joints: Dict[str, Dict[str, float]],
) -> Dict[str, Dict[str, float]]:
    """
    计算视频关节点与角色关节点之间的偏移量

    返回: {joint_name: {"offset_x", "offset_y", "offset_z", "scale"}}
    """
    offsets = {}
    for joint_name in calibration_video_joints:
        vj = calibration_video_joints[joint_name]
        mj = calibration_model_joints.get(joint_name)
        if not mj:
            continue

        # 计算位置偏移
        offsets[joint_name] = {
            "offset_x": mj["x"] - vj["x"],
            "offset_y": mj["y"] - vj["y"],
            "offset_z": mj["z"] - vj["z"],
            # 尺度因子（基于髋宽比例）
            "scale": 1.0,
        }

    # 如果 hips 都存在，用髋宽计算整体尺度
    if "leftHip" in calibration_video_joints and "rightHip" in calibration_video_joints:
        vlh = calibration_video_joints["leftHip"]
        vrh = calibration_video_joints["rightHip"]
        v_hip_width = math.sqrt(
            (vlh["x"] - vrh["x"])**2 +
            (vlh["y"] - vrh["y"])**2 +
            (vlh["z"] - vrh["z"])**2
        )
        mlh = calibration_model_joints.get("leftHip")
        mrh = calibration_model_joints.get("rightHip")
        if mlh and mrh and v_hip_width > 1e-6:
            m_hip_width = math.sqrt(
                (mlh["x"] - mrh["x"])**2 +
                (mlh["y"] - mrh["y"])**2 +
                (mlh["z"] - mrh["z"])**2
            )
            scale = m_hip_width / v_hip_width
            for joint_name in offsets:
                offsets[joint_name]["scale"] = scale

    return offsets


def apply_calibration(
    video_joints: Dict[str, Dict[str, float]],
    calibration_offsets: Dict[str, Dict[str, float]],
    scale_to_model: bool = True,
) -> Dict[str, Dict[str, float]]:
    """
    将视频关节点通过校准偏移转换到角色坐标系

    应用：角色关节 = 视频关节 * scale + offset
    """
    result = {}
    for joint_name, vj in video_joints.items():
        offset = calibration_offsets.get(joint_name)
        if not offset:
            result[joint_name] = dict(vj)
            continue

        scale = offset.get("scale", 1.0) if scale_to_model else 1.0
        result[joint_name] = {
            "x": vj["x"] * scale + offset["offset_x"],
            "y": vj["y"] * scale + offset["offset_y"],
            "z": vj["z"] * scale + offset["offset_z"],
            "confidence": vj.get("confidence", 1.0),
        }
    return result


def compute_model_joints_from_rest_pose(
    model_bone_hierarchy: Dict[str, Dict],
    bone_binding: Dict[str, str],  # canonical -> model bone
) -> Dict[str, Dict[str, float]]:
    """
    从角色 Rest Pose 骨骼层级计算关节点坐标

    思路：遍历骨骼，累加局部位置得到世界位置
    """
    joints = {}

    # 先找到根骨骼
    root = None
    for bone, info in model_bone_hierarchy.items():
        if not info.get("parent"):
            root = bone
            break

    if not root:
        return joints

    # 计算世界位置（递归）
    world_pos = {}

    def calc_world(bone_name, parent_world=None):
        info = model_bone_hierarchy.get(bone_name)
        if not info:
            return
        local_pos = info.get("position", [0, 0, 0])
        if parent_world:
            wx = parent_world[0] + local_pos[0]
            wy = parent_world[1] + local_pos[1]
            wz = parent_world[2] + local_pos[2]
        else:
            wx, wy, wz = local_pos
        world_pos[bone_name] = (wx, wy, wz)
        for child in info.get("children", []):
            calc_world(child, (wx, wy, wz))

    calc_world(root)

    # 将 model bone 位置映射回 canonical joint
    # 需要反向查找：model bone -> canonical joint
    reverse_binding = {m: c for c, m in bone_binding.items()}

    for model_bone, pos in world_pos.items():
        c_name = reverse_binding.get(model_bone)
        if c_name:
            joints[c_name] = {"x": pos[0], "y": pos[1], "z": pos[2], "confidence": 1.0}

    # 对于 spine/neck 等特殊关节，需要插值计算
    # spine = hips 和 chest 之间
    if "hips" in joints and "chest" in joints:
        h = joints["hips"]
        c = joints["chest"]
        joints["spine"] = {
            "x": (h["x"] + c["x"]) / 2,
            "y": (h["y"] + c["y"]) / 2,
            "z": (h["z"] + c["z"]) / 2,
            "confidence": 1.0,
        }

    # neck = chest 和 head 之间
    if "chest" in joints and "head" in joints:
        c = joints["chest"]
        h = joints["head"]
        joints["neck"] = {
            "x": (c["x"] + h["x"]) / 2,
            "y": (c["y"] + h["y"]) / 2,
            "z": (c["z"] + h["z"]) / 2,
            "confidence": 1.0,
        }

    return joints


def auto_select_calibration_frame(
    joint_frames: List[Dict[str, Dict[str, float]]],
) -> int:
    """
    自动选择最佳校准帧
    选择标准：人物站得最直的一帧
    - 左右肩高度差最小
    - 左右髋高度差最小
    - 脊柱接近垂直
    """
    best_idx = 0
    best_score = float('inf')

    for idx, joints in enumerate(joint_frames):
        score = 0
        # 肩高差
        ls = joints.get("leftShoulder")
        rs = joints.get("rightShoulder")
        if ls and rs:
            score += abs(ls["y"] - rs["y"])

        # 髋高差
        lh = joints.get("leftHip")
        rh = joints.get("rightHip")
        if lh and rh:
            score += abs(lh["y"] - rh["y"])

        # 脊柱垂直度（hip->chest 的 x/z 偏移应小）
        hip = joints.get("hips")
        chest = joints.get("chest")
        if hip and chest:
            dx = chest["x"] - hip["x"]
            dz = chest["z"] - hip["z"]
            score += math.sqrt(dx*dx + dz*dz)

        if score < best_score:
            best_score = score
            best_idx = idx

    return best_idx
