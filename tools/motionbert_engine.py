"""
MotionBERT 推理引擎

流程：
1. MediaPipe 提取 2D 关键点（Halpe 26 格式）
2. 保存为 AlphaPose 风格 JSON
3. 调用 MotionBERT infer_wild.py 做 3D 提升
4. 输出 X3D.npy → 转成 canonical.json

依赖：
- 已安装 MediaPipe
- MotionBERT 仓库（需克隆 + 下载权重）
"""

import sys
import os
import json
import math
import subprocess
from pathlib import Path
from typing import Dict, List, Any, Optional

import numpy as np

# ── MediaPipe 2D 提取 ──────────────────────

# ── MediaPipe API 兼容层 ──────────────────────

_MEDIAPIPE_USE_LEGACY = False

try:
    import mediapipe as _mp
    _ = _mp.solutions.pose.Pose  # 测试旧版 API
    _MEDIAPIPE_USE_LEGACY = True
except (AttributeError, ImportError):
    _MEDIAPIPE_USE_LEGACY = False


def _extract_2d_legacy(video_path: Path):
    """旧版 mp.solutions.pose 提取 2D"""
    import cv2
    import mediapipe as mp
    mp_pose = mp.solutions.pose
    pose = mp_pose.Pose(
        static_image_mode=False,
        model_complexity=1,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    cap = cv2.VideoCapture(str(video_path))
    all_landmarks = []
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
        h, w = frame.shape[:2]
        result = pose.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        if result.pose_landmarks:
            all_landmarks.append([(lm.x * w, lm.y * h, lm.visibility) for lm in result.pose_landmarks.landmark])
        else:
            all_landmarks.append(None)
    cap.release()
    pose.close()
    return all_landmarks


def _extract_2d_tasks(video_path: Path):
    """新版 Tasks API 提取 2D"""
    import cv2
    import mediapipe as mp
    from mediapipe.tasks import python as mp_tasks
    from mediapipe.tasks.python import vision as mp_vision

    # 复用 extract_motion.py 的模型下载逻辑
    from tools.extract_motion import ensure_model, POSE_MODEL_PATH
    if not ensure_model():
        raise RuntimeError("MediaPipe 模型下载失败")

    base_options = mp_tasks.BaseOptions(model_asset_path=str(POSE_MODEL_PATH))
    options = mp_vision.PoseLandmarkerOptions(
        base_options=base_options,
        output_segmentation_masks=False,
        running_mode=mp_vision.RunningMode.VIDEO,
    )

    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    all_landmarks = []
    frame_idx = 0
    with mp_vision.PoseLandmarker.create_from_options(options) as landmarker:
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            h, w = frame.shape[:2]
            timestamp_ms = int((frame_idx / fps) * 1000)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            result = landmarker.detect_for_video(mp_image, timestamp_ms)
            if result.pose_landmarks:
                all_landmarks.append([(lm.x * w, lm.y * h, lm.visibility) for lm in result.pose_landmarks[0]])
            else:
                all_landmarks.append(None)
            frame_idx += 1
    cap.release()
    return all_landmarks


def extract_2d_with_mediapipe(video_path: Path, output_json: Path) -> bool:
    """用 MediaPipe 提取每帧 2D 关键点，保存为 AlphaPose 风格 JSON"""
    try:
        import cv2
        import mediapipe as mp
    except ImportError as e:
        print(f"[motionbert] MediaPipe 未安装: {e}")
        return False

    # MediaPipe 33 关键点 → Halpe 26 的映射
    MP_TO_HALPE = {
        0: 0,    2: 1,    5: 2,    7: 3,    8: 4,
        11: 5,   12: 6,   13: 7,   14: 8,   15: 9,
        16: 10,  23: 11,  24: 12,  25: 13,  26: 14,
        27: 15,  28: 16,  31: 20,  32: 21,  29: 24,  30: 25,
    }

    try:
        if _MEDIAPIPE_USE_LEGACY:
            all_landmarks = _extract_2d_legacy(video_path)
        else:
            all_landmarks = _extract_2d_tasks(video_path)
    except Exception as e:
        print(f"[motionbert] MediaPipe 提取失败: {e}")
        return False

    results_list = []
    for frame_idx, landmarks in enumerate(all_landmarks):
        if landmarks is None:
            continue
        kpts = np.zeros((26, 3), dtype=np.float32)
        for mp_idx, halpe_idx in MP_TO_HALPE.items():
            kpts[halpe_idx] = landmarks[mp_idx]
        # 补充 Halpe 没有的关节
        kpts[17] = kpts[0]                                    # Head ≈ Nose
        kpts[18] = (kpts[5] + kpts[6]) / 2.0                  # Neck
        kpts[19] = (kpts[11] + kpts[12]) / 2.0                # Hip
        kpts[22] = kpts[20]                                   # LSmallToe
        kpts[23] = kpts[21]                                   # RSmallToe
        confs = np.ones(26, dtype=np.float32)
        for i in range(26):
            confs[i] = kpts[i, 2] if kpts[i, 2] > 0 else 0.5
        keypoints_flat = []
        for i in range(26):
            keypoints_flat.extend([float(kpts[i, 0]), float(kpts[i, 1]), float(confs[i])])
        results_list.append({"image_id": f"{frame_idx:06d}.jpg", "idx": 0, "keypoints": keypoints_flat})

    with open(output_json, "w") as f:
        json.dump(results_list, f)

    print(f"[motionbert] 提取 {len(all_landmarks)} 帧, {len(results_list)} 帧检测到人物 → {output_json}")
    return len(results_list) > 0


# ── 3D 提升 ─────────────────────────────────

def run_motionbert_3d(
    repo_path: Path,
    checkpoint_path: Path,
    json_path: Path,
    vid_path: Path,
    out_dir: Path,
) -> Optional[Path]:
    """调用 MotionBERT infer_wild.py 做 3D 提升"""
    infer_script = repo_path / "infer_wild.py"
    if not infer_script.exists():
        print(f"[motionbert] 找不到 infer_wild.py: {infer_script}")
        return None

    config_path = repo_path / "configs" / "pose3d" / "MB_ft_h36m_global_lite.yaml"
    if not config_path.exists():
        print(f"[motionbert] 找不到 config: {config_path}")
        return None

    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        str(infer_script),
        "--config", str(config_path),
        "--evaluate", str(checkpoint_path),
        "--json_path", str(json_path),
        "--vid_path", str(vid_path),
        "--out_path", str(out_dir),
    ]

    env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH", "")
    repo_str = str(repo_path.resolve())
    env["PYTHONPATH"] = f"{repo_str}{os.pathsep}{pythonpath}" if pythonpath else repo_str

    print(f"[motionbert] 运行: {' '.join(cmd)}")
    print(f"[motionbert] PYTHONPATH={env['PYTHONPATH']}")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(repo_path), env=env)

    if result.stdout:
        print(f"[motionbert] stdout:\n{result.stdout}")
    if result.returncode != 0:
        print(f"[motionbert] 推理失败 (returncode={result.returncode}):\n{result.stderr}")
        return None

    npy_path = out_dir / "X3D.npy"
    if not npy_path.exists():
        print(f"[motionbert] 输出文件不存在: {npy_path}")
        return None

    return npy_path


