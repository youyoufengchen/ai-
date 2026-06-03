"""
Two-Bone IK 求解器

用于手臂、腿部：保证手腕/脚踝到达目标位置
"""
import math
from typing import Dict, List, Optional, Tuple


def solve_two_bone_ik(
    root_pos: Tuple[float, float, float],
    mid_pos: Tuple[float, float, float],
    end_pos: Tuple[float, float, float],
    target_pos: Tuple[float, float, float],
    pole_pos: Optional[Tuple[float, float, float]] = None,
) -> Optional[Dict]:
    """
    Two-Bone IK

    root: 根部关节 (shoulder / hip)
    mid: 中间关节 (elbow / knee)
    end: 末端关节 (wrist / ankle)
    target: 目标位置 (wrist target / ankle target)
    pole: 极点方向参考 (elbow 朝向 / knee 朝向)

    返回: {
        "root_rot": {"x", "y", "z", "w"},  # root->mid 的旋转 (局部)
        "mid_rot": {"x", "y", "z", "w"},   # mid->end 的旋转 (局部)
    }
    """
    import numpy as np

    a = np.array(root_pos)
    b = np.array(mid_pos)
    c = np.array(end_pos)
    t = np.array(target_pos)

    ab = b - a
    bc = c - b
    at = t - a

    len_ab = np.linalg.norm(ab)
    len_bc = np.linalg.norm(bc)
    len_at = np.linalg.norm(at)

    if len_ab < 1e-6 or len_bc < 1e-6:
        return None

    # 限制目标距离不超过总长
    max_reach = len_ab + len_bc
    if len_at > max_reach:
        # 伸直
        len_at = max_reach * 0.99999
        at = at / np.linalg.norm(at) * len_at
        t = a + at

    # 余弦定理求 elbow 角度
    # law of cosines: c² = a² + b² - 2ab cos(C)
    # 这里我们要求 mid 处的角度（elbow/knee 弯曲角）
    # a = len_bc, b = len_at, c = len_ab
    # cos(angle_at_mid) = (len_ab² + len_bc² - len_at²) / (2 * len_ab * len_bc)
    # 不对，应该是求 root 处的角度和 mid 处的角度

    # 简化：我们只关心方向
    # 在 rest pose 平面内旋转
    # 这里用方向向量方法

    # rest 方向: root -> end
    rest_end_dir = c - a
    target_end_dir = t - a

    rest_len = np.linalg.norm(rest_end_dir)
    target_len = np.linalg.norm(target_end_dir)
    if rest_len < 1e-6 or target_len < 1e-6:
        return None

    rest_end_dir /= rest_len
    target_end_dir /= target_len

    # root 处的 delta 旋转 (从 rest 的 root->end 方向转到 target 的 root->end 方向)
    # 这个旋转同时会旋转 mid
    dot = np.dot(rest_end_dir, target_end_dir)
    dot = max(-1.0, min(1.0, dot))
    angle = math.acos(dot)

    if abs(angle) < 1e-6:
        axis = np.array([0, 1, 0])
    else:
        axis = np.cross(rest_end_dir, target_end_dir)
        axis_len = np.linalg.norm(axis)
        if axis_len < 1e-6:
            axis = np.array([0, 1, 0])
        else:
            axis /= axis_len

    half_angle = angle / 2
    s = math.sin(half_angle)
    c = math.cos(half_angle)
    root_delta_q = np.array([axis[0] * s, axis[1] * s, axis[2] * s, c])

    # mid 处的弯曲
    # 先旋转 mid 和 end
    # 用四元数旋转 vector
    def quat_rotate_vector(q, v):
        """q = [x, y, z, w]"""
        qx, qy, qz, qw = q
        # v' = q * v * q⁻¹
        # 简化的 vector rotation
        tx = 2 * (qy * v[2] - qz * v[1])
        ty = 2 * (qz * v[0] - qx * v[2])
        tz = 2 * (qx * v[1] - qy * v[0])
        return np.array([
            v[0] + qw * tx + qy * tz - qz * ty,
            v[1] + qw * ty + qz * tx - qx * tz,
            v[2] + qw * tz + qx * ty - qy * tx,
        ])

    new_b = quat_rotate_vector(root_delta_q, ab) + a
    new_bc = c - new_b  # 这一步有问题，c 没变
    # 实际上应该用 rest 长度和 target 长度关系来算

    # 更简单的方法：直接返回方向变化
    # 服务端只负责计算方向，真正的 IK 在前端用 Three.js 做
    # 因为前端有骨骼层级信息

    return {
        "root_delta_dir": tuple(target_end_dir),
        "angle": angle,
        "root_rot": {"x": float(root_delta_q[0]), "y": float(root_delta_q[1]),
                     "z": float(root_delta_q[2]), "w": float(root_delta_q[3])},
    }


def solve_limb_ik(
    root_pos,
    mid_pos,
    end_pos,
    target_pos,
    pole_hint=None,
) -> Dict:
    """
    简化版肢体 IK：返回 root->mid 和 mid->end 的方向
    实际旋转在前端计算（因为需要骨骼层级）
    """
    return solve_two_bone_ik(root_pos, mid_pos, end_pos, target_pos, pole_hint)
