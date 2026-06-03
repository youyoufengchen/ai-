"""
action_planner.py
AI动作编排模块
负责：根据意图生成动作序列
"""

import json
import random
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from enum import Enum

class ActionType(Enum):
    ANIMATION = "animation"
    LOCOMOTION = "locomotion"
    GAZE = "gaze"
    WAIT = "wait"
    DIALOGUE = "dialogue"
    CAMERA_SWITCH = "camera_switch"

@dataclass
class Action:
    type: str
    params: Dict[str, Any]
    id: str = ""
    
    def to_dict(self):
        return {
            "type": self.type,
            **self.params
        }

class ActionPlanner:
    """动作编排器"""
    
    def __init__(self):
        self.action_weights = self._load_action_weights()
        self.negation_words = ["不", "别", "勿", "没", "未", "否", "无"]
        self.preference_indicators = ["要", "想", "希望", "喜欢", "最好"]
        
    def _load_action_weights(self) -> Dict:
        """加载动作权重配置"""
        return {
            "walk": {"walk_slow": 20, "walk_normal": 50, "walk_fast": 30},
            "run": {"run_jog": 30, "run_normal": 50, "run_sprint": 20},
            "fly": {"fly_hover": 60, "fly_up": 20, "fly_down": 20}
        }
    
    def analyze_intent(self, text: str, context: Dict) -> Dict:
        """
        分析用户意图
        
        Args:
            text: 对话文本
            context: 上下文（当前位置、目标位置、商品信息等）
        
        Returns:
            结构化意图对象
        """
        intent = {
            "raw_text": text,
            "type": None,
            "keywords": [],
            "negated_keywords": [],
            "target": None,
            "speed_preference": "normal",
            "style_preference": "default",
            "mood": "neutral"
        }
        
        # 提取关键词
        movement_keywords = {
            "走": "walk", "跑": "run", "飞": "fly", "飞": "fly",
            "跳": "jump", "爬": "climb", "游": "swim"
        }
        
        action_keywords = {
            "拿": "fetch", "取": "fetch", "给": "give", "递": "hand_over",
            "放": "place", "展示": "present", "看": "look"
        }
        
        # 检测否定
        for word, action in movement_keywords.items():
            if word in text:
                # 检查是否被否定
                negated = False
                for neg in self.negation_words:
                    if f"{neg}{word}" in text or text.startswith(neg):
                        negated = True
                        break
                
                if negated:
                    intent["negated_keywords"].append(action)
                else:
                    intent["keywords"].append(action)
        
        # 检测速度偏好
        if "快" in text and "慢" not in text:
            intent["speed_preference"] = "fast"
        elif "慢" in text:
            intent["speed_preference"] = "slow"
        
        # 检测情绪
        if any(w in text for w in ["哈哈", "开心", "好耶"]):
            intent["mood"] = "happy"
        elif any(w in text for w in ["抱歉", "对不起", "不好意思"]):
            intent["mood"] = "apologetic"
        elif any(w in text for w in ["快点", " hurry"]):
            intent["mood"] = "urgent"
        
        # 确定意图类型
        if "fetch" in intent["keywords"] or "拿" in text or "取" in text:
            intent["type"] = "fetch_item"
            intent["target"] = self._extract_target(text, context)
        elif any(k in intent["keywords"] for k in ["walk", "run", "fly"]):
            intent["type"] = "move_to_target"
            intent["target"] = context.get("target_location")
        
        return intent
    
    def _extract_target(self, text: str, context: Dict) -> Optional[str]:
        """从文本中提取目标物体"""
        # TODO: 更复杂的实体提取
        # 简单版本：检查商品名称
        products = context.get("products", [])
        for product in products:
            if product["name"] in text:
                return product["id"]
        return None
    
    def select_action(self, action_category: str, intent: Dict) -> str:
        """
        根据意图选择具体动作
        
        Args:
            action_category: 动作类别 (walk/run/fly)
            intent: 分析后的意图
        
        Returns:
            选中的动作ID
        """
        weights = self.action_weights.get(action_category, {})
        
        # 应用意图调整权重
        adjusted_weights = {}
        for action, weight in weights.items():
            adjusted_weight = weight
            
            # 否定词排除
            if action in intent.get("negated_keywords", []):
                adjusted_weight = 0
            
            # 关键词提升
            if any(kw in action for kw in intent.get("keywords", [])):
                adjusted_weight *= 3
            
            # 速度偏好
            if intent.get("speed_preference") == "fast" and "fast" in action:
                adjusted_weight *= 2
            elif intent.get("speed_preference") == "slow" and "slow" in action:
                adjusted_weight *= 2
            
            adjusted_weights[action] = adjusted_weight
        
        # 过滤掉权重为0的
        valid_actions = {k: v for k, v in adjusted_weights.items() if v > 0}
        
        if not valid_actions:
            # 如果没有有效动作，返回默认值
            return f"{action_category}_normal"
        
        # 加权随机选择
        total = sum(valid_actions.values())
        r = random.uniform(0, total)
        cumulative = 0
        
        for action, weight in valid_actions.items():
            cumulative += weight
            if r <= cumulative:
                return action
        
        return list(valid_actions.keys())[-1]
    
    def plan_action_flow(self, intent: Dict, context: Dict) -> List[Action]:
        """
        规划完整动作流
        
        Args:
            intent: 分析后的意图
            context: 场景上下文
        
        Returns:
            动作序列
        """
        actions = []
        
        if intent["type"] == "fetch_item":
            actions = self._plan_fetch_flow(intent, context)
        elif intent["type"] == "move_to_target":
            actions = self._plan_movement_flow(intent, context)
        else:
            # 默认待机
            actions = [
                Action("animation", {"action": "idle_stand", "loop": True, "duration": 2})
            ]
        
        # 为每个动作分配ID
        for i, action in enumerate(actions):
            action.id = f"{action.type}_{i}"
        
        return actions
    
    def _plan_fetch_flow(self, intent: Dict, context: Dict) -> List[Action]:
        """规划取物动作流"""
        actions = []
        
        # 1. 看向货架
        actions.append(Action("gaze", {"target": "shelf", "duration": 0.5}))
        
        # 2. 转向货架
        actions.append(Action("animation", {"action": "turn_toward", "duration": 0.5}))
        
        # 3. 选择并执行移动动作
        move_action = self.select_action("walk", intent)
        target_pos = context.get("shelf_position", {"x": 0, "y": 0, "z": -3})
        
        actions.append(Action("locomotion", {
            "action": move_action,
            "to": target_pos,
            "speed": 1.0 if intent.get("speed_preference") == "normal" else 1.5
        }))
        
        # 4. 取物（根据高度选择）
        shelf_height = context.get("shelf_height", 1.2)
        if shelf_height > 1.8:
            reach_action = "reach_high"
        elif shelf_height > 0.8:
            reach_action = "reach_mid"
        else:
            reach_action = "reach_low"
        
        actions.append(Action("animation", {"action": reach_action}))
        
        # 5. 抓取（根据商品大小）
        product = context.get("target_product", {})
        size = product.get("size_category", "medium")
        
        if size in ["large", "heavy"]:
            grab_action = "grab_twohand"
        elif size == "sphere":
            grab_action = "grab_sphere"
        else:
            grab_action = "grab_onehand"
        
        actions.append(Action("animation", {"action": grab_action}))
        
        # 6. 返回
        actions.append(Action("locomotion", {
            "action": move_action,
            "to": context.get("return_position", {"x": 0, "y": 0, "z": 0}),
            "speed": 0.8  # 拿东西走慢点
        }))
        
        # 7. 展示
        actions.append(Action("animation", {"action": "present_show"}))
        
        return actions
    
    def _plan_movement_flow(self, intent: Dict, context: Dict) -> List[Action]:
        """规划移动动作流"""
        actions = []
        
        move_action = self.select_action(intent.get("keywords", ["walk"])[0], intent)
        
        actions.append(Action("locomotion", {
            "action": move_action,
            "to": intent.get("target", {"x": 0, "y": 0, "z": 0}),
            "speed": 1.5 if intent.get("speed_preference") == "fast" else 1.0
        }))
        
        return actions
    
    def plan_from_dialogue(self, dialogue: str, context: Dict) -> List[Dict]:
        """
        从对话文本直接生成动作流（对外接口）
        
        Args:
            dialogue: NPC对话文本
            context: 场景上下文
        
        Returns:
            动作流JSON数组
        """
        intent = self.analyze_intent(dialogue, context)
        actions = self.plan_action_flow(intent, context)
        
        return [action.to_dict() for action in actions]


# 全局实例
planner = ActionPlanner()

def plan_actions(dialogue: str, context: Dict) -> List[Dict]:
    """对外接口函数"""
    return planner.plan_from_dialogue(dialogue, context)
