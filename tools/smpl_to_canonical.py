"""
SMPL pose → Canonical Motion JSON 转换器

将 4DHumans/VIBE 输出的 SMPL 参数转换为系统内部 canonical.json 格式。

输入：
    - smpl_pose: [T, 72] 旋转参数（Rodrigues 向量，每关节 3 维）
    - smpl_trans: [T, 3] 根节点平移（可选，默认零）
    - smpl_shape: [10,] 体型参数（可选，默认零向量）

输出：
    - canonical.json（v5.1 格式，含 joints 位置和 hips 旋转）

用法示例：
    python tools/smpl_to_canonical.py --pkl outputs/result.pkl --out motion/
    python tools/smpl_to_canonical.py --pose pose.npy --trans trans.npy --out motion/
"""

import json
import sys
from pathlib import Path
import numpy as np

try:
    import torch
except ImportError:
    torch = None

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

# ---------------------------------------------------------------------------
# SMPL 关节索引 (0-23) → Canonical 关节名
# 参考: https://meshcapade.wiki/SMPL
# ---------------------------------------------------------------------------
SMPL_JOINT_NAMES = [
    "pelvis",          # 0
    "left_hip",        # 1
    "right_hip",       # 2
    "spine1",          # 3
    "left_knee",       # 4
    "right_knee",      # 5
    "spine2",          # 6
    "left_ankle",      # 7
    "right_ankle",     # 8
    "spine3",          # 9
    "left_foot",       # 10
    "right_foot",      # 11
    "neck",            # 12
    "left_collar",     # 13
    "right_collar",    # 14
    "head",            # 15
    "left_shoulder",   # 16
    "right_shoulder",  # 17
    "left_elbow",      # 18
    "right_elbow",     # 19
    "left_wrist",      # 20
    "right_wrist",     # 21
    "left_hand",       # 22
    "right_hand",      # 23
]

# SMPL 索引 → Canonical 名（未列出的索引丢弃）
SMPL_TO_CANONICAL = {
    0:  "hips",
    1:  "leftUpperLeg",
    2:  "rightUpperLeg",
    3:  "spine",
    4:  "leftLowerLeg",
    5:  "rightLowerLeg",
    9:  "chest",          # spine3 映射为 chest
    7:  "leftFoot",
    8:  "rightFoot",
    12: "neck",
    13: "leftShoulder",  # collar/clavicle
    14: "rightShoulder",
    15: "head",
    16: "leftUpperArm",  # humerus
    17: "rightUpperArm",
    18: "leftLowerArm",  # radius/ulna
    19: "rightLowerArm",
    20: "leftHand",      # wrist
    21: "rightHand",
}

# spine2 (索引 6) 被丢弃，因为 canonical 只有 hips → spine → chest 两层中间节点


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------
def rodrigues_to_matrix(rvec: np.ndarray) -> np.ndarray:
    """Rodrigues 旋转向量 → 3x3 旋转矩阵"""
    theta = np.linalg.norm(rvec)
    if theta < 1e-6:
        return np.eye(3)
    k = rvec / theta
    K = np.array([[0, -k[2], k[1]],
                  [k[2], 0, -k[0]],
                  [-k[1], k[0], 0]])
    R = np.eye(3) + np.sin(theta) * K + (1 - np.cos(theta)) * (K @ K)
    return R


def matrix_to_euler_xyz(R: np.ndarray) -> np.ndarray:
    """
    旋转矩阵 → Euler 角 (XYZ 内禀旋转，即 X→Y→Z 顺序)
    返回 [rx, ry, rz] 弧度
    """
    # 处理万向节锁
    if abs(R[2, 0]) > 0.999999:
        # cos(ry) ≈ 0，ry ≈ ±90°
        ry = -np.pi / 2 if R[2, 0] > 0 else np.pi / 2
        rz = 0.0
        rx = np.arctan2(-R[0, 1], R[0, 2])
    else:
        ry = np.arctan2(-R[2, 0], np.sqrt(R[0, 0]**2 + R[1, 0]**2))
        rx = np.arctan2(R[1, 0], R[0, 0])
        rz = np.arctan2(R[2, 1], R[2, 2])
    return np.array([rx, ry, rz])


