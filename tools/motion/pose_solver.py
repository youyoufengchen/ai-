"""
姿态求解器 (Pose Solver) — 修正版 v2.0

修复：v1.0 把 world-space rotation 直接当作了 local rotation，
      导致四肢绑定错位（手对不上手、脚对不上脚）。

核心思想：
- 输入：关节点坐标（来自视频+深度重建+校准）
- 输出：角色骨骼的局部旋转（AnimationClip 用的 quaternion）
- 方法：层级 FK —— 从 hips 开始递归，利用父骨骼 world rot 反推局部 rot

坐标系：Three.js Y-up
"""

import math
from typing import Dict, List, Optional, Tuple


def _norm(v):
    x, y, z = v
    length = math.sqrt(x*x + y*y + z*z)
    if length < 1e-6:
        return (0.0, 1.0, 0.0)
    return (x/length, y/length, z/length)


def _cross(a, b):
    return (
        a[1]*b[2] - a[2]*b[1],
        a[2]*b[0] - a[0]*b[2],
        a[0]*b[1] - a[1]*b[0],
    )


def _dot(a, b):
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]


def quat_from_vectors(from_vec, to_vec):
    """
    计算从 from_vec 旋转到 to_vec 的四元数
    等效于 Three.js Quaternion.setFromUnitVectors
    """
    fx, fy, fz = _norm(from_vec)
    tx, ty, tz = _norm(to_vec)

    dot = fx*tx + fy*ty + fz*tz
    dot = max(-1.0, min(1.0, dot))

    if dot > 0.99999:
        return (0.0, 0.0, 0.0, 1.0)

    if dot < -0.99999:
        # 180度
        ax, ay, az = (1.0, 0.0, 0.0) if abs(fx) < 0.9 else (0.0, 1.0, 0.0)
        return (ax, ay, az, 0.0)

    angle = math.acos(dot)
    cx = fy*tz - fz*ty
    cy = fz*tx - fx*tz
    cz = fx*ty - fy*tx
    axis_len = math.sqrt(cx*cx + cy*cy + cz*cz)
    if axis_len < 1e-6:
        return (0.0, 0.0, 0.0, 1.0)

    half = angle / 2
    s = math.sin(half) / axis_len
    c = math.cos(half)
    return (cx*s, cy*s, cz*s, c)


def quat_multiply(q1, q2):
    """四元数乘法: q1 * q2"""
    x1, y1, z1, w1 = q1
    x2, y2, z2, w2 = q2
    return (
        w1*x2 + x1*w2 + y1*z2 - z1*y2,
        w1*y2 - x1*z2 + y1*w2 + z1*x2,
        w1*z2 + x1*y2 - y1*x2 + z1*w2,
        w1*w2 - x1*x2 - y1*y2 - z1*z2,
    )


def quat_invert(q):
    """四元数逆（假设归一化）"""
    x, y, z, w = q
    return (-x, -y, -z, w)


