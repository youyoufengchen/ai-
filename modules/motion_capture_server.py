"""
MotionCaptureServer - 实时动捕WebSocket服务器

功能：
1. 接收前端MediaPipe发送的骨骼数据
2. 转发给直播间NPC，实时驱动VRM角色
3. 支持多人同时动捕（主播+助手）

WebSocket端口：8766（与主WebSocket 8765分开）
"""

import asyncio
import json
import logging
from typing import Dict, Set, Optional
from dataclasses import dataclass

try:
    import websockets
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False

logger = logging.getLogger("motion_capture")


@dataclass
class MotionFrame:
    """一帧骨骼数据"""
    skeleton: Dict
    timestamp: int
    source_id: str  # 来源标识（主播ID）


class MotionCaptureServer:
    """
    动捕WebSocket服务器
    
    协议：
    - 前端（主播端）连接 ws://host:8766，发送骨骼数据
    - 直播间订阅骨骼数据，接收后驱动NPC
    """
    
    def __init__(self, host: str = "0.0.0.0", port: int = 8766):
        self.host = host
        self.port = port
        self.server = None
        
        # 连接管理
        self.capture_clients: Set[websockets.WebSocketServerProtocol] = set()  # 动捕发送端
        self.consumer_callbacks: Set[callable] = set()  # 消费端回调（直播间）
        
        # 最新帧缓存（用于新连接立即获取）
        self.latest_frame: Optional[MotionFrame] = None
        
        # 运行状态
        self.is_running = False
        
    async def start(self):
        """启动服务器"""
        if not WEBSOCKETS_AVAILABLE:
            logger.error("websockets库未安装，动捕服务器无法启动")
            logger.info("安装命令: pip install websockets")
            return False
        
        if self.is_running:
            return True
        
        try:
            self.server = await websockets.serve(
                self._handle_connection,
                self.host,
                self.port,
                ping_interval=20,
                ping_timeout=10
            )
            
            self.is_running = True
            logger.info(f"🎥 动捕服务器已启动: ws://{self.host}:{self.port}")
            return True
            
        except Exception as e:
            logger.error(f"动捕服务器启动失败: {e}")
            return False
    
    async def stop(self):
        """停止服务器"""
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        
        # 关闭所有连接
        for client in list(self.capture_clients):
            await client.close()
        
        self.is_running = False
        logger.info("🎥 动捕服务器已停止")
    
    async def _handle_connection(self, websocket, path):
        """处理新连接"""
        client_type = None
        
        try:
            # 等待客户端类型声明
            msg = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            data = json.loads(msg)
            client_type = data.get('type')
            
            if client_type == 'capture':
                # 动捕发送端（主播摄像头）
                await self._handle_capture_client(websocket, data)
            elif client_type == 'consumer':
                # 消费端（直播间）
                await self._handle_consumer_client(websocket, data)
            else:
                logger.warning(f"未知客户端类型: {client_type}")
                await websocket.close(1008, "Unknown client type")
                
        except asyncio.TimeoutError:
            logger.warning("客户端类型声明超时")
            await websocket.close(1008, "Timeout waiting for client type")
        except Exception as e:
            logger.error(f"连接处理错误: {e}")
    
    async def _handle_capture_client(self, websocket, init_data):
        """处理动捕发送端"""
        source_id = init_data.get('source_id', 'default')
        self.capture_clients.add(websocket)
        
        logger.info(f"🎥 动捕客户端连接: {source_id}")
        
        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    
                    if data.get('type') == 'motion_capture':
                        frame = MotionFrame(
                            skeleton=data.get('skeleton', {}),
                            timestamp=data.get('timestamp', 0),
                            source_id=source_id
                        )
                        
                        # 缓存最新帧
                        self.latest_frame = frame
                        
                        # 转发给所有消费端
                        await self._broadcast_to_consumers(frame)
                        
                except json.JSONDecodeError:
                    logger.warning("收到无效的JSON数据")
                    
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.capture_clients.discard(websocket)
            logger.info(f"🎥 动捕客户端断开: {source_id}")
    
    async def _handle_consumer_client(self, websocket, init_data):
        """处理消费端（直播间）"""
        consumer_id = init_data.get('consumer_id', 'unknown')
        
        logger.info(f"👁 消费端连接: {consumer_id}")
        
        # 立即发送最新帧（如果有）
        if self.latest_frame:
            await websocket.send(json.dumps({
                "type": "motion_frame",
                "skeleton": self.latest_frame.skeleton,
                "timestamp": self.latest_frame.timestamp,
                "source_id": self.latest_frame.source_id
            }))
        
        try:
            # 保持连接，接收控制命令（如暂停/恢复）
            async for message in websocket:
                try:
                    data = json.loads(message)
                    cmd = data.get('cmd')
                    
                    if cmd == 'ping':
                        await websocket.send(json.dumps({"type": "pong"}))
                    
                except json.JSONDecodeError:
                    pass
                    
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            logger.info(f"👁 消费端断开: {consumer_id}")
    
    async def _broadcast_to_consumers(self, frame: MotionFrame):
        """广播骨骼数据给所有消费端"""
        if not self.consumer_callbacks:
            return
        
        message = json.dumps({
            "type": "motion_frame",
            "skeleton": frame.skeleton,
            "timestamp": frame.timestamp,
            "source_id": frame.source_id
        })
        
        # 调用所有消费端回调
        for callback in list(self.consumer_callbacks):
            try:
                await callback(frame.skeleton, frame.timestamp, frame.source_id)
            except Exception as e:
                logger.error(f"消费端回调错误: {e}")
    
    def register_consumer(self, callback: callable):
        """注册消费端回调（用于直播间接收骨骼数据）"""
        self.consumer_callbacks.add(callback)
        logger.info(f"👁 消费端已注册，当前数量: {len(self.consumer_callbacks)}")
    
    def unregister_consumer(self, callback: callable):
        """注销消费端回调"""
        self.consumer_callbacks.discard(callback)
        logger.info(f"👁 消费端已注销，当前数量: {len(self.consumer_callbacks)}")
    
    def get_status(self) -> Dict:
        """获取服务器状态"""
        return {
            "running": self.is_running,
            "capture_clients": len(self.capture_clients),
            "consumers": len(self.consumer_callbacks),
            "latest_frame_time": self.latest_frame.timestamp if self.latest_frame else None
        }


# 全局实例
_motion_capture_server: Optional[MotionCaptureServer] = None


def init_motion_capture_server(host: str = "0.0.0.0", port: int = 8766) -> MotionCaptureServer:
    """初始化全局动捕服务器"""
    global _motion_capture_server
    if _motion_capture_server is None:
        _motion_capture_server = MotionCaptureServer(host, port)
    return _motion_capture_server


def get_motion_capture_server() -> Optional[MotionCaptureServer]:
    """获取全局动捕服务器实例"""
    return _motion_capture_server
