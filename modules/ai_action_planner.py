"""
AI Action Planner - AI驱动的动作规划器

核心职责：根据NPC回复文本生成完整的3D动作序列

设计原则：
1. 基于NPC生成的回复文本预规划动作（非用户原始输入）
2. 提前规划确保语音+动作同步无卡顿
3. 支持意图识别、商品提取、动作序列生成
"""

import json
import logging
import uuid
import time
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

from modules.action_retriever import ActionRetriever

logger = logging.getLogger("ai_action_planner")


class ActionType(Enum):
    """动作类型"""
    ANIMATION = "animation"          # 骨骼动画
    LOCOMOTION = "locomotion"        # 移动（走路、跑步）
    GAZE = "gaze"                    # 视线/头部朝向
    INTERACTION = "interaction"      # 交互（抓取、递送）
    EFFECT = "effect"                # 特效（显示物品、高亮）
    WAIT = "wait"                    # 等待
    TRANSFORMATION = "transformation" # 变身序列（切换形态+特效+音效）
    EXPRESSION = "expression"        # 表情触发（morph/overlay/骨骼面部）
    SPECIAL_SKILL = "special_skill"  # 特殊技能（道具挂载+粒子+音效复合）
    SOUND = "sound"                  # 纯音效（无视觉动画）
    PROP_ATTACH = "prop_attach"      # 道具挂载/移除
    ACTOR_SPAWN = "actor_spawn"      # 召唤另一个Actor出场


class PlanStatus(Enum):
    """计划状态"""
    PENDING = "pending"
    APPROVED = "approved"
    EXECUTING = "executing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass
class PlannedAction:
    """计划中的单个动作"""
    id: str
    type: str                          # animation/locomotion/gaze/effect/transformation...
    action_id: str                     # 具体动作标识
    actor_id: str = "bao_qing_host"   # 执行此动作的Actor ID（默认主播）
    params: Dict[str, Any] = field(default_factory=dict)
    start_time: float = 0.0            # 相对于音频开始的时间点(秒)
    duration: float = 1.0              # 动作持续时间
    wait_for_complete: bool = True     # 是否等待完成才进行下一步
    can_interrupt: bool = False        # 是否可被高优先级打断
    depends_on: Optional[str] = None  # 依赖的前置动作ID
    sounds: Optional[Dict] = None     # 随动作触发的音效 {on_start, on_complete, loop_during}

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "action_id": self.action_id,
            "actor_id": self.actor_id,
            "params": self.params,
            "start_time": self.start_time,
            "duration": self.duration,
            "wait_for_complete": self.wait_for_complete,
            "can_interrupt": self.can_interrupt,
            "depends_on": self.depends_on,
            "sounds": self.sounds,
        }


@dataclass
class SyncPoint:
    """语音-动作同步点"""
    time_offset: float                 # 相对于音频开始的时间(秒)
    action_id: Optional[str] = None   # 触发的动作ID
    subtitle_text: Optional[str] = None
    effect: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            "time_offset": self.time_offset,
            "action_id": self.action_id,
            "subtitle_text": self.subtitle_text,
            "effect": self.effect
        }


@dataclass
class ActionPlan:
    """AI生成的动作计划"""
    id: str
    dialogue_id: str
    trigger_type: str                  # product_query/gift/order/chat
    trigger_sku_id: Optional[str] = None
    trigger_emotion: str = "neutral"
    actions: List[PlannedAction] = field(default_factory=list)
    sync_points: List[SyncPoint] = field(default_factory=list)
    estimated_duration: float = 0.0
    audio_duration: Optional[float] = None
    status: str = "pending"
    priority: int = 5
    created_at: float = field(default_factory=time.time)
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "dialogue_id": self.dialogue_id,
            "trigger_type": self.trigger_type,
            "trigger_sku_id": self.trigger_sku_id,
            "trigger_emotion": self.trigger_emotion,
            "actions": [a.to_dict() for a in self.actions],
            "sync_points": [s.to_dict() for s in self.sync_points],
            "estimated_duration": self.estimated_duration,
            "audio_duration": self.audio_duration,
            "status": self.status,
            "priority": self.priority,
            "created_at": self.created_at
        }


@dataclass
class ParsedIntent:
    """解析的意图"""
    intent_type: str                   # product_present/greeting/thanks/chat/special_skill/transformation
    target_products: List[str] = field(default_factory=list)
    actions_implied: List[str] = field(default_factory=list)
    emotion: str = "neutral"
    special_skill_hint: Optional[str] = None  # snap_fingers_fire / transform_fox_partial / None
    key_phrases: List[str] = field(default_factory=list)
    location_references: List[str] = field(default_factory=list)
    needs_fetch: bool = False          # 是否需要取货
    needs_present: bool = False        # 是否需要展示