# ── H36M → Canonical ────────────────────────

def h36m_to_canonical(npy_path: Path, fps: float = 30.0) -> Dict[str, Any]:
    """
    把 MotionBERT 输出的 H36M 17 关键点转成 canonical.json (v5.1)

    H36M 17 joints:
    0: Pelvis/Hips
    1: RHip
    2: RKnee
    3: RAnkle
    4: LHip
    5: LKnee
    6: LAnkle
    7: Spine
    8: Thorax
    9: Neck/Nose
    10: Head
    11: LShoulder
    12: LElbow
    13: LWrist
    14: RShoulder
    15: RElbow
    16: RWrist
    """
    poses_3d = np.load(npy_path)  # [T, 17, 3]
    T = poses_3d.shape[0]

    # H36M → canonical 关节名映射
    # 注意：canonical 格式关节名需和 bvh_to_canonical.py / 前端 JOINT_TO_BONE_MAP 一致
    # 关节名必须与前端 reconstruction 表匹配
    H36M_TO_CANONICAL = {
        0:  "hips",
        1:  "rightHip",
        2:  "rightKnee",
        3:  "rightAnkle",
        4:  "leftHip",
        5:  "leftKnee",
        6:  "leftAnkle",
        7:  "spine",
        8:  "chest",
        9:  "neck",
        10: "head",
        11: "leftShoulder",
        12: "leftElbow",
        13: "leftWrist",
        14: "rightShoulder",
        15: "rightElbow",
        16: "rightWrist",
    }

    import math

    def _calc_dir(joints, from_name, to_name):
        f = joints.get(from_name)
        t = joints.get(to_name)
        if not f or not t:
            return None
        dx = t["x"] - f["x"]
        dy = t["y"] - f["y"]
        dz = t["z"] - f["z"]
        length = math.sqrt(dx*dx + dy*dy + dz*dz)
        if length < 1e-6:
            return None
        return {"x": dx/length, "y": dy/length, "z": dz/length}

    def _estimate_hips_yaw(joints):
        """
        从 shoulders 相对位置估算 hips Y 轴旋转（yaw）。
        人物面朝 +Z 时，左肩(+X) - 右肩(-X) → 肩宽向量沿 +X → yaw = 0
        左转 90° 面朝 -X 时，肩宽向量沿 +Z → yaw = π/2
        右转 90° 面朝 +X 时，肩宽向量沿 -Z → yaw = -π/2
        """
        ls = joints.get("leftShoulder")
        rs = joints.get("rightShoulder")
        if not ls or not rs:
            return 0.0
        sx = ls["x"] - rs["x"]
        sz = ls["z"] - rs["z"]
        norm = math.sqrt(sx * sx + sz * sz)
        if norm < 1e-6:
            return 0.0
        return math.atan2(sz, sx)

    frames = []
    for t in range(T):
        joints = {}
        for h36m_idx, canonical_name in H36M_TO_CANONICAL.items():
            pos = poses_3d[t, h36m_idx]
            # H36M → Three.js 坐标系：Y 向下 → Y 向上，Z 朝向相反
            joints[canonical_name] = {
                "x": float(pos[0]),
                "y": float(-pos[1]),
                "z": float(-pos[2]),
                "confidence": 1.0,
            }

        # 端点近似（用于视频骨骼绘制，不影响角色绑定）
        for side, wrist_name, elbow_name in [
            ("left",  "leftWrist",  "leftElbow"),
            ("right", "rightWrist", "rightElbow"),
        ]:
            wrist = joints[wrist_name]
            elbow = joints[elbow_name]
            dx = wrist["x"] - elbow["x"]
            dy = wrist["y"] - elbow["y"]
            dz = wrist["z"] - elbow["z"]
            joints[f"{side}Hand"] = {
                "x": wrist["x"] + dx * 0.3,
                "y": wrist["y"] + dy * 0.3,
                "z": wrist["z"] + dz * 0.3,
                "confidence": 1.0,
            }

        for side, ankle_name, knee_name in [
            ("left",  "leftAnkle",  "leftKnee"),
            ("right", "rightAnkle", "rightKnee"),
        ]:
            ankle = joints[ankle_name]
            knee  = joints[knee_name]
            dx = ankle["x"] - knee["x"]
            dy = ankle["y"] - knee["y"]
            dz = ankle["z"] - knee["z"]
            joints[f"{side}Foot"] = {
                "x": ankle["x"] + dx * 0.3,
                "y": ankle["y"] + dy * 0.3,
                "z": ankle["z"] + dz * 0.3,
                "confidence": 1.0,
            }

        # 从 shoulders 位置反推 hips Y 轴旋转（解决转身问题）
        yaw = _estimate_hips_yaw(joints)

        # 让前端 v5 reconstruction 自动从 joints 重建 bones.dir
        # 后端补充 hips.rotation，使人物能转身
        bones = {
            "hips": {
                "position": {
                    "x": joints["hips"]["x"],
                    "y": joints["hips"]["y"],
                    "z": joints["hips"]["z"],
                },
                "rotation": {
                    "x": 0.0,
                    "y": yaw,
                    "z": 0.0,
                }
            }
        }

        frames.append({
            "time": round(t / fps, 4),
            "joints": joints,
            "bones": bones,
        })

    duration = T / fps

    return {
        "version": "5.1",
        "hasJoints": True,
        "metadata": {
            "source": "motionbert",
            "joint_count": len(H36M_TO_CANONICAL) + 6,
            "frame_count": T,
            "fps": fps,
            "duration": round(duration, 3),
        },
        "frames": frames,
    }