def matrix_to_quaternion(R: np.ndarray) -> dict:
    """
    3x3 旋转矩阵 → 四元数 {x, y, z, w}
    使用 Shepperd 方法，数值稳定
    """
    trace = R[0, 0] + R[1, 1] + R[2, 2]
    if trace > 0:
        s = 0.5 / np.sqrt(trace + 1.0)
        w = 0.25 / s
        x = (R[2, 1] - R[1, 2]) * s
        y = (R[0, 2] - R[2, 0]) * s
        z = (R[1, 0] - R[0, 1]) * s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = 2.0 * np.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2])
        w = (R[2, 1] - R[1, 2]) / s
        x = 0.25 * s
        y = (R[0, 1] + R[1, 0]) / s
        z = (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = 2.0 * np.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2])
        w = (R[0, 2] - R[2, 0]) / s
        x = (R[0, 1] + R[1, 0]) / s
        y = 0.25 * s
        z = (R[1, 2] + R[2, 1]) / s
    else:
        s = 2.0 * np.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1])
        w = (R[1, 0] - R[0, 1]) / s
        x = (R[0, 2] + R[2, 0]) / s
        y = (R[1, 2] + R[2, 1]) / s
        z = 0.25 * s
    return {"x": float(x), "y": float(y), "z": float(z), "w": float(w)}


def _load_smpl_data_struct(npz_path: str):
    """从 .npz 文件加载 SMPL 参数，构造 smplx 所需的 data_struct。"""
    from types import SimpleNamespace
    npz = np.load(npz_path, allow_pickle=True)
    data = SimpleNamespace()
    for key in npz.files:
        val = npz[key]
        # 跳过非数值的 object 数组（如 pose_training_info dict）
        if val.dtype == object:
            continue
        setattr(data, key, val)
    # shapedirs 在原始 .pkl 中被 chumpy 包裹且无法正确恢复，
    # 对于 betas=0 的标准体型可安全使用零数组替代
    if not hasattr(data, 'shapedirs') or getattr(data, 'shapedirs', None) is None or \
            (hasattr(data.shapedirs, 'ndim') and data.shapedirs.ndim == 0):
        data.shapedirs = np.zeros((6890, 3, 10), dtype=np.float32)
    return data


def compute_smpl_joint_positions(smpl_pose: np.ndarray,
                                  smpl_trans: np.ndarray = None,
                                  smpl_shape: np.ndarray = None,
                                  model_path: str = None) -> np.ndarray:
    """
    使用 smplx 计算 SMPL 关节世界坐标。

    Args:
        smpl_pose: [T, 72] 或 [T, 24, 3] Rodrigues 向量
        smpl_trans: [T, 3] 根节点平移，可选
        smpl_shape: [10,] 体型参数，可选
        model_path: SMPL .npz 文件路径，默认 data/basicModel_neutral_lbs_10_207_0_v1.0.0.npz

    Returns:
        joint_positions: [T, 24, 3] 关节世界坐标（仅 body joints，不含 hand）
    """
    try:
        import smplx
    except ImportError:
        raise ImportError("请先安装 smplx: pip install smplx")

    if model_path is None:
        model_path = str(Path(__file__).parent.parent / "data" / "basicModel_neutral_lbs_10_207_0_v1.0.0.npz")

    T = smpl_pose.shape[0]

    # 检测 pose 格式: [T,24,3,3] 为旋转矩阵, [T,72] 或 [T,24,3] 为 Rodrigues
    use_rotmat = (smpl_pose.ndim == 4)
    if not use_rotmat and smpl_pose.ndim == 3:
        smpl_pose = smpl_pose.reshape(T, -1)

    if smpl_trans is None:
        smpl_trans = np.zeros((T, 3), dtype=np.float32)
    elif smpl_trans.ndim == 1:
        smpl_trans = smpl_trans.reshape(1, -1).repeat(T, axis=0)

    if smpl_shape is None:
        smpl_shape = np.zeros(10, dtype=np.float32)
    if smpl_shape.ndim == 1:
        smpl_shape = smpl_shape.reshape(1, -1)

    device = "cpu"

    data_struct = _load_smpl_data_struct(model_path)
    body_model = smplx.body_models.SMPL(
        model_path='',
        data_struct=data_struct,
        gender="neutral",
        batch_size=T,
    ).to(device)

    pose_tensor = smplx.utils.to_tensor(smpl_pose, dtype=torch.float32).to(device)
    trans_tensor = smplx.utils.to_tensor(smpl_trans, dtype=torch.float32).to(device)
    shape_tensor = smplx.utils.to_tensor(smpl_shape, dtype=torch.float32).to(device)

    if use_rotmat:
        # pose_tensor shape: [T, 24, 3, 3]
        # smplx global_orient 需要 [T, 1, 3, 3]，body_pose 需要 [T, 23, 3, 3]
        g_orient = pose_tensor[:, 0:1]   # [T, 1, 3, 3]
        b_pose   = pose_tensor[:, 1:]    # [T, 23, 3, 3]
        output = body_model(
            global_orient=g_orient,
            body_pose=b_pose,
            transl=trans_tensor,
            betas=shape_tensor,
            pose2rot=False,
        )
    else:
        output = body_model(
            global_orient=pose_tensor[:, :3],
            body_pose=pose_tensor[:, 3:],
            transl=trans_tensor,
            betas=shape_tensor,
        )

    # smplx joints 输出包含 body + hand = 45 个关节，取前 24 个 body joints
    joint_positions = output.joints[:, :24].detach().cpu().numpy()
    return joint_positions


