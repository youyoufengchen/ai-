"""
extract_motion.py - MediaPipe 视频动作提取脚本 (v4.0)

工作流程：
1. 从视频提取 MediaPipe Pose 关键点（优先 world landmarks）
2. 计算身体坐标系和骨骼方向
3. 滤波平滑
4. 生成 Canonical Motion JSON
5. 质量分析
6. 输出：raw.json / canonical.json / meta.json / 占位 GLB

用法：
    python tools/extract_motion.py <video_path> <output_glb> [--fps 30]
"""

import sys
import io
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import json
import math
import argparse
import struct
from pathlib import Path
from typing import List, Dict, Any, Optional

# 添加 motion 模块到路径
sys.path.insert(0, str(Path(__file__).parent))
from motion import (
    canonical_names,
    CanonicalSkeleton,
    smooth_bone_sequence,
    constrain_bone_lengths,
    solve_body_basis,
    solve_root_transform,
    analyze_motion_quality,
    build_joints_from_landmarks,
    calculate_bone_lengths_from_joints,
    STANDARD_BONE_CONNECTIONS,
    JOINT_NAMES,
    estimate_depth_from_bone_lengths,
    apply_ground_constraint,
    normalize_scale_by_hip_width,
    OneEuroFilter,
    STANDARD_BONE_LENGTH_RATIOS,
)

try:
    import cv2
    import numpy as np
    import mediapipe as mp
    from mediapipe import solutions as mp_solutions
    from mediapipe.framework.formats import landmark_pb2
    MEDIAPIPE_AVAILABLE = True
    USE_TASKS_API = False
except (ImportError, AttributeError):
    try:
        import cv2
        import numpy as np
        import mediapipe as mp
        MEDIAPIPE_AVAILABLE = True
        USE_TASKS_API = True
    except ImportError as e:
        MEDIAPIPE_AVAILABLE = False
        USE_TASKS_API = False
        print(f"错误: MediaPipe 依赖未安装: {e}")
        sys.exit(1)

import os as _os
MODEL_DIR = Path(_os.environ.get("TEMP", _os.path.expanduser("~"))) / "bqf_mediapipe"
POSE_MODEL_PATH = MODEL_DIR / "pose_landmarker_full.task"
POSE_MODEL_URL = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task"

POSE_LANDMARK_NAMES = [
    "NOSE","LEFT_EYE_INNER","LEFT_EYE","LEFT_EYE_OUTER","RIGHT_EYE_INNER","RIGHT_EYE","RIGHT_EYE_OUTER",
    "LEFT_EAR","RIGHT_EAR","MOUTH_LEFT","MOUTH_RIGHT",
    "LEFT_SHOULDER","RIGHT_SHOULDER","LEFT_ELBOW","RIGHT_ELBOW","LEFT_WRIST","RIGHT_WRIST",
    "LEFT_PINKY","RIGHT_PINKY","LEFT_INDEX","RIGHT_INDEX","LEFT_THUMB","RIGHT_THUMB",
    "LEFT_HIP","RIGHT_HIP","LEFT_KNEE","RIGHT_KNEE","LEFT_ANKLE","RIGHT_ANKLE",
    "LEFT_HEEL","RIGHT_HEEL","LEFT_FOOT_INDEX","RIGHT_FOOT_INDEX"
]


def ensure_model():
    if not USE_TASKS_API:
        return True
    if POSE_MODEL_PATH.exists():
        return True
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    print(f"下载 MediaPipe 姿势模型...")
    try:
        import urllib.request
        urllib.request.urlretrieve(POSE_MODEL_URL, POSE_MODEL_PATH)
        print(f"模型下载完成: {POSE_MODEL_PATH}")
        return True
    except Exception as e:
        print(f"模型下载失败: {e}")
        return False


