"""
重投影误差计算 (Reprojection Error)

核心思想：
- 把角色3D关节点投影回视频画面
- 与原始 MediaPipe 2D 关键点比较
- 误差越小，说明动作越贴合原视频

投影公式（简化透视投影）：
    screen_x = (world_x / world_z) * focal_length + center_x
    screen_y = (world_y / world_z) * focal_length + center_y

但更简单的做法是用 MediaPipe 原始 2D 坐标作为 ground truth。

输入：
- 角色3D关节点坐标（校准后的）
- 原始视频 MediaPipe 2D 关键点坐标

输出：
- 每帧每关节的像素误差
- 总体拟合分数
"""

import math
from typing import Dict, List, Tuple


def project_3d_to_2d(
    point_3d: Tuple[float, float, float],
    focal_length: float = 1.0,
    center: Tuple[float, float] = (0.5, 0.5),
) -> Tuple[float, float]:
    """
    简化的透视投影
    假设相机在原点，看向 -Z，Z > 0 的点才被投影
    """
    x, y, z = point_3d
    if abs(z) < 1e-6:
        z = 1e-6
    sx = (x / z) * focal_length + center[0]
    sy = (y / z) * focal_length + center[1]
    return (sx, sy)


def calculate_reprojection_error(
    character_joints: Dict[str, Dict[str, float]],
    original_landmarks: Dict[int, Dict],
    joint_to_mp_mapping: Dict[str, int],  # joint_name -> mediapipe landmark id
) -> Dict[str, float]:
    """
    计算重投影误差

    返回: {joint_name: error_in_pixels_or_normalized}
    """
    errors = {}

    for joint_name, joint_pos in character_joints.items():
        mp_id = joint_to_mp_mapping.get(joint_name)
        if mp_id is None:
            continue

        orig = original_landmarks.get(mp_id)
        if not orig:
            continue

        # 角色关节投影到 2D
        proj = project_3d_to_2d(
            (joint_pos["x"], joint_pos["y"], joint_pos["z"]),
            focal_length=1.0,
        )

        # 原始 2D 坐标
        orig_x = orig.get("x", 0)
        orig_y = orig.get("y", 0)

        # 误差（归一化坐标，0-1范围）
        dx = proj[0] - orig_x
        dy = proj[1] - orig_y
        error = math.sqrt(dx*dx + dy*dy)
        errors[joint_name] = error

    return errors


def calculate_overall_fitness(
    joint_frames: List[Dict[str, Dict[str, float]]],
    raw_frames: List[Dict],
    joint_to_mp_mapping: Dict[str, int],
) -> Dict:
    """
    计算整体拟合分数

    返回: {
        "score": 0-100,
        "per_joint_score": {joint_name: 0-100},
        "worst_joints": [(joint_name, avg_error), ...],
    }
    """
    if not joint_frames or not raw_frames:
        return {"score": 0, "per_joint_score": {}, "worst_joints": []}

    joint_errors = {name: [] for name in joint_to_mp_mapping.keys()}

    for idx, (joints, raw) in enumerate(zip(joint_frames, raw_frames)):
        lm_by_id = {lm["id"]: lm for lm in raw.get("landmarks", [])}
        errors = calculate_reprojection_error(joints, lm_by_id, joint_to_mp_mapping)
        for name, err in errors.items():
            joint_errors[name].append(err)

    # 计算每关节平均误差
    per_joint_score = {}
    total_score = 0
    count = 0

    for name, errs in joint_errors.items():
        if not errs:
            continue
        avg_err = sum(errs) / len(errs)
        # 误差 0.0 -> 100分，误差 0.5 -> 0分
        score = max(0, min(100, int((1.0 - avg_err * 2) * 100)))
        per_joint_score[name] = score
        total_score += score
        count += 1

    overall = total_score / count if count > 0 else 0

    # 最差关节
    worst = sorted(
        [(name, sum(errs)/len(errs)) for name, errs in joint_errors.items() if errs],
        key=lambda x: -x[1],
    )[:5]

    return {
        "score": int(overall),
        "per_joint_score": per_joint_score,
        "worst_joints": worst,
    }


# 标准关节点 -> MediaPipe landmark ID 映射
JOINT_TO_MP_ID = {
    "hips": None,  #  hips 是计算的，没有直接对应的 MP 点
    "spine": None,
    "chest": None,
    "neck": None,
    "head": 0,  # NOSE
    "leftShoulder": 11,
    "leftElbow": 13,
    "leftWrist": 15,
    "leftHand": 19,
    "rightShoulder": 12,
    "rightElbow": 14,
    "rightWrist": 16,
    "rightHand": 20,
    "leftHip": 23,
    "leftKnee": 25,
    "leftAnkle": 27,
    "leftFoot": 31,
    "rightHip": 24,
    "rightKnee": 26,
    "rightAnkle": 28,
    "rightFoot": 32,
}
