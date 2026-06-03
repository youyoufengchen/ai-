"""
BVH 文件解析器

支持：
- HIERARCHY 段解析（骨骼层级、偏移量、通道定义）
- MOTION 段解析（帧数据，支持 POSITION + ROTATION 通道）
- 转换为关节点 3D 坐标（用于 canonical.json）
- 转换为局部旋转（四元数，用于 glTF 动画）

用法：
    from tools.bvh_parser import BVHParser
    bvh = BVHParser.load("path/to/file.bvh")
    
    # 获取关节世界坐标（每帧）
    frames = bvh.compute_joint_positions()
    
    # 获取局部旋转四元数（每帧）
    rotations = bvh.compute_local_rotations()
"""

import re
import math
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field


@dataclass
class Joint:
    """骨骼关节定义"""
    name: str
    parent: Optional["Joint"] = None
    children: List["Joint"] = field(default_factory=list)
    offset: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    channels: List[str] = field(default_factory=list)  # 如 ["Xposition","Yposition","Zposition","Zrotation","Xrotation","Yrotation"]
    is_end_site: bool = False


@dataclass
class BVHData:
    """解析后的 BVH 数据"""
    root: Joint
    joints: Dict[str, Joint]  # name -> Joint
    joint_order: List[str]    # 通道在帧数据中的顺序
    fps: float
    frame_count: int
    frames: List[List[float]]  # [frame][channel_value]
    
    def compute_joint_positions(self) -> List[Dict[str, Tuple[float, float, float]]]:
        """
        计算每帧每个关节的世界坐标（Y-up）
        
        Returns:
            [{
                "joint_name": (x, y, z),
                ...
            }, ...]
        """
        results = []
        
        for frame_data in self.frames:
            # 构建每关节的局部变换矩阵
            world_pos = {}
            channel_idx = 0
            
            def process_joint(joint: Joint, parent_transform=None):
                nonlocal channel_idx
                
                # 读取本关节的通道数据
                tx, ty, tz = 0.0, 0.0, 0.0
                rx, ry, rz = 0.0, 0.0, 0.0
                
                for ch in joint.channels:
                    val = frame_data[channel_idx]
                    channel_idx += 1
                    if ch == "Xposition":
                        tx = val
                    elif ch == "Yposition":
                        ty = val
                    elif ch == "Zposition":
                        tz = val
                    elif ch == "Xrotation":
                        rx = math.radians(val)
                    elif ch == "Yrotation":
                        ry = math.radians(val)
                    elif ch == "Zrotation":
                        rz = math.radians(val)
                
                # 本地偏移 + 旋转
                # BVH 使用 Tait-Bryan ZXY 或 ZYX 顺序（取决于通道顺序）
                # 这里简化：按 channels 中的顺序做欧拉角乘法
                local_pos = self._rotate_point((tx + joint.offset[0], 
                                                 ty + joint.offset[1], 
                                                 tz + joint.offset[2]),
                                               rx, ry, rz, joint.channels)
                
                if parent_transform is None:
                    world_pos[joint.name] = local_pos
                else:
                    world_pos[joint.name] = (
                        parent_transform[0] + local_pos[0],
                        parent_transform[1] + local_pos[1],
                        parent_transform[2] + local_pos[2],
                    )
                
                for child in joint.children:
                    process_joint(child, world_pos[joint.name])
            
            process_joint(self.root)
            results.append(world_pos)
        
        return results
    
    def _rotate_point(self, point, rx, ry, rz, channels):
        """按欧拉角旋转点（简化版 ZYX）"""
        x, y, z = point
        # 简化为 ZYX 顺序（BVH常见）
        # 先绕 Z
        if rz != 0:
            cos_z, sin_z = math.cos(rz), math.sin(rz)
            x, y = x * cos_z - y * sin_z, x * sin_z + y * cos_z
        # 再绕 Y
        if ry != 0:
            cos_y, sin_y = math.cos(ry), math.sin(ry)
            x, z = x * cos_y + z * sin_y, -x * sin_y + z * cos_y
        # 再绕 X
        if rx != 0:
            cos_x, sin_x = math.cos(rx), math.sin(rx)
            y, z = y * cos_x - z * sin_x, y * sin_x + z * cos_x
        return (x, y, z)
    
    def compute_local_rotations(self) -> List[Dict[str, Tuple[float, float, float, float]]]:
        """
        计算每帧每个关节的局部旋转（四元数 w,x,y,z）
        
        Returns:
            [{
                "joint_name": (w, x, y, z),
                ...
            }, ...]
        """
        results = []
        
        for frame_data in self.frames:
            local_rots = {}
            channel_idx = 0
            
            def process_joint(joint: Joint):
                nonlocal channel_idx
                
                rx, ry, rz = 0.0, 0.0, 0.0
                for ch in joint.channels:
                    val = frame_data[channel_idx]
                    channel_idx += 1
                    if ch == "Xrotation":
                        rx = math.radians(val)
                    elif ch == "Yrotation":
                        ry = math.radians(val)
                    elif ch == "Zrotation":
                        rz = math.radians(val)
                
                # 欧拉角 -> 四元数 (ZYX 顺序)
                q = euler_to_quaternion(rx, ry, rz, order="ZYX")
                local_rots[joint.name] = q
                
                for child in joint.children:
                    process_joint(child)
            
            process_joint(self.root)
            results.append(local_rots)
        
        return results