def estimate_hips_yaw(joints: dict) -> float:
    """
    从 shoulders 和 hips 的相对位置估算 hips Y 轴旋转（yaw）。

    核心思路：人物转身时，左右肩在水平面的相对位置会变化。
    面朝 +Z 时，左肩在 +X，右肩在 -X，肩宽向量沿 +X。
    左转 90° 时，肩宽向量沿 +Z。

    Returns:
        yaw: 弧度，范围 [-π, π]
    """
    left_shoulder = joints.get("leftShoulder")
    right_shoulder = joints.get("rightShoulder")

    if not left_shoulder or not right_shoulder:
        return 0.0

    shoulder_vec = np.array([
        left_shoulder["x"] - right_shoulder["x"],
        left_shoulder["z"] - right_shoulder["z"],
    ], dtype=np.float64)

    norm = np.linalg.norm(shoulder_vec)
    if norm < 1e-6:
        return 0.0

    # atan2(z, x)：肩宽向量在 XZ 平面的角度
    yaw = float(np.arctan2(shoulder_vec[1], shoulder_vec[0]))

    # 校准：T-pose 面朝 +Z 时，左肩(+X) - 右肩(-X) = [2*width, 0]
    # atan2(0, pos) = 0，此时 yaw 应为 0，无需偏移

    return yaw


