"""
motion - 动作提取核心模块 (v5.0)

包含：
- canonical_skeleton: 标准人体骨骼定义
- joints_builder: 从 MediaPipe 构建标准关节点坐标
- binding_templates: 角色骨骼绑定模板
- calibration: 校准帧机制
- depth_reconstructor: Z轴深度重建
- pose_solver: 从关节点求解骨骼旋转 (IK+FK)
- reprojection: 重投影误差计算
- filters: 时间滤波 / 骨长约束
- body_solver: 身体朝向估计
- ik_solver: TwoBone IK
- retarget: 重定向到目标模型
- quality_analyzer: 动作质量评分
"""

from .canonical_skeleton import CanonicalSkeleton, canonical_names
from .joints_builder import (
    build_joints_from_landmarks,
    calculate_bone_lengths_from_joints,
    STANDARD_BONE_CONNECTIONS,
    JOINT_NAMES,
)
from .binding_templates import (
    BindingTemplateManager,
    BUILTIN_TEMPLATES,
    get_model_rest_pose_bone_dirs,
)
from .calibration import (
    calculate_joint_offsets,
    apply_calibration,
    compute_model_joints_from_rest_pose,
    auto_select_calibration_frame,
)
from .depth_reconstructor import (
    estimate_depth_from_bone_lengths,
    smooth_joint_z_sequence,
    apply_ground_constraint,
    normalize_scale_by_hip_width,
    apply_user_z_correction,
    STANDARD_BONE_LENGTH_RATIOS,
)
from .pose_solver import (
    solve_pose_from_joints,
    solve_spine_chain,
    solve_limb_ik,
    quat_from_vectors,
)
from .reprojection import (
    calculate_reprojection_error,
    calculate_overall_fitness,
    JOINT_TO_MP_ID,
)
from .filters import OneEuroFilter, smooth_bone_sequence, constrain_bone_lengths
from .body_solver import solve_body_basis, solve_root_transform
from .ik_solver import solve_two_bone_ik, solve_limb_ik
from .retarget import retarget_to_bones
from .quality_analyzer import analyze_motion_quality

__all__ = [
    # 标准骨架
    "CanonicalSkeleton", "canonical_names",
    # 关节点构建
    "build_joints_from_landmarks", "calculate_bone_lengths_from_joints",
    "STANDARD_BONE_CONNECTIONS", "JOINT_NAMES",
    # 绑定模板
    "BindingTemplateManager", "BUILTIN_TEMPLATES", "get_model_rest_pose_bone_dirs",
    # 校准
    "calculate_joint_offsets", "apply_calibration",
    "compute_model_joints_from_rest_pose", "auto_select_calibration_frame",
    # 深度重建
    "estimate_depth_from_bone_lengths", "smooth_joint_z_sequence",
    "apply_ground_constraint", "normalize_scale_by_hip_width",
    "apply_user_z_correction", "STANDARD_BONE_LENGTH_RATIOS",
    # 姿态求解
    "solve_pose_from_joints", "solve_spine_chain", "solve_limb_ik", "quat_from_vectors",
    # 重投影
    "calculate_reprojection_error", "calculate_overall_fitness", "JOINT_TO_MP_ID",
    # 旧模块（兼容）
    "OneEuroFilter", "smooth_bone_sequence", "constrain_bone_lengths",
    "solve_body_basis", "solve_root_transform",
    "solve_two_bone_ik", "solve_limb_ik",
    "retarget_to_bones",
    "analyze_motion_quality",
]