class ActorRegistry:
    """
    Actor注册表 — 加载 actors.json，提供能力路由、表情查询、音效查询。
    这是实现“谁去做什么”不随机、冠与能力相关的核心类。
    """

    # 任务类型 → 所需能力映射
    TASK_CAPABILITY_MAP: Dict[str, List[str]] = {
        "FETCH_PRODUCT":   ["LOCOMOTION", "MANIPULATION"],
        "PRESENT_PRODUCT": ["MANIPULATION"],
        "NAVIGATE_TO":     ["LOCOMOTION", "NAVIGATION"],
        "SUMMON_ACTOR":    ["SPAWNING"],
        "TRANSFORM":       ["TRANSFORMATION"],
        "EXPRESS_EMOTION": ["EXPRESSION"],
    }

    def __init__(self, actors_path: str = "config/actors.json",
                 expression_path: str = "config/expression_catalog.json",
                 sound_path: str = "config/sound_catalog.json"):
        self._actors: Dict[str, Dict] = {}
        self._expressions: Dict[str, Dict] = {}
        self._sounds: Dict[str, Dict] = {}
        self._busy: set = set()  # 当前正在执行任务的actor_id集合
        self._load(actors_path, expression_path, sound_path)

    def _load(self, actors_path: str, expression_path: str, sound_path: str):
        try:
            data = json.loads(Path(actors_path).read_text(encoding="utf-8"))
            for actor in data.get("actors", []):
                self._actors[actor["id"]] = actor
            logger.info(f"[ActorRegistry] Loaded {len(self._actors)} actors: {list(self._actors.keys())}")
        except Exception as e:
            logger.warning(f"[ActorRegistry] Failed to load actors.json: {e}")

        try:
            data = json.loads(Path(expression_path).read_text(encoding="utf-8"))
            for set_id, expr_set in data.get("expression_sets", {}).items():
                for expr in expr_set.get("expressions", []):
                    key = f"{set_id}:{expr['emotion_tag']}"
                    self._expressions[key] = expr
            logger.info(f"[ActorRegistry] Loaded {len(self._expressions)} expression entries")
        except Exception as e:
            logger.warning(f"[ActorRegistry] Failed to load expression_catalog.json: {e}")

        try:
            data = json.loads(Path(sound_path).read_text(encoding="utf-8"))
            for snd in data.get("sounds", []):
                self._sounds[snd["id"]] = snd
            logger.info(f"[ActorRegistry] Loaded {len(self._sounds)} sounds")
        except Exception as e:
            logger.warning(f"[ActorRegistry] Failed to load sound_catalog.json: {e}")

    # ── 能力路由 ─────────────────────────────────────────────────

    def resolve_actor_for_task(self, task_type: str,
                               preferred_actor: str = "bao_qing_host") -> str:
        """
        根据任务类型返回最合适的actor_id。
        优先尝试preferred_actor，不满足能力时自动路由。
        """
        required = self.TASK_CAPABILITY_MAP.get(task_type, [])
        if not required:
            return preferred_actor

        # 先尝试首选actor
        preferred = self._actors.get(preferred_actor, {})
        preferred_caps = preferred.get("capabilities", [])
        if all(c in preferred_caps for c in required) and preferred_actor not in self._busy:
            return preferred_actor

        # 首选不满足，遍历所有actor找能能完成任务的
        for actor_id, actor in self._actors.items():
            if actor_id == preferred_actor:
                continue
            caps = actor.get("capabilities", [])
            if all(c in caps for c in required) and actor_id not in self._busy:
                logger.info(f"[ActorRegistry] Task '{task_type}' routed to '{actor_id}' "
                            f"('{preferred_actor}' lacks {[c for c in required if c not in preferred_caps]})")
                return actor_id

        logger.warning(f"[ActorRegistry] No available actor for task '{task_type}'")
        return preferred_actor  # 堆外回倦，让调用方处理失败

    def get_actor(self, actor_id: str) -> Optional[Dict]:
        return self._actors.get(actor_id)

    def is_position_locked(self, actor_id: str) -> bool:
        return self._actors.get(actor_id, {}).get("position_locked", False)

    def get_current_form(self, actor_id: str) -> str:
        return self._actors.get(actor_id, {}).get("current_form",
               self._actors.get(actor_id, {}).get("default_form", "human"))

    def set_current_form(self, actor_id: str, form: str):
        if actor_id in self._actors:
            self._actors[actor_id]["current_form"] = form

    def mark_busy(self, actor_id: str):
        self._busy.add(actor_id)

    def mark_free(self, actor_id: str):
        self._busy.discard(actor_id)

    # ── 表情查询 ─────────────────────────────────────────────────

    def get_expression(self, actor_id: str, emotion: str) -> Optional[Dict]:
        """
        查找最匹配的表情实现。
        查找顺序：actor当前form专属表情集 → 公共层回退。
        """
        actor = self._actors.get(actor_id, {})
        current_form = self.get_current_form(actor_id)

        # 将form映射到对应的expression_set
        forms = actor.get("forms", {})
        form_cfg = forms.get(current_form, {})
        expr_set_id = form_cfg.get("expression_set")

        # 先在form专属表情集中找
        if expr_set_id:
            key = f"{expr_set_id}:{emotion}"
            if key in self._expressions:
                return self._expressions[key]

        # 回退到公共层
        fallback_key = f"human_npc_base:{emotion}"
        return self._expressions.get(fallback_key)

    # ── 音效查询 ─────────────────────────────────────────────────

    def get_emotion_sounds(self, actor_id: str, emotion: str) -> Optional[Dict]:
        """
        获取情绪音效配置（优先匹配当前form，否则降级）。
        返回 actors.json 中 emotion_sound_map 内的配置。
        """
        actor = self._actors.get(actor_id, {})
        return actor.get("emotion_sound_map", {}).get(emotion)

    def get_transform_sounds(self, actor_id: str, target_form: str) -> Optional[Dict]:
        """获取变身音效，来自 actors.json forms[target_form].sounds"""
        actor = self._actors.get(actor_id, {})
        forms = actor.get("forms", {})
        return forms.get(target_form, {}).get("sounds")


class SceneContext:
    """
    场景上下文 — 基于 scenes.json 中 objects[] 的真实3D坐标。
    不再使用2D像素坐标转换。
    """

    def __init__(self, cfg):
        self.cfg = cfg
        self._scene_cache: Optional[Dict] = None

    def _get_scene(self) -> Dict:
        if self._scene_cache is None:
            self._scene_cache = self.cfg.get_scene() or {}
        return self._scene_cache

    def invalidate(self):
        """场景切换后调用，清除缓存"""
        self._scene_cache = None

    @property
    def host_position(self) -> Dict[str, float]:
        """NPC固定站位（来自 host_position_3d 字段）"""
        scene = self._get_scene()
        pos = scene.get("host_position_3d")
        if pos and isinstance(pos, dict):
            return {"x": float(pos.get("x", 0)),
                    "y": float(pos.get("y", 0)),
                    "z": float(pos.get("z", 0))}
        return {"x": 0.0, "y": 0.0, "z": 0.0}

    def get_shelf_position(self, shelf_id: str) -> Optional[Dict[str, float]]:
        """从 objects[] 读取货架的真实3D坐标"""
        scene = self._get_scene()
        for obj in scene.get("objects", []):
            if obj.get("id") == shelf_id:
                pos = obj.get("position", {})
                return {
                    "x": float(pos.get("x", 0)),
                    "y": float(pos.get("y", 0)),
                    "z": float(pos.get("z", 0)),
                }
        return None

    def find_sku_slot(self, sku_id: str) -> Optional[Dict]:
        """
        查找绑定了指定商品的货架对象。
        优先读 objects[].sku_id（3D新系统），回退旧 slots[].sku_id。
        """
        scene = self._get_scene()
        # 新系统：3D objects 上的 sku_id 字段
        for obj in scene.get("objects", []):
            if obj.get("sku_id") == sku_id and obj.get("type") in ("shelf", "prop"):
                pos = obj.get("position", {})
                return {
                    "id": obj["id"],
                    "x": float(pos.get("x", 0)),
                    "y": float(pos.get("y", 0)),   # y = 货架在3D中的高度
                    "z": float(pos.get("z", 0)),
                    "label": obj.get("label", ""),
                    "sku_id": sku_id,
                }
        # 旧系统回退：slots[]（2D百分比坐标，y值无意义）
        for slot in scene.get("slots", []):
            if slot.get("sku_id") == sku_id:
                return {
                    "id": slot.get("id", ""),
                    "x": 0.0,
                    "y": 240.0,  # 给旧slot一个"中等高度"默认值
                    "z": -2.0,
                    "label": slot.get("label", ""),
                    "sku_id": sku_id,
                }
        return None


