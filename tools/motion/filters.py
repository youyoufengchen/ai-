"""
滤波器：时间平滑、骨长约束、置信度插值
"""
import math
from typing import List, Dict, Any, Optional, Tuple


class OneEuroFilter:
    """
    One Euro Filter - 自适应平滑滤波器
    低延迟、少抖动，适合实时/离线动作平滑
    
    参考: https://cristal.univ-lille.fr/~casiez/1euro/
    """
    def __init__(self, freq=30.0, min_cutoff=1.0, beta=0.0, d_cutoff=1.0):
        self.freq = freq
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self.x_prev = None
        self.dx_prev = None
        self.t_prev = None

    def _alpha(self, cutoff):
        tau = 1.0 / (2.0 * math.pi * cutoff)
        te = 1.0 / self.freq
        return 1.0 / (1.0 + tau / te)

    def filter(self, x, t=None):
        """
        x: 当前值 (float or tuple)
        t: 当前时间 (秒)，None 时按 freq 步进
        """
        if self.x_prev is None:
            self.x_prev = x
            self.dx_prev = 0.0 if isinstance(x, (int, float)) else tuple(0.0 for _ in x)
            self.t_prev = t or 0.0
            return x

        dt = (t - self.t_prev) if t is not None else (1.0 / self.freq)
        self.freq = 1.0 / dt if dt > 0 else self.freq
        self.t_prev = t or (self.t_prev + dt)

        # 差值滤波 (导数)
        if isinstance(x, (int, float)):
            dx = (x - self.x_prev) * self.freq
            edx = self.dx_prev + self._alpha(self.d_cutoff) * (dx - self.dx_prev)
            cutoff = self.min_cutoff + self.beta * abs(edx)
            result = self.x_prev + self._alpha(cutoff) * (x - self.x_prev)
            self.dx_prev = edx
        else:
            # tuple/list 支持
            dx = tuple((a - b) * self.freq for a, b in zip(x, self.x_prev))
            edx = tuple(
                p + self._alpha(self.d_cutoff) * (d - p)
                for p, d in zip(self.dx_prev, dx)
            )
            cutoff = self.min_cutoff + self.beta * math.sqrt(sum(v * v for v in edx))
            result = tuple(
                p + self._alpha(cutoff) * (v - p)
                for p, v in zip(self.x_prev, x)
            )
            self.dx_prev = edx

        self.x_prev = result
        return result


def smooth_bone_sequence(
    bone_frames: List[Dict[str, Any]],
    freq=30.0,
    min_cutoff=1.0,
    beta=0.05,
) -> List[Dict[str, Any]]:
    """
    对骨骼方向序列做 One Euro 平滑
    
    bone_frames: [{time, dir: {x,y,z}}, ...]
    返回平滑后的序列
    """
    if not bone_frames:
        return bone_frames

    fx = OneEuroFilter(freq=freq, min_cutoff=min_cutoff, beta=beta)
    fy = OneEuroFilter(freq=freq, min_cutoff=min_cutoff, beta=beta)
    fz = OneEuroFilter(freq=freq, min_cutoff=min_cutoff, beta=beta)

    result = []
    for f in bone_frames:
        d = f.get("dir")
        if d is None:
            result.append(f)
            continue
        t = f.get("time", 0.0)
        sx = fx.filter(d["x"], t)
        sy = fy.filter(d["y"], t)
        sz = fz.filter(d["z"], t)
        # 归一化
        length = math.sqrt(sx * sx + sy * sy + sz * sz)
        if length > 1e-6:
            sx, sy, sz = sx / length, sy / length, sz / length
        result.append({
            **f,
            "dir": {"x": sx, "y": sy, "z": sz},
            "smoothed": True,
        })
    return result


def constrain_bone_lengths(
    frames: List[Dict[str, Any]],
    bone_map: Dict[str, Tuple[int, int]],
    target_lengths: Dict[str, float],
) -> List[Dict[str, Any]]:
    """
    约束骨长：根据目标长度调整关节点位置
    
    frames: 原始关键点帧 [{time, landmarks: [{id,x,y,z,wx,wy,wz,visibility}, ...]}, ...]
    bone_map: 骨骼名 -> (起点landmark_idx, 终点landmark_idx)
    target_lengths: 骨骼名 -> 目标长度
    """
    if not frames or not target_lengths:
        return frames

    result = []
    for frame in frames:
        lms = {lm["id"]: lm for lm in frame.get("landmarks", [])}
        modified = False

        for bone, (from_idx, to_idx) in bone_map.items():
            target_len = target_lengths.get(bone)
            if target_len is None:
                continue
            f_lm = lms.get(from_idx)
            t_lm = lms.get(to_idx)
            if not f_lm or not t_lm:
                continue

            # 优先使用 world landmarks
            def get_xyz(lm):
                if lm.get("wx") is not None and lm.get("wy") is not None and lm.get("wz") is not None:
                    return (lm["wx"], lm["wy"], lm["wz"])
                return (lm["x"], lm["y"], lm["z"])

            fx, fy, fz = get_xyz(f_lm)
            tx, ty, tz = get_xyz(t_lm)

            dx, dy, dz = tx - fx, ty - fy, tz - fz
            current_len = math.sqrt(dx * dx + dy * dy + dz * dz)
            if current_len < 1e-6:
                continue

            # 调整到目标长度
            scale = target_len / current_len
            nx, ny, nz = fx + dx * scale, fy + dy * scale, fz + dz * scale

            # 只修改终点，保持起点
            if t_lm.get("wx") is not None:
                t_lm["wx"] = nx
                t_lm["wy"] = ny
                t_lm["wz"] = nz
            else:
                t_lm["x"] = nx
                t_lm["y"] = ny
                t_lm["z"] = nz
            modified = True

        result.append(frame if not modified else {
            **frame,
            "landmarks": list(lms.values()),
        })

    return result
