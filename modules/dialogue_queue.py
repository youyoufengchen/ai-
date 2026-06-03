"""
对话队列管理器 - 管理待回复的弹幕/消息
支持优先级、手动排序、插队、取消
"""

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class DialogueStatus(Enum):
    PENDING = "pending"      # 等待AI生成回复
    GENERATING = "generating"  # AI正在生成
    QUEUED = "queued"        # 回复已生成，等待播放
    PLAYING = "playing"      # 正在播放
    COMPLETED = "completed"  # 已完成
    CANCELLED = "cancelled"  # 已取消/忽略
    EMERGENCY = "emergency"  # 紧急插队


@dataclass
class ExecutionState:
    """3D执行状态"""
    current_action_idx: int = -1         # 当前执行到的动作索引
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    action_states: Dict[str, str] = field(default_factory=dict)  # action_id -> state


@dataclass
class DialogueItem:
    id: str
    username: str
    message: str
    reply: str = ""                      # AI生成的回复
    status: DialogueStatus = DialogueStatus.PENDING
    priority: int = 5                    # 1-10, 越小越优先
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    tags: List[str] = field(default_factory=list)  # 标签: product_query, urgent, gift 等
    source: str = "danmaku"              # danmaku, manual, webhook
    sku_id: Optional[str] = None         # 关联的商品
    interrupt_current: bool = False      # 是否打断当前播放
    emotion: Optional[str] = None       # AI决定的情感（用于MiniMax TTS）
    
    # === Action Flow 支持字段 ===
    action_plan: Optional[Any] = None    # AIActionPlanner生成的动作计划
    parsed_intent: Dict[str, Any] = field(default_factory=dict)  # 解析的意图
    mentioned_skus: List[str] = field(default_factory=list)      # 提到的商品
    audio_url: Optional[str] = None      # TTS音频URL
    audio_duration: float = 0.0           # 音频时长（秒）
    execution_state: ExecutionState = field(default_factory=lambda: ExecutionState())
    
    def to_dict(self) -> dict:
        base = {
            "id": self.id,
            "username": self.username,
            "message": self.message[:50] + "..." if len(self.message) > 50 else self.message,
            "reply": self.reply[:50] + "..." if len(self.reply) > 50 else self.reply,
            "status": self.status.value,
            "priority": self.priority,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "tags": self.tags,
            "source": self.source,
            "sku_id": self.sku_id,
            "interrupt_current": self.interrupt_current,
            "emotion": self.emotion,
            # === Action Flow 字段 ===
            "has_action_plan": self.action_plan is not None,
            "action_plan": self.action_plan.to_dict() if self.action_plan else None,
            "parsed_intent": self.parsed_intent,
            "mentioned_skus": self.mentioned_skus,
            "audio_url": self.audio_url,
            "audio_duration": self.audio_duration,
            "execution_state": {
                "current_action_idx": self.execution_state.current_action_idx,
                "started_at": self.execution_state.started_at,
                "completed_at": self.execution_state.completed_at,
                "action_states": self.execution_state.action_states
            } if self.execution_state.started_at else None
        }
        return base


