"""
动作质量分析

自动检测常见问题并给出评分和建议
"""
import math
from typing import Dict, List, Any


def analyze_motion_quality(frames: List[Dict]) -> Dict[str, Any]:
    """
    分析动作质量

    返回: {
        "score": float,  # 0-100
        "issues": [{"type": str, "message": str, "severity": str, "frames": [int]}],
        "stats": {...}
    }
    """
    if not frames:
        return {"score": 0, "issues": [{"type": "empty", "message": "没有帧数据", "severity": "error"}], "stats": {}}

    issues = []
    total_frames = len(frames)

    # 1. 关键点数量检查
    empty_count = 0
    for f in frames:
        lms = f.get("landmarks", [])
        if not lms:
            empty_count += 1

    if empty_count > 0:
        issues.append({
            "type": "missing_landmarks",
            "message": f"{empty_count}/{total_frames} 帧缺少关键点",
            "severity": "warning" if empty_count < total_frames * 0.5 else "error",
            "frames": [i for i, f in enumerate(frames) if not f.get("landmarks")],
        })

    # 2. 置信度分析
    low_conf_frames = []
    for i, f in enumerate(frames):
        for lm in f.get("landmarks", []):
            if lm.get("visibility", 1.0) < 0.5:
                low_conf_frames.append(i)
                break

    if low_conf_frames:
        issues.append({
            "type": "low_confidence",
            "message": f"{len(set(low_conf_frames))} 帧存在低置信度关键点",
            "severity": "warning",
            "frames": list(set(low_conf_frames)),
        })

    # 3. 脚高度稳定性
    foot_heights = []
    for f in frames:
        for lm in f.get("landmarks", []):
            if lm["id"] in (27, 28):  # ankles
                y = lm.get("wy") if lm.get("wy") is not None else (1.0 - lm["y"])
                foot_heights.append(y)

    if foot_heights:
        height_std = math.sqrt(sum((h - sum(foot_heights)/len(foot_heights))**2 for h in foot_heights) / len(foot_heights))
        if height_std > 0.15:
            issues.append({
                "type": "foot_floating",
                "message": f"脚高度不稳定 (std={height_std:.3f})",
                "severity": "warning",
            })

    # 4. 骨骼抖动 (方向向量变化率)
    bone_jitter = {}
    for i in range(1, len(frames)):
        prev_bones = frames[i-1].get("bones", {})
        curr_bones = frames[i].get("bones", {})
        for b_name in set(prev_bones.keys()) & set(curr_bones.keys()):
            d1 = prev_bones[b_name].get("dir", {})
            d2 = curr_bones[b_name].get("dir", {})
            if d1 and d2:
                dx = d1["x"] - d2["x"]
                dy = d1["y"] - d2["y"]
                dz = d1["z"] - d2["z"]
                diff = math.sqrt(dx*dx + dy*dy + dz*dz)
                bone_jitter[b_name] = bone_jitter.get(b_name, 0) + diff

    jittery_bones = [b for b, v in bone_jitter.items() if v > 5.0]
    if jittery_bones:
        issues.append({
            "type": "jitter",
            "message": f"骨骼抖动过大: {', '.join(jittery_bones)}",
            "severity": "warning",
        })

    # 5. 评分
    score = 100
    for issue in issues:
        sev = issue["severity"]
        if sev == "error":
            score -= 25
        elif sev == "warning":
            score -= 10

    score = max(0, min(100, score))

    return {
        "score": round(score, 1),
        "issues": issues,
        "stats": {
            "total_frames": total_frames,
            "empty_frames": empty_count,
            "low_conf_frames": len(set(low_conf_frames)),
        },
    }
