"""
BVH → Canonical Motion JSON 转换器

将 MoCapAnything 输出的 BVH 文件转换为系统内部使用的 canonical.json 格式。

用法：
    python tools/bvh_to_canonical.py <input.bvh> <output_dir>

输出：
    - output_dir/<name>.canonical.json
    - output_dir/<name>.meta.json
"""

import json
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.bvh_parser import BVHParser


# BVH 关节名 → 系统 Canonical 关节名 的映射
# MoCapAnything 输出的是标准人形 BVH，关节名通常是 mixamo/humanoid 风格
JOINT_NAME_MAP = {
    # 常见 BVH 名称 -> 系统 canonical 名称
    "Hips": "hips",
    "Spine": "spine",
    "Spine1": "spine",
    "Spine2": "chest",
    "Chest": "chest",
    "Neck": "neck",
    "Neck1": "neck",
    "Head": "head",
    "Head_end": None,
    
    # 左臂（BVH 中的 LeftShoulder 是锁骨/肩胛，前端不需要；LeftArm 是上臂根部）
    "LeftShoulder": None,
    "LeftArm": "leftShoulder",
    "LeftUpperArm": "leftShoulder",
    "LeftForeArm": "leftElbow",
    "LeftLowerArm": "leftElbow",
    "LeftHand": "leftHand",
    "LeftWrist": "leftWrist",
    "LeftHand_end": None,

    # 右臂
    "RightShoulder": None,
    "RightArm": "rightShoulder",
    "RightUpperArm": "rightShoulder",
    "RightForeArm": "rightElbow",
    "RightLowerArm": "rightElbow",
    "RightHand": "rightHand",
    "RightWrist": "rightWrist",
    "RightHand_end": None,
    
    # 左腿
    "LeftUpLeg": "leftHip",
    "LeftLeg": "leftKnee",
    "LeftLowerLeg": "leftKnee",
    "LeftFoot": "leftFoot",
    "LeftAnkle": "leftAnkle",
    "LeftFoot_end": None,
    "LeftToeBase": "leftFoot",
    "LeftToeBase_end": None,
    
    # 右腿
    "RightUpLeg": "rightHip",
    "RightLeg": "rightKnee",
    "RightLowerLeg": "rightKnee",
    "RightFoot": "rightFoot",
    "RightAnkle": "rightAnkle",
    "RightFoot_end": None,
    "RightToeBase": "rightFoot",
    "RightToeBase_end": None,
}


def bvh_to_canonical(bvh_path: Path, output_dir: Path) -> Path:
    """
    转换 BVH 到 canonical.json
    
    Returns:
        canonical.json 的输出路径
    """
    bvh = BVHParser.load(str(bvh_path))
    
    # 计算关节世界坐标
    positions_per_frame = bvh.compute_joint_positions()
    
    # 映射到 canonical 关节名
    canonical_frames = []
    # 诊断：记录第一帧中所有 BVH 原始关节名和映射结果
    first_frame_mapped = {}
    bvh_joint_names = set()
    for i, frame_pos in enumerate(positions_per_frame):
        joints = {}
        for bvh_name, pos in frame_pos.items():
            bvh_joint_names.add(bvh_name)
            canonical_name = JOINT_NAME_MAP.get(bvh_name)
            if canonical_name is None:
                continue
            if i == 0:
                first_frame_mapped[bvh_name] = canonical_name
            if canonical_name in joints:
                existing = joints[canonical_name]
                joints[canonical_name] = {
                    "x": (existing["x"] + pos[0]) / 2,
                    "y": (existing["y"] + pos[1]) / 2,
                    "z": (existing["z"] + pos[2]) / 2,
                    "confidence": 1.0,
                }
            else:
                joints[canonical_name] = {
                    "x": pos[0],
                    "y": pos[1],
                    "z": pos[2],
                    "confidence": 1.0,
                }
        if i == 0 and bvh_joint_names:
            print(f"[bvh2canonical] BVH joints ({len(bvh_joint_names)}): {sorted(bvh_joint_names)}")
            print(f"[bvh2canonical] Mapped: {first_frame_mapped}")
            print(f"[bvh2canonical] Output joints ({len(joints)}): {sorted(joints.keys())}")
        
        # 全局相对化：以第一帧 hips 为基准
        if i == 0 and "hips" in joints:
            base_x = joints["hips"]["x"]
            base_y = joints["hips"]["y"]
            base_z = joints["hips"]["z"]
        
        # 全局相对化：所有关节以第一帧 hips 为原点
        for j in joints.values():
            j["x"] -= base_x
            j["y"] -= base_y
            j["z"] -= base_z
        
        # 补全前端需要但 BVH 中不存在的关节别名（BVH 的手/脚关节实际就在手腕/脚踝位置）
        if "leftHand" in joints and "leftWrist" not in joints:
            joints["leftWrist"] = dict(joints["leftHand"])
        if "rightHand" in joints and "rightWrist" not in joints:
            joints["rightWrist"] = dict(joints["rightHand"])
        if "leftFoot" in joints and "leftAnkle" not in joints:
            joints["leftAnkle"] = dict(joints["leftFoot"])
        if "rightFoot" in joints and "rightAnkle" not in joints:
            joints["rightAnkle"] = dict(joints["rightFoot"])
        
        canonical_frames.append({
            "time": i / bvh.fps,
            "joints": joints,
        })
    
    # 输出
    output_dir.mkdir(parents=True, exist_ok=True)
    name = bvh_path.stem
    
    canonical_data = {
        "version": "5.1",
        "type": "canonical_motion",
        "source": "mocap_anything_bvh",
        "fps": bvh.fps,
        "duration": bvh.frame_count / bvh.fps,
        "frameCount": bvh.frame_count,
        "frames": canonical_frames,
        "jointNames": sorted({jn for jn in JOINT_NAME_MAP.values() if jn}),
        "hasJoints": True,
        "hasBones": False,
    }
    
    canonical_path = output_dir / f"{name}.canonical.json"
    with open(canonical_path, "w", encoding="utf-8") as f:
        json.dump(canonical_data, f, ensure_ascii=False, indent=2)
    
    meta_data = {
        "version": "5.1",
        "type": "motion_meta",
        "source": "mocap_anything_bvh",
        "fps": bvh.fps,
        "duration": bvh.frame_count / bvh.fps,
        "frameCount": bvh.frame_count,
        "jointNames": sorted({jn for jn in JOINT_NAME_MAP.values() if jn}),
        "bvh_joints": list(bvh.joints.keys()),
    }
    
    meta_path = output_dir / f"{name}.meta.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta_data, f, ensure_ascii=False, indent=2)
    
    print(f"[OK] Canonical JSON: {canonical_path}")
    print(f"[OK] Meta JSON: {meta_path}")
    
    return canonical_path


def main():
    import argparse
    parser = argparse.ArgumentParser(description="BVH → Canonical JSON 转换")
    parser.add_argument("bvh", help="输入 BVH 文件路径")
    parser.add_argument("output_dir", help="输出目录")
    args = parser.parse_args()
    
    bvh_path = Path(args.bvh)
    output_dir = Path(args.output_dir)
    
    if not bvh_path.exists():
        print(f"[ERROR] BVH 文件不存在: {bvh_path}")
        sys.exit(1)
    
    canonical_path = bvh_to_canonical(bvh_path, output_dir)
    print(f"\n转换完成: {canonical_path}")


if __name__ == "__main__":
    main()