# ---------------------------------------------------------------------------
# 主转换函数
# ---------------------------------------------------------------------------
def smpl_to_canonical(smpl_pose: np.ndarray,
                       smpl_trans: np.ndarray = None,
                       smpl_shape: np.ndarray = None,
                       fps: float = 30.0,
                       model_path: str = None) -> dict:
    """
    SMPL 参数 → canonical.json dict

    Returns:
        canonical_data: 可直接 json.dump 的字典
    """
    # 1. 计算关节世界坐标
    joint_positions = compute_smpl_joint_positions(
        smpl_pose, smpl_trans, smpl_shape, model_path
    )
    T = joint_positions.shape[0]

    # 2. 提取 hips 第一帧位置作为基准（全局相对化）
    base = joint_positions[0, 0]  # [3,] 第一帧 hips

    # 预计算所有帧的旋转矩阵
    # smpl_pose 可能是 [T,72], [T,24,3] 或 [T,24,3,3]
    if smpl_pose.ndim == 4:
        # 已经是旋转矩阵 [T,24,3,3]
        rot_mats = smpl_pose  # [T,24,3,3]
    else:
        # Rodrigues 向量转旋转矩阵
        pose_flat = smpl_pose.reshape(T, 24, 3)
        rot_mats = np.stack([
            np.stack([rodrigues_to_matrix(pose_flat[t, j]) for j in range(24)])
            for t in range(T)
        ])  # [T,24,3,3]

    frames = []
    for t in range(T):
        # 映射关节位置
        # HMR2 输出的 smplx joint 坐标 Y 轴向下（相机坐标系），需要翻转 Y 和 Z
        # 变换: x→x, y→-y, z→-z （右手系保持不变，头在 +Y，前方在 +Z）
        joints = {}
        for smpl_idx, canonical_name in SMPL_TO_CANONICAL.items():
            pos = joint_positions[t, smpl_idx] - base
            joints[canonical_name] = {
                "x": float(pos[0]),
                "y": float(-pos[1]),
                "z": float(-pos[2]),
                "confidence": 1.0,
            }

        # 补全前端 reconstructions 需要的关节别名
        # 前端 reconstructions 格式: [bone, from_joint, to_joint]
        # SMPL 关节点实际含义:
        #   leftUpperLeg(1)=髋, leftLowerLeg(4)=膝, leftFoot(7)=踝
        #   leftShoulder(13)=锁骨, leftUpperArm(16)=真正肩关节, leftLowerArm(18)=肘, leftHand(20)=腕
        aliases = [
            ("leftHand",     "leftWrist"),    # idx20=wrist
            ("rightHand",    "rightWrist"),
            ("leftFoot",     "leftAnkle"),    # idx7=ankle
            ("rightFoot",    "rightAnkle"),
            ("leftUpperLeg", "leftHip"),      # idx1=hip → from for leftUpperLeg bone
            ("rightUpperLeg","rightHip"),
            ("leftLowerLeg", "leftKnee"),     # idx4=knee → to for leftUpperLeg, from for leftLowerLeg
            ("rightLowerLeg","rightKnee"),
            ("leftLowerArm", "leftElbow"),    # idx18=elbow → to for leftUpperArm, from for leftLowerArm
            ("rightLowerArm","rightElbow"),
        ]
        for src, dst in aliases:
            if src in joints and dst not in joints:
                joints[dst] = dict(joints[src])

        # bones：hips 只输出 position，旋转由前端从 joints 坐标反推
        root_pos = joint_positions[t, 0] - base
        bones = {
            "hips": {
                "position": {
                    "x": float(root_pos[0]),
                    "y": float(-root_pos[1]),
                    "z": float(-root_pos[2]),
                },
            }
        }

        frames.append({
            "time": t / fps,
            "joints": joints,
            "bones": bones,
        })

    canonical_data = {
        "version": "5.0",
        "type": "canonical_motion",
        "source": "4dhumans_smpl",
        "fps": fps,
        "duration": T / fps,
        "frameCount": T,
        "frames": frames,
        "jointNames": sorted(set(SMPL_TO_CANONICAL.values())),
        "hasJoints": True,
        "hasBones": True,
    }

    return canonical_data


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    import argparse
    parser = argparse.ArgumentParser(description="SMPL → Canonical JSON 转换")
    parser.add_argument("--pkl", type=str, help="4DHumans 输出的 .pkl 文件路径")
    parser.add_argument("--pose", type=str, help="SMPL pose .npy 文件 [T, 72]")
    parser.add_argument("--trans", type=str, help="SMPL translation .npy 文件 [T, 3]")
    parser.add_argument("--shape", type=str, help="SMPL shape .npy 文件 [10,]")
    parser.add_argument("--out", type=str, required=True, help="输出目录")
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument("--model", type=str, default=None, help="SMPL .npz 模型路径（默认 data/basicModel_neutral_lbs_10_207_0_v1.0.0.npz）")
    args = parser.parse_args()

    # 加载输入
    if args.pkl:
        import pickle
        with open(args.pkl, "rb") as f:
            data = pickle.load(f)
        # 4DHumans track.py 输出的 pkl 结构较复杂，这里简化处理
        # 实际使用时会根据 4DHumans 输出格式调整
        smpl_pose = data["pose"]
        smpl_trans = data.get("trans")
        smpl_shape = data.get("betas")
    else:
        if not args.pose:
            print("[ERROR] 必须提供 --pkl 或 --pose")
            sys.exit(1)
        smpl_pose = np.load(args.pose)
        smpl_trans = np.load(args.trans) if args.trans else None
        smpl_shape = np.load(args.shape) if args.shape else None

    # 转换
    canonical_data = smpl_to_canonical(
        smpl_pose, smpl_trans, smpl_shape,
        fps=args.fps, model_path=args.model,
    )

    # 保存
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "motion.canonical.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(canonical_data, f, ensure_ascii=False, indent=2)

    print(f"[OK] Canonical JSON 已保存: {out_path}")
    print(f"    帧数: {canonical_data['frameCount']}, 时长: {canonical_data['duration']:.2f}s")


if __name__ == "__main__":
    main()