def euler_to_quaternion(rx, ry, rz, order="ZYX") -> Tuple[float, float, float, float]:
    """
    欧拉角（弧度）转四元数 (w, x, y, z)
    默认 ZYX 顺序（BVH 标准）
    """
    cx, sx = math.cos(rx / 2), math.sin(rx / 2)
    cy, sy = math.cos(ry / 2), math.sin(ry / 2)
    cz, sz = math.cos(rz / 2), math.sin(rz / 2)
    
    if order == "ZYX":
        w = cx * cy * cz + sx * sy * sz
        x = sx * cy * cz - cx * sy * sz
        y = cx * sy * cz + sx * cy * sz
        z = cx * cy * sz - sx * sy * cz
    elif order == "XYZ":
        w = cx * cy * cz - sx * sy * sz
        x = sx * cy * cz + cx * sy * sz
        y = cx * sy * cz - sx * cy * sz
        z = cx * cy * sz + sx * sy * cz
    else:
        # 默认 ZYX
        w = cx * cy * cz + sx * sy * sz
        x = sx * cy * cz - cx * sy * sz
        y = cx * sy * cz + sx * cy * sz
        z = cx * cy * sz - sx * sy * cz
    
    # 归一化
    norm = math.sqrt(w * w + x * x + y * y + z * z)
    if norm > 0:
        w, x, y, z = w / norm, x / norm, y / norm, z / norm
    return (w, x, y, z)


