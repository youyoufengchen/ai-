"""
关节点构建器 (Joint Position Builder)

核心思想：
- 从 MediaPipe 33 关键点中提取人体关节的 3D 坐标
- 输出是“关节点位置”，不是“骨骼方向”
- 关节点可直接用于 IK、深度修正、重投影误差计算
- 坐标系：Three.js 右手系 Y-up，+Z 朝向相机

标准关节点列表 (21个):
    hips, spine, chest, neck, head,
    leftShoulder, leftElbow, leftWrist, leftHand,
    rightShoulder, rightElbow, rightWrist, rightHand,
    leftHip, leftKnee, leftAnkle, leftFoot,
    rightHip, rightKnee, rightAnkle, rightFoot
"""

import math
from typing import Dict, List, Optional, Tuple

# MediaPipe Pose 33 关键点索引
MP_NOSE = 0
MP_LEFT_EYE_INNER = 1; MP_LEFT_EYE = 2; MP_LEFT_EYE_OUTER = 3
MP_RIGHT_EYE_INNER = 4; MP_RIGHT_EYE = 5; MP_RIGHT_EYE_OUTER = 6
MP_LEFT_EAR = 7; MP_RIGHT_EAR = 8
MP_MOUTH_LEFT = 9; MP_MOUTH_RIGHT = 10
MP_LEFT_SHOULDER = 11; MP_RIGHT_SHOULDER = 12
MP_LEFT_ELBOW = 13; MP_RIGHT_ELBOW = 14
MP_LEFT_WRIST = 15; MP_RIGHT_WRIST = 16
MP_LEFT_PINKY = 17; MP_RIGHT_PINKY = 18
MP_LEFT_INDEX = 19; MP_RIGHT_INDEX = 20
MP_LEFT_THUMB = 21; MP_RIGHT_THUMB = 22
MP_LEFT_HIP = 23; MP_RIGHT_HIP = 24
MP_LEFT_KNEE = 25; MP_RIGHT_KNEE = 26
MP_LEFT_ANKLE = 27; MP_RIGHT_ANKLE = 28
MP_LEFT_HEEL = 29; MP_RIGHT_HEEL = 30
MP_LEFT_FOOT_INDEX = 31; MP_RIGHT_FOOT_INDEX = 32

# 标准关节点名列表（按拓扑顺序：根到末端）
JOINT_NAMES = [
    "hips", "spine", "chest", "neck", "head",
    "leftShoulder", "leftElbow", "leftWrist", "leftHand",
    "rightShoulder", "rightElbow", "rightWrist", "rightHand",
    "leftHip", "leftKnee", "leftAnkle", "leftFoot",
    "rightHip", "rightKnee", "rightAnkle", "rightFoot",
]

# 关节点 → MediaPipe landmark 映射
# 格式：joint_name -> landmark_idx 或 计算方式
JOINT_TO_MP = {
    "hips":        "midpoint_23_24",  # 左髋+右髋中心
    "spine":       "midpoint_23_24_11_12",  # 髋中心→肩中心之间
    "chest":       "midpoint_11_12",  # 肩中心
    "neck":        "midpoint_11_12_nose",  # 肩中心→鼻子之间
    "head":        MP_NOSE,
    "leftShoulder": MP_LEFT_SHOULDER,
    "leftElbow":   MP_LEFT_ELBOW,
    "leftWrist":   MP_LEFT_WRIST,
    "leftHand":    MP_LEFT_INDEX,
    "rightShoulder": MP_RIGHT_SHOULDER,
    "rightElbow":  MP_RIGHT_ELBOW,
    "rightWrist":  MP_RIGHT_WRIST,
    "rightHand":   MP_RIGHT_INDEX,
    "leftHip":     MP_LEFT_HIP,
    "leftKnee":    MP_LEFT_KNEE,
    "leftAnkle":   MP_LEFT_ANKLE,
    "leftFoot":    MP_LEFT_FOOT_INDEX,
    "rightHip":    MP_RIGHT_HIP,
    "rightKnee":   MP_RIGHT_KNEE,
    "rightAnkle":  MP_RIGHT_ANKLE,
    "rightFoot":   MP_RIGHT_FOOT_INDEX,
}


def _mp_to_xyz(lm: Dict, use_world: bool = True) -> Tuple[float, float, float]:
    """
    MediaPipe landmark -> Three.js 坐标
    MediaPipe world: right-handed, Y-down, +Z away from camera
    Three.js: right-handed, Y-up, +Z towards camera
    """
    if use_world and lm.get("wx") is not None:
        # MediaPipe world landmarks: Y-up, +Z away from camera
        # Three.js: Y-up, +Z towards camera
        # 所以只有 Z 需要翻转
        return (float(lm["wx"]), float(lm["wy"]), -float(lm["wz"]))
    return (float(lm["x"]), 1.0 - float(lm["y"]), float(lm.get("z", 0)) * 0.3)


def _get_lm(lm_by_id: Dict, idx: int, use_world: bool = True) -> Optional[Tuple[float, float, float]]:
    lm = lm_by_id.get(idx)
    if not lm:
        return None
    return _mp_to_xyz(lm, use_world)


def _midpoint(*points) -> Optional[Tuple[float, float, float]]:
    valid = [p for p in points if p is not None]
    if not valid:
        return None
    n = len(valid)
    return (
        sum(p[0] for p in valid) / n,
        sum(p[1] for p in valid) / n,
        sum(p[2] for p in valid) / n,
    )


