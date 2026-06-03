"""
抖音直播弹幕抓取模块
支持：弹幕、礼物、进入直播间、点赞等事件
"""

import asyncio
import json
import logging
import re
import time
from typing import Callable, Dict, Optional, Set
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger("douyin_danmaku")


class DanmakuType(Enum):
    CHAT = "chat"           # 普通弹幕
    GIFT = "gift"           # 礼物
    ENTER = "enter"         # 进入直播间
    LIKE = "like"           # 点赞
    FOLLOW = "follow"       # 关注
    SHARE = "share"         # 分享
    ORDER = "order"         # 下单（通过弹幕关键词推断）


@dataclass
class DanmakuEvent:
    """弹幕事件"""
    type: DanmakuType
    username: str
    content: str = ""           # 弹幕内容
    gift_name: str = ""         # 礼物名称
    gift_count: int = 0         # 礼物数量
    gift_value: int = 0         # 礼物价值（抖币）
    user_id: str = ""           # 用户ID
    timestamp: float = 0        # 时间戳
    raw_data: Dict = None       # 原始数据


class DouyinDanmakuCrawler:
    """
    抖音弹幕抓取器
    
    说明：
    - 抖音直播弹幕抓取需要处理签名验证和WebSocket连接
    - 本模块提供基础框架，实际抓取需要根据抖音最新API调整
    - 建议使用第三方库如：douyin-live（pip install）或自行抓包分析
    
    替代方案：
    1. 使用 OBS 浏览器源 + 抖音直播伴侣的弹幕显示
    2. 使用第三方弹幕工具（如：弹幕姬）转发到本地WebSocket
    3. 使用抖音开放平台（需企业认证）的Webhook推送
    """
    
    def __init__(self, room_id: Optional[str] = None):
        self.room_id = room_id
        self.is_running = False
        self._handlers: Dict[DanmakuType, Set[Callable]] = {
            t: set() for t in DanmakuType
        }
        self._last_gift_time: Dict[str, float] = {}  # 礼物去重
        self._user_last_chat: Dict[str, float] = {}  # 用户发言限流
        
    def on(self, event_type: DanmakuType):
        """事件装饰器"""
        def decorator(func: Callable):
            self._handlers[event_type].add(func)
            return func
        return decorator
    
    def off(self, event_type: DanmakuType, func: Callable):
        """移除事件处理器"""
        self._handlers[event_type].discard(func)
    
    async def _emit(self, event: DanmakuEvent):
        """触发事件"""
        handlers = self._handlers.get(event.type, set())
        for handler in handlers:
            try:
                await handler(event)
            except Exception as e:
                logger.error(f"Event handler error: {e}")
    
    async def start(self, room_id: Optional[str] = None):
        """
        开始抓取弹幕
        优先使用真实抓取，失败则降级到模拟模式
        """
        if room_id:
            self.room_id = room_id
        
        self.is_running = True
        
        if self.room_id:
            logger.info(f"Starting danmaku crawler for room: {self.room_id}")
            success = await self._try_real_crawler()
            if success:
                return
            logger.warning("Real crawler failed, falling back to simulation mode")
        else:
            logger.info("No room_id, starting danmaku crawler in simulation mode")
        
        await self._simulate_danmaku()
    
    async def _try_real_crawler(self) -> bool:
        """
        尝试启动真实弹幕抓取
        依次尝试多种抓取方式
        """
        # 方式1：TikTokLive（抖音国际版 / TikTok 直播）
        try:
            from TikTokLive import TikTokLiveClient
            logger.info("[弹幕] 使用 TikTokLive 库抓取（TikTok）")
            await self._run_tiktoklive()
            return True
        except ImportError:
            logger.info("[弹幕] TikTokLive 未安装")
        except Exception as e:
            logger.warning(f"[弹幕] TikTokLive 失败: {e}")
        
        # 方式2：尝试使用 pyDouyinLive 库（抖音国内版）
        try:
            from pyDouyinLive import DouyinLive
            logger.info("[弹幕] 使用 pyDouyinLive 库抓取")
            await self._run_pydouyin_live()
            return True
        except ImportError:
            logger.info("[弹幕] pyDouyinLive 未安装")
        except Exception as e:
            logger.warning(f"[弹幕] pyDouyinLive 失败: {e}")
        
        # 方式3：尝试使用 douyin-live 库
        try:
            from douyin_live import DouyinLiveClient
            logger.info("[弹幕] 使用 douyin-live 库抓取")
            await self._run_douyin_live_client()
            return True
        except ImportError:
            logger.info("[弹幕] douyin-live 未安装")
        except Exception as e:
            logger.warning(f"[弹幕] douyin-live 失败: {e}")
        
        # 方式4：HTTP轮询抓取（抖音直播开放接口）
        try:
            logger.info("[弹幕] 尝试HTTP轮询抓取")
            await self._run_http_polling()
            return True
        except Exception as e:
            logger.warning(f"[弹幕] HTTP轮询失败: {e}")
        
        return False
    
    async def _run_tiktoklive(self):
        """使用 TikTokLive 库抓取弹幕（TikTok/抖音国际版）"""
        from TikTokLive import TikTokLiveClient
        from TikTokLive.events import CommentEvent, GiftEvent, ConnectEvent, DisconnectEvent, FollowEvent, LikeEvent
        
        # room_id 可以是用户名 @username 格式或数字ID
        unique_id = self.room_id
        if not unique_id.startswith("@"):
            unique_id = f"@{unique_id}"
        
        client = TikTokLiveClient(unique_id=unique_id)
        
        @client.on(ConnectEvent)
        async def on_connect(event: ConnectEvent):
            logger.info(f"[TikTokLive] 已连接直播间: {event.unique_id}")
        
        @client.on(DisconnectEvent)
        async def on_disconnect(event: DisconnectEvent):
            logger.warning("[TikTokLive] 连接断开，尝试重连...")
            if self.is_running:
                await asyncio.sleep(5)
                await client.start()
        
        @client.on(CommentEvent)
        async def on_comment(event: CommentEvent):
            if not self.is_running:
                return
            await self._emit(DanmakuEvent(
                type=DanmakuType.CHAT,
                username=event.user.nickname if event.user else "用户",
                content=event.comment,
                user_id=str(event.user.unique_id if event.user else ""),
                timestamp=time.time()
            ))
        
        @client.on(GiftEvent)
        async def on_gift(event: GiftEvent):
            if not self.is_running:
                return
            await self._emit(DanmakuEvent(
                type=DanmakuType.GIFT,
                username=event.user.nickname if event.user else "用户",
                gift_name=event.gift.name if event.gift else "",
                gift_count=event.repeat_count or 1,
                gift_value=event.gift.diamond_count if event.gift else 0,
                user_id=str(event.user.unique_id if event.user else ""),
                timestamp=time.time()
            ))
        
        @client.on(LikeEvent)
        async def on_like(event: LikeEvent):
            if not self.is_running:
                return
            await self._emit(DanmakuEvent(
                type=DanmakuType.LIKE,
                username=event.user.nickname if event.user else "用户",
                user_id=str(event.user.unique_id if event.user else ""),
                timestamp=time.time()
            ))
        
        @client.on(FollowEvent)
        async def on_follow(event: FollowEvent):
            if not self.is_running:
                return
            await self._emit(DanmakuEvent(
                type=DanmakuType.FOLLOW,
                username=event.user.nickname if event.user else "用户",
                user_id=str(event.user.unique_id if event.user else ""),
                timestamp=time.time()
            ))
        
        await client.start()
    
    async def _run_pydouyin_live(self):
        """使用 pyDouyinLive 库抓取弹幕"""
        from pyDouyinLive import DouyinLive
        
        client = DouyinLive(self.room_id)
        
        @client.on("comment")
        async def on_comment(data):
            if not self.is_running:
                return
            event = DanmakuEvent(
                type=DanmakuType.CHAT,
                username=data.get("nickname", "用户"),
                content=data.get("content", ""),
                user_id=str(data.get("user_id", "")),
                timestamp=time.time()
            )
            await self._emit(event)
        
        @client.on("gift")
        async def on_gift(data):
            if not self.is_running:
                return
            event = DanmakuEvent(
                type=DanmakuType.GIFT,
                username=data.get("nickname", "用户"),
                gift_name=data.get("gift_name", ""),
                gift_count=data.get("count", 1),
                gift_value=data.get("diamond_count", 0),
                user_id=str(data.get("user_id", "")),
                timestamp=time.time()
            )
            await self._emit(event)
        
        @client.on("enter_room")
        async def on_enter(data):
            if not self.is_running:
                return
            event = DanmakuEvent(
                type=DanmakuType.ENTER,
                username=data.get("nickname", "用户"),
                user_id=str(data.get("user_id", "")),
                timestamp=time.time()
            )
            await self._emit(event)
        
        @client.on("like")
        async def on_like(data):
            if not self.is_running:
                return
            event = DanmakuEvent(
                type=DanmakuType.LIKE,
                username=data.get("nickname", "用户"),
                user_id=str(data.get("user_id", "")),
                timestamp=time.time()
            )
            await self._emit(event)
        
        await client.start()
    
    async def _run_douyin_live_client(self):
        """使用 douyin-live 库抓取弹幕"""
        from douyin_live import DouyinLiveClient
        
        client = DouyinLiveClient(room_id=self.room_id)
        
        client.on_chat(lambda data: asyncio.create_task(self._emit(DanmakuEvent(
            type=DanmakuType.CHAT,
            username=data.get("user", {}).get("nickname", "用户"),
            content=data.get("content", ""),
            timestamp=time.time()
        ))))
        
        client.on_gift(lambda data: asyncio.create_task(self._emit(DanmakuEvent(
            type=DanmakuType.GIFT,
            username=data.get("user", {}).get("nickname", "用户"),
            gift_name=data.get("gift", {}).get("name", ""),
            gift_count=data.get("count", 1),
            gift_value=data.get("gift", {}).get("diamond_count", 0),
            timestamp=time.time()
        ))))
        
        while self.is_running:
            await client.connect()
            await asyncio.sleep(1)
    
    async def _run_http_polling(self):
        """HTTP轮询方式抓取弹幕（备用方案）"""
        import aiohttp
        
        # 构造抖音直播间API地址
        api_url = f"https://live.douyin.com/webcast/room/enter/?room_id={self.room_id}"
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": f"https://live.douyin.com/{self.room_id}",
        }
        
        seen_ids = set()
        
        async with aiohttp.ClientSession(headers=headers) as session:
            while self.is_running:
                try:
                    async with session.get(api_url) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            messages = data.get("data", {}).get("messages", [])
                            for msg in messages:
                                msg_id = msg.get("msg_id", "")
                                if msg_id in seen_ids:
                                    continue
                                seen_ids.add(msg_id)
                                # 保持seen_ids不过大
                                if len(seen_ids) > 1000:
                                    seen_ids.clear()
                                
                                msg_type = msg.get("msg_type", "")
                                user = msg.get("user", {})
                                username = user.get("nickname", "用户")
                                
                                if msg_type == "chat":
                                    await self._emit(DanmakuEvent(
                                        type=DanmakuType.CHAT,
                                        username=username,
                                        content=msg.get("content", ""),
                                        timestamp=time.time()
                                    ))
                except Exception as e:
                    logger.debug(f"HTTP轮询出错: {e}")
                
                await asyncio.sleep(2)  # 每2秒轮询一次
    
    async def _simulate_danmaku(self):
        """模拟弹幕（用于测试）"""
        test_users = ["小明", "茶友888", "奶茶妹妹", "古风爱好者", "test_user"]
        test_messages = [
            "这茶多少钱？",
            "介绍一下",
            "已拍",
            "好看！",
            "主播好美",
            "怎么买？",
            "小黄车在哪",
            "666",
            "关注主播了",
        ]
        
        test_gifts = [
            ("小心心", 1, 1),
            ("啤酒", 2, 2),
            ("玫瑰花", 5, 5),
            ("墨镜", 10, 10),
            ("嘉年华", 3000, 3000),
        ]
        
        while self.is_running:
            await asyncio.sleep(3)  # 每3秒模拟一个事件
            
            import random
            event_type = random.choices(
                [DanmakuType.CHAT, DanmakuType.GIFT, DanmakuType.ENTER, DanmakuType.LIKE],
                weights=[0.6, 0.1, 0.2, 0.1]
            )[0]
            
            username = random.choice(test_users)
            
            if event_type == DanmakuType.CHAT:
                event = DanmakuEvent(
                    type=DanmakuType.CHAT,
                    username=username,
                    content=random.choice(test_messages),
                    timestamp=time.time()
                )
            elif event_type == DanmakuType.GIFT:
                gift = random.choice(test_gifts)
                event = DanmakuEvent(
                    type=DanmakuType.GIFT,
                    username=username,
                    gift_name=gift[0],
                    gift_count=random.randint(1, 3),
                    gift_value=gift[2],
                    timestamp=time.time()
                )
            elif event_type == DanmakuType.ENTER:
                event = DanmakuEvent(
                    type=DanmakuType.ENTER,
                    username=username,
                    timestamp=time.time()
                )
            else:  # LIKE
                event = DanmakuEvent(
                    type=DanmakuType.LIKE,
                    username=username,
                    timestamp=time.time()
                )
            
            await self._emit(event)
    
    async def stop(self):
        """停止抓取"""
        self.is_running = False
        logger.info("Danmaku crawler stopped")
    
    # ========== 实用方法 ==========
    
    @staticmethod
    def extract_room_id(url: str) -> Optional[str]:
        """从抖音直播间链接提取room_id"""
        # 支持格式：
        # https://live.douyin.com/123456789
        # https://webcast.amemv.com/webcast/reflow/123456789
        patterns = [
            r'live\.douyin\.com/(\d+)',
            r'reflow/(\d+)',
            r'room_id=(\d+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None
    
    @staticmethod
    def is_product_query(text: str) -> bool:
        """判断是否是商品咨询"""
        keywords = ["多少钱", "价格", "怎么卖", "介绍一下", "这个茶", "怎么样", "怎么买", "小黄车"]
        return any(kw in text for kw in keywords)
    
    @staticmethod
    def is_order_placed(text: str) -> bool:
        """判断是否已下单"""
        keywords = ["已拍", "拍了", "下单", "买了", "付款", "订单"]
        return any(kw in text for kw in keywords)


class WebhookReceiver:
    """
    Webhook接收器
    
    接收抖音开放平台或其他第三方平台的Webhook推送
    """
    
    def __init__(self, secret: Optional[str] = None):
        self.secret = secret
        self._handlers: Dict[str, Set[Callable]] = {}
    
    def on(self, event_type: str):
        """注册事件处理器"""
        def decorator(func: Callable):
            if event_type not in self._handlers:
                self._handlers[event_type] = set()
            self._handlers[event_type].add(func)
            return func
        return decorator
    
    async def handle_webhook(self, payload: Dict) -> bool:
        """
        处理Webhook请求
        
        Args:
            payload: Webhook JSON数据
            
        Returns:
            bool: 是否处理成功
        """
        try:
            event_type = payload.get("event_type", "unknown")
            handlers = self._handlers.get(event_type, set())
            
            for handler in handlers:
                try:
                    await handler(payload)
                except Exception as e:
                    logger.error(f"Webhook handler error: {e}")
            
            return True
        except Exception as e:
            logger.error(f"Webhook processing error: {e}")
            return False
    
    def verify_signature(self, payload: str, signature: str) -> bool:
        """验证Webhook签名（抖音开放平台）"""
        if not self.secret:
            return True  # 无secret时不验证
        
        import hmac
        import hashlib
        
        expected = hmac.new(
            self.secret.encode(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(expected, signature)


# ========== 便捷函数 ==========

def create_danmaku_crawler(room_id: Optional[str] = None) -> DouyinDanmakuCrawler:
    """创建弹幕抓取器"""
    return DouyinDanmakuCrawler(room_id)


def create_webhook_receiver(secret: Optional[str] = None) -> WebhookReceiver:
    """创建Webhook接收器"""
    return WebhookReceiver(secret)