class BVHParser:
    """BVH 文件解析器"""
    
    @staticmethod
    def load(path: str) -> BVHData:
        """加载并解析 BVH 文件"""
        text = Path(path).read_text(encoding="utf-8", errors="ignore")
        return BVHParser.parse(text)
    
    @staticmethod
    def parse(text: str) -> BVHData:
        """从文本解析 BVH"""
        lines = text.strip().splitlines()
        idx = 0
        
        # 解析 HIERARCHY
        root = BVHParser._parse_hierarchy(lines)
        
        # 收集所有关节
        joints = {}
        joint_order = []
        
        def collect_joints(j):
            joints[j.name] = j
            joint_order.append(j.name)
            for c in j.children:
                collect_joints(c)
        
        collect_joints(root)
        
        # 找到 MOTION 段
        motion_idx = None
        for i, line in enumerate(lines):
            if line.strip().upper().startswith("MOTION"):
                motion_idx = i
                break
        
        if motion_idx is None:
            raise ValueError("BVH 文件缺少 MOTION 段")
        
        # 解析帧数
        frame_count = 0
        fps = 30.0
        
        for i in range(motion_idx + 1, len(lines)):
            line = lines[i].strip()
            if line.upper().startswith("FRAMES:"):
                frame_count = int(line.split(":")[1].strip())
            elif line.upper().startswith("FRAME TIME:"):
                fps = 1.0 / float(line.split(":")[1].strip())
            elif frame_count > 0 and line:
                break
        
        # 解析帧数据
        frames = []
        data_started = False
        for i in range(motion_idx + 1, len(lines)):
            line = lines[i].strip()
            if not line:
                continue
            if line.upper().startswith("FRAMES:") or line.upper().startswith("FRAME TIME:"):
                continue
            
            values = [float(v) for v in line.split()]
            if values:
                frames.append(values)
        
        if len(frames) != frame_count:
            frame_count = len(frames)
        
        return BVHData(
            root=root,
            joints=joints,
            joint_order=joint_order,
            fps=fps,
            frame_count=frame_count,
            frames=frames,
        )
    
    @staticmethod
    def _parse_hierarchy(lines: List[str]) -> Joint:
        """解析 HIERARCHY 段"""
        idx = 0
        
        # 跳过到 ROOT
        while idx < len(lines) and not lines[idx].strip().upper().startswith("ROOT"):
            idx += 1
        
        if idx >= len(lines):
            raise ValueError("BVH 文件缺少 ROOT 定义")
        
        root, idx = BVHParser._parse_joint(lines, idx, None)
        return root
    
    @staticmethod
    def _parse_joint(lines: List[str], idx: int, parent: Optional[Joint]) -> Tuple[Joint, int]:
        """递归解析单个关节，返回 (joint, next_idx)"""
        line = lines[idx].strip()
        
        # ROOT 或 JOINT
        if line.upper().startswith("ROOT"):
            name = line.split(None, 1)[1].strip()
            joint_type = "ROOT"
        elif line.upper().startswith("JOINT"):
            name = line.split(None, 1)[1].strip()
            joint_type = "JOINT"
        elif line.upper().startswith("END"):
            # End Site
            name = f"{parent.name}_end" if parent else "end"
            joint_type = "END"
        else:
            raise ValueError(f"未知的关节类型: {line}")
        
        joint = Joint(name=name, parent=parent, is_end_site=(joint_type == "END"))
        
        if parent:
            parent.children.append(joint)
        
        idx += 1  # 跳过 ROOT/JOINT/End Site 行
        
        # 期望 {
        while idx < len(lines) and lines[idx].strip() != "{":
            idx += 1
        idx += 1  # 跳过 {
        
        # OFFSET
        while idx < len(lines):
            line = lines[idx].strip().upper()
            if line.startswith("OFFSET"):
                vals = lines[idx].strip().split()[1:]
                joint.offset = tuple(float(v) for v in vals[:3])
                idx += 1
            elif line.startswith("CHANNELS"):
                parts = lines[idx].strip().split()
                count = int(parts[1])
                joint.channels = parts[2:2 + count]
                idx += 1
            elif line.startswith("JOINT") or line.startswith("END") or line.startswith("ROOT"):
                # 子关节
                child, idx = BVHParser._parse_joint(lines, idx, joint)
            elif lines[idx].strip() == "}":
                idx += 1
                break
            else:
                idx += 1
        
        return joint, idx


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python bvh_parser.py <bvh_file>")
        sys.exit(1)
    
    bvh = BVHParser.load(sys.argv[1])
    print(f"关节数: {len(bvh.joints)}")
    print(f"帧数: {bvh.frame_count}, FPS: {bvh.fps:.2f}")
    print(f"关节列表: {list(bvh.joints.keys())}")
    
    # 测试坐标计算
    positions = bvh.compute_joint_positions()
    if positions:
        first_frame = positions[0]
        print(f"\n第一帧关节坐标:")
        for name, pos in list(first_frame.items())[:5]:
            print(f"  {name}: ({pos[0]:.3f}, {pos[1]:.3f}, {pos[2]:.3f})")
