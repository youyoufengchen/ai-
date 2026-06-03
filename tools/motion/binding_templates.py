"""
角色绑定模板系统 (Character Binding Templates)

定义“标准骨架 → 角色骨架”的映射关系，支持：
- 自动匹配（按命名规则）
- 手动修正
- 模板保存/复用
- 绑定到不同模型（X Bot, VRM, 自定义GLB）

核心数据结构：
    BindingTemplate = {
        "template_name": "Mixamo_X_Bot",
        "description": "Mixamo X Bot 默认人形骨骼",
        "canonical_to_model": {
            "hips": "mixamorigHips",
            "spine": "mixamorigSpine",
            "chest": "mixamorigSpine1",
            "neck": "mixamorigNeck",
            "head": "mixamorigHead",
            "leftShoulder": "mixamorigLeftShoulder",
            "leftUpperArm": "mixamorigLeftArm",
            "leftLowerArm": "mixamorigLeftForeArm",
            "leftHand": "mixamorigLeftHand",
            "rightShoulder": "mixamorigRightShoulder",
            "rightUpperArm": "mixamorigRightArm",
            "rightLowerArm": "mixamorigRightForeArm",
            "rightHand": "mixamorigRightHand",
            "leftUpperLeg": "mixamorigLeftUpLeg",
            "leftLowerLeg": "mixamorigLeftLeg",
            "leftFoot": "mixamorigLeftFoot",
            "leftToe": "mixamorigLeftToeBase",
            "rightUpperLeg": "mixamorigRightUpLeg",
            "rightLowerLeg": "mixamorigRightLeg",
            "rightFoot": "mixamorigRightFoot",
            "rightToe": "mixamorigRightToeBase",
        },
        # 骨骼轴向修正（如果模型骨骼轴向与标准不同）
        "axis_corrections": {
            "hips": {"rotateX": 0, "rotateY": 0, "rotateZ": 0},
        },
        # Rest Pose 类型
        "rest_pose_type": "T-pose",  # T-pose / A-pose
        "scale_factor": 1.0,
    }
"""

