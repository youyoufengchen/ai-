"""
标准人体骨骼定义 (Canonical Skeleton)

与具体模型无关，只描述人体通用骨骼。
"""
from typing import Dict, List, Optional, Tuple

# MediaPipe Pose 33 关键点
MP_NOSE = 0
MP_LEFT_EYE_INNER = 1
MP_LEFT_EYE = 2
MP_LEFT_EYE_OUTER = 3
MP_RIGHT_EYE_INNER = 4
MP_RIGHT_EYE = 5
MP_RIGHT_EYE_OUTER = 6
MP_LEFT_EAR = 7
MP_RIGHT_EAR = 8
MP_MOUTH_LEFT = 9
MP_MOUTH_RIGHT = 10
MP_LEFT_SHOULDER = 11
MP_RIGHT_SHOULDER = 12
MP_LEFT_ELBOW = 13
MP_RIGHT_ELBOW = 14
MP_LEFT_WRIST = 15
MP_RIGHT_WRIST = 16
MP_LEFT_PINKY = 17
MP_RIGHT_PINKY = 18
MP_LEFT_INDEX = 19
MP_RIGHT_INDEX = 20
MP_LEFT_THUMB = 21
MP_RIGHT_THUMB = 22
MP_LEFT_HIP = 23
MP_RIGHT_HIP = 24
MP_LEFT_KNEE = 25
MP_RIGHT_KNEE = 26
MP_LEFT_ANKLE = 27
MP_RIGHT_ANKLE = 28
MP_LEFT_HEEL = 29
MP_RIGHT_HEEL = 30
MP_LEFT_FOOT_INDEX = 31
MP_RIGHT_FOOT_INDEX = 32

# 标准人体骨骼名
canonical_names = [
    "hips", "spine", "chest", "neck", "head",
    "leftShoulder", "leftUpperArm", "leftLowerArm", "leftHand",
    "rightShoulder", "rightUpperArm", "rightLowerArm", "rightHand",
    "leftUpperLeg", "leftLowerLeg", "leftFoot", "leftToe",
    "rightUpperLeg", "rightLowerLeg", "rightFoot", "rightToe",
]


class CanonicalSkeleton:
    """标准人体骨骼，定义层级、骨长约束、MediaPipe 映射"""

    # 骨骼层级：父 -> [子]
    hierarchy: Dict[str, List[str]] = {
        "hips": ["spine", "leftUpperLeg", "rightUpperLeg"],
        "spine": ["chest"],
        "chest": ["neck"],
        "neck": ["head"],
        "leftShoulder": ["leftUpperArm"],
        "leftUpperArm": ["leftLowerArm"],
        "leftLowerArm": ["leftHand"],
        "rightShoulder": ["rightUpperArm"],
        "rightUpperArm": ["rightLowerArm"],
        "rightLowerArm": ["rightHand"],
        "leftUpperLeg": ["leftLowerLeg"],
        "leftLowerLeg": ["leftFoot"],
        "leftFoot": ["leftToe"],
        "rightUpperLeg": ["rightLowerLeg"],
        "rightLowerLeg": ["rightFoot"],
        "rightFoot": ["rightToe"],
    }

    # 骨骼 -> 起止 MediaPipe landmark
    bone_landmarks: Dict[str, Tuple[int, int]] = {
        "leftUpperArm": (MP_LEFT_SHOULDER, MP_LEFT_ELBOW),
        "leftLowerArm": (MP_LEFT_ELBOW, MP_LEFT_WRIST),
        "leftHand": (MP_LEFT_WRIST, MP_LEFT_INDEX),
        "rightUpperArm": (MP_RIGHT_SHOULDER, MP_RIGHT_ELBOW),
        "rightLowerArm": (MP_RIGHT_ELBOW, MP_RIGHT_WRIST),
        "rightHand": (MP_RIGHT_WRIST, MP_RIGHT_INDEX),
        "leftUpperLeg": (MP_LEFT_HIP, MP_LEFT_KNEE),
        "leftLowerLeg": (MP_LEFT_KNEE, MP_LEFT_ANKLE),
        "leftFoot": (MP_LEFT_ANKLE, MP_LEFT_FOOT_INDEX),
        "rightUpperLeg": (MP_RIGHT_HIP, MP_RIGHT_KNEE),
        "rightLowerLeg": (MP_RIGHT_KNEE, MP_RIGHT_ANKLE),
        "rightFoot": (MP_RIGHT_ANKLE, MP_RIGHT_FOOT_INDEX),
    }

    # 特殊骨骼：hip center / shoulder center 用于方向
    # "hips": (leftHip + rightHip) / 2 -> (leftShoulder + rightShoulder) / 2
    # "spine": (leftShoulder + rightShoulder) / 2 -> neck (暂无)

    @classmethod
    def get_children(cls, bone: str) -> List[str]:
        return cls.hierarchy.get(bone, [])

    @classmethod
    def get_parent(cls, bone: str) -> Optional[str]:
        for p, children in cls.hierarchy.items():
            if bone in children:
                return p
        return None

    @classmethod
    def get_root_bones(cls) -> List[str]:
        """返回可以独立旋转的根级骨骼"""
        return ["hips", "leftShoulder", "rightShoulder"]

    @classmethod
    def get_limb_chain(cls, limb: str) -> List[str]:
        """返回某条肢体的骨骼链，如 leg -> [leftUpperLeg, leftLowerLeg, leftFoot]"""
        chains = {
            "leftLeg": ["leftUpperLeg", "leftLowerLeg", "leftFoot"],
            "rightLeg": ["rightUpperLeg", "rightLowerLeg", "rightFoot"],
            "leftArm": ["leftUpperArm", "leftLowerArm", "leftHand"],
            "rightArm": ["rightUpperArm", "rightLowerArm", "rightHand"],
        }
        return chains.get(limb, [])