# ── 主入口 ────────────────────────────────────

def process_video(video_path: str, output_dir: str, repo_path: str = None, checkpoint_path: str = None) -> Dict[str, Any]:
    """
    MotionBERT 完整推理流程

    返回: {"ok": bool, "canonical_path": str, "error": str}
    """
    video_path = Path(video_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. 提取 2D
    json_path = output_dir / "motionbert_2d.json"
    if not extract_2d_with_mediapipe(video_path, json_path):
        return {"ok": False, "error": "MediaPipe 2D 提取失败"}

    # 2. 运行 MotionBERT 3D 提升
    if repo_path and checkpoint_path:
        repo = Path(repo_path)
        ckpt = Path(checkpoint_path)
        tmp_dir = output_dir / "motionbert_tmp"
        npy_path = run_motionbert_3d(repo, ckpt, json_path, video_path, tmp_dir)
        if not npy_path:
            return {"ok": False, "error": "MotionBERT 3D 提升失败（检查仓库和权重）"}
    else:
        # fallback：直接用 MediaPipe World Landmarks 近似 3D（不需要 MotionBERT 权重）
        print("[motionbert] 未配置 MotionBERT 仓库/权重，使用 MediaPipe World Landmarks fallback")
        npy_path = _extract_3d_with_mediapipe_fallback(video_path, output_dir)
        if not npy_path:
            return {"ok": False, "error": "MediaPipe 3D fallback 失败"}

    # 3. 转成 canonical
    canonical = h36m_to_canonical(npy_path)
    canonical_path = output_dir / f"{video_path.stem}.canonical.json"
    with open(canonical_path, "w", encoding="utf-8") as f:
        json.dump(canonical, f, ensure_ascii=False, indent=2)

    return {
        "ok": True,
        "canonical_path": str(canonical_path),
        "frame_count": canonical["metadata"]["frame_count"],
        "duration": canonical["metadata"]["duration"],
    }


def _extract_3d_with_mediapipe_fallback(video_path: Path, output_dir: Path) -> Optional[Path]:
    """
    未安装 MotionBERT 时的 fallback：直接用 MediaPipe Pose World Landmarks
    输出形状 [T, 17, 3] 的 npy 文件
    """
    import cv2
    import mediapipe as mp

    # MediaPipe world landmarks → H36M 17 映射
    MP_H36M_MAP = {
        0: 9,   11: 11,  12: 14,  13: 12,  14: 15,
        15: 13,  16: 16,  23: 4,   24: 1,   25: 5,
        26: 2,  27: 6,   28: 3,
    }

    all_poses = []

    if _MEDIAPIPE_USE_LEGACY:
        mp_pose = mp.solutions.pose
        pose = mp_pose.Pose(
            static_image_mode=False, model_complexity=1,
            min_detection_confidence=0.5, min_tracking_confidence=0.5,
        )
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return None
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            result = pose.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            if result.pose_world_landmarks:
                lm = result.pose_world_landmarks.landmark
                h36m = np.zeros((17, 3), dtype=np.float32)
                for mp_idx, h36m_idx in MP_H36M_MAP.items():
                    h36m[h36m_idx] = [lm[mp_idx].x, lm[mp_idx].y, lm[mp_idx].z]
                h36m[0]  = (h36m[4] + h36m[1]) / 2.0
                h36m[8]  = (h36m[11] + h36m[14]) / 2.0
                h36m[7]  = (h36m[0] + h36m[8]) / 2.0
                h36m[9]  = (h36m[8] + np.array([lm[0].x, lm[0].y, lm[0].z])) / 2.0
                h36m[10] = np.array([lm[0].x, lm[0].y, lm[0].z])
                all_poses.append(h36m)
            else:
                all_poses.append(all_poses[-1].copy() if all_poses else np.zeros((17, 3), dtype=np.float32))
        cap.release()
        pose.close()
    else:
        # 新版 Tasks API
        from mediapipe.tasks import python as mp_tasks
        from mediapipe.tasks.python import vision as mp_vision
        from tools.extract_motion import ensure_model, POSE_MODEL_PATH
        if not ensure_model():
            raise RuntimeError("MediaPipe 模型下载失败")
        base_options = mp_tasks.BaseOptions(model_asset_path=str(POSE_MODEL_PATH))
        options = mp_vision.PoseLandmarkerOptions(
            base_options=base_options, output_segmentation_masks=False,
            running_mode=mp_vision.RunningMode.VIDEO,
        )
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return None
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frame_idx = 0
        with mp_vision.PoseLandmarker.create_from_options(options) as landmarker:
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    break
                timestamp_ms = int((frame_idx / fps) * 1000)
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                result = landmarker.detect_for_video(mp_image, timestamp_ms)
                if result.pose_world_landmarks:
                    lm = result.pose_world_landmarks[0]
                    h36m = np.zeros((17, 3), dtype=np.float32)
                    for mp_idx, h36m_idx in MP_H36M_MAP.items():
                        h36m[h36m_idx] = [lm[mp_idx].x, lm[mp_idx].y, lm[mp_idx].z]
                    h36m[0]  = (h36m[4] + h36m[1]) / 2.0
                    h36m[8]  = (h36m[11] + h36m[14]) / 2.0
                    h36m[7]  = (h36m[0] + h36m[8]) / 2.0
                    h36m[9]  = (h36m[8] + np.array([lm[0].x, lm[0].y, lm[0].z])) / 2.0
                    h36m[10] = np.array([lm[0].x, lm[0].y, lm[0].z])
                    all_poses.append(h36m)
                else:
                    all_poses.append(all_poses[-1].copy() if all_poses else np.zeros((17, 3), dtype=np.float32))
                frame_idx += 1
        cap.release()

    if not all_poses:
        return None
    poses = np.stack(all_poses, axis=0)
    poses *= 1000.0
    npy_path = output_dir / "motionbert_fallback.npy"
    np.save(npy_path, poses)
    return npy_path


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=str)
    parser.add_argument("--output-dir", type=str, default=".")
    parser.add_argument("--repo", type=str, default=None)
    parser.add_argument("--ckpt", type=str, default=None)
    args = parser.parse_args()

    result = process_video(args.video, args.output_dir, args.repo, args.ckpt)
    print(json.dumps(result, ensure_ascii=False, indent=2))