def solve_limb_ik(
    root_pos: Tuple[float, float, float],
    mid_pos: Tuple[float, float, float],
    end_pos: Tuple[float, float, float],
    target_pos: Tuple[float, float, float],
    pole_hint: Optional[Tuple[float, float, float]] = None,
) -> Optional[Dict]:
    """
    Two-Bone IK 求解

    返回: {
        "root_rot": (x, y, z, w),  # root 局部旋转
        "mid_rot": (x, y, z, w),   # mid 局部旋转
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

    # 限制目标距离
    max_reach = len_ab + len_bc
    if len_at > max_reach:
        len_at = max_reach * 0.99999
        at = at / np.linalg.norm(at) * len_at
        t = a + at

    # 余弦定理求 mid 角度
    # cos(angle) = (len_ab² + len_bc² - len_at²) / (2 * len_ab * len_bc)
    cos_mid = (len_ab**2 + len_bc**2 - len_at**2) / (2 * len_ab * len_bc)
    cos_mid = max(-1.0, min(1.0, cos_mid))
    mid_angle = math.acos(cos_mid)

    # root 旋转：让 root->mid 指向目标方向
    rest_end_dir = _norm(tuple(c - a))
    target_end_dir = _norm(tuple(t - a))

    root_delta_q = quat_from_vectors(rest_end_dir, target_end_dir)

    # 应用 pole hint（肘/膝方向）
    if pole_hint is not None:
        # 简化：如果有 pole hint，微调 root 旋转使 mid 朝向 pole
        pass

    # mid 的旋转：在 root 旋转后，mid 需要弯曲
    # 先计算 root 旋转后的 mid 位置
    def quat_rotate(q, v):
        x, y, z, w = q
        tx = 2 * (y * v[2] - z * v[1])
        ty = 2 * (z * v[0] - x * v[2])
        tz = 2 * (x * v[1] - y * v[0])
        return (
            v[0] + w * tx + y * tz - z * ty,
            v[1] + w * ty + z * tx - x * tz,
            v[2] + w * tz + x * ty - y * tx,
        )

    new_b = tuple(np.array(quat_rotate(root_delta_q, tuple(ab))) + a)
    new_bc = tuple(np.array(c) - np.array(new_b))
    target_bc = tuple(np.array(t) - np.array(new_b))

    mid_delta_q = quat_from_vectors(new_bc, target_bc)

    return {
        "root_rot": root_delta_q,
        "mid_rot": mid_delta_q,
    }


def _quat_rotate_vector(q, v):
    """四元数旋转向量（q = [x, y, z, w]）"""
    x, y, z, w = q
    tx = 2 * (y * v[2] - z * v[1])
    ty = 2 * (z * v[0] - x * v[2])
    tz = 2 * (x * v[1] - y * v[0])
    return (
        v[0] + w * tx + y * tz - z * ty,
        v[1] + w * ty + z * tx - x * tz,
        v[2] + w * tz + x * ty - y * tx,
    )


def _build_model_rest_local_dirs(model_bone_hierarchy: Dict[str, Dict]) -> Dict[str, Tuple[float, float, float]]:
    """从 model 层级计算每根骨骼在 rest pose 中的局部方向（child.position - parent.position 的归一化）"""
    dirs = {}
    for bone_name, info in model_bone_hierarchy.items():
        children = info.get("children", [])
        if not children:
            continue
        parent_pos = info.get("position", [0, 0, 0])
        # 选 Y 差最大的子骨骼（对 hips 选 spine，对四肢选延伸方向）
        best_child = children[0]
        best_dy = -float("inf")
        for child in children:
            child_info = model_bone_hierarchy.get(child)
            if not child_info:
                continue
            child_pos = child_info.get("position", [0, 0, 0])
            dy = child_pos[1] - parent_pos[1]
            if dy > best_dy:
                best_dy = dy
                best_child = child
        child_info = model_bone_hierarchy.get(best_child)
        if child_info:
            cp = child_info.get("position", [0, 0, 0])
            dx = cp[0] - parent_pos[0]
            dy = cp[1] - parent_pos[1]
            dz = cp[2] - parent_pos[2]
            length = math.sqrt(dx * dx + dy * dy + dz * dz)
            if length > 1e-6:
                dirs[bone_name] = (dx / length, dy / length, dz / length)
    return dirs


def solve_pose_from_joints(
    joints: Dict[str, Dict[str, float]],
    model_bone_hierarchy: Dict[str, Dict],
    bone_binding: Dict[str, str],  # canonical -> model
) -> Dict[str, Dict]:
    """
    从关节点坐标求解角色骨骼的局部旋转

    修复 v1.0 的 world-rotation-as-local 错误：
    现在通过骨骼层级递归，先算 world rotation，再反推 local rotation。

    返回: {model_bone_name: {"position": {...}, "rotation": {...}}}
    """
    from .joints_builder import STANDARD_BONE_CONNECTIONS
    from .canonical_skeleton import CanonicalSkeleton

    result = {}
    model_to_canonical = {v: k for k, v in bone_binding.items()}
    rest_local_dirs = _build_model_rest_local_dirs(model_bone_hierarchy)

    # 1. 计算每根 canonical 骨骼的 world 方向
    canon_dirs = {}
    for bone_name, (from_joint, to_joint) in STANDARD_BONE_CONNECTIONS.items():
        fj = joints.get(from_joint)
        tj = joints.get(to_joint)
        if not fj or not tj:
            continue
        dx = tj["x"] - fj["x"]
        dy = tj["y"] - fj["y"]
        dz = tj["z"] - fj["z"]
        length = math.sqrt(dx * dx + dy * dy + dz * dz)
        if length > 1e-6:
            canon_dirs[bone_name] = (dx / length, dy / length, dz / length)

    # 2. 找到 model 根骨骼（没有 parent 的）
    root_bones = [b for b in model_bone_hierarchy if not model_bone_hierarchy[b].get("parent")]
    if not root_bones:
        hip_model = bone_binding.get("hips")
        if hip_model:
            root_bones = [hip_model]

    # 3. 递归计算局部旋转
    def compute_recursive(model_name: str, parent_world_rot: Tuple[float, float, float, float]):
        """递归遍历 model 骨骼树，计算局部旋转"""
        canon_name = model_to_canonical.get(model_name)
        if not canon_name:
            # 该 model 骨骼没有 canonical 映射，继续递归子骨骼
            info = model_bone_hierarchy.get(model_name, {})
            for child in info.get("children", []):
                compute_recursive(child, parent_world_rot)
            return

        # 获取目标 world 方向
        target_world_dir = canon_dirs.get(canon_name)
        if target_world_dir:
            # 获取该骨骼在 rest pose 中的局部方向
            rest_local_dir = rest_local_dirs.get(model_name, (0.0, 1.0, 0.0))

            # 关键修正：把目标 world 方向投影到父骨骼的局部空间
            # target_in_parent = inv(parent_world_rot) * target_world_dir
            inv_p = quat_invert(parent_world_rot)
            target_in_parent = _quat_rotate_vector(inv_p, target_world_dir)

            # 局部旋转 = 从 rest_local_dir 旋转到 target_in_parent
            local_rot = quat_from_vectors(rest_local_dir, target_in_parent)

            result[model_name] = {
                "rotation": {"x": local_rot[0], "y": local_rot[1], "z": local_rot[2], "w": local_rot[3]}
            }

            # 该骨骼的 world rotation = parent_world_rot * local_rot
            world_rot = quat_multiply(parent_world_rot, local_rot)
        else:
            # 没有目标方向（比如某些手指骨骼），保持 identity
            world_rot = parent_world_rot

        # 递归子骨骼
        info = model_bone_hierarchy.get(model_name, {})
        for child in info.get("children", []):
            compute_recursive(child, world_rot)

    # 4. 启动递归：从根骨骼开始
    # hips 的 parent_world_rot 是 identity，但 hips 自身的 world rotation
    # 需要从 body_basis 传入（或从 hips->spine 方向推导）
    for root in root_bones:
        canon_hip = model_to_canonical.get(root)
        if canon_hip and canon_hip in canon_dirs:
            # 用 hips->spine 方向作为 hips 骨骼的世界方向
            # hips 的 rest_local_dir 通常指向 spine（Y 向上）
            rest_dir = rest_local_dirs.get(root, (0.0, 1.0, 0.0))
            target_dir = canon_dirs[canon_hip]
            # hips 没有父骨骼，local = world
            local_rot = quat_from_vectors(rest_dir, target_dir)
            result[root] = {
                "position": {
                    "x": joints["hips"]["x"],
                    "y": joints["hips"]["y"],
                    "z": joints["hips"]["z"],
                },
                "rotation": {"x": local_rot[0], "y": local_rot[1], "z": local_rot[2], "w": local_rot[3]}
            }
            world_rot = local_rot
        else:
            world_rot = (0.0, 0.0, 0.0, 1.0)

        compute_recursive(root, world_rot)

    return result


def solve_spine_chain(
    joints: Dict[str, Dict[str, float]],
    model_bone_hierarchy: Dict[str, Dict],
    bone_binding: Dict[str, str],
    parent_world_rot: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0),
) -> Dict[str, Dict]:
    """
    求解脊柱链：hips -> spine -> chest -> neck -> head
    使用层级 FK，正确计算局部旋转（修复 v1.0 的 world-as-local 错误）
    """
    bones = {}
    rest_local_dirs = _build_model_rest_local_dirs(model_bone_hierarchy)

    chain = [
        ("hips", "spine", "spine"),
        ("spine", "chest", "chest"),
        ("chest", "neck", "neck"),
        ("neck", "head", "head"),
    ]

    current_world_rot = parent_world_rot
    for from_joint, to_joint, canonical_name in chain:
        fj = joints.get(from_joint)
        tj = joints.get(to_joint)
        if not fj or not tj:
            continue

        target_world_dir = _norm((
            tj["x"] - fj["x"],
            tj["y"] - fj["y"],
            tj["z"] - fj["z"],
        ))

        model_name = bone_binding.get(canonical_name)
        if not model_name or model_name not in model_bone_hierarchy:
            continue

        rest_local_dir = rest_local_dirs.get(model_name, (0.0, 1.0, 0.0))

        # 投影到父空间
        inv_p = quat_invert(current_world_rot)
        target_in_parent = _quat_rotate_vector(inv_p, target_world_dir)
        local_rot = quat_from_vectors(rest_local_dir, target_in_parent)

        bones[model_name] = {
            "rotation": {"x": local_rot[0], "y": local_rot[1], "z": local_rot[2], "w": local_rot[3]}
        }

        # 更新 world rotation 供下一级使用
        current_world_rot = quat_multiply(current_world_rot, local_rot)

    return bones