class DialogueQueueManager:
    """
    对话队列管理器
    
    流程：
    1. 收到弹幕/消息 -> 创建DialogueItem -> PENDING队列
    2. AI异步生成回复 -> reply字段填充 -> 移入QUEUED队列
    3. 按优先级和顺序播放 -> PLAYING -> 完成后COMPLETED
    4. 运营可手动：调整顺序、插队、取消、紧急处理
    """
    
    def __init__(self, ai_service, tts_service, cfg=None, action_planner=None):
        self.ai = ai_service
        self.tts = tts_service
        self.cfg = cfg  # ConfigManager实例，用于获取角色信息
        self.action_planner = action_planner  # AIActionPlanner实例
        
        # 三个队列
        self.pending: Dict[str, DialogueItem] = {}      # 等待AI生成
        self.queued: Dict[str, DialogueItem] = {}       # 等待播放（已生成回复）
        self.history: List[DialogueItem] = []           # 已完成的历史
        self.history_limit = 100
        
        # 回调函数
        self.on_item_added: Optional[Callable] = None
        self.on_item_updated: Optional[Callable] = None
        self.on_item_removed: Optional[Callable] = None
        self.on_queue_changed: Optional[Callable] = None
        
        # Action Flow 专用回调
        self.on_action_plan_ready: Optional[Callable] = None  # 动作计划生成完成
        self.on_3d_execution_start: Optional[Callable] = None  # 3D执行开始
        self.on_3d_execution_complete: Optional[Callable] = None  # 3D执行完成
        
        self._lock = asyncio.Lock()
        self._processing = False
        self._current_item: Optional[DialogueItem] = None
        
        # 直接播报模式：跳过ActionPlanner动作计划生成，直接TTS
        self.direct_broadcast: bool = False
        
        # WebSocket广播句柄（由外部设置）
        self._broadcast_fn: Optional[Callable] = None
        
    async def add_message(self, username: str, message: str, 
                         priority: int = 5, tags: List[str] = None,
                         source: str = "danmaku", sku_id: str = None,
                         interrupt: bool = False) -> str:
        """
        添加新消息到队列
        
        Returns:
            item_id: 可用于后续操作
        """
        item_id = str(uuid.uuid4())[:8]
        
        item = DialogueItem(
            id=item_id,
            username=username,
            message=message,
            priority=priority,
            tags=tags or [],
            source=source,
            sku_id=sku_id,
            interrupt_current=interrupt
        )
        
        async with self._lock:
            self.pending[item_id] = item
        
        logger.info(f"Dialogue added: [{item_id}] {username}: {message[:30]}... (p={priority})")
        
        if self.on_item_added:
            await self.on_item_added(item)
        
        # 触发AI异步生成
        asyncio.create_task(self._generate_reply(item_id))
        
        return item_id
    
    async def add_manual(self, text: str, username: str = "坊主", 
                        emergency: bool = False) -> str:
        """
        手动添加话术（跳过AI生成，直接进入待播放队列）
        """
        item_id = str(uuid.uuid4())[:8]
        item = DialogueItem(
            id=item_id,
            username=username,
            message="[手动话术]",
            reply=text,
            priority=0 if emergency else 3,  # 手动优先级高
            tags=["manual", "emergency" if emergency else ""],
            source="manual",
            interrupt_current=emergency,
            status=DialogueStatus.QUEUED  # 直接进入queued
        )
        
        async with self._lock:
            self.queued[item_id] = item
        
        logger.info(f"Manual dialogue: [{item_id}] {text[:30]}... (emergency={emergency})")
        
        if self.on_item_added:
            await self.on_item_added(item)
        if self.on_queue_changed:
            await self.on_queue_changed()
        
        return item_id
    
    async def _generate_reply(self, item_id: str):
        """异步生成AI回复和动作计划"""
        async with self._lock:
            if item_id not in self.pending:
                return
            item = self.pending[item_id]
            item.status = DialogueStatus.GENERATING
            item.updated_at = time.time()
        
        try:
            # Step 1: 调用AI生成回复
            if self.ai.api_key and self.cfg:
                character = self.cfg.get_character()
                style_id = self.cfg.get_current_style()
                sku = self.cfg.get_sku(item.sku_id) if item.sku_id else None
                
                reply = await self.ai.chat(
                    user_message=item.message,
                    username=item.username,
                    character=character,
                    style_id=style_id,
                    sku=sku
                )
                if isinstance(reply, tuple):
                    reply_text, reply_emotion = reply
                    item.emotion = reply_emotion
                else:
                    reply_text = reply
                item.reply = reply_text or "客官的问题很有意思，容坊主想想~"
            else:
                # AI不可用的默认回复
                item.reply = f"{item.username}客官说得好！"
            
            # Step 2: 【Action Flow】使用ActionPlanner生成动作计划
            # 直接播报模式下跳过，不生成动作计划
            if self.action_planner and not self.direct_broadcast:
                try:
                    action_plan = await self.action_planner.plan_for_dialogue(
                        dialogue_id=item_id,
                        reply_text=item.reply,
                        emotion=item.emotion,
                        audio_duration=None  # 还未合成TTS，先估算
                    )
                    item.action_plan = action_plan
                    item.parsed_intent = {
                        "intent": action_plan.trigger_type,
                        "emotion": action_plan.trigger_emotion
                    }
                    item.mentioned_skus = [action_plan.trigger_sku_id] if action_plan.trigger_sku_id else []
                    
                    logger.info(f"[ActionFlow] Plan generated for {item_id}: "
                               f"{len(action_plan.actions)} actions, "
                               f"duration={action_plan.estimated_duration:.1f}s")
                    
                    # 通知动作计划就绪
                    if self.on_action_plan_ready:
                        await self.on_action_plan_ready(item, action_plan)
                    
                except Exception as e:
                    logger.error(f"[ActionFlow] Failed to plan actions for {item_id}: {e}")
                    # 失败时不阻塞，继续执行（只是没有3D动作）
            
            async with self._lock:
                if item_id in self.pending:
                    item.status = DialogueStatus.QUEUED
                    item.updated_at = time.time()
                    # 移动到queued队列
                    self.queued[item_id] = self.pending.pop(item_id)
                    
                    logger.info(f"Reply generated: [{item_id}] {item.reply[:30]}...")
                    
                    if self.on_item_updated:
                        await self.on_item_updated(item)
                    if self.on_queue_changed:
                        await self.on_queue_changed()
                        
        except Exception as e:
            logger.error(f"Failed to generate reply for {item_id}: {e}")
            async with self._lock:
                if item_id in self.pending:
                    item = self.pending[item_id]
                    item.status = DialogueStatus.CANCELLED
                    item.reply = "哎呀，坊主走神了，请再说一遍~"
                    self.queued[item_id] = self.pending.pop(item_id)
    
    def get_next_to_play(self) -> Optional[DialogueItem]:
        """获取下一个要播放的（按优先级和时间排序）"""
        if not self.queued:
            return None
        
        # 排序：优先级 -> 时间
        items = sorted(
            self.queued.values(),
            key=lambda x: (x.priority, x.created_at)
        )
        
        return items[0] if items else None
    
    async def mark_playing(self, item_id: str):
        """标记为正在播放，同时触发3D动作流执行"""
        async with self._lock:
            if item_id in self.queued:
                item = self.queued[item_id]
                item.status = DialogueStatus.PLAYING
                item.updated_at = time.time()
                self._current_item = item
                
                # 【Action Flow】标记执行开始
                item.execution_state.started_at = time.time()
                
                # 【Action Flow】广播3D动作流执行指令
                if item.action_plan and self._broadcast_fn:
                    asyncio.create_task(
                        self._broadcast_action_flow_start(item)
                    )
                
                if self.on_item_updated:
                    await self.on_item_updated(item)
    
    def set_broadcast_handler(self, broadcast_fn: Callable):
        """设置WebSocket广播函数"""
        self._broadcast_fn = broadcast_fn
    
    async def _broadcast_action_flow_start(self, item: DialogueItem):
        """广播Action Flow执行开始事件"""
        if not self._broadcast_fn or not item.action_plan:
            return
        
        plan = item.action_plan
        
        # 广播动作流开始
        await self._broadcast_fn({
            "action": "action_flow_start",
            "dialogue_id": item.id,
            "plan_id": plan.id,
            "audio_url": item.audio_url,
            "audio_duration": item.audio_duration or plan.audio_duration,
            "estimated_duration": plan.estimated_duration,
            "actions_count": len(plan.actions),
            "trigger_type": plan.trigger_type,
            "emotion": plan.trigger_emotion
        })
        
        # execute_action_flow 由 scene_director 在 TTS 合成完成后广播（带正确的 audio_url/duration）
        logger.info(f"[ActionFlow] action_flow_start notified for dialogue {item.id}")
    
    async def on_action_flow_completed(self, item_id: str):
        """前端通知3D动作流完成时调用"""
        async with self._lock:
            if item_id in self.queued:
                item = self.queued[item_id]
                item.execution_state.completed_at = time.time()
                
                if self.on_3d_execution_complete:
                    await self.on_3d_execution_complete(item)
    
    async def on_action_flow_interrupted(self, item_id: str, reason: str = ""):
        """处理动作流被打断"""
        logger.info(f"[ActionFlow] Interrupted: {item_id}, reason={reason}")
        
        # 打断时清理状态
        if self._broadcast_fn:
            await self._broadcast_fn({
                "action": "action_flow_interrupted",
                "dialogue_id": item_id,
                "reason": reason
            })
    
    async def mark_completed(self, item_id: str):
        """标记为已完成"""
        async with self._lock:
            if item_id in self.queued:
                item = self.queued.pop(item_id)
                item.status = DialogueStatus.COMPLETED
                item.updated_at = time.time()
                self.history.append(item)
                self._current_item = None
                
                # 限制历史长度
                if len(self.history) > self.history_limit:
                    self.history = self.history[-self.history_limit:]
                
                if self.on_item_updated:
                    await self.on_item_updated(item)
    
    async def cancel_item(self, item_id: str) -> bool:
        """取消/忽略某个排队项"""
        async with self._lock:
            # 在pending中
            if item_id in self.pending:
                item = self.pending.pop(item_id)
                item.status = DialogueStatus.CANCELLED
                logger.info(f"Cancelled pending item: {item_id}")
                if self.on_item_removed:
                    await self.on_item_removed(item)
                return True
            
            # 在queued中
            if item_id in self.queued:
                item = self.queued.pop(item_id)
                item.status = DialogueStatus.CANCELLED
                logger.info(f"Cancelled queued item: {item_id}")
                if self.on_item_removed:
                    await self.on_item_removed(item)
                return True
            
            return False
    
    async def set_emergency(self, item_id: str) -> bool:
        """设置为紧急插队（立即播放）"""
        async with self._lock:
            if item_id in self.queued:
                item = self.queued[item_id]
                item.status = DialogueStatus.EMERGENCY
                item.priority = 0  # 最高优先级
                item.interrupt_current = True
                item.updated_at = time.time()
                
                logger.info(f"Emergency item: {item_id}")
                if self.on_item_updated:
                    await self.on_item_updated(item)
                return True
            return False
    
    async def reorder_items(self, item_ids: List[str]):
        """手动调整顺序（通过修改优先级实现）"""
        async with self._lock:
            for idx, item_id in enumerate(item_ids):
                if item_id in self.queued:
                    # 优先级 = 顺序索引（越小越优先）
                    self.queued[item_id].priority = idx + 1
        
        logger.info(f"Queue reordered: {len(item_ids)} items")
        if self.on_queue_changed:
            await self.on_queue_changed()
    
    async def skip_current(self) -> bool:
        """跳过当前正在播放的"""
        async with self._lock:
            if self._current_item and self._current_item.id in self.queued:
                item = self.queued.pop(self._current_item.id)
                item.status = DialogueStatus.CANCELLED
                self._current_item = None
                logger.info(f"Skipped current: {item.id}")
                return True
        return False
    
    def get_queue_status(self) -> dict:
        """获取队列状态"""
        return {
            "pending_count": len(self.pending),
            "queued_count": len(self.queued),
            "history_count": len(self.history),
            "current_item": self._current_item.to_dict() if self._current_item else None,
            "pending": [item.to_dict() for item in sorted(self.pending.values(), key=lambda x: x.created_at)],
            "queued": [item.to_dict() for item in sorted(self.queued.values(), key=lambda x: (x.priority, x.created_at))],
            "history": [item.to_dict() for item in self.history[-20:]]  # 最近20条
        }
    
    def clear_all(self):
        """清空所有队列"""
        self.pending.clear()
        self.queued.clear()
        self._current_item = None
        logger.info("All dialogue queues cleared")


# 便捷函数
def create_dialogue_queue_manager(
    ai_service, 
    tts_service, 
    cfg=None, 
    action_planner=None
) -> DialogueQueueManager:
    """创建对话队列管理器实例（支持Action Flow）"""
    return DialogueQueueManager(ai_service, tts_service, cfg, action_planner)
