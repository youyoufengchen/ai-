"""
语音通话管理器
支持实时通话和语音消息两种模式
包含戏剧性挂断场景管理
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

class VoiceMode(Enum):
    """语音模式"""
    MESSAGE = "message"      # 语音消息（微信式）
    CALL = "call"            # 实时通话（电话式）

class CallStatus(Enum):
    """通话状态"""
    IDLE = "idle"
    CONNECTING = "connecting"
    TALKING = "talking"
    ENDING = "ending"        # 正在找借口挂断
    ENDED = "ended"

@dataclass
class VoiceSession:
    """语音会话"""
    session_id: str
    user_id: str
    username: str
    mode: VoiceMode
    created_at: datetime
    expires_at: datetime
    call_status: CallStatus = CallStatus.IDLE
    
    # 实时通话专用
    max_duration: int = 60                 # 最大通话时长（秒）
    current_duration: int = 0              # 当前已通话时长
    
    # 音频数据
    audio_chunks: List[bytes] = field(default_factory=list)
    transcribed_text: str = ""
    
    # 挂断借口场景
    ending_scene: Optional[Dict] = None
    
    def is_expired(self) -> bool:
        return datetime.now() > self.expires_at


# ========== 戏剧性挂断场景库 ==========
EMERGENCY_SCENES = [
    {
        "id": "mouse_appears",
        "name": "老鼠出现",
        "emoji": "🐭",
        "excuses": [
            "哎呀，那边好像有只老鼠，我去看看！",
            "等等，我听到奇怪的声音，先失陪一下！",
            "抱歉，好像有只小动物跑进来了，我得处理一下！"
        ],
        "actions": ["look_surprised", "run_to_corner", "chase_mouse"],
        "priority": "high"
    },
    {
        "id": "shelf_fire",
        "name": "货架起火",
        "emoji": "🔥",
        "excuses": [
            "糟糕，货架那边好像有烟雾，我去检查一下！",
            "等等，有紧急情况需要处理，先挂一下！",
            "抱歉，好像有点状况，我马上回来！"
        ],
        "actions": ["look_concerned", "run_to_shelf", "extinguish_fire"],
        "priority": "critical"
    },
    {
        "id": "delivery_arrived",
        "name": "快递敲门",
        "emoji": "🚪",
        "excuses": [
            "有人敲门，可能是快递到了，我去开一下门！",
            "稍等，外面好像有人找我！",
            "抱歉，有客人来了，我马上回来！"
        ],
        "actions": ["look_away", "walk_to_door", "open_door"],
        "priority": "normal"
    },
    {
        "id": "phone_ringing",
        "name": "电话响起",
        "emoji": "📞",
        "excuses": [
            "等等，我的电话响了，可能是有急事！",
            "抱歉，我需要接个电话！",
            "有个重要电话进来，我先接一下！"
        ],
        "actions": ["look_at_phone", "pick_up_phone", "answer_call"],
        "priority": "normal"
    },
    {
        "id": "baby_crying",
        "name": "小孩哭闹",
        "emoji": "👶",
        "excuses": [
            "好像听到小朋友在哭，我去看看！",
            "等等，需要照顾一下宝宝！",
            "抱歉，家里有状况，我马上处理！"
        ],
        "actions": ["look_concerned", "walk_away", "comfort_baby"],
        "priority": "high"
    },
    {
        "id": "alarm_clock",
        "name": "闹钟响起",
        "emoji": "⏰",
        "excuses": [
            "哎呀，闹钟响了，我有个预约要处理！",
            "等等，提醒我该做某件事了！",
            "抱歉，时间到了，我需要去处理一些事情！"
        ],
        "actions": ["look_at_clock", "turn_off_alarm", "prepare_leave"],
        "priority": "normal"
    },
    {
        "id": "pet_mess",
        "name": "宠物捣乱",
        "emoji": "🐕",
        "excuses": [
            "哎呀，小猫/小狗又在捣乱了！",
            "等等，宠物好像打翻了什么东西！",
            "抱歉，我得去照顾一下毛孩子！"
        ],
        "actions": ["look_surprised", "run_to_pet", "clean_mess"],
        "priority": "normal"
    },
    {
        "id": "water_leak",
        "name": "水管漏水",
        "emoji": "💧",
        "excuses": [
            "等等，我听到水声，好像哪里漏水了！",
            "糟糕，可能是水管出了问题！",
            "抱歉，需要去检查一下水源！"
        ],
        "actions": ["listen_carefully", "find_leak", "fix_pipe"],
        "priority": "high"
    }
]


class VoiceChatManager:
    """语音通话管理器"""
    
    def __init__(self):
        self.sessions: Dict[str, VoiceSession] = {}
        self.active_calls: Dict[str, VoiceSession] = {}  # 实时通话中的会话
        self.event_handlers: List[Callable] = []
        self._cleanup_task = None
        self._call_monitor_task = None
        
    def start(self):
        """启动管理器"""
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        self._call_monitor_task = asyncio.create_task(self._call_monitor_loop())
        logger.info("[VoiceChatManager] 已启动")
    
    def stop(self):
        """停止管理器"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
        if self._call_monitor_task:
            self._call_monitor_task.cancel()
        logger.info("[VoiceChatManager] 已停止")
    
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
                logger.error(f"[VoiceChatManager] 事件处理错误: {e}")
    
    def create_session(
        self, 
        user_id: str, 
        username: str, 
        mode: VoiceMode = VoiceMode.MESSAGE,
        max_duration: int = 60
    ) -> str:
        """创建语音会话"""
        session_id = str(uuid.uuid4())[:8]
        now = datetime.now()
        
        session = VoiceSession(
            session_id=session_id,
            user_id=user_id,
            username=username,
            mode=mode,
            created_at=now,
            expires_at=now + timedelta(minutes=10),  # 会话10分钟过期
            max_duration=max_duration,
            call_status=CallStatus.IDLE if mode == VoiceMode.MESSAGE else CallStatus.CONNECTING
        )
        
        self.sessions[session_id] = session
        
        if mode == VoiceMode.CALL:
            self.active_calls[session_id] = session
            # 启动通话计时
            asyncio.create_task(self._call_timer(session_id))
        
        logger.info(f"[VoiceChatManager] 创建会话: {session_id} (模式: {mode.value}, 用户: {username})")
        return session_id
    
    def get_session(self, session_id: str) -> Optional[VoiceSession]:
        """获取会话"""
        session = self.sessions.get(session_id)
        if session and session.is_expired():
            self._end_session(session_id)
            return None
        return session
    
    async def start_call(self, session_id: str):
        """开始实时通话"""
        session = self.get_session(session_id)
        if not session or session.mode != VoiceMode.CALL:
            return False
        
        session.call_status = CallStatus.TALKING
        await self.emit("call_started", {
            "session_id": session_id,
            "username": session.username,
            "max_duration": session.max_duration
        })
        
        logger.info(f"[VoiceChatManager] 通话开始: {session_id}")
        return True
    
    async def end_call(self, session_id: str, reason: str = "user"):
        """结束通话"""
        await self._end_call_internal(session_id, reason)
    
    async def _call_timer(self, session_id: str):
        """通话计时器，超时后触发戏剧性挂断"""
        session = self.get_session(session_id)
        if not session:
            return
        
        await asyncio.sleep(session.max_duration)
        
        # 检查会话是否还在通话中
        session = self.get_session(session_id)
        if session and session.call_status == CallStatus.TALKING:
            logger.info(f"[VoiceChatManager] 通话超时: {session_id}，触发戏剧性挂断")
            await self._trigger_drama_end(session_id)
    
    async def _trigger_drama_end(self, session_id: str):
        """触发戏剧性挂断场景"""
        session = self.get_session(session_id)
        if not session:
            return
        
        session.call_status = CallStatus.ENDING
        
        # 随机选择一个挂断借口场景
        import random
        ending_scene = random.choice(EMERGENCY_SCENES)
        session.ending_scene = ending_scene
        
        # 随机选择一句借口
        excuse = random.choice(ending_scene["excuses"])
        
        logger.info(f"[VoiceChatManager] 戏剧性挂断: {ending_scene['name']} - {excuse}")
        
        # 触发事件，通知NPC执行
        await self.emit("call_ending_drama", {
            "session_id": session_id,
            "username": session.username,
            "scene": ending_scene,
            "excuse": excuse,
            "actions": ending_scene["actions"],
            "countdown": 10  # 10秒后真正挂断
        })
        
        # 等待NPC表演完成
        await asyncio.sleep(10)
        
        # 真正挂断
        await self._end_call_internal(session_id, "timeout_drama")
    
    async def _end_call_internal(self, session_id: str, reason: str):
        """内部结束通话"""
        session = self.get_session(session_id)
        if not session:
            return
        
        session.call_status = CallStatus.ENDED
        
        if session_id in self.active_calls:
            del self.active_calls[session_id]
        
        await self.emit("call_ended", {
            "session_id": session_id,
            "username": session.username,
            "reason": reason,
            "duration": session.current_duration,
            "ending_scene": session.ending_scene
        })
        
        logger.info(f"[VoiceChatManager] 通话结束: {session_id} (原因: {reason})")
    
    def _end_session(self, session_id: str):
        """结束会话"""
        if session_id in self.sessions:
            session = self.sessions[session_id]
            if session.mode == VoiceMode.CALL and session_id in self.active_calls:
                del self.active_calls[session_id]
            del self.sessions[session_id]
            logger.info(f"[VoiceChatManager] 会话过期清理: {session_id}")
    
    async def _cleanup_loop(self):
        """清理过期会话的循环"""
        while True:
            try:
                await asyncio.sleep(60)  # 每分钟检查一次
                expired = [
                    sid for sid, s in self.sessions.items() 
                    if s.is_expired()
                ]
                for sid in expired:
                    self._end_session(sid)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[VoiceChatManager] 清理循环错误: {e}")
    
    async def _call_monitor_loop(self):
        """监控通话状态的循环"""
        while True:
            try:
                await asyncio.sleep(1)
                for session in list(self.active_calls.values()):
                    if session.call_status == CallStatus.TALKING:
                        session.current_duration += 1
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[VoiceChatManager] 监控循环错误: {e}")
    
    async def handle_voice_data(self, session_id: str, audio_data: bytes) -> Dict:
        """处理语音数据"""
        session = self.get_session(session_id)
        if not session:
            return {"success": False, "error": "会话不存在或已过期"}
        
        session.audio_chunks.append(audio_data)
        
        return {
            "success": True,
            "session_id": session_id,
            "received_bytes": len(audio_data),
            "mode": session.mode.value,
            "status": session.call_status.value if session.mode == VoiceMode.CALL else "recording"
        }
    
    async def finish_voice_input(self, session_id: str) -> Dict:
        """完成语音输入，进行识别"""
        session = self.get_session(session_id)
        if not session:
            return {"success": False, "error": "会话不存在或已过期"}
        
        # TODO: 调用STT服务识别完整音频
        # 模拟识别结果
        transcribed_text = f"这是{session.username}的语音输入"
        session.transcribed_text = transcribed_text
        
        await self.emit("voice_transcribed", {
            "session_id": session_id,
            "username": session.username,
            "text": transcribed_text,
            "mode": session.mode.value
        })
        
        # 如果是消息模式，结束会话
        if session.mode == VoiceMode.MESSAGE:
            self._end_session(session_id)
        
        return {
            "success": True,
            "session_id": session_id,
            "transcribed_text": transcribed_text,
            "username": session.username
        }
    
    def get_active_calls(self) -> List[Dict]:
        """获取所有进行中的通话"""
        return [
            {
                "session_id": s.session_id,
                "username": s.username,
                "duration": s.current_duration,
                "max_duration": s.max_duration,
                "remaining": s.max_duration - s.current_duration
            }
            for s in self.active_calls.values()
            if s.call_status == CallStatus.TALKING
        ]
    
    def get_available_scenes(self) -> List[Dict]:
        """获取所有可用的戏剧性场景"""
        return [
            {
                "id": s["id"],
                "name": s["name"],
                "emoji": s["emoji"],
                "priority": s["priority"],
                "excuse_count": len(s["excuses"])
            }
            for s in EMERGENCY_SCENES
        ]


# 单例实例
_voice_manager: Optional[VoiceChatManager] = None

def init_voice_manager() -> VoiceChatManager:
    """初始化语音管理器"""
    global _voice_manager
    _voice_manager = VoiceChatManager()
    _voice_manager.start()
    return _voice_manager

def get_voice_manager() -> Optional[VoiceChatManager]:
    """获取语音管理器实例"""
    return _voice_manager
