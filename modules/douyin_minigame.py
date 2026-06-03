"""
抖音直播玩法（小程序）对接模块
用于实现观众语音互动功能
"""
import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timedelta
from typing import Dict, Optional, Callable, List
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

@dataclass
class VoiceSession:
    """语音会话"""
    session_id: str
    user_id: str
    username: str
    created_at: datetime
    expires_at: datetime
    status: str = "active"  # active, processing, completed, expired
    audio_chunks: List[bytes] = field(default_factory=list)
    transcribed_text: str = ""
    
    def is_expired(self) -> bool:
        return datetime.now() > self.expires_at


class DouyinMiniGameAdapter:
    """抖音直播玩法适配器"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.enabled = config.get("enabled", False)
        self.app_id = config.get("app_id", "")
        self.app_secret = config.get("app_secret", "")
        self.access_token = config.get("access_token", "")
        self.session_ttl = config.get("voice_session_ttl", 300)  # 5分钟
        
        # 会话管理
        self.sessions: Dict[str, VoiceSession] = {}
        self.event_handlers: List[Callable] = []
        
        # STT服务（可通过 set_stt_service 注入）
        self.stt_service = None
        
        logger.info(f"[DouyinMiniGame] 适配器初始化，enabled={self.enabled}")
    
    def set_stt_service(self, stt_service):
        """注入STT语音识别服务实例"""
        self.stt_service = stt_service
        logger.info("[DouyinMiniGame] STT服务已集成")
    
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
                logger.error(f"[DouyinMiniGame] 事件处理错误: {e}")
    
    def create_voice_session(self, user_id: str, username: str) -> str:
        """创建语音会话，返回session_id"""
        session_id = str(uuid.uuid4())[:8]  # 短ID便于播报
        now = datetime.now()
        
        session = VoiceSession(
            session_id=session_id,
            user_id=user_id,
            username=username,
            created_at=now,
            expires_at=now + timedelta(seconds=self.session_ttl),
            status="active"
        )
        
        self.sessions[session_id] = session
        
        # 清理过期会话
        self._cleanup_expired_sessions()
        
        logger.info(f"[DouyinMiniGame] 创建语音会话: {session_id} (用户: {username})")
        return session_id
    
    def get_session(self, session_id: str) -> Optional[VoiceSession]:
        """获取会话信息"""
        session = self.sessions.get(session_id)
        if session and session.is_expired():
            session.status = "expired"
            return None
        return session
    
    def _cleanup_expired_sessions(self):
        """清理过期会话"""
        expired = [
            sid for sid, s in self.sessions.items() 
            if s.is_expired()
        ]
        for sid in expired:
            del self.sessions[sid]
            logger.info(f"[DouyinMiniGame] 清理过期会话: {sid}")
    
    async def handle_voice_data(self, session_id: str, audio_data: bytes) -> Dict:
        """处理语音数据（流式接收片段，累积到会话缓冲区）"""
        session = self.get_session(session_id)
        if not session:
            return {"success": False, "error": "会话不存在或已过期"}
        
        # 保存音频片段到会话缓冲区
        session.audio_chunks.append(audio_data)
        session.status = "processing"
        
        logger.info(
            f"[DouyinMiniGame] 接收语音数据: {session_id}, "
            f"{len(audio_data)} bytes（总计{sum(len(c) for c in session.audio_chunks)} bytes）"
        )
        
        return {
            "success": True,
            "session_id": session_id,
            "received_bytes": len(audio_data),
            "total_bytes": sum(len(c) for c in session.audio_chunks),
            "status": "received"
        }
    
    async def finish_voice_input(self, session_id: str) -> Dict:
        """完成语音输入，调用STT识别完整音频"""
        session = self.get_session(session_id)
        if not session:
            return {"success": False, "error": "会话不存在或已过期"}
        
        if not session.audio_chunks:
            return {"success": False, "error": "未接收到任何音频数据"}
        
        # 调用STT识别完整音频
        transcribed_text = ""
        if self.stt_service is not None:
            try:
                # 拼接所有音频片段
                import base64
                full_audio = b"".join(session.audio_chunks)
                audio_b64 = base64.b64encode(full_audio).decode("utf-8")
                
                # 调用STT转录
                transcribed_text = await self.stt_service.transcribe(audio_b64, language="zh")
                if not transcribed_text:
                    transcribed_text = ""
                logger.info(f"[DouyinMiniGame] STT识别成功: {session_id} -> {transcribed_text}")
            except Exception as e:
                logger.error(f"[DouyinMiniGame] STT识别失败: {e}", exc_info=True)
                transcribed_text = ""
        else:
            logger.warning(
                f"[DouyinMiniGame] STT服务未集成，返回空结果. "
                f"请调用 set_stt_service() 注入STT实例"
            )
        
        session.transcribed_text = transcribed_text
        session.status = "completed"
        
        logger.info(f"[DouyinMiniGame] 语音识别完成: {session_id} -> {transcribed_text}")
        
        # 触发事件
        await self.emit("voice_transcribed", {
            "session_id": session_id,
            "username": session.username,
            "user_id": session.user_id,
            "text": transcribed_text,
            "timestamp": datetime.now().isoformat()
        })
        
        return {
            "success": True,
            "session_id": session_id,
            "transcribed_text": transcribed_text,
            "username": session.username
        }
    
    def get_voice_link(self, session_id: str, base_url: str) -> str:
        """生成语音页面链接"""
        return f"{base_url}/voice/{session_id}"
    
    async def handle_minigame_event(self, event_data: Dict) -> Dict:
        """处理直播玩法事件"""
        event_type = event_data.get("event")
        
        handlers = {
            "voice_start": self._handle_voice_start,
            "voice_data": self._handle_voice_data,
            "voice_end": self._handle_voice_end,
            "barrage": self._handle_barrage,
            "gift": self._handle_gift,
        }
        
        handler = handlers.get(event_type)
        if handler:
            return await handler(event_data)
        
        return {"success": False, "error": f"未知事件类型: {event_type}"}
    
    async def _handle_voice_start(self, data: Dict) -> Dict:
        """处理开始语音事件"""
        user_id = data.get("user_id", "")
        username = data.get("username", "未知用户")
        
        session_id = self.create_voice_session(user_id, username)
        
        return {
            "success": True,
            "session_id": session_id,
            "expires_in": self.session_ttl,
            "message": "可以开始说话"
        }
    
    async def _handle_voice_data(self, data: Dict) -> Dict:
        """处理语音数据片段"""
        session_id = data.get("session_id", "")
        audio_base64 = data.get("audio", "")
        
        if not audio_base64:
            return {"success": False, "error": "缺少音频数据"}
        
        import base64
        audio_data = base64.b64decode(audio_base64)
        
        return await self.handle_voice_data(session_id, audio_data)
    
    async def _handle_voice_end(self, data: Dict) -> Dict:
        """处理结束语音事件"""
        session_id = data.get("session_id", "")
        return await self.finish_voice_input(session_id)
    
    async def _handle_barrage(self, data: Dict) -> Dict:
        """处理弹幕事件"""
        await self.emit("chat", {
            "username": data.get("username", ""),
            "content": data.get("content", ""),
            "timestamp": datetime.now().isoformat()
        })
        return {"success": True}
    
    async def _handle_gift(self, data: Dict) -> Dict:
        """处理礼物事件"""
        await self.emit("gift", {
            "username": data.get("username", ""),
            "gift_name": data.get("gift_name", ""),
            "amount": data.get("amount", 1),
            "timestamp": datetime.now().isoformat()
        })
        return {"success": True}


# 单例实例
_minigame_adapter: Optional[DouyinMiniGameAdapter] = None

def init_minigame_adapter(config: Dict) -> DouyinMiniGameAdapter:
    """初始化直播玩法适配器"""
    global _minigame_adapter
    _minigame_adapter = DouyinMiniGameAdapter(config)
    return _minigame_adapter

def get_minigame_adapter() -> Optional[DouyinMiniGameAdapter]:
    """获取适配器实例"""
    return _minigame_adapter