import json
import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# 内置绑定模板
BUILTIN_TEMPLATES = {
    "mixamo_x_bot": {
        "template_name": "Mixamo X Bot (mixamorig)",
        "description": "Mixamo X Bot 默认命名（无分隔符，如 mixamorigHips）",
        "canonical_to_model": {
            "hips":          "mixamorigHips",
            "spine":         "mixamorigSpine",
            "chest":         "mixamorigSpine1",
            "neck":          "mixamorigNeck",
            "head":          "mixamorigHead",
            "leftShoulder":  "mixamorigLeftShoulder",
            "leftUpperArm":  "mixamorigLeftArm",
            "leftLowerArm":  "mixamorigLeftForeArm",
            "leftHand":      "mixamorigLeftHand",
            "rightShoulder": "mixamorigRightShoulder",
            "rightUpperArm": "mixamorigRightArm",
            "rightLowerArm": "mixamorigRightForeArm",
            "rightHand":     "mixamorigRightHand",
            "leftUpperLeg":  "mixamorigLeftUpLeg",
            "leftLowerLeg":  "mixamorigLeftLeg",
            "leftFoot":      "mixamorigLeftFoot",
            "leftToe":       "mixamorigLeftToeBase",
            "rightUpperLeg": "mixamorigRightUpLeg",
            "rightLowerLeg": "mixamorigRightLeg",
            "rightFoot":     "mixamorigRightFoot",
            "rightToe":      "mixamorigRightToeBase",
        },
        "rest_pose_type": "T-pose",
        "axis_corrections": {},
        "scale_factor": 1.0,
    },
    "mixamo_colon": {
        "template_name": "Mixamo (mixamorig:XXX)",
        "description": "Mixamo 带冒号命名（如 mixamorig:Hips）",
        "canonical_to_model": {
            "hips":          "mixamorig:Hips",
            "spine":         "mixamorig:Spine",
            "chest":         "mixamorig:Spine1",
            "neck":          "mixamorig:Neck",
            "head":          "mixamorig:Head",
            "leftShoulder":  "mixamorig:LeftShoulder",
            "leftUpperArm":  "mixamorig:LeftArm",
            "leftLowerArm":  "mixamorig:LeftForeArm",
            "leftHand":      "mixamorig:LeftHand",
            "rightShoulder": "mixamorig:RightShoulder",
            "rightUpperArm": "mixamorig:RightArm",
            "rightLowerArm": "mixamorig:RightForeArm",
            "rightHand":     "mixamorig:RightHand",
            "leftUpperLeg":  "mixamorig:LeftUpLeg",
            "leftLowerLeg":  "mixamorig:LeftLeg",
            "leftFoot":      "mixamorig:LeftFoot",
            "leftToe":       "mixamorig:LeftToeBase",
            "rightUpperLeg": "mixamorig:RightUpLeg",
            "rightLowerLeg": "mixamorig:RightLeg",
            "rightFoot":     "mixamorig:RightFoot",
            "rightToe":      "mixamorig:RightToeBase",
        },
        "rest_pose_type": "T-pose",
        "axis_corrections": {},
        "scale_factor": 1.0,
    },
    "vrm_humanoid": {
        "template_name": "VRM Standard Humanoid",
        "description": "VRM 0.x / 1.0 标准人形骨骼",
        "canonical_to_model": {
            "hips":          " hips",
            "spine":         " spine",
            "chest":         " chest",
            "neck":          " neck",
            "head":          " head",
            "leftShoulder":  " leftShoulder",
            "leftUpperArm":  " leftUpperArm",
            "leftLowerArm":  " leftLowerArm",
            "leftHand":      " leftHand",
            "rightShoulder": " rightShoulder",
            "rightUpperArm": " rightUpperArm",
            "rightLowerArm": " rightLowerArm",
            "rightHand":     " rightHand",
            "leftUpperLeg":  " leftUpperLeg",
            "leftLowerLeg":  " leftLowerLeg",
            "leftFoot":      " leftFoot",
            "leftToe":       " leftToes",
            "rightUpperLeg": " rightUpperLeg",
            "rightLowerLeg": " rightLowerLeg",
            "rightFoot":     " rightFoot",
            "rightToe":      " rightToes",
        },
        "rest_pose_type": "T-pose",
        "axis_corrections": {},
        "scale_factor": 1.0,
    },
    "simple_humanoid": {
        "template_name": "Simple Humanoid",
        "description": "通用简化人形骨骼（无 twist bone）",
        "canonical_to_model": {
            "hips":          "Hips",
            "spine":         "Spine",
            "chest":         "Chest",
            "neck":          "Neck",
            "head":          "Head",
            "leftShoulder":  "LeftShoulder",
            "leftUpperArm":  "LeftArm",
            "leftLowerArm":  "LeftForeArm",
            "leftHand":      "LeftHand",
            "rightShoulder": "RightShoulder",
            "rightUpperArm": "RightArm",
            "rightLowerArm": "RightForeArm",
            "rightHand":     "RightHand",
            "leftUpperLeg":  "LeftUpLeg",
            "leftLowerLeg":  "LeftLeg",
            "leftFoot":      "LeftFoot",
            "leftToe":       "LeftToeBase",
            "rightUpperLeg": "RightUpLeg",
            "rightLowerLeg": "RightLeg",
            "rightFoot":     "RightFoot",
            "rightToe":      "RightToeBase",
        },
        "rest_pose_type": "T-pose",
        "axis_corrections": {},
        "scale_factor": 1.0,
    },
}


