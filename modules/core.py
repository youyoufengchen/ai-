"""
核心数据类型：枚举、事件、队列管理、弹窗管理、WebSocket Hub
"""

import asyncio
import json
import logging
import time
import heapq
import datetime
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Set

from websockets.server import WebSocketServerProtocol

logger = logging.getLogger("server")

# ============== 状态枚举 ==============
class HostState(Enum):
    IDLE = auto()
    WAITING = auto()
    PLAYING = auto()
    SPEAKING = auto()
    PROCESSING = auto()


class EventPriority(Enum):
    ORDER_PLACED    = 1
    GIFT_BIG        = 2
    URGENT_QUESTION = 3
    PRODUCT_QUERY   = 4
    STYLE_SWITCH    = 5
    GIFT_SMALL      = 6
    GENERAL_CHAT    = 7
    USER_ENTER      = 8
    LIKE_RECEIVED   = 9


PRIORITY_MAP = {
    "order_placed":     EventPriority.ORDER_PLACED,
    "gift_big":         EventPriority.GIFT_BIG,
    "urgent_question":  EventPriority.URGENT_QUESTION,
    "product_query":    EventPriority.PRODUCT_QUERY,
    "style_switch":     EventPriority.STYLE_SWITCH,
    "gift_small":       EventPriority.GIFT_SMALL,
    "general_chat":     EventPriority.GENERAL_CHAT,
    "user_enter":       EventPriority.USER_ENTER,
    "like_received":    EventPriority.LIKE_RECEIVED,
}


@dataclass
class Event:
    priority: EventPriority
    intent: str
    data: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    event_id: str = field(default_factory=lambda: str(time.time()))

    def __lt__(self, other):
        if self.priority.value != other.priority.value:
            return self.priority.value < other.priority.value
        return self.timestamp < other.timestamp


@dataclass
class PopupWindow:
    id: str
    type: str
    content: Dict[str, Any]
    duration_ms: int
    priority: int
    created_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + 8)


# ============== 事件队列管理器 ==============
class EventQueueManager:
    def __init__(self, cfg: Dict[str, Any]):
        self.queue: List[Event] = []
        rate = cfg.get("rate_limit", {})
        self.max_size = rate.get("queue_max_size", 50)
        self.ai_calls_per_minute = rate.get("ai_calls_per_minute", 30)
        self.low_priority_per_minute = rate.get("low_priority_per_minute", 5)
        self.stats = {
            "total_received": 0,
            "total_processed": 0,
            "dropped": 0,
            "ai_calls_this_minute": 0,
            "low_priority_this_minute": 0,
            "last_minute_reset": time.time(),
        }
        self._lock = asyncio.Lock()
        self.recent_events: list = []

    async def submit(self, intent: str, data: Dict[str, Any],
                     priority: Optional[EventPriority] = None) -> bool:
        async with self._lock:
            self._reset_counters_if_needed()
            if priority is None:
                priority = PRIORITY_MAP.get(intent, EventPriority.GENERAL_CHAT)
            elif isinstance(priority, int):
                priority = EventPriority(priority)
            if len(self.queue) >= self.max_size:
                if priority.value > 4:
                    self.stats["dropped"] += 1
                    logger.warning(f"Queue full, dropped: {intent}")
                    return False
            if priority.value >= 7:
                if self.stats["low_priority_this_minute"] >= self.low_priority_per_minute:
                    self.stats["dropped"] += 1
                    logger.warning(f"Rate limit, dropped: {intent}")
                    return False
                self.stats["low_priority_this_minute"] += 1
            event = Event(priority=priority, intent=intent, data=data)
            heapq.heappush(self.queue, event)
            self.stats["total_received"] += 1
            self.recent_events.append({
                "event_id": event.event_id,
                "intent": intent,
                "priority": priority.value,
                "username": data.get("username", ""),
                "time": datetime.datetime.now().strftime("%H:%M:%S"),
                "status": "queued",
            })
            if len(self.recent_events) > 50:
                self.recent_events.pop(0)
            logger.info(f"Event queued: {intent} (priority={priority.value}, size={len(self.queue)})")
            return True

    async def get_next(self) -> Optional[Event]:
        async with self._lock:
            if not self.queue:
                return None
            return heapq.heappop(self.queue)

    async def remove_event(self, event_id: str) -> bool:
        async with self._lock:
            for i, ev in enumerate(self.queue):
                if ev.event_id == event_id:
                    self.queue.pop(i)
                    heapq.heapify(self.queue)
                    for re in self.recent_events:
                        if re.get("event_id") == event_id:
                            re["status"] = "ignored"
                    logger.info(f"Event removed: {ev.intent}")
                    return True
            return False

    async def reorder_event_up(self, event_id: str) -> bool:
        async with self._lock:
            sorted_q = sorted(self.queue, key=lambda e: (e.priority.value, e.timestamp))
            target_idx = next((i for i, ev in enumerate(sorted_q) if ev.event_id == event_id), -1)
            if target_idx <= 0:
                return False
            prev_ev = sorted_q[target_idx - 1]
            target_ev = sorted_q[target_idx]
            if prev_ev.priority.value == target_ev.priority.value:
                prev_ev.timestamp, target_ev.timestamp = target_ev.timestamp, prev_ev.timestamp
            else:
                target_ev.priority = prev_ev.priority
                target_ev.timestamp = prev_ev.timestamp - 0.001
            heapq.heapify(self.queue)
            return True

    def peek_next(self) -> Optional[Event]:
        if self.queue:
            return self.queue[0]
        return None

    async def get_queue_status(self) -> Dict[str, Any]:
        async with self._lock:
            priority_counts: Dict[str, int] = {}
            pending_events = []
            for event in self.queue:
                p_name = event.priority.name
                priority_counts[p_name] = priority_counts.get(p_name, 0) + 1
                pending_events.append({
                    "intent": event.intent,
                    "priority": event.priority.value,
                    "username": event.data.get("username", ""),
                })
            return {
                "queue_size": len(self.queue),
                "max_size": self.max_size,
                "priority_distribution": priority_counts,
                "stats": self.stats,
                "pending": pending_events,
                "recent": list(reversed(self.recent_events[-20:])),
            }

    def _reset_counters_if_needed(self):
        now = time.time()
        if now - self.stats["last_minute_reset"] >= 60:
            self.stats["ai_calls_this_minute"] = 0
            self.stats["low_priority_this_minute"] = 0
            self.stats["last_minute_reset"] = now


