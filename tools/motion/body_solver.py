"""
身体朝向估计

从 MediaPipe 关键点估计身体局部坐标系 (right, up, forward)
"""
import math
from typing import Dict, List, Optional, Tuple


def _norm(v):
    """归一化向量"""
    x, y, z = v
    length = math.sqrt(x * x + y * y + z * z)
    if length < 1e-6:
        return (0.0, 1.0, 0.0)
    return (x / length, y / length, z / length)


def _cross(a, b):
    """向量叉积"""
    ax, ay, az = a
    bx, by, bz = b
    return (ay * bz - az * by, az * bx - ax * bz, ax * by - ay * bx)


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def solve_body_basis(
    landmarks: List[Dict],
    use_world: bool = True,
) -> Optional[Dict]:
    """
    从 MediaPipe 关键点计算身体坐标系

    返回: {
        "right": (x, y, z),   # 右肩到左肩方向（矫正为纯左右）
        "up": (x, y, z),      # 胯部到肩膀方向
        "forward": (x, y, z), # 前向 = right x up
        "hips_center": (x, y, z),
        "shoulder_center": (x, y, z),
    }

    use_world: True 使用 wx/wy/wz, False 使用 x/y/z
    """
    lm_by_id = {lm["id"]: lm for lm in landmarks}

    def get_xyz(lm):
        if use_world and lm.get("wx") is not None:
            # MediaPipe world: right-handed, Y-down, +Z AWAY from camera
            # Three.js: right-handed, Y-up, +Z TOWARDS camera
            # X: MediaPipe +X points to person's RIGHT (same as Three.js) -> no flip
            # Y: MediaPipe Y-down -> Three.js Y-up -> flip
            # Z: MediaPipe +Z away -> Three.js +Z towards -> flip
            return (lm["wx"], -lm["wy"], -lm["wz"])
        # 图像坐标：x向右，y向下（图像原点在左上角）
        # 转换为Three.js：x不变，y翻转（1.0 - y），z使用深度值（缩放因子0.3为经验值）
        # 注意：MediaPipe图像坐标的y轴向下，需要翻转
        return (lm["x"], 1.0 - lm["y"], lm.get("z", 0) * 0.3)

    def get_lm(idx):
        lm = lm_by_id.get(idx)
        if not lm:
            return None
        return get_xyz(lm)

    left_shoulder = get_lm(11)
    right_shoulder = get_lm(12)
    left_hip = get_lm(23)
    right_hip = get_lm(24)

    if not all([left_shoulder, right_shoulder, left_hip, right_hip]):
        return None

    shoulder_center = (
        (left_shoulder[0] + right_shoulder[0]) / 2,
        (left_shoulder[1] + right_shoulder[1]) / 2,
        (left_shoulder[2] + right_shoulder[2]) / 2,
    )
    hip_center = (
        (left_hip[0] + right_hip[0]) / 2,
        (left_hip[1] + right_hip[1]) / 2,
        (left_hip[2] + right_hip[2]) / 2,
    )

    # up: hip_center -> shoulder_center (torso direction)
    up_raw = _sub(shoulder_center, hip_center)
    up = _norm(up_raw)

    # 计算肩部向量（从右肩到左肩）
    shoulder_vec = _sub(left_shoulder, right_shoulder)
    shoulder_len = math.sqrt(shoulder_vec[0]**2 + shoulder_vec[1]**2 + shoulder_vec[2]**2)

    if shoulder_len < 1e-6:
        right = (1.0, 0.0, 0.0)
    else:
        # MediaPipe world: +X points to camera's RIGHT (= person's LEFT).
        # left_shoulder (person's right shoulder) has SMALLER x,
        # right_shoulder (person's left shoulder) has LARGER x.
        # shoulder_vec = left - right points from person's left shoulder to right shoulder,
        # which IS the person's RIGHT direction. No negation needed.
        right = (shoulder_vec[0] / shoulder_len,
                 shoulder_vec[1] / shoulder_len,
                 shoulder_vec[2] / shoulder_len)

    # forward = right × up  (right-handed basis: X × Y = Z)
    forward = _norm(_cross(right, up))

    # Re-orthogonalize: up = forward × right to guarantee right-handed orthonormal basis
    up = _norm(_cross(forward, right))

    return {
        "right": right,
        "up": up,
        "forward": forward,
        "hips_center": hip_center,
        "shoulder_center": shoulder_center,
    }


def solve_root_transform(
    body_basis: Dict,
) -> Dict:
    """
    从身体坐标系计算 root (hips) 世界旋转和位置

    返回: {
        "position": {"x": ..., "y": ..., "z": ...},
        "rotation": {"x": ..., "y": ..., "z": ..., "w": ...},  # 四元数
        "basis": body_basis,
    }
    """
    if not body_basis:
        return None

    right = body_basis["right"]
    up = body_basis["up"]
    forward = body_basis["forward"]

    # 从旋转矩阵转四元数
    # Three.js 坐标系: 右手系, Y-up
    # 局部 +X = right, +Y = up, +Z = forward
    # 矩阵列向量 = [right up forward]
    # [ rx  ux  fx ]
    # [ ry  uy  fy ]
    # [ rz  uz  fz ]
    rx, ry, rz = right
    ux, uy, uz = up
    fx, fy, fz = forward

    # 使用更稳健的四元数计算方法，避免在trace接近-1时数值不稳定
    # 参考：https://www.euclideanspace.com/maths/geometry/rotations/conversions/matrixToQuaternion/
    trace = rx + uy + fz
    
    if trace > 0:
        s = 0.5 / math.sqrt(trace + 1.0)
        qw = 0.25 / s
        qx = (uz - fy) * s
        qy = (fx - rz) * s
        qz = (ry - ux) * s
    else:
        # 当trace <= 0时，使用更稳定的分支选择
        if rx >= uy and rx >= fz:
            # X轴是最大的对角线元素
            s = 2.0 * math.sqrt(1.0 + rx - uy - fz)
            # 防止除零
            if abs(s) < 1e-8:
                s = 1e-8
            qw = (uz - fy) / s
            qx = 0.25 * s
            qy = (ux + ry) / s
            qz = (fx + rz) / s
        elif uy >= fz:
            # Y轴是最大的对角线元素
            s = 2.0 * math.sqrt(1.0 + uy - rx - fz)
            if abs(s) < 1e-8:
                s = 1e-8
            qw = (fx - rz) / s
            qx = (ux + ry) / s
            qy = 0.25 * s
            qz = (fy + uz) / s
        else:
            # Z轴是最大的对角线元素
            s = 2.0 * math.sqrt(1.0 + fz - rx - uy)
            if abs(s) < 1e-8:
                s = 1e-8
            qw = (ry - ux) / s
            qx = (fx + rz) / s
            qy = (fy + uz) / s
            qz = 0.25 * s

    # 归一化
    length = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw)
    if length > 1e-6:
        qx, qy, qz, qw = qx / length, qy / length, qz / length, qw / length

    hc = body_basis["hips_center"]
    return {
        "position": {"x": hc[0], "y": hc[1], "z": hc[2]},
        "rotation": {"x": qx, "y": qy, "z": qz, "w": qw},
        "basis": body_basis,
    }