class BindingTemplateManager:
    """绑定模板管理器：自动匹配、手动修正、保存加载"""

    def __init__(self, templates_dir: Optional[Path] = None):
        self.templates = dict(BUILTIN_TEMPLATES)
        self.templates_dir = templates_dir or (Path(__file__).parent.parent.parent / "config" / "binding_templates")
        self._load_custom_templates()

    def _load_custom_templates(self):
        if not self.templates_dir.exists():
            return
        for f in self.templates_dir.glob("*.json"):
            try:
                with open(f, 'r', encoding='utf-8') as fh:
                    tmpl = json.load(fh)
                    key = f.stem
                    self.templates[key] = tmpl
            except Exception as e:
                print(f"[BindingTemplate] 加载模板失败 {f}: {e}")

    def list_templates(self) -> List[Dict]:
        """列出所有可用模板"""
        return [
            {"key": k, "name": v["template_name"], "description": v.get("description", "")}
            for k, v in self.templates.items()
        ]

    def get_template(self, key: str) -> Optional[Dict]:
        return self.templates.get(key)

    def auto_detect_template(self, model_bone_names: List[str]) -> Optional[str]:
        """
        根据角色骨骼名自动检测最匹配的模板
        返回模板 key
        """
        model_set = set(model_bone_names)
        best_key = None
        best_score = 0

        for key, tmpl in self.templates.items():
            mapping = tmpl.get("canonical_to_model", {})
            matched = sum(1 for c_name, m_name in mapping.items() if m_name in model_set)
            score = matched / len(mapping) if mapping else 0
            if score > best_score:
                best_score = score
                best_key = key

        return best_key

    def create_binding_from_template(
        self,
        template_key: str,
        model_bone_names: List[str],
        allow_fuzzy_match: bool = True,
    ) -> Dict[str, str]:
        """
        从模板创建绑定映射，对未匹配的尝试模糊匹配
        返回: {canonical_name: model_bone_name}
        """
        tmpl = self.templates.get(template_key)
        if not tmpl:
            return {}

        mapping = dict(tmpl.get("canonical_to_model", {}))
        model_set = set(model_bone_names)

        # 精确匹配确认
        result = {}
        for c_name, m_name in mapping.items():
            if m_name in model_set:
                result[c_name] = m_name

        if not allow_fuzzy_match:
            return result

        # 模糊匹配未绑定的
        unbound_canonical = [c for c in mapping.keys() if c not in result]
        used_model = set(result.values())

        for c_name in unbound_canonical:
            expected = mapping[c_name]
            # 尝试常见变体
            candidates = [
                expected,
                expected.replace(":", "_"),
                expected.replace("_", ":"),
                expected.replace("mixamorig", "").lstrip("_:"),
                expected.replace("mixamorig_", ""),
                expected.replace("mixamorig:", ""),
                expected.lower(),
                expected.replace("mixamorig", "").lstrip("_:").lower(),
            ]
            for cand in candidates:
                if cand in model_set and cand not in used_model:
                    result[c_name] = cand
                    used_model.add(cand)
                    break

        # 仍没匹配的：按名字包含关系
        for c_name in unbound_canonical:
            if c_name in result:
                continue
            c_lower = c_name.lower()
            for m_name in model_set:
                if m_name in used_model:
                    continue
                m_lower = m_name.lower().replace("_", "").replace(":", "")
                if c_lower in m_lower or m_lower in c_lower:
                    result[c_name] = m_name
                    used_model.add(m_name)
                    break

        return result

    def save_custom_template(self, key: str, template: Dict):
        """保存自定义模板"""
        self.templates[key] = template
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        path = self.templates_dir / f"{key}.json"
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(template, f, ensure_ascii=False, indent=2)
        print(f"[BindingTemplate] 已保存模板: {path}")


def get_model_rest_pose_bone_dirs(
    model_bone_names: List[str],
    bone_hierarchy: Dict[str, Dict],
) -> Dict[str, Dict[str, float]]:
    """
    从角色骨骼层级计算 Rest Pose 中每根骨骼的方向

    bone_hierarchy: {
        bone_name: {"parent": parent_name, "children": [child_names], "position": [x,y,z]},
        ...
    }

    返回: {bone_name: {"x": dir_x, "y": dir_y, "z": dir_z}}
    """
    rest_dirs = {}
    for bone_name in model_bone_names:
        info = bone_hierarchy.get(bone_name)
        if not info:
            continue
        children = info.get("children", [])
        if not children:
            continue
        # 取第一个子骨骼的方向（对于hips，选y差最大的）
        parent_pos = info.get("position", [0, 0, 0])
        best_child = children[0]
        best_dy = -float('inf')
        for child in children:
            child_info = bone_hierarchy.get(child)
            if not child_info:
                continue
            child_pos = child_info.get("position", [0, 0, 0])
            dy = child_pos[1] - parent_pos[1]
            if dy > best_dy:
                best_dy = dy
                best_child = child

        child_info = bone_hierarchy.get(best_child)
        if child_info:
            child_pos = child_info.get("position", [0, 0, 0])
            dx = child_pos[0] - parent_pos[0]
            dy = child_pos[1] - parent_pos[1]
            dz = child_pos[2] - parent_pos[2]
            length = math.sqrt(dx*dx + dy*dy + dz*dz)
            if length > 1e-6:
                rest_dirs[bone_name] = {
                    "x": dx / length,
                    "y": dy / length,
                    "z": dz / length,
                }
    return rest_dirs
