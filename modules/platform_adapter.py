"""
多直播平台统一适配器
支持抖音、视频号、小红书、淘宝、快手、火山等平台的事件接入
"""
import asyncio
import hashlib
import hmac
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Callable, Any

logger = logging.getLogger(__name__)

@dataclass
class LiveEvent:
    """统一直播事件格式"""
    platform: str  # douyin, wechat, xiaohongshu, taobao, kuaishou, huoshan
    event_type: str  # chat, gift, enter, like, order, follow, share
    user_id: str
    username: str
    content: str = ""  # 弹幕内容/礼物名称等
    amount: int = 0  # 数量（点赞数/礼物数量等）
    price: float = 0.0  # 金额（礼物价值/订单金额）
    sku_id: str = ""  # 商品ID（下单事件）
    timestamp: datetime = field(default_factory=datetime.now)
    raw_data: Dict = field(default_factory=dict)  # 原始平台数据


class BasePlatformAdapter(ABC):
    """平台适配器基类"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.enabled = config.get("enabled", False)
        self.event_handlers: List[Callable[[LiveEvent], None]] = []
    
    def on_event(self, handler: Callable[[LiveEvent], None]):
        """注册事件处理器"""
        self.event_handlers.append(handler)
    
    async def emit(self, event: LiveEvent):
        """触发事件"""
        for handler in self.event_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception as e:
                logger.error(f"Event handler error: {e}")
    
    @abstractmethod
    async def validate_webhook(self, request) -> bool:
        """验证webhook请求合法性"""
        pass
    
    @abstractmethod
    async def parse_event(self, data: Dict) -> Optional[LiveEvent]:
        """解析平台特定格式为统一事件"""
        pass


class DouyinAdapter(BasePlatformAdapter):
    """抖音适配器"""
    
    async def validate_webhook(self, request) -> bool:
        """验证抖音webhook签名"""
        # 抖音开放平台签名验证
        secret = self.config.get("webhook_secret", "")
        if not secret:
            return True  # 未配置密钥则不验证
        
        signature = request.headers.get("X-Douyin-Signature", "")
        body = await request.text()
        expected = hmac.new(
            secret.encode(),
            body.encode(),
            hashlib.sha256
        ).hexdigest()
        return signature == expected
    
    async def parse_event(self, data: Dict) -> Optional[LiveEvent]:
        """解析抖音事件"""
        event_type_map = {
            "live.chat": "chat",
            "live.gift": "gift",
            "live.enter": "enter",
            "live.like": "like",
            "live.follow": "follow",
            "order.placed": "order",
        }
        
        raw_type = data.get("event_type", "")
        event_type = event_type_map.get(raw_type, "unknown")
        
        if event_type == "unknown":
            return None
        
        user = data.get("user", {})
        
        return LiveEvent(
            platform="douyin",
            event_type=event_type,
            user_id=user.get("id", ""),
            username=user.get("nickname", "神秘客官"),
            content=data.get("content", ""),
            amount=data.get("amount", 0),
            price=data.get("price", 0.0),
            sku_id=data.get("sku_id", ""),
            raw_data=data
        )


class WechatChannelAdapter(BasePlatformAdapter):
    """微信视频号适配器"""
    
    async def validate_webhook(self, request) -> bool:
        """验证视频号webhook"""
        token = self.config.get("token", "")
        if not token:
            return True
        
        signature = request.headers.get("X-Wechat-Signature", "")
        timestamp = request.headers.get("X-Wechat-Timestamp", "")
        nonce = request.headers.get("X-Wechat-Nonce", "")
        
        # 微信签名算法
        params = [token, timestamp, nonce]
        params.sort()
        expected = hashlib.sha1("".join(params).encode()).hexdigest()
        return signature == expected
    
    async def parse_event(self, data: Dict) -> Optional[LiveEvent]:
        """解析视频号事件"""
        # 视频号事件格式参考：https://developers.weixin.qq.com/
        event_type_map = {
            "TEXT": "chat",
            "GIFT": "gift",
            "ENTER": "enter",
            "LIKE": "like",
            "FOLLOW": "follow",
            "ORDER": "order",
        }
        
        raw_type = data.get("MsgType", data.get("event", ""))
        event_type = event_type_map.get(raw_type, "unknown")
        
        if event_type == "unknown":
            return None
        
        return LiveEvent(
            platform="wechat",
            event_type=event_type,
            user_id=data.get("FromUserName", ""),
            username=data.get("nickname", "微信用户"),
            content=data.get("Content", ""),
            amount=data.get("like_count", 0),
            price=data.get("total_amount", 0.0) / 100,  # 视频号金额单位为分
            sku_id=data.get("sku_id", ""),
            raw_data=data
        )


class XiaohongshuAdapter(BasePlatformAdapter):
    """小红书适配器"""
    
    async def validate_webhook(self, request) -> bool:
        """验证小红书webhook"""
        # 小红书需要HTTPS + 特定认证
        api_key = self.config.get("api_key", "")
        signature = request.headers.get("X-Red-Signature", "")
        return signature == api_key  # 简化验证
    
    async def parse_event(self, data: Dict) -> Optional[LiveEvent]:
        """解析小红书事件"""
        event_type = data.get("event_type", "").lower()
        
        type_map = {
            "comment": "chat",
            "gift": "gift",
            "enter_room": "enter",
            "like": "like",
            "follow": "follow",
            "order": "order",
        }
        
        event_type = type_map.get(event_type, event_type)
        
        return LiveEvent(
            platform="xiaohongshu",
            event_type=event_type,
            user_id=data.get("user_id", ""),
            username=data.get("nickname", "小红书用户"),
            content=data.get("content", data.get("gift_name", "")),
            amount=data.get("count", 1),
            price=data.get("price", 0.0),
            raw_data=data
        )


class TaobaoAdapter(BasePlatformAdapter):
    """淘宝直播适配器"""
    
    async def validate_webhook(self, request) -> bool:
        """验证淘宝千牛/开放平台webhook"""
        app_secret = self.config.get("app_secret", "")
        if not app_secret:
            return True
        
        # 淘宝TOP签名验证
        sign = request.headers.get("X-Taobao-Sign", "")
        body = await request.text()
        expected = hashlib.md5(f"{body}{app_secret}".encode()).hexdigest()
        return sign == expected
    
    async def parse_event(self, data: Dict) -> Optional[LiveEvent]:
        """解析淘宝直播事件"""
        event_type = data.get("event", "").lower()
        
        type_map = {
            "comment": "chat",
            "present": "gift",  # 淘宝礼物叫present
            "enter": "enter",
            "like": "like",
            "follow": "follow",
            "trade": "order",  # 订单
        }
        
        event_type = type_map.get(event_type, event_type)
        
        return LiveEvent(
            platform="taobao",
            event_type=event_type,
            user_id=data.get("buyer_id", data.get("user_id", "")),
            username=data.get("buyer_nick", data.get("nick", "淘宝用户")),
            content=data.get("content", ""),
            amount=data.get("num", 1),
            price=data.get("total_fee", 0.0),
            sku_id=data.get("auction_id", ""),
            raw_data=data
        )


class KuaishouAdapter(BasePlatformAdapter):
    """快手适配器"""
    
    async def validate_webhook(self, request) -> bool:
        """验证快手webhook"""
        secret = self.config.get("secret", "")
        if not secret:
            return True
        
        sign = request.headers.get("X-Kuaishou-Sign", "")
        body = await request.text()
        expected = hmac.new(
            secret.encode(),
            body.encode(),
            hashlib.sha256
        ).hexdigest()
        return sign == expected
    
    async def parse_event(self, data: Dict) -> Optional[LiveEvent]:
        """解析快手直播事件"""
        # 快手开放平台格式
        event_type = data.get("type", "").lower()
        
        type_map = {
            "comment": "chat",
            "gift": "gift",
            "enter_room": "enter",
            "like": "like",
            "follow": "follow",
            "buy": "order",
        }
        
        event_type = type_map.get(event_type, event_type)
        
        user = data.get("user", {})
        gift = data.get("gift", {})
        
        return LiveEvent(
            platform="kuaishou",
            event_type=event_type,
            user_id=str(user.get("id", "")),
            username=user.get("name", "快手用户"),
            content=data.get("content", gift.get("name", "")),
            amount=gift.get("count", 1),
            price=gift.get("value", 0.0),
            raw_data=data
        )


class HuoshanAdapter(BasePlatformAdapter):
    """火山引擎/抖音火山版适配器"""
    
    async def validate_webhook(self, request) -> bool:
        """验证火山webhook（同抖音体系）"""
        return await DouyinAdapter(self.config).validate_webhook(request)
    
    async def parse_event(self, data: Dict) -> Optional[LiveEvent]:
        """解析火山事件（同抖音）"""
        event = await DouyinAdapter(self.config).parse_event(data)
        if event:
            event.platform = "huoshan"
        return event


class PlatformManager:
    """平台管理器 - 统一管理所有直播平台接入"""
    
    def __init__(self, config: Dict[str, Dict]):
        self.config = config
        self.adapters: Dict[str, BasePlatformAdapter] = {}
        self._init_adapters()
    
    def _init_adapters(self):
        """初始化所有启用的平台适配器"""
        adapter_classes = {
            "douyin": DouyinAdapter,
            "wechat": WechatChannelAdapter,
            "xiaohongshu": XiaohongshuAdapter,
            "taobao": TaobaoAdapter,
            "kuaishou": KuaishouAdapter,
            "huoshan": HuoshanAdapter,
        }
        
        for platform, cfg in self.config.items():
            if cfg.get("enabled", False) and platform in adapter_classes:
                self.adapters[platform] = adapter_classes[platform](cfg)
                logger.info(f"Platform adapter initialized: {platform}")
    
    def get_adapter(self, platform: str) -> Optional[BasePlatformAdapter]:
        """获取指定平台的适配器"""
        return self.adapters.get(platform)
    
    def on_event(self, handler: Callable[[LiveEvent], None]):
        """注册全局事件处理器（所有平台）"""
        for adapter in self.adapters.values():
            adapter.on_event(handler)
    
    async def handle_webhook(self, platform: str, request) -> Dict:
        """处理webhook请求"""
        adapter = self.adapters.get(platform)
        if not adapter:
            return {"ok": False, "error": f"Unknown platform: {platform}"}
        
        # 验证请求
        if not await adapter.validate_webhook(request):
            return {"ok": False, "error": "Invalid signature"}
        
        try:
            data = await request.json()
            event = await adapter.parse_event(data)
            
            if event:
                await adapter.emit(event)
                return {"ok": True, "event": event.event_type}
            else:
                return {"ok": True, "message": "Event ignored"}
                
        except Exception as e:
            logger.error(f"Webhook handle error: {e}")
            return {"ok": False, "error": str(e)}


# 单例模式
_platform_manager: Optional[PlatformManager] = None

def init_platform_manager(config: Dict[str, Dict]):
    """初始化平台管理器"""
    global _platform_manager
    _platform_manager = PlatformManager(config)
    return _platform_manager

def get_platform_manager() -> Optional[PlatformManager]:
    """获取平台管理器实例"""
    return _platform_manager
