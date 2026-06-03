"""
语音互动排队管理器
支持固定入口链接 + 观众排队 + 主播控制
"""
import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Callable, Any
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)

class VoiceFeature(Enum):
    """语音功能类型"""
    MESSAGE = "message"      # 语音消息
    CALL = "call"            # 实时通话

class QueueStatus(Enum):
    """排队状态"""
    WAITING = "waiting"      # 等待中
    CONNECTING = "connecting"  # 正在连接
    ACTIVE = "active"        # 进行中
    COMPLETED = "completed"  # 已完成
    CANCELLED = "cancelled"  # 已取消

@dataclass
class VoiceRequest:
    """语音互动请求"""
    request_id: str
    user_id: str
    username: str
    feature: VoiceFeature      # 请求的功能类型
    status: QueueStatus
    created_at: datetime
    
    # 通话相关
    session_id: Optional[str] = None
    max_duration: int = 60
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    
    # 数据
    audio_chunks: List[bytes] = field(default_factory=list)
    transcribed_text: str = ""
    
    def get_wait_time(self) -> int:
        """获取已等待时间（秒）"""
        return int((datetime.now() - self.created_at).total_seconds())


class VoiceQueueManager:
    """语音互动排队管理器"""
    
    def __init__(self):
        # 配置
        self.config = {
            "voice_message_enabled": True,    # 语音消息开关
            "voice_call_enabled": True,       # 实时通话开关
            "max_queue_size": 10,             # 最大排队人数
            "auto_accept": False,             # 自动接受（False=主播手动接受）
            "default_call_duration": 60,      # 默认通话时长
            "max_call_duration": 3600,        # 最大通话时长（1小时）
            "entry_url_path": "/voice/join",  # 固定入口路径
        }
        
        # 队列管理
        self.waiting_queue: List[VoiceRequest] = []      # 等待队列
        self.active_sessions: Dict[str, VoiceRequest] = {}  # 进行中的会话
        self.history: List[VoiceRequest] = []             # 历史记录（保留最近50条）
        
        # 事件处理器
        self.event_handlers: List[Callable] = []
        
        # 统计
        self.stats = {
            "total_requests": 0,
            "total_completed": 0,
            "total_cancelled": 0
        }
        
        logger.info("[VoiceQueueManager] 初始化完成")
    
    def update_config(self, **kwargs):
        """更新配置"""
        for key, value in kwargs.items():
            if key in self.config:
                self.config[key] = value
                logger.info(f"[VoiceQueueManager] 配置更新: {key} = {value}")
    
    def get_config(self) -> Dict:
        """获取当前配置"""
        return self.config.copy()
    
    def is_feature_enabled(self, feature: VoiceFeature) -> bool:
        """检查功能是否启用"""
        if feature == VoiceFeature.MESSAGE:
            return self.config["voice_message_enabled"]
        elif feature == VoiceFeature.CALL:
            return self.config["voice_call_enabled"]
        return False
    
    def on_event(self, handler: Callable):
        """注册事件处理器"""
        self.event_handlers.append(handler)
    
    async def emit(self, event_type: str, data: Dict):
        """触发事件"""
        for handler in self.event_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event_type, data)
                else:
                    handler(event_type, data)
            except Exception as e:
                logger.error(f"[VoiceQueueManager] 事件处理错误: {e}")
    
    def join_queue(self, username: str, user_id: str, feature_type: str) -> Dict:
        """
        加入排队队列
        返回: {"success": bool, "position": int, "estimated_wait": int, "request_id": str}
        """
        # 检查功能是否启用
        feature = VoiceFeature.CALL if feature_type == "call" else VoiceFeature.MESSAGE
        if not self.is_feature_enabled(feature):
            return {
                "success": False,
                "error": f"{'实时通话' if feature == VoiceFeature.CALL else '语音消息'}功能当前未开启"
            }
        
        # 检查队列是否已满
        if len(self.waiting_queue) >= self.config["max_queue_size"]:
            return {
                "success": False,
                "error": "排队人数已满，请稍后再试"
            }
        
        # 检查是否已在队列中
        existing = next((r for r in self.waiting_queue if r.user_id == user_id), None)
        if existing:
            return {
                "success": False,
                "error": "你已经在排队中了",
                "position": self.waiting_queue.index(existing) + 1
            }
        
        # 创建请求
        request = VoiceRequest(
            request_id=str(uuid.uuid4())[:8],
            user_id=user_id,
            username=username,
            feature=feature,
            status=QueueStatus.WAITING,
            created_at=datetime.now(),
            max_duration=self.config["default_call_duration"]
        )
        
        self.waiting_queue.append(request)
        self.stats["total_requests"] += 1
        
        position = len(self.waiting_queue)
        estimated_wait = position * 30  # 估算每人30秒
        
        logger.info(f"[VoiceQueueManager] {username} 加入排队 ({feature.value}), 位置: {position}")
        
        # 触发事件
        asyncio.create_task(self.emit("user_joined_queue", {
            "request_id": request.request_id,
            "username": username,
            "feature": feature.value,
            "position": position,
            "queue_length": len(self.waiting_queue)
        }))
        
        # 如果是自动接受模式，且是第一个，自动接受
        if self.config["auto_accept"] and position == 1:
            asyncio.create_task(self._auto_accept_request(request.request_id))
        
        return {
            "success": True,
            "request_id": request.request_id,
            "position": position,
            "estimated_wait": estimated_wait,
            "feature": feature.value
        }
    
    async def _auto_accept_request(self, request_id: str):
        """自动接受请求"""
        await asyncio.sleep(2)  # 给主播2秒反应时间
        result = self.accept_request(request_id)
        if result["success"]:
            logger.info(f"[VoiceQueueManager] 自动接受请求: {request_id}")
    
    def accept_request(self, request_id: str, max_duration: int = None) -> Dict:
        """主播接受请求"""
        # 查找请求
        request = next((r for r in self.waiting_queue if r.request_id == request_id), None)
        if not request:
            return {"success": False, "error": "请求不存在或已处理"}
        
        # 从等待队列移除
        self.waiting_queue.remove(request)
        
        # 设置通话时长
        if max_duration:
            request.max_duration = min(max_duration, self.config["max_call_duration"])
        
        # 创建会话
        request.session_id = str(uuid.uuid4())[:8]
        request.status = QueueStatus.ACTIVE
        request.started_at = datetime.now()
        
        self.active_sessions[request.session_id] = request
        
        logger.info(f"[VoiceQueueManager] 接受请求: {request.username} ({request.feature.value}), 时长: {request.max_duration}s")
        
        # 触发事件
        asyncio.create_task(self.emit("request_accepted", {
            "request_id": request.request_id,
            "session_id": request.session_id,
            "username": request.username,
            "feature": request.feature.value,
            "max_duration": request.max_duration
        }))
        
        # 如果是通话模式，启动计时器
        if request.feature == VoiceFeature.CALL:
            asyncio.create_task(self._call_timer(request.session_id))
        
        return {
            "success": True,
            "session_id": request.session_id,
            "feature": request.feature.value,
            "max_duration": request.max_duration
        }
    
    def reject_request(self, request_id: str, reason: str = "主播拒绝了请求") -> Dict:
        """主播拒绝请求"""
        request = next((r for r in self.waiting_queue if r.request_id == request_id), None)
        if not request:
            return {"success": False, "error": "请求不存在"}
        
        self.waiting_queue.remove(request)
        request.status = QueueStatus.CANCELLED
        self.stats["total_cancelled"] += 1
        
        logger.info(f"[VoiceQueueManager] 拒绝请求: {request.username}, 原因: {reason}")
        
        asyncio.create_task(self.emit("request_rejected", {
            "request_id": request_id,
            "username": request.username,
            "reason": reason
        }))
        
        return {"success": True}
    
    def cancel_request(self, request_id: str) -> Dict:
        """用户取消请求"""
        request = next((r for r in self.waiting_queue if r.request_id == request_id), None)
        if not request:
            return {"success": False, "error": "请求不存在"}
        
        self.waiting_queue.remove(request)
        request.status = QueueStatus.CANCELLED
        self.stats["total_cancelled"] += 1
        
        logger.info(f"[VoiceQueueManager] 用户取消: {request.username}")
        
        return {"success": True}
    
    async def _call_timer(self, session_id: str):
        """通话计时器"""
        request = self.active_sessions.get(session_id)
        if not request or request.feature != VoiceFeature.CALL:
            return
        
        await asyncio.sleep(request.max_duration)
        
        # 检查是否还在进行中
        request = self.active_sessions.get(session_id)
        if request and request.status == QueueStatus.ACTIVE:
            logger.info(f"[VoiceQueueManager] 通话超时: {request.username}")
            await self.end_session(session_id, "timeout")
    
    async def end_session(self, session_id: str, reason: str = "completed") -> Dict:
        """结束会话"""
        request = self.active_sessions.get(session_id)
        if not request:
            return {"success": False, "error": "会话不存在"}
        
        request.status = QueueStatus.COMPLETED if reason == "completed" else QueueStatus.CANCELLED
        request.ended_at = datetime.now()
        
        # 移到历史记录
        self.history.insert(0, request)
        if len(self.history) > 50:
            self.history = self.history[:50]
        
        # 从活跃会话移除
        del self.active_sessions[session_id]
        
        if reason == "completed":
            self.stats["total_completed"] += 1
        
        duration = 0
        if request.started_at and request.ended_at:
            duration = int((request.ended_at - request.started_at).total_seconds())
        
        logger.info(f"[VoiceQueueManager] 会话结束: {request.username}, 原因: {reason}, 时长: {duration}s")
        
        asyncio.create_task(self.emit("session_ended", {
            "session_id": session_id,
            "request_id": request.request_id,
            "username": request.username,
            "reason": reason,
            "duration": duration,
            "feature": request.feature.value
        }))
        
        return {"success": True}
    
    def get_queue_status(self, request_id: str = None) -> Dict:
        """获取排队状态"""
        result = {
            "queue_length": len(self.waiting_queue),
            "active_sessions": len(self.active_sessions),
            "config": self.get_config(),
            "waiting_list": [
                {
                    "request_id": r.request_id,
                    "username": r.username,
                    "feature": r.feature.value,
                    "wait_time": r.get_wait_time(),
                    "position": i + 1
                }
                for i, r in enumerate(self.waiting_queue)
            ],
            "active_list": [
                {
                    "session_id": r.session_id,
                    "request_id": r.request_id,
                    "username": r.username,
                    "feature": r.feature.value,
                    "duration": int((datetime.now() - r.started_at).total_seconds()) if r.started_at else 0,
                    "max_duration": r.max_duration
                }
                for r in self.active_sessions.values()
            ]
        }
        
        if request_id:
            request = next((r for r in self.waiting_queue if r.request_id == request_id), None)
            if request:
                result["my_position"] = self.waiting_queue.index(request) + 1
                result["my_wait_time"] = request.get_wait_time()
        
        return result
    
    def get_entry_url(self, base_url: str) -> str:
        """获取固定入口链接"""
        return f"{base_url}{self.config['entry_url_path']}"
    
    async def handle_voice_data(self, session_id: str, audio_data: bytes) -> Dict:
        """处理语音数据"""
        request = self.active_sessions.get(session_id)
        if not request:
            return {"success": False, "error": "会话不存在或已结束"}
        
        request.audio_chunks.append(audio_data)
        
        return {
            "success": True,
            "received_bytes": len(audio_data),
            "feature": request.feature.value
        }
    
    async def finish_voice_input(self, session_id: str) -> Dict:
        """完成语音输入"""
        request = self.active_sessions.get(session_id)
        if not request:
            return {"success": False, "error": "会话不存在或已结束"}
        
        # TODO: STT识别
        transcribed_text = f"这是{request.username}的语音"
        request.transcribed_text = transcribed_text
        
        asyncio.create_task(self.emit("voice_transcribed", {
            "session_id": session_id,
            "request_id": request.request_id,
            "username": request.username,
            "text": transcribed_text,
            "feature": request.feature.value
        }))
        
        # 如果是语音消息模式，自动结束会话
        if request.feature == VoiceFeature.MESSAGE:
            await self.end_session(session_id, "completed")
        
        return {
            "success": True,
            "transcribed_text": transcribed_text
        }


# 单例实例
_queue_manager: Optional[VoiceQueueManager] = None

def init_voice_queue_manager() -> VoiceQueueManager:
    """初始化排队管理器"""
    global _queue_manager
    _queue_manager = VoiceQueueManager()
    return _queue_manager

def get_voice_queue_manager() -> Optional[VoiceQueueManager]:
    """获取排队管理器实例"""
    return _queue_manager