def extract_pose_from_video(video_path: Path, target_fps: float = 30.0, progress_every: int = 30) -> List[Dict[str, Any]]:
    """从视频提取姿势关键点（自动选择 API）"""
    if USE_TASKS_API:
        return _extract_with_tasks_api(video_path, target_fps, progress_every)
    else:
        return _extract_with_legacy_api(video_path, target_fps, progress_every)


def _extract_with_legacy_api(video_path: Path, target_fps: float, progress_every: int) -> List[Dict[str, Any]]:
    """旧版 mp.solutions.pose 提取"""
    pose_module = mp_solutions.pose
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError(f"无法打开视频: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frame_interval = max(1, int(fps / target_fps)) if fps > target_fps else 1
    print(f"视频信息: {fps:.1f}fps, {total_frames}帧, 采样间隔:{frame_interval}")

    frames = []
    with pose_module.Pose(
        static_image_mode=False, model_complexity=1,
        smooth_landmarks=True, min_detection_confidence=0.5, min_tracking_confidence=0.5
    ) as pose:
        frame_count = processed_count = 0
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            if frame_count % frame_interval != 0:
                frame_count += 1
                continue
            results = pose.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            frame_data = {"frame": processed_count, "time": processed_count / target_fps, "landmarks": []}
            # 优先使用 world landmarks（真 3D 坐标）
            world_landmarks = results.pose_world_landmarks.landmark if results.pose_world_landmarks else None
            if results.pose_landmarks:
                for i, lm in enumerate(results.pose_landmarks.landmark):
                    wlm = world_landmarks[i] if world_landmarks and i < len(world_landmarks) else None
                    frame_data["landmarks"].append({
                        "id": i,
                        "name": POSE_LANDMARK_NAMES[i] if i < len(POSE_LANDMARK_NAMES) else str(i),
                        "x": lm.x, "y": lm.y, "z": lm.z, "visibility": lm.visibility,
                        "wx": wlm.x if wlm else None,
                        "wy": wlm.y if wlm else None,
                        "wz": wlm.z if wlm else None,
                    })
            frames.append(frame_data)
            processed_count += 1
            frame_count += 1
            if processed_count % progress_every == 0:
                print(f"处理进度: {frame_count/total_frames*100:.1f}% ({processed_count}帧)")
        cap.release()
    print(f"提取完成: {len(frames)}帧")
    return frames


def _extract_with_tasks_api(video_path: Path, target_fps: float, progress_every: int) -> List[Dict[str, Any]]:
    """新版 mediapipe Tasks API 提取"""
    from mediapipe.tasks import python as mp_tasks
    from mediapipe.tasks.python import vision as mp_vision

    if not ensure_model():
        raise RuntimeError("MediaPipe 模型文件下载失败")

    base_options = mp_tasks.BaseOptions(model_asset_path=str(POSE_MODEL_PATH))
    options = mp_vision.PoseLandmarkerOptions(
        base_options=base_options,
        output_segmentation_masks=False,
        running_mode=mp_vision.RunningMode.VIDEO
    )

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError(f"无法打开视频: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frame_interval = max(1, int(fps / target_fps)) if fps > target_fps else 1
    print(f"视频信息: {fps:.1f}fps, {total_frames}帧, 采样间隔:{frame_interval}")

    frames = []
    with mp_vision.PoseLandmarker.create_from_options(options) as landmarker:
        frame_count = processed_count = 0
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            if frame_count % frame_interval != 0:
                frame_count += 1
                continue
            timestamp_ms = int((frame_count / fps) * 1000)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            result = landmarker.detect_for_video(mp_image, timestamp_ms)
            frame_data = {"frame": processed_count, "time": processed_count / target_fps, "landmarks": []}
            world_landmarks = result.pose_world_landmarks[0] if getattr(result, "pose_world_landmarks", None) else None
            if result.pose_landmarks:
                for i, lm in enumerate(result.pose_landmarks[0]):
                    wlm = world_landmarks[i] if world_landmarks and i < len(world_landmarks) else None
                    frame_data["landmarks"].append({
                        "id": i,
                        "name": POSE_LANDMARK_NAMES[i] if i < len(POSE_LANDMARK_NAMES) else str(i),
                        "x": lm.x, "y": lm.y, "z": lm.z, "visibility": lm.visibility,
                        "wx": wlm.x if wlm else None,
                        "wy": wlm.y if wlm else None,
                        "wz": wlm.z if wlm else None,
                    })
            frames.append(frame_data)
            processed_count += 1
            frame_count += 1
            if processed_count % progress_every == 0:
                print(f"处理进度: {frame_count/total_frames*100:.1f}% ({processed_count}帧)")
        cap.release()
    print(f"提取完成: {len(frames)}帧")
    return frames


def calculate_canonical_motion(frames):
    """
    从 MediaPipe 关键点生成 Canonical Motion (v5.0)

    新格式包含两种数据：
    - joints: 关节点 3D 坐标（核心，用于 IK/深度修正/重投影）
    - bones: 骨骼方向（兼容旧版，用于旧前端）
    """
    canonical_frames = []

    for frame in frames:
        landmarks = frame.get("landmarks", [])
        if not landmarks:
            continue

        has_world = any(lm.get("wx") is not None for lm in landmarks)

        # === v5.0: 构建关节点坐标 ===
        joints = build_joints_from_landmarks(landmarks, use_world=has_world)

        # === v4.0 兼容：计算骨骼方向 ===
        body_basis = solve_body_basis(landmarks, use_world=has_world)
        root_transform = solve_root_transform(body_basis) if body_basis else None
        bones = {}
        lm_by_id = {lm["id"]: lm for lm in landmarks}

        def get_xyz(lm):
            if lm.get("wx") is not None and lm.get("wy") is not None and lm.get("wz") is not None:
                # MediaPipe world: Y-up, +Z away; Three.js: Y-up, +Z towards
                return (lm["wx"], lm["wy"], -lm["wz"])
            return (lm["x"], 1.0 - lm["y"], lm.get("z", 0) * 0.3)

        def get_dir(from_idx, to_idx):
            f = lm_by_id.get(from_idx)
            t = lm_by_id.get(to_idx)
            if not f or not t:
                return None
            fx, fy, fz = get_xyz(f)
            tx, ty, tz = get_xyz(t)
            dx, dy, dz = tx - fx, ty - fy, tz - fz
            length = math.sqrt(dx*dx + dy*dy + dz*dz)
            if length < 1e-6:
                return None
            return (dx / length, dy / length, dz / length)

        # 注意：不计算 hand/foot 的 dir，因为 MediaPipe 的 wrist→index_finger / ankle→foot_index
        # 与 Mixamo rest pose 的 wrist→finger_base / ankle→toe_base 端点不匹配，
        # setFromUnitVectors 会把指根/趾根强行转向指尖/脚尖，导致手/脚严重扭曲。
        # hand/foot 跟随前臂/小腿链自然摆动即可（identity 局部旋转）。
        mappings = [
            ("leftUpperArm", 11, 13), ("leftLowerArm", 13, 15),
            ("rightUpperArm", 12, 14), ("rightLowerArm", 14, 16),
            ("leftUpperLeg", 23, 25), ("leftLowerLeg", 25, 27),
            ("rightUpperLeg", 24, 26), ("rightLowerLeg", 26, 28),
            ("head", 0, 5),
        ]
        for name, from_idx, to_idx in mappings:
            d = get_dir(from_idx, to_idx)
            if d:
                bones[name] = {"dir": {"x": d[0], "y": d[1], "z": d[2]}}

        if body_basis:
            hc = body_basis["hips_center"]
            bones["hips"] = {
                "position": {"x": hc[0], "y": hc[1], "z": hc[2]},
                "dir": {"x": body_basis["up"][0], "y": body_basis["up"][1], "z": body_basis["up"][2]},
            }
            if root_transform:
                bones["hips"]["rotation"] = root_transform["rotation"]
            bones["spine"] = {"dir": {"x": body_basis["up"][0], "y": body_basis["up"][1], "z": body_basis["up"][2]}}
            nose_lm = lm_by_id.get(0)
            if nose_lm:
                nx, ny, nz = get_xyz(nose_lm)
                sc = body_basis["shoulder_center"]
                dx, dy, dz = nx - sc[0], ny - sc[1], nz - sc[2]
                length = math.sqrt(dx*dx + dy*dy + dz*dz)
                if length > 1e-6:
                    bones["neck"] = {"dir": {"x": dx/length, "y": dy/length, "z": dz/length}}

        canonical_frames.append({
            "time": frame["time"],
            "joints": joints if joints else {},  # v5.0 关节点坐标
            "bones": bones,  # v4.0 兼容
        })

    # 平滑处理（对 joints 和 bones 都做）
    if canonical_frames:
        # 计算角速度判断动作类型
        total_angular_velocity = 0.0
        velocity_count = 0
        for i in range(1, len(canonical_frames)):
            for bone_name in CanonicalSkeleton.bone_landmarks.keys():
                prev_bd = canonical_frames[i-1]["bones"].get(bone_name)
                curr_bd = canonical_frames[i]["bones"].get(bone_name)
                if prev_bd and curr_bd and "dir" in prev_bd and "dir" in curr_bd:
                    dt = canonical_frames[i]["time"] - canonical_frames[i-1]["time"]
                    if dt > 0:
                        dx = curr_bd["dir"]["x"] - prev_bd["dir"]["x"]
                        dy = curr_bd["dir"]["y"] - prev_bd["dir"]["y"]
                        dz = curr_bd["dir"]["z"] - prev_bd["dir"]["z"]
                        angular_vel = math.sqrt(dx*dx + dy*dy + dz*dz) / dt
                        total_angular_velocity += angular_vel
                        velocity_count += 1

        avg_velocity = total_angular_velocity / max(1, velocity_count)

        if avg_velocity > 5.0:
            min_cutoff, beta = 3.0, 0.005
        elif avg_velocity > 2.0:
            min_cutoff, beta = 1.5, 0.01
        else:
            min_cutoff, beta = 0.8, 0.03

        print(f"动作类型分析: 平均角速度={avg_velocity:.2f}, 使用滤波参数: min_cutoff={min_cutoff}, beta={beta}")

        # 平滑 bones
        for bone_name in CanonicalSkeleton.bone_landmarks.keys():
            sequence = []
            for cf in canonical_frames:
                bd = cf["bones"].get(bone_name)
                if bd and "dir" in bd:
                    sequence.append({"time": cf["time"], "dir": bd["dir"]})
            if len(sequence) > 2:
                smoothed = smooth_bone_sequence(sequence, freq=30.0, min_cutoff=min_cutoff, beta=beta)
                sm_dict = {s["time"]: s["dir"] for s in smoothed}
                for cf in canonical_frames:
                    if bone_name in cf["bones"] and cf["time"] in sm_dict:
                        cf["bones"][bone_name]["dir"] = sm_dict[cf["time"]]

    # ═══════════════════════════════════════════════════════════════
    # v5.0: 对 joints 做平滑、尺度归一化、骨长约束、地面约束
    # ═══════════════════════════════════════════════════════════════
    if canonical_frames:
        # 1. joints 平滑（One Euro Filter 分别对 x/y/z）
        all_joint_names = set()
        for cf in canonical_frames:
            all_joint_names.update(cf.get("joints", {}).keys())

        for joint_name in all_joint_names:
            fx = OneEuroFilter(freq=30.0, min_cutoff=1.0, beta=0.05)
            fy = OneEuroFilter(freq=30.0, min_cutoff=1.0, beta=0.05)
            fz = OneEuroFilter(freq=30.0, min_cutoff=1.0, beta=0.05)
            for cf in canonical_frames:
                j = cf.get("joints", {}).get(joint_name)
                if j:
                    j["x"] = fx.filter(j.get("x", 0), cf["time"])
                    j["y"] = fy.filter(j.get("y", 0), cf["time"])
                    j["z"] = fz.filter(j.get("z", 0), cf["time"])

        # 2. 归一化尺度（以髋宽为基准，让不同身高的人尺度一致）
        joint_frames = [cf.get("joints", {}) for cf in canonical_frames]
        normalized = normalize_scale_by_hip_width(joint_frames, target_hip_width=0.25)
        for i, cf in enumerate(canonical_frames):
            cf["joints"] = normalized[i]

        # 3. 计算参考骨长：优先用标准人体比例，缺失的从数据平均补充
        # 这样避免"用带Z误差的数据平均"导致的系统性偏差
        hip_width = 0.25  # normalize_scale_by_hip_width 的目标髋宽
        ref_lengths = {bone: ratio * hip_width for bone, ratio in STANDARD_BONE_LENGTH_RATIOS.items()}
        # 缺失的骨骼从数据平均补充
        data_lengths = {}
        bone_counts = {}
        for joints in normalized:
            lengths = calculate_bone_lengths_from_joints(joints, STANDARD_BONE_CONNECTIONS)
            for bone, length in lengths.items():
                if bone not in ref_lengths:
                    data_lengths[bone] = data_lengths.get(bone, 0) + length
                    bone_counts[bone] = bone_counts.get(bone, 0) + 1
        for bone in data_lengths:
            if bone_counts[bone] > 0:
                ref_lengths[bone] = data_lengths[bone] / bone_counts[bone]

        # 4. 骨长约束（根据参考骨长推测/修正 Z 深度）
        for i, cf in enumerate(canonical_frames):
            cf["joints"] = estimate_depth_from_bone_lengths(
                cf["joints"], STANDARD_BONE_CONNECTIONS, ref_lengths
            )

        # 5. 地面约束（脚不穿透地面）
        joint_frames = [cf.get("joints", {}) for cf in canonical_frames]
        grounded = apply_ground_constraint(joint_frames, ground_y=0.0)
        for i, cf in enumerate(canonical_frames):
            cf["joints"] = grounded[i]

        # 6. 全局相对化：以第一帧 hips 为基准，所有关节点记录相对偏移
        # 这样 hips 在 (0,0,0)，其他关节点是相对于 hips 的局部坐标
        # 前端可以直接用 joints 重建骨骼方向，hips.position = 相对位移
        if canonical_frames:
            base_hips = canonical_frames[0]["joints"].get("hips", {})
            base_x = base_hips.get("x", 0)
            base_y = base_hips.get("y", 0)
            base_z = base_hips.get("z", 0)
            for cf in canonical_frames:
                for joint_name, joint in cf["joints"].items():
                    joint["x"] = joint.get("x", 0) - base_x
                    joint["y"] = joint.get("y", 0) - base_y
                    joint["z"] = joint.get("z", 0) - base_z

        print(f"[v5.0] joints 处理完成: 平滑 {len(all_joint_names)} 个关节点, "
              f"参考骨长 {len(ref_lengths)} 根, 归一化尺度完成")

    return canonical_frames


def generate_output(raw_frames, canonical_frames, output_path, fps=30.0):
    if not canonical_frames:
        print("警告: 未提取到有效的骨骼数据")
        return False
    raw_data = {"version": "1.0", "type": "raw_landmarks", "fps": fps, "frames": raw_frames}
    raw_path = output_path.with_suffix('.raw.json')
    with open(raw_path, 'w', encoding='utf-8') as f:
        json.dump(raw_data, f, ensure_ascii=False, indent=2)
    print(f"  - {raw_path} (原始关键点)")

    # v5.0: 包含 joints 和 bones
    canonical_data = {
        "version": "5.0", "type": "canonical_motion",
        "fps": fps, "duration": len(canonical_frames) / fps,
        "frameCount": len(canonical_frames), "frames": canonical_frames,
        # 额外元数据
        "jointNames": JOINT_NAMES,
        "hasJoints": True,
        "hasBones": True,
    }
    canonical_path = output_path.with_suffix('.canonical.json')
    with open(canonical_path, 'w', encoding='utf-8') as f:
        json.dump(canonical_data, f, ensure_ascii=False, indent=2)
    print(f"  - {canonical_path} (标准动作 v5.0)")

    quality = analyze_motion_quality(raw_frames)
    meta_data = {
        "version": "5.0", "type": "motion_meta",
        "fps": fps, "duration": len(canonical_frames) / fps,
        "frameCount": len(canonical_frames), "quality": quality,
        "jointNames": JOINT_NAMES,
    }
    meta_path = output_path.with_suffix('.meta.json')
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(meta_data, f, ensure_ascii=False, indent=2)
    print(f"  - {meta_path} (质量报告: {quality['score']}/100)")

    header = struct.pack('<4sII', b'glTF', 2, 12)
    with open(output_path, 'wb') as f:
        f.write(header)
    print(f"  - {output_path} (占位 GLB)")
    return True


def save_preview_frames(video_path, action_id, n_frames=4):
    preview_dir = Path(__file__).parent.parent / "cache" / "action_previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return []
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total <= 0:
        cap.release()
        return []
    saved = []
    margin = max(1, int(total * 0.05))
    indices = [margin + int((total - 2 * margin) * i / (n_frames - 1)) for i in range(n_frames)] if n_frames > 1 else [total // 2]
    for i, idx in enumerate(indices):
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = cap.read()
        if not ret:
            continue
        out_path = preview_dir / f"{action_id}_frame{i:02d}.png"
        cv2.imwrite(str(out_path), frame)
        saved.append(out_path)
    cap.release()
    print(f"  - 保存 {len(saved)} 帧预览图")
    return saved


def main():
    parser = argparse.ArgumentParser(description='从视频提取动作（MediaPipe）')
    parser.add_argument('video', help='输入视频路径')
    parser.add_argument('output', help='输出GLB路径')
    parser.add_argument('--fps', type=float, default=30.0, help='目标帧率')
    parser.add_argument('--skeleton-type', default='humanoid', help='骨骼类型（兼容性参数，暂不使用）')
    args = parser.parse_args()
    video_path = Path(args.video)
    output_path = Path(args.output)
    if not video_path.exists():
        print(f"错误: 视频文件不存在: {video_path}")
        sys.exit(1)
    print(f"开始处理: {video_path}")
    print(f"目标帧率: {args.fps}fps")
    try:
        print("\n[1/3] 提取骨骼关键点...")
        raw_frames = extract_pose_from_video(video_path, target_fps=args.fps)
        if not raw_frames:
            print("错误: 未能从视频提取任何姿势数据")
            sys.exit(1)
        print("\n[2/3] 生成标准动作...")
        canonical_frames = calculate_canonical_motion(raw_frames)
        print("\n[3/3] 输出文件...")
        success = generate_output(raw_frames, canonical_frames, output_path, fps=args.fps)
        if success:
            print(f"\n[OK] 完成: {output_path}")
            action_id = output_path.stem
            preview_paths = save_preview_frames(video_path, action_id, n_frames=4)
            meta = {
                "ok": True,
                "glb_path": str(output_path),
                "json_path": str(output_path.with_suffix('.canonical.json')),
                "canonical_path": str(output_path.with_suffix('.canonical.json')),
                "raw_path": str(output_path.with_suffix('.raw.json')),
                "meta_path": str(output_path.with_suffix('.meta.json')),
                "video_path": str(output_path.with_suffix('.mp4')),
                "duration": len(canonical_frames) / args.fps,
                "frames": len(canonical_frames),
                "fps": args.fps,
                "action_id": action_id,
                "preview_frames": [str(p) for p in preview_paths]
            }
            print(json.dumps(meta, ensure_ascii=False))
        else:
            print("\n[FAIL] 生成失败")
            sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