def build_joints_from_landmarks(
    landmarks: List[Dict],
    use_world: bool = True,
) -> Optional[Dict[str, Dict[str, float]]]:
    """
    从 MediaPipe landmarks 构建标准关节点坐标

    返回: {
        joint_name: {"x": float, "y": float, "z": float, "confidence": float},
        ...
    }
    """
    lm_by_id = {lm["id"]: lm for lm in landmarks}

    def get(idx):
        return _get_lm(lm_by_id, idx, use_world)

    joints = {}

    # 基础关键点
    left_shoulder = get(MP_LEFT_SHOULDER)
    right_shoulder = get(MP_RIGHT_SHOULDER)
    left_hip = get(MP_LEFT_HIP)
    right_hip = get(MP_RIGHT_HIP)
    nose = get(MP_NOSE)
    left_elbow = get(MP_LEFT_ELBOW)
    right_elbow = get(MP_RIGHT_ELBOW)
    left_wrist = get(MP_LEFT_WRIST)
    right_wrist = get(MP_RIGHT_WRIST)
    left_knee = get(MP_LEFT_KNEE)
    right_knee = get(MP_RIGHT_KNEE)
    left_ankle = get(MP_LEFT_ANKLE)
    right_ankle = get(MP_RIGHT_ANKLE)
    left_hand = get(MP_LEFT_INDEX)
    right_hand = get(MP_RIGHT_INDEX)
    left_foot = get(MP_LEFT_FOOT_INDEX)
    right_foot = get(MP_RIGHT_FOOT_INDEX)

    # hips = 左右髋中心
    hips = _midpoint(left_hip, right_hip)
    if hips:
        joints["hips"] = {"x": hips[0], "y": hips[1], "z": hips[2], "confidence": 1.0}

    # chest = 肩中心
    chest = _midpoint(left_shoulder, right_shoulder)
    if chest:
        joints["chest"] = {"x": chest[0], "y": chest[1], "z": chest[2], "confidence": 1.0}

    # spine = 髋中心 → 肩中心 的 0.4 处
    if hips and chest:
        t = 0.4
        joints["spine"] = {
            "x": hips[0] + (chest[0] - hips[0]) * t,
            "y": hips[1] + (chest[1] - hips[1]) * t,
            "z": hips[2] + (chest[2] - hips[2]) * t,
            "confidence": 1.0,
        }

    # neck = 肩中心 → 鼻子 的 0.3 处
    if chest and nose:
        t = 0.3
        joints["neck"] = {
            "x": chest[0] + (nose[0] - chest[0]) * t,
            "y": chest[1] + (nose[1] - chest[1]) * t,
            "z": chest[2] + (nose[2] - chest[2]) * t,
            "confidence": 1.0,
        }

    # head = 鼻子
    if nose:
        joints["head"] = {"x": nose[0], "y": nose[1], "z": nose[2], "confidence": 1.0}

    # 直接映射的关键点
    direct_map = {
        "leftShoulder": left_shoulder, "leftElbow": left_elbow,
        "leftWrist": left_wrist, "leftHand": left_hand,
        "rightShoulder": right_shoulder, "rightElbow": right_elbow,
        "rightWrist": right_wrist, "rightHand": right_hand,
        "leftHip": left_hip, "leftKnee": left_knee,
        "leftAnkle": left_ankle, "leftFoot": left_foot,
        "rightHip": right_hip, "rightKnee": right_knee,
        "rightAnkle": right_ankle, "rightFoot": right_foot,
    }

    for name, pos in direct_map.items():
        if pos:
            joints[name] = {"x": pos[0], "y": pos[1], "z": pos[2], "confidence": 1.0}

    return joints if joints else None


def calculate_bone_lengths_from_joints(
    joints: Dict[str, Dict[str, float]],
    bone_connections: Dict[str, Tuple[str, str]],
) -> Dict[str, float]:
    """
    根据关节点计算骨长

    bone_connections: {"leftUpperArm": ("leftShoulder", "leftElbow"), ...}
    """
    lengths = {}
    for bone_name, (from_joint, to_joint) in bone_connections.items():
        f = joints.get(from_joint)
        t = joints.get(to_joint)
        if not f or not t:
            continue
        dx = t["x"] - f["x"]
        dy = t["y"] - f["y"]
        dz = t["z"] - f["z"]
        lengths[bone_name] = math.sqrt(dx*dx + dy*dy + dz*dz)
    return lengths


# 标准骨骼连接定义（从关节点 -> 骨骼）
# 格式: bone_name -> (from_joint, to_joint)
STANDARD_BONE_CONNECTIONS = {
    "hips":          ("leftHip", "rightHip"),  # 伪骨骼，用于hips宽度
    "spine":         ("hips", "spine"),
    "chest":         ("spine", "chest"),
    "neck":          ("chest", "neck"),
    "head":          ("neck", "head"),
    "leftShoulder":  ("chest", "leftShoulder"),
    "leftUpperArm":  ("leftShoulder", "leftElbow"),
    "leftLowerArm":  ("leftElbow", "leftWrist"),
    "leftHand":      ("leftWrist", "leftHand"),
    "rightShoulder": ("chest", "rightShoulder"),
    "rightUpperArm": ("rightShoulder", "rightElbow"),
    "rightLowerArm": ("rightElbow", "rightWrist"),
    "rightHand":     ("rightWrist", "rightHand"),
    "leftUpperLeg":  ("leftHip", "leftKnee"),
    "leftLowerLeg":  ("leftKnee", "leftAnkle"),
    "leftFoot":      ("leftAnkle", "leftFoot"),
    "rightUpperLeg": ("rightHip", "rightKnee"),
    "rightLowerLeg": ("rightKnee", "rightAnkle"),
    "rightFoot":     ("rightAnkle", "rightFoot"),
}