class AIActionPlanner:
    """
    AI驱动的动作规划器

    动作通过 ActionRetriever 从 config/action_catalog.json 检索，
    不再硬编码文件路径。新增动作只需在 catalog 中注册即可生效。
    """

    # ── 固定语义查询（用于 INTENT_SEQUENCES 中的 key → 检索）────────────
    _ACTION_QUERIES = {
        "idle":         "待机站立等待",
        "walk":         "走路移动",
        "walk_normal":  "正常走路走路循环",
        "greeting":     "打招呼挥手欢迎",
        "present":      "双手展示商品给观众看",
        "handover":     "单手递给顾客",
        "reach_high":   "取高处货架商品",
        "reach_mid":    "取中层货架商品",
        "reach_low":    "取低处货架商品",
        "reach_crouch": "弯腰深取地面物品",
        "crouch":       "蹲下捡地面物品",
        "bend":         "弯腰取低处",
    }

    # ═══════════════════════════════════════════════════════════
    #  移动策略配置（用于AI决策选择最优方案）
    # ═══════════════════════════════════════════════════════════
    MOVEMENT_STRATEGIES = {
        "walk": {
            "speed": 1.5,           # 米/秒
            "energy_cost": 10,      # 能量消耗
            "drama_score": 0.2,     # 戏剧性评分(0-1)
            "max_height_diff": 0.5, # 最大高度差
            "requires_navmesh": True
        },
        "fly": {
            "speed": 3.0,
            "energy_cost": 30,
            "drama_score": 0.8,
            "max_height_diff": 100,
            "requires_navmesh": False,
            "abilities_needed": ["can_fly"]
        },
        "climb": {
            "speed": 1.0,
            "energy_cost": 15,
            "drama_score": 0.4,
            "max_height_diff": 10,
            "requires_navmesh": True,
            "abilities_needed": ["can_climb"],
            "requires_path": True  # 需要预定义攀爬路径
        },
        "extend": {
            "speed": 0,             # 主体不动
            "energy_cost": 5,
            "drama_score": 1.0,     # 最高戏剧性！
            "max_height_diff": 5,
            "max_horizontal_dist": 8,
            "requires_navmesh": False,
            "abilities_needed": ["can_extend"]
        }
    }

    # ═══════════════════════════════════════════════════════════
    #  意图 → 动作序列定义
    #  每条规则：list of (action_key, duration_sec, loop)
    # ═══════════════════════════════════════════════════════════
    INTENT_SEQUENCES = {
        # 打招呼：挥手 → 回到待机
        "greeting": [
            ("greeting", 2.0, False),
            ("idle",     4.0, True),
        ],
        # 感谢/道谢：点头/鞠躬式待机
        "thanks": [
            ("greeting", 1.5, False),
            ("idle",     4.0, True),
        ],
        # 告别
        "goodbye": [
            ("greeting", 2.0, False),
            ("idle",     2.0, False),
        ],
        # 日常聊天：保持待机
        "chat": [
            ("idle", 8.0, True),
        ],
        # 商品介绍（无需取货）：展示姿势 → 待机
        "product_introduce": [
            ("present", 3.0, False),
            ("idle",    6.0, True),
        ],
        # 商品展示（需取货）：动态生成，见 _plan_product_fetch
        "product_present": [],
    }

    def __init__(self, ai_service, cfg):
        self.ai = ai_service
        self.cfg = cfg
        self.scene_context = SceneContext(cfg)
        catalog_path = Path("config/action_catalog.json")
        self.retriever = ActionRetriever(str(catalog_path))
        self.actor_registry = ActorRegistry()
        logger.info(f"[ActionPlanner] Retriever ready, mode={self.retriever.mode}, "
                    f"{len(self.retriever.actions)} actions loaded")
        
    async def plan_for_dialogue(
        self, 
        dialogue_id: str,
        reply_text: str,
        emotion: str = "neutral",
        audio_duration: Optional[float] = None
    ) -> ActionPlan:
        """
        为对话生成完整的动作计划
        
        Args:
            dialogue_id: 对话项ID
            reply_text: NPC回复文本
            emotion: 情感标签
            audio_duration: 音频时长（如果已知）
            
        Returns:
            ActionPlan: 完整的动作计划
        """
        logger.info(f"[ActionPlanner] Planning actions for dialogue {dialogue_id}")
        
        # Step 1: AI解析回复内容
        parsed = await self._parse_reply_with_ai(reply_text)
        logger.debug(f"[ActionPlanner] Parsed intent: {parsed.intent_type}")
        
        # Step 2: 提取提到的商品
        skus = self._extract_mentioned_skus(reply_text, parsed)
        
        # Step 3: 根据意图类型规划动作序列
        actions = self._plan_actions_for_intent(parsed, skus, audio_duration)
        
        # Step 4: 计算同步点
        sync_points = self._calculate_sync_points(
            actions, reply_text, audio_duration
        )
        
        # Step 5: 计算预估时长
        estimated_duration = sum(a.duration for a in actions)
        if audio_duration and audio_duration > estimated_duration:
            # 如果音频更长，调整最后一个动作为循环
            if actions:
                actions[-1].duration = audio_duration - sum(
                    a.duration for a in actions[:-1]
                )
                actions[-1].params["loop"] = True
                estimated_duration = audio_duration
        
        # Step 6: 组装ActionPlan
        resolved_emotion = emotion or parsed.emotion
        plan = ActionPlan(
            id=str(uuid.uuid4())[:8],
            dialogue_id=dialogue_id,
            trigger_type=parsed.intent_type,
            trigger_sku_id=skus[0] if skus else None,
            trigger_emotion=resolved_emotion,
            actions=actions,
            sync_points=sync_points,
            estimated_duration=estimated_duration,
            audio_duration=audio_duration
        )

        # Step 7: 注入情绪音效（与TTS台词并行播放的非语言声音）
        if resolved_emotion and resolved_emotion != "neutral":
            self._inject_emotion_sound("bao_qing_host", resolved_emotion, plan)

        # Step 8: 注入表情（与动作并行，不阻塞动作序列）
        if resolved_emotion and resolved_emotion != "neutral":
            expr_action = self._plan_expression("bao_qing_host", resolved_emotion,
                                                start_time=0.0)
            if expr_action:
                plan.actions.insert(0, expr_action)

        logger.info(f"[ActionPlanner] Created plan {plan.id} with {len(plan.actions)} actions "
                    f"(emotion={resolved_emotion}), duration={estimated_duration:.1f}s")

        return plan
    
    async def _parse_reply_with_ai(self, reply: str) -> ParsedIntent:
        """
        使用AI解析NPC回复，提取结构化意图
        
        如果AI不可用，使用规则回退
        """
        # 尝试使用AI解析
        if self.ai and self.ai.api_key:
            try:
                result = await self._call_ai_parser(reply)
                if result:
                    return result
            except Exception as e:
                logger.warning(f"AI parser failed: {e}, using fallback")
        
        # 规则回退解析
        return self._parse_reply_fallback(reply)
    
    async def _call_ai_parser(self, reply: str) -> Optional[ParsedIntent]:
        """调用AI API解析回复"""
        prompt = f"""分析以下NPC直播回复，提取结构化信息：

回复内容："{reply}"

请返回JSON格式：
{{
    "intent_type": "意图类型(product_present/greeting/thanks/chat/goodbye/fetch/special_skill/transformation)",
    "target_products": ["提到的商品名称关键词"],
    "actions_implied": ["walk", "grab", "present", "turn", "greet", "snap_fingers", "transform"],
    "emotion": "happy/sad/surprised/neutral/excited/thanks/cute/angry/mysterious/embarrassed",
    "key_phrases": ["关键动作短语"],
    "location_references": ["位置指代:货架/这边/那里"],
    "needs_fetch": true/false,
    "needs_present": true/false,
    "special_skill_hint": "snap_fingers_fire或transform_fox_partial或null"
}}

识别规则：弹手指/响指/火苗→special_skill(hint:snap_fingers_fire)；变身/狐化→transformation(hint:transform_fox_partial)；其他→对应意图。
只返回JSON，不要其他文字。"""

        try:
            result = await self.ai.quick_completion(prompt, max_tokens=300)
            data = json.loads(result)
            
            return ParsedIntent(
                intent_type=data.get("intent_type", "chat"),
                target_products=data.get("target_products", []),
                actions_implied=data.get("actions_implied", []),
                emotion=data.get("emotion", "neutral"),
                special_skill_hint=data.get("special_skill_hint") or None,
                key_phrases=data.get("key_phrases", []),
                location_references=data.get("location_references", []),
                needs_fetch=data.get("needs_fetch", False),
                needs_present=data.get("needs_present", False)
            )
        except Exception as e:
            logger.error(f"Failed to parse AI response: {e}")
            return None
    
    def _parse_reply_fallback(self, reply: str) -> ParsedIntent:
        """规则回退解析（AI不可用时）"""
        reply_lower = reply.lower()
        
        # 意图识别关键词
        intent = "chat"
        if any(w in reply_lower for w in ["介绍", "这茶", "这商品", "看看", "给你"]):
            intent = "product_present"
        elif any(w in reply_lower for w in ["欢迎", "来了", "请进", "里面请"]):
            intent = "greeting"
        elif any(w in reply_lower for w in ["谢谢", "感谢", "多谢", "谢了"]):
            intent = "thanks"
        elif any(w in reply_lower for w in ["慢走", "再见", "再来", "拜拜"]):
            intent = "goodbye"
        
        # 提取商品
        target_products = []
        skus = self.cfg.skus.get("skus", {})
        for sku_id, sku in skus.items():
            name = sku.get("name", "")
            if name and name in reply:
                target_products.append(sku_id)
        
        # 情感识别
        emotion = "neutral"
        if any(w in reply_lower for w in ["开心", "高兴", "哈哈", "好", "棒", "赞"]):
            emotion = "happy"
        elif any(w in reply_lower for w in ["抱歉", "对不起", "不好意思"]):
            emotion = "sad"
        elif any(w in reply_lower for w in ["惊讶", "真的", "哇", "呀"]):
            emotion = "surprised"
        
        # 判断是否需要取货/展示
        # 特殊技能/变身关键词识别
        skill_hint = None
        if any(w in reply_lower for w in ["响指", "弹指", "打响指", "变出火", "召唤火", "魔法", "厉害吧"]):
            intent = "special_skill"
            skill_hint = "snap_fingers_fire"
        elif any(w in reply_lower for w in ["变身", "变成狐狸", "露出耳朵", "九尾", "狐化", "兽耳"]):
            intent = "transformation"
            skill_hint = "transform_fox_partial"

        needs_fetch = any(w in reply_lower for w in ["拿", "取", "给你", "介绍", "看看"])
        needs_present = needs_fetch or any(w in reply_lower for w in ["展示", "看", "这"])

        return ParsedIntent(
            intent_type=intent,
            special_skill_hint=skill_hint,
            target_products=target_products,
            actions_implied=[],
            emotion=emotion,
            key_phrases=[],
            location_references=[],
            needs_fetch=needs_fetch,
            needs_present=needs_present
        )
    
    def _extract_mentioned_skus(
        self, 
        reply: str, 
        parsed: ParsedIntent
    ) -> List[str]:
        """从回复中提取提到的商品ID列表"""
        skus = self.cfg.skus.get("skus", {})
        mentioned = []
        
        # 1. 直接匹配商品名称
        for sku_id, sku in skus.items():
            name = sku.get("name", "")
            if name and name in reply:
                mentioned.append(sku_id)
        
        # 2. 如果AI解析提供了商品名，尝试匹配
        for product_name in parsed.target_products:
            for sku_id, sku in skus.items():
                if sku.get("name") == product_name:
                    if sku_id not in mentioned:
                        mentioned.append(sku_id)
        
        return mentioned
    
    def _get_file_path(self, action_key: str) -> str:
        """通过检索器将动作key转换为实际文件路径，找不到时回退到idle"""
        query = self._ACTION_QUERIES.get(action_key, action_key)
        results = self.retriever.search(query, top_k=1)
        if results:
            return results[0]["file"]
        logger.warning(f"[ActionPlanner] No match for action_key='{action_key}', fallback to idle")
        fallback = self.retriever.get_by_id("idle_stand")
        return fallback["file"] if fallback else "基础姿态/直立站立/Standing Arguing.glb"

    def _search_action(self, query: str, category: Optional[str] = None,
                       constraints: Optional[Dict] = None) -> str:
        """自然语言查询检索最佳动作文件路径（供外部直接使用）"""
        results = self.retriever.search(query, top_k=1,
                                        category_filter=category,
                                        constraints=constraints)
        if results:
            logger.debug(f"[ActionPlanner] search('{query}') → {results[0]['id']} ({results[0]['score']:.3f})")
            return results[0]["file"]
        fallback = self.retriever.get_by_id("idle_stand")
        return fallback["file"] if fallback else "基础姿态/直立站立/Standing Arguing.glb"

    def _make_action(
        self,
        action_id: str,
        action_key: str,
        start_time: float,
        duration: float,
        loop: bool = False,
        action_type: str = "animation",
        params: Optional[Dict] = None,
        wait_for_complete: bool = True,
        can_interrupt: bool = False,
        actor_id: str = "bao_qing_host",
        sounds: Optional[Dict] = None,
    ) -> PlannedAction:
        """统一构造PlannedAction，注入真实file_path和actor_id"""
        p = dict(params or {})
        if action_type not in ("transformation", "expression", "sound",
                               "prop_attach", "actor_spawn"):
            p["file_path"] = self._get_file_path(action_key)
        p["loop"] = loop
        return PlannedAction(
            id=action_id,
            type=action_type,
            action_id=action_key,
            actor_id=actor_id,
            params=p,
            start_time=start_time,
            duration=duration,
            wait_for_complete=wait_for_complete,
            can_interrupt=can_interrupt,
            sounds=sounds,
        )

    def _build_sequence_from_template(
        self, template_key: str, audio_duration: Optional[float] = None
    ) -> List[PlannedAction]:
        """
        根据 INTENT_SEQUENCES 模板生成动作列表。
        末尾若有 loop=True 的动作，时长自动撑满 audio_duration。
        """
        template = self.INTENT_SEQUENCES.get(template_key, self.INTENT_SEQUENCES["chat"])
        actions = []
        t = 0.0
        for i, (key, dur, loop) in enumerate(template):
            is_last = (i == len(template) - 1)
            # 最后一个 loop 动作时长撑到音频结束
            if is_last and loop and audio_duration and audio_duration > t:
                dur = max(audio_duration - t, dur)
            actions.append(self._make_action(
                action_id=f"{template_key}_{i}_{key}",
                action_key=key,
                start_time=t,
                duration=dur,
                loop=loop,
                wait_for_complete=not loop,
                can_interrupt=loop,
            ))
            if not loop:
                t += dur
        return actions

    def _plan_actions_for_intent(
        self,
        parsed: ParsedIntent,
        sku_ids: List[str],
        audio_duration: Optional[float] = None,
    ) -> List[PlannedAction]:
        """根据意图类型规划动作序列"""
        intent = parsed.intent_type

        if intent == "product_present" and sku_ids and parsed.needs_fetch:
            return self._plan_product_fetch(sku_ids[0], audio_duration)

        if intent in ("product_present", "product_introduce") and sku_ids:
            return self._build_sequence_from_template("product_introduce", audio_duration)

        if intent == "greeting":
            return self._build_sequence_from_template("greeting", audio_duration)

        if intent == "thanks":
            return self._build_sequence_from_template("thanks", audio_duration)

        if intent == "goodbye":
            return self._build_sequence_from_template("goodbye", audio_duration)

        if intent == "special_skill":
            return self._plan_special_skill(parsed, audio_duration)

        if intent == "transformation":
            hint = getattr(parsed, 'special_skill_hint', None) or ""
            target_form = "fox_partial"
            if "full" in hint or "full" in " ".join(parsed.actions_implied):
                target_form = "fox_full"
            return self._plan_transformation("bao_qing_host", target_form, start_time=0.0)

        # 默认：待机
        return self._build_sequence_from_template("chat", audio_duration)

    def _plan_special_skill(
        self,
        parsed: "ParsedIntent",
        audio_duration: Optional[float] = None,
    ) -> List[PlannedAction]:
        """
        规划特殊技能动作。
        优先使用 special_skill_hint 精确命中，否则按 emotion/actions_implied 向量检索。
        """
        hint = getattr(parsed, 'special_skill_hint', None)
        actor_id = self.actor_registry.resolve_actor_for_task(
            "EXPRESS_EMOTION", preferred_actor="bao_qing_host"
        )

        # 优先：hint精确命中
        if hint and hint != "null":
            catalog = self.retriever.get_by_id(hint)
            if catalog:
                sounds = catalog.get("sounds")
                dur = float(catalog.get("duration", 1.5))
                skill_action = PlannedAction(
                    id=f"skill_{hint}",
                    type=ActionType.SPECIAL_SKILL.value,
                    action_id=hint,
                    actor_id=actor_id,
                    params={"file_path": self._get_file_path(hint),
                            "loop": False,
                            "bone_effects": catalog.get("bone_effects", [])},
                    start_time=0.0,
                    duration=dur,
                    wait_for_complete=True,
                    sounds=sounds,
                )
                # 技能结束后回待机
                idle_dur = max((audio_duration or 4.0) - dur, 1.0)
                idle_action = self._make_action(
                    "skill_idle", "idle", dur, idle_dur,
                    loop=True, wait_for_complete=False, can_interrupt=True,
                    actor_id=actor_id,
                )
                return [skill_action, idle_action]

        # 降级：按情绪+implied动作向量检索 special_skill 类动作
        query_parts = parsed.actions_implied + ([parsed.emotion] if parsed.emotion else [])
        query = " ".join(query_parts) or "展示特殊技能魔法"
        results = self.retriever.search(
            query,
            top_k=1,
            category_filter="特殊技能",
        )
        if results:
            best = results[0]
            dur = float(best.get("duration", 1.5))
            skill_action = PlannedAction(
                id=f"skill_retrieved",
                type=ActionType.SPECIAL_SKILL.value,
                action_id=best["id"],
                actor_id=actor_id,
                params={"file_path": self._get_file_path(best["id"]),
                        "loop": False,
                        "bone_effects": best.get("bone_effects", [])},
                start_time=0.0,
                duration=dur,
                wait_for_complete=True,
                sounds=best.get("sounds"),
            )
            idle_dur = max((audio_duration or 4.0) - dur, 1.0)
            idle_action = self._make_action(
                "skill_idle", "idle", dur, idle_dur,
                loop=True, wait_for_complete=False, can_interrupt=True,
                actor_id=actor_id,
            )
            return [skill_action, idle_action]

        # 最终降级：普通chat
        return self._build_sequence_from_template("chat", audio_duration)

    def _plan_product_fetch(
        self, sku_id: str, audio_duration: Optional[float] = None
    ) -> List[PlannedAction]:
        """
        取货展示序列 —— 通过能力路由决定由谁去取货：
        - 主播NPC无LOCOMOTION → 自动路由到robot_helper_01
        - 机器人负责走到货架取货返回，NPC同时做召唤手势+等待
        - 机器人返回后NPC接过来展示给观众
        """
        slot = self.scene_context.find_sku_slot(sku_id)
        reach_key = self._select_reach_key(slot)
        shelf_pos = self._resolve_shelf_pos(sku_id, slot)
        host_pos = self.scene_context.host_position or {"x": 0.0, "y": 0.0, "z": 1.5}

        fetch_actor = self.actor_registry.resolve_actor_for_task(
            "FETCH_PRODUCT", preferred_actor="bao_qing_host"
        )
        host_actor = "bao_qing_host"
        actions: List[PlannedAction] = []
        t = 0.0

        if fetch_actor != host_actor:
            # ── 机器人取货分支 ──────────────────────────────────
            # NPC: 召唤手势
            summon_catalog = self.retriever.get_by_id("summon_robot_gesture")
            summon_sounds = (summon_catalog or {}).get("sounds")
            actions.append(PlannedAction(
                id="fetch_summon",
                type=ActionType.SPECIAL_SKILL.value,
                action_id="summon_robot_gesture",
                actor_id=host_actor,
                params={"file_path": self._get_file_path("idle"),
                        "spawns_actor": fetch_actor, "loop": False},
                start_time=t, duration=2.0,
                wait_for_complete=True,
                sounds=summon_sounds,
            ))
            t += 2.0

            # Robot: 走向货架（使用 walk_normal 真实走路动画）
            walk_dur = max(self._calculate_walk_duration(host_pos, shelf_pos, 1.2), 1.0)
            actions.append(PlannedAction(
                id="fetch_robot_walk",
                type=ActionType.LOCOMOTION.value,
                action_id="walk_normal",
                actor_id=fetch_actor,
                params={"file_path": self._get_file_path("walk_normal"),
                        "to": shelf_pos, "speed": 1.2, "loop": True},
                start_time=t, duration=walk_dur,
                wait_for_complete=True,
            ))
            t += walk_dur

            # Robot: 取物
            actions.append(PlannedAction(
                id="fetch_robot_reach",
                type=ActionType.ANIMATION.value,
                action_id=reach_key,
                actor_id=fetch_actor,
                params={"file_path": self._get_file_path(reach_key), "loop": False},
                start_time=t, duration=1.5,
                wait_for_complete=True,
                sounds={"on_start": "assets/sounds/action/item_grab.mp3"},
            ))
            t += 1.5

            # Robot: 返回主播位（使用 walk_normal）
            back_dur = max(self._calculate_walk_duration(shelf_pos, host_pos, 0.9), 1.0)
            actions.append(PlannedAction(
                id="fetch_robot_return",
                type=ActionType.LOCOMOTION.value,
                action_id="walk_normal",
                actor_id=fetch_actor,
                params={"file_path": self._get_file_path("walk_normal"),
                        "to": host_pos, "speed": 0.9, "loop": True,
                        "carrying_sku": sku_id},
                start_time=t, duration=back_dur,
                wait_for_complete=True,
                sounds={"on_complete": "assets/sounds/action/item_place.mp3"},
            ))
            t += back_dur

            # NPC: 接过并展示
            present_dur = max((audio_duration or 8.0) - t, 2.0)
            actions.append(PlannedAction(
                id="fetch_host_present",
                type=ActionType.ANIMATION.value,
                action_id="present",
                actor_id=host_actor,
                params={"file_path": self._get_file_path("present"),
                        "loop": True, "sku_id": sku_id},
                start_time=t, duration=present_dur,
                wait_for_complete=False, can_interrupt=True,
            ))

        else:
            # ── NPC自己去取（有LOCOMOTION时走此分支，使用 walk_normal）──────────────
            walk_dur = max(self._calculate_walk_duration(host_pos, shelf_pos, 1.0), 1.0)
            actions.append(self._make_action(
                "fetch_walk_to", "walk_normal", t, walk_dur,
                action_type="locomotion", loop=True, wait_for_complete=True,
                params={"to": shelf_pos, "speed": 1.0},
                actor_id=host_actor,
            ))
            t += walk_dur

            actions.append(self._make_action(
                "fetch_reach", reach_key, t, 1.5,
                action_type="animation", loop=False, wait_for_complete=True,
                actor_id=host_actor,
                sounds={"on_start": "assets/sounds/action/item_grab.mp3"},
            ))
            t += 1.5

            back_dur = max(self._calculate_walk_duration(shelf_pos, host_pos, 0.8), 1.0)
            actions.append(self._make_action(
                "fetch_walk_back", "walk", t, back_dur,
                action_type="locomotion", loop=True, wait_for_complete=True,
                params={"to": host_pos, "speed": 0.8, "carrying_sku": sku_id},
                actor_id=host_actor,
            ))
            t += back_dur

            present_dur = max((audio_duration or 8.0) - t, 2.0)
            actions.append(self._make_action(
                "fetch_present", "present", t, present_dur,
                loop=True, wait_for_complete=False, can_interrupt=True,
                params={"sku_id": sku_id},
                actor_id=host_actor,
            ))

        return actions

    def _resolve_shelf_pos(self, sku_id: str, slot: Optional[Dict]) -> Dict:
        """
        获取NPC前往货架时的停靠点3D坐标。查找优先级：
        1. slot 已含 x/y/z（来自 objects[]）→ 直接用 slot 坐标
        2. scene objects[] 中找到货架 npc_stop_point → 用停靠点
        3. scene objects[] 中找到货架 position → 用货架坐标偏移
        4. hardcode 兜底（开发测试用）
        """
        scene = self.scene_context._get_scene()

        # 优先：slot 本身已有3D坐标（来自 find_sku_slot 的 objects[]）
        if slot and "x" in slot and "z" in slot:
            # 若 objects[] 有对应的 npc_stop_point 则优先使用
            shelf_id = slot.get("id", "")
            if shelf_id:
                for obj in scene.get("objects", []):
                    if obj.get("id") == shelf_id:
                        sp = obj.get("npc_stop_point", {})
                        pos_list = sp.get("position")  # [x, y, z] 列表格式
                        if pos_list and len(pos_list) >= 3:
                            return {"x": pos_list[0], "y": pos_list[1], "z": pos_list[2]}
                        # 也接受字典格式 {"x":..., "y":..., "z":...}
                        if sp and "x" in sp:
                            return {"x": float(sp.get("x", 0)),
                                    "y": float(sp.get("y", 0)),
                                    "z": float(sp.get("z", 0))}
            # slot 坐标本身就是货架位置，NPC站在货架前方稍微偏移
            return {"x": float(slot["x"]), "y": float(slot.get("y", 0)), "z": float(slot["z"])}

        # 次级：按 sku_id 扫描 objects[]
        for obj in scene.get("objects", []):
            if obj.get("sku_id") == sku_id:
                sp = obj.get("npc_stop_point", {})
                pos_list = sp.get("position")
                if pos_list and len(pos_list) >= 3:
                    return {"x": pos_list[0], "y": pos_list[1], "z": pos_list[2]}
                if sp and "x" in sp:
                    return {"x": float(sp.get("x", 0)),
                            "y": float(sp.get("y", 0)),
                            "z": float(sp.get("z", 0))}
                # 没有 stop_point 就用 object position 本身
                pos = obj.get("position", {})
                if pos:
                    return {"x": float(pos.get("x", 0)),
                            "y": float(pos.get("y", 0)),
                            "z": float(pos.get("z", -2.0))}

        # 兜底（保留原有demo坐标，仅开发测试时用）
        _fallback = {
            "tea_001":  {"x": -2.2, "y": 0.0, "z": -1.3},
            "tea_002":  {"x":  0.0, "y": 0.0, "z": -1.5},
            "tea_003":  {"x":  2.2, "y": 0.0, "z": -1.3},
            "gift_001": {"x":  3.5, "y": 0.0, "z": -0.3},
        }
        return _fallback.get(sku_id, {"x": 0.0, "y": 0.0, "z": -2.0})

    def _plan_expression(
        self, actor_id: str, emotion: str, start_time: float = 0.0
    ) -> Optional[PlannedAction]:
        """
        为指定actor和情绪生成表情动作。
        自动按actor当前form选择对应的表情集和音效。
        """
        expr = self.actor_registry.get_expression(actor_id, emotion)
        if not expr:
            return None
        return PlannedAction(
            id=f"expr_{actor_id}_{emotion}",
            type=ActionType.EXPRESSION.value,
            action_id=expr["id"],
            actor_id=actor_id,
            params={
                "implementation": expr.get("implementation", "morph"),
                "morph_weights": expr.get("morph_weights", {}),
                "transition_duration_s": expr.get("transition_duration_s", 0.3),
                "animation_file": expr.get("animation_file"),
            },
            start_time=start_time,
            duration=expr.get("transition_duration_s", 0.3),
            wait_for_complete=False,
            sounds=expr.get("sounds"),
        )

    def _plan_transformation(
        self, actor_id: str, target_form: str, start_time: float = 0.0
    ) -> List[PlannedAction]:
        """
        生成变身序列：特效遮盖 → 换模型/MorphTarget → 倒计时自动还原。

        前端 executeTransformation 负责：
          1. 播放 transition_effect WebM/粒子（遮盖切换瞬间）
          2. 若 model_override 非空 → 隐藏原模型，显示/加载目标模型
          3. 若有 morph_weights → 渐变应用形态键
          4. 若有 prop_attachments → 挂载道具到骨骼
          5. 启动 revert_after_seconds 倒计时，时限到后自动还原
        """
        # 从 actors.json 读取目标 form 的完整配置
        actor_data  = self.actor_registry.get_actor(actor_id) or {}
        form_cfg    = (actor_data.get("forms") or {}).get(target_form, {})
        origin_form = actor_data.get("current_form", "human")

        catalog_action = self.retriever.get_by_id(f"transform_{target_form}")
        sounds   = (catalog_action or {}).get("sounds") or \
                   self.actor_registry.get_transform_sounds(actor_id, target_form)
        duration = (catalog_action or {}).get("duration", 1.5)

        trigger_cfg = form_cfg.get("trigger", {})
        effect      = trigger_cfg.get("transition_effect") or \
                      (catalog_action or {}).get("transition_effect")
        trans_dur   = trigger_cfg.get("transition_duration_s", 1.2)

        revert_after   = form_cfg.get("revert_after_seconds", 180)
        revert_to_form = form_cfg.get("revert_to_form", origin_form)
        revert_effect  = form_cfg.get("revert_transition_effect", effect)

        actions: List[PlannedAction] = []
        actions.append(PlannedAction(
            id=f"transform_{actor_id}_{target_form}",
            type=ActionType.TRANSFORMATION.value,
            action_id=f"transform_{target_form}",
            actor_id=actor_id,
            params={
                # 变身目标信息
                "target_form":          target_form,
                "model_override":       form_cfg.get("model_override"),
                "morph_weights":        form_cfg.get("morph_weights", {}),
                "prop_attachments":     form_cfg.get("prop_attachments", []),
                "scale":                form_cfg.get("scale", 1.0),
                "tts_voice":            form_cfg.get("tts_voice"),
                # 特效
                "transition_effect":    effect,
                "transition_duration_s": trans_dur,
                # 还原信息（前端持有，倒计时后自动发还原指令）
                "revert_to_form":       revert_to_form,
                "revert_after_seconds": revert_after,
                "revert_effect":        revert_effect,
                "origin_model":         (actor_data.get("forms") or {})
                                        .get(origin_form, {}).get("model_override"),
                "origin_morph_weights": (actor_data.get("forms") or {})
                                        .get(origin_form, {}).get("morph_weights", {}),
                "origin_prop_attachments": (actor_data.get("forms") or {})
                                        .get(origin_form, {}).get("prop_attachments", []),
            },
            start_time=start_time,
            duration=duration,
            wait_for_complete=True,
            sounds=sounds,
        ))

        # 后端同步更新内存中的 form 状态
        self.actor_registry.set_current_form(actor_id, target_form)

        # 变身完成后触发新 form 对应的表情
        expr = self._plan_expression(actor_id, "angry",
                                     start_time=start_time + duration)
        if expr:
            actions.append(expr)
        return actions

    def _inject_emotion_sound(
        self, actor_id: str, emotion: str, plan: "ActionPlan"
    ):
        """
        将情绪音效注入ActionPlan首位作为独立SOUND动作，与TTS台词并行播放。
        这是"撒娇时发出娇嗔声/生气时低吼"的实现入口。
        """
        snd_cfg = self.actor_registry.get_emotion_sounds(actor_id, emotion)
        if not snd_cfg:
            return
        file_on_enter = snd_cfg.get("on_enter")
        if file_on_enter:
            plan.actions.insert(0, PlannedAction(
                id=f"emosnd_{actor_id}_{emotion}",
                type=ActionType.SOUND.value,
                action_id=f"emotion_sound_{emotion}",
                actor_id=actor_id,
                params={"file": file_on_enter, "volume": 0.6},
                start_time=0.0, duration=1.0,
                wait_for_complete=False,
            ))
    
    def _calculate_walk_duration(
        self, 
        from_pos: Dict[str, float], 
        to_pos: Dict[str, float],
        speed: float = 1.0
    ) -> float:
        """计算行走所需时间"""
        import math
        dx = to_pos.get("x", 0) - from_pos.get("x", 0)
        dz = to_pos.get("z", 0) - from_pos.get("z", 0)
        distance = math.sqrt(dx * dx + dz * dz)
        
        # 速度1.0 = 1米/秒
        return max(distance / max(speed, 0.1), 0.5)  # 最少0.5秒
    
    def _select_reach_key(self, slot: Optional[Dict]) -> str:
        """根据货架高度选择取货动作key（3D世界坐标，单位：米）"""
        if not slot:
            return "reach_mid"
        y = slot.get("y", 1.0)  # 3D世界坐标，默认1米（腰部高度）
        if y < 0.3:             # 地面/脚边
            return "reach_crouch"
        elif y < 0.8:           # 低处（膝盖到腰）
            return "reach_low"
        elif y > 1.6:           # 高处（肩部以上）
            return "reach_high"
        return "reach_mid"      # 中等（腰到肩）

    def _select_movement_strategy(
        self,
        from_pos: Dict[str, float],
        to_pos: Dict[str, float],
        npc_abilities: List[str],
        context: Dict = None
    ) -> Dict[str, Any]:
        """
        AI智能选择最优移动策略
        
        考虑因素：
        - 时间效率（距离/速度）
        - 能量消耗
        - 戏剧性（直播效果）
        - NPC能力限制
        - 场景条件（是否有楼梯）
        
        Returns:
            {
                "strategy": "walk|fly|climb|extend",
                "score": 0.85,  # 综合得分
                "reason": "选择理由",
                "actions": [...]  # 对应的动作序列
            }
        """
        import math
        
        context = context or {}
        dx = to_pos.get("x", 0) - from_pos.get("x", 0)
        dy = to_pos.get("y", 0) - from_pos.get("y", 0)
        dz = to_pos.get("z", 0) - from_pos.get("z", 0)
        
        horizontal_dist = math.sqrt(dx * dx + dz * dz)
        height_diff = abs(dy)
        
        # 决策权重（可配置）
        time_weight = context.get("time_weight", 0.4)
        drama_weight = context.get("drama_weight", 0.3)
        energy_weight = context.get("energy_weight", 0.3)
        
        strategies = []
        
        # 方案1：普通行走
        if height_diff < 0.5:  # 目标在地面高度
            walk_time = horizontal_dist / self.MOVEMENT_STRATEGIES["walk"]["speed"]
            walk_energy = self.MOVEMENT_STRATEGIES["walk"]["energy_cost"]
            walk_drama = self.MOVEMENT_STRATEGIES["walk"]["drama_score"]
            
            walk_score = (
                (1 / max(walk_time, 0.5)) * time_weight +
                walk_drama * drama_weight +
                (1 - walk_energy / 50) * energy_weight
            )
            
            strategies.append({
                "strategy": "walk",
                "score": walk_score,
                "time": walk_time,
                "actions": [
                    ("walk", walk_time, True),  # 循环行走
                    ("reach_mid", 1.5, False)   # 假设中等高度
                ],
                "reason": "目标在地面，行走最直接"
            })
        
        # 方案2：飞行
        if "can_fly" in npc_abilities and height_diff > 0.5:
            fly_time = max(horizontal_dist, height_diff) / self.MOVEMENT_STRATEGIES["fly"]["speed"]
            fly_time += 2.0  # 加上起飞和降落时间
            fly_energy = self.MOVEMENT_STRATEGIES["fly"]["energy_cost"]
            fly_drama = self.MOVEMENT_STRATEGIES["fly"]["drama_score"]
            
            fly_score = (
                (1 / max(fly_time, 0.5)) * time_weight +
                fly_drama * drama_weight +
                (1 - fly_energy / 50) * energy_weight
            )
            
            strategies.append({
                "strategy": "fly",
                "score": fly_score,
                "time": fly_time,
                "actions": [
                    ("takeoff", 1.0, False),
                    ("fly_loop", fly_time - 2.0, True),
                    ("land", 1.0, False),
                    ("reach_high", 1.5, False)  # 飞行后通常取高处
                ],
                "reason": "飞行最快且最具观赏性" if fly_drama > 0.7 else "高度差大，飞行合适"
            })
        
        # 方案3：攀爬（如果有楼梯）
        if "can_climb" in npc_abilities and context.get("has_stairs") and height_diff > 1.0:
            climb_time = horizontal_dist / self.MOVEMENT_STRATEGIES["climb"]["speed"]
            climb_energy = self.MOVEMENT_STRATEGIES["climb"]["energy_cost"]
            climb_drama = self.MOVEMENT_STRATEGIES["climb"]["drama_score"]
            
            climb_score = (
                (1 / max(climb_time, 0.5)) * time_weight +
                climb_drama * drama_weight +
                (1 - climb_energy / 50) * energy_weight
            )
            
            strategies.append({
                "strategy": "climb",
                "score": climb_score,
                "time": climb_time,
                "actions": [
                    ("climb_start", 0.8, False),
                    ("climb_loop", climb_time - 1.6, True),
                    ("climb_end", 0.8, False),
                    ("reach_mid", 1.5, False)
                ],
                "reason": "有楼梯，攀爬更真实"
            })
        
        # 方案4：手臂伸长（特殊能力，最具戏剧性）
        if "can_extend" in npc_abilities and horizontal_dist < 8 and height_diff < 5:
            extend_time = 2.0 + 2.0  # 伸长+缩回时间
            extend_energy = self.MOVEMENT_STRATEGIES["extend"]["energy_cost"]
            extend_drama = self.MOVEMENT_STRATEGIES["extend"]["drama_score"]
            
            extend_score = (
                (1 / max(extend_time, 0.5)) * time_weight +
                extend_drama * drama_weight +
                (1 - extend_energy / 50) * energy_weight
            )
            
            # 戏剧性权重高时，伸长手臂得分加成
            if drama_weight > 0.4:
                extend_score *= 1.2
            
            strategies.append({
                "strategy": "extend",
                "score": extend_score,
                "time": extend_time,
                "actions": [
                    ("idle", 0.5, True),  # 准备姿态
                    ("arm_extend", 1.0, False),
                    ("arm_grab", 1.0, False),
                    ("arm_retract", 1.0, False),
                    ("present", 2.0, False)  # 展示拿到的物品
                ],
                "reason": "距离近，伸长手臂最具戏剧性！" if extend_drama > 0.9 else "省力且快速"
            })
        
        # 选择最优策略
        if not strategies:
            # 默认行走
            return {
                "strategy": "walk",
                "score": 0.5,
                "actions": [("walk", 2.0, True), ("idle", 1.0, True)],
                "reason": "默认方案"
            }
        
        strategies.sort(key=lambda x: x["score"], reverse=True)
        best = strategies[0]
        
        logger.info(f"[AIPlanner] 移动策略选择: {best['strategy']} (得分: {best['score']:.2f}, 原因: {best['reason']})")
        
        return {
            "strategy": best["strategy"],
            "score": best["score"],
            "estimated_time": best["time"],
            "actions": best["actions"],
            "reason": best["reason"],
            "all_options": [
                {"strategy": s["strategy"], "score": s["score"], "reason": s["reason"]} 
                for s in strategies
            ]
        }
    
    def _calculate_sync_points(
        self,
        actions: List[PlannedAction],
        reply_text: str,
        audio_duration: Optional[float]
    ) -> List[SyncPoint]:
        """
        计算语音与动作的同步点
        
        策略：
        - 取货动作开始时：显示字幕
        - 展示动作开始时：高亮相关货架
        - 根据文本长度估算关键时间点
        """
        sync_points = []
        
        if not audio_duration:
            # 估算音频时长：中文约3.8字/秒
            audio_duration = len(reply_text) / 3.8 + 0.8
        
        # 为每个关键动作添加同步点
        for action in actions:
            if action.action_id == "present":
                # 展示开始时高亮货架
                sync_points.append(SyncPoint(
                    time_offset=action.start_time,
                    action_id=action.id,
                    effect="highlight_shelf"
                ))
        
        return sync_points
    
    def create_emergency_plan(
        self,
        dialogue_id: str,
        emergency_type: str
    ) -> ActionPlan:
        """创建紧急情况的简化动作计划（使用真实文件路径）"""
        if emergency_type in ("gift_big", "order"):
            # 大礼物/下单：打招呼挥手 → 待机
            actions = [
                self._make_action("emerg_0", "greeting", 0.0,  2.0, loop=False),
                self._make_action("emerg_1", "idle",     2.0,  4.0, loop=True, can_interrupt=True),
            ]
        else:
            # 普通紧急：待机
            actions = [
                self._make_action("emerg_0", "greeting", 0.0, 2.0, loop=False),
                self._make_action("emerg_1", "idle",     2.0, 4.0, loop=True, can_interrupt=True),
            ]
        
        return ActionPlan(
            id=str(uuid.uuid4())[:8],
            dialogue_id=dialogue_id,
            trigger_type=emergency_type,
            trigger_sku_id=None,
            trigger_emotion="happy",
            actions=actions,
            estimated_duration=sum(a.duration for a in actions),
            priority=1,  # 最高优先级
            status="pending"
        )


# 便捷函数
def create_action_planner(ai_service, cfg) -> AIActionPlanner:
    """创建动作规划器实例"""
    return AIActionPlanner(ai_service, cfg)