# ============== 弹窗管理器 ==============
class PopupManager:
    MAX_POPUPS = 2

    def __init__(self):
        self.active_popups: Dict[str, PopupWindow] = {}
        self.popup_queue: List[PopupWindow] = []
        self._lock = asyncio.Lock()

    async def request_popup(self, popup_type: str, content: Dict[str, Any],
                            duration_ms: int, priority: int = 5) -> Optional[str]:
        async with self._lock:
            popup_id = f"popup_{int(time.time() * 1000)}"
            popup = PopupWindow(
                id=popup_id, type=popup_type, content=content,
                duration_ms=duration_ms, priority=priority,
                expires_at=time.time() + (duration_ms / 1000),
            )
            to_remove = [pid for pid, p in self.active_popups.items() if p.type == popup_type]
            for pid in to_remove:
                del self.active_popups[pid]
            if len(self.active_popups) < self.MAX_POPUPS:
                self.active_popups[popup_id] = popup
                return popup_id
            lowest = min(self.active_popups.values(), key=lambda p: p.priority)
            if priority > lowest.priority:
                del self.active_popups[lowest.id]
                self.active_popups[popup_id] = popup
                return popup_id
            self.popup_queue.append(popup)
            self.popup_queue.sort(key=lambda p: p.priority, reverse=True)
            return popup_id

    async def release_popup(self, popup_id: str):
        async with self._lock:
            if popup_id in self.active_popups:
                del self.active_popups[popup_id]
            while self.popup_queue and len(self.active_popups) < self.MAX_POPUPS:
                next_popup = self.popup_queue.pop(0)
                self.active_popups[next_popup.id] = next_popup
                return next_popup.id
            return None

    async def cleanup_expired(self) -> List[str]:
        async with self._lock:
            now = time.time()
            expired = [pid for pid, p in self.active_popups.items() if p.expires_at <= now]
            for pid in expired:
                del self.active_popups[pid]
            return expired

    async def get_active_popups(self) -> List[Dict[str, Any]]:
        async with self._lock:
            return [
                {
                    "id": p.id,
                    "type": p.type,
                    "priority": p.priority,
                    "remaining_seconds": round(p.expires_at - time.time(), 1),
                }
                for p in self.active_popups.values()
            ]


# ============== WebSocket 通信中心 ==============
class WSHub:
    def __init__(self):
        self.clients: Set[WebSocketServerProtocol] = set()

    async def register(self, ws: WebSocketServerProtocol):
        self.clients.add(ws)
        logger.info(f"Client connected. Total: {len(self.clients)}")

    async def unregister(self, ws: WebSocketServerProtocol):
        self.clients.discard(ws)
        logger.info(f"Client disconnected. Total: {len(self.clients)}")

    async def broadcast(self, payload: Dict[str, Any]):
        if not self.clients:
            return
        msg = json.dumps(payload, ensure_ascii=False)
        await asyncio.gather(
            *[self._safe_send(c, msg) for c in self.clients],
            return_exceptions=True,
        )

    @staticmethod
    async def _safe_send(ws: WebSocketServerProtocol, msg: str):
        try:
            await ws.send(msg)
        except Exception as e:
            logger.warning(f"Send failed: {e}")
