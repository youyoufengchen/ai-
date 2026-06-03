"""
直播会话录制器 - 自动收录本次直播生成的AI回复
支持循环存储、标签自动匹配、批量入库到永久素材库
"""

import asyncio
import time
import json
from pathlib import Path
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field, asdict
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class AutoTag(Enum):
    """系统自动标签（基于意图/场景）"""
    WELCOME = "welcome"           # 欢迎/进入
    THANKS = "thanks"             # 感谢/点赞/关注
    PRODUCT = "product"           # 商品介绍
    PRICE = "price"               # 价格相关
    GUIDE = "guide"               # 下单引导
    JOKE = "joke"                 # 俏皮/调侃
    EMOTIONAL = "emotional"       # 情感丰富（有动作描述）
    FAQ = "faq"                   # 常见问题
    URGENT = "urgent"             # 紧急/催单
    CHAT = "chat"                 # 普通闲聊


@dataclass
class RecordedSession:
    """一条录制的会话"""
    id: str
    timestamp: float
    user_message: str           # 用户原话
    ai_reply: str              # AI回复（净文本，无[e:标签]）
    emotion: str               # AI情感
    style_id: str              # 当前风格（同时也是音色标识）
    voice_id: str              # 音色ID（实际MiniMax音色）
    character_id: str = ""     # 角色ID（如bao_qing_fang）
    category: str = "chat"     # 主分类（对应presets分类id：welcome/thanks/recommend/guide/chat）
    auto_tags: List[str] = field(default_factory=list)  # 系统自动标签
    saved: bool = False        # 是否已保存到永久库
    saved_to_category: str = ""  # 已保存到哪个分类
    mp3_filename: str = ""     # 缓存的MP3文件名
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "user_message": self.user_message,
            "ai_reply": self.ai_reply,
            "emotion": self.emotion,
            "style_id": self.style_id,
            "voice_id": self.voice_id,
            "character_id": self.character_id,
            "category": self.category,
            "auto_tags": self.auto_tags,
            "saved": self.saved,
            "saved_to_category": self.saved_to_category,
            "mp3_filename": self.mp3_filename
        }


class SessionRecorder:
    """
    会话录制管理器
    - 循环存储：按数量/容量限制，超限时淘汰最旧
    - 自动标签：基于内容特征自动分类
    - 批量入库：选择会话保存到 presets.json
    """
    
    def __init__(self, max_records: int = 500, data_dir: Optional[Path] = None):
        self.max_records = max_records
        self.data_dir = data_dir or Path(__file__).parent.parent / "cache" / "session_records"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.records: List[RecordedSession] = []
        self.enabled: bool = False
        self._lock = asyncio.Lock()
        
        # 自动标签规则（关键词匹配）- 扩展覆盖20+场景分类
        self.tag_rules: Dict[AutoTag, Set[str]] = {
            AutoTag.WELCOME: {"欢迎", "光临", "客官来啦", "请进", "大驾", "贵宾", "新客", "初次"},
            AutoTag.THANKS: {"谢谢", "感谢", "点赞", "关注", "捧场", "破费", "打赏", "礼物", "送花"},
            AutoTag.PRODUCT: {"介绍", "功效", "产地", "凤凰单丛", "茶", "香气", "口感", "品质", "工艺", "制作"},
            AutoTag.PRICE: {"钱", "价格", "元", "优惠", "打折", "便宜", "贵", "划算", "省钱", "促销", "特价", "满减"},
            AutoTag.GUIDE: {"小黄车", "拍下", "点击", "购买", "下单", "链接", "购物车", "加购", "付款", "支付"},
            AutoTag.JOKE: {"哈哈", "笑话", "调皮", "坊主", "~", "呢~", "嘿嘿", "嘻嘻", "噗嗤"},
            AutoTag.EMOTIONAL: {"掩唇", "轻笑", "拂袖", "颔首", "轻叹", "娇嗔", "莞尔", "嫣然", "蹙眉", "展颜"},
            AutoTag.URGENT: {"快点", " hurry", "立即", "马上", "抓紧", "倒计时", "限量", "秒杀", "抢购"},
            AutoTag.FAQ: {"怎么", "如何", "什么", "多少", "多久", "为什么", "吗？", "呢？", "请问"},
            AutoTag.CHAT: {"聊天", "闲聊", "唠嗑", "家长里短", "天气", "今天", "哈哈", "嗯嗯"},
        }
        
        # 标签 -> presets分类id 的优先级映射（映射到20+内置分类）
        # 一条会话可能命中多个tag，按此优先级取第一个作为主分类
        self.tag_to_category_priority = [
            (AutoTag.WELCOME.value, "welcome"),
            (AutoTag.THANKS.value, "thanks"),  # 感谢词
            ("thanks_gift", "thanks_gift"),   # 感谢礼物（特殊标记）
            ("thanks_follow", "thanks_follow"), # 感谢关注（特殊标记）
            (AutoTag.URGENT.value, "urgency"),  # 催单
            (AutoTag.GUIDE.value, "guide"),     # 下单引导
            ("guide_cart", "guide_cart"),       # 购物车引导
            ("guide_coupon", "guide_coupon"),   # 优惠券
            (AutoTag.PRODUCT.value, "product_intro"),  # 产品介绍
            ("product_feature", "product_feature"),    # 产品卖点
            (AutoTag.PRICE.value, "price"),       # 价格说明
            ("recommend", "recommend"),          # 推荐词
            (AutoTag.JOKE.value, "joke"),         # 幽默调侃
            ("story", "story"),                   # 故事讲述
            ("emotion_happy", "emotion_happy"),   # 开心氛围
            (AutoTag.FAQ.value, "qa"),            # 问答回复
            ("interaction", "interaction"),        # 互动话术
            ("farewell", "farewell"),              # 告别话术
            ("welcome_vip", "welcome_vip"),       # VIP欢迎
            (AutoTag.EMOTIONAL.value, "emotion_happy"),  # 情感丰富->开心氛围
            (AutoTag.CHAT.value, "chat"),          # 闲聊兜底
        ]
        
        # 加载历史（本次会话的）
        self._load_session()
    
    def _infer_category(self, auto_tags: List[str]) -> str:
        """根据自动标签推断主分类"""
        for tag, cat in self.tag_to_category_priority:
            if tag in auto_tags:
                return cat
        return "chat"
    
    def _generate_id(self) -> str:
        import uuid
        return uuid.uuid4().hex[:12]
    
    def _auto_tag(self, user_msg: str, ai_reply: str) -> List[str]:
        """基于内容自动打标签"""
        text = (user_msg + " " + ai_reply).lower()
        tags = []
        for tag, keywords in self.tag_rules.items():
            if any(kw in text for kw in keywords):
                tags.append(tag.value)
        if not tags:
            tags.append(AutoTag.CHAT.value)
        return tags
    
    async def record(self, user_message: str, ai_reply: str, emotion: str,
                     style_id: str, voice_id: str, character_id: str = "",
                     mp3_filename: str = "") -> Optional[str]:
        """
        记录一条会话
        Returns: 记录ID 或 None（未开启录制）
        """
        if not self.enabled:
            return None
            
        async with self._lock:
            auto_tags = self._auto_tag(user_message, ai_reply)
            session = RecordedSession(
                id=self._generate_id(),
                timestamp=time.time(),
                user_message=user_message[:200],  # 限制长度
                ai_reply=ai_reply[:200],
                emotion=emotion,
                style_id=style_id,
                voice_id=voice_id,
                character_id=character_id,
                category=self._infer_category(auto_tags),  # 自动主分类
                auto_tags=auto_tags,
                mp3_filename=mp3_filename
            )
            
            self.records.append(session)
            
            # 循环淘汰：超限时删除最旧的
            while len(self.records) > self.max_records:
                old = self.records.pop(0)
                # 清理对应的MP3文件（如果未被保存到永久库）
                if old.mp3_filename and not old.saved:
                    mp3_path = self.data_dir.parent / "tts_minimax" / old.mp3_filename
                    if mp3_path.exists():
                        try:
                            mp3_path.unlink()
                            logger.debug(f"Cleaned old session MP3: {old.mp3_filename}")
                        except Exception:
                            pass
            
            return session.id
    
    async def get_records(self, tag: Optional[str] = None, 
                          saved_only: Optional[bool] = None,
                          limit: int = 100) -> List[Dict]:
        """获取录制列表，支持过滤"""
        async with self._lock:
            result = self.records.copy()
            
            if tag:
                result = [r for r in result if tag in r.auto_tags]
            if saved_only is not None:
                result = [r for r in result if r.saved == saved_only]
            
            # 按时间倒序，返回最新的
            result = sorted(result, key=lambda x: x.timestamp, reverse=True)[:limit]
            return [r.to_dict() for r in result]
    
    async def mark_saved(self, record_ids: List[str], saved: bool = True):
        """标记会话为已保存/未保存"""
        async with self._lock:
            id_set = set(record_ids)
            for r in self.records:
                if r.id in id_set:
                    r.saved = saved
    
    async def update_category(self, record_id: str, category: str) -> bool:
        """更新单条记录的主分类（用户手动调整）"""
        async with self._lock:
            for r in self.records:
                if r.id == record_id:
                    r.category = category
                    return True
            return False
    
    async def bulk_save_to_presets(self, record_ids: List[str], 
                                   override_category: str = "",
                                   presets_path: Optional[Path] = None) -> Dict:
        """
        批量保存选中会话到永久素材库
        - 默认每条记录按自己的 category 分发到对应分类
        - 若传入 override_category，则全部强制保存到该分类
        - 保存为对象格式 {text, voice_id, style_id, character_id, emotion}，
          以便后续按音色匹配/重新合成
        Returns: {saved: int, failed: int, errors: [], by_category: {cat: count}}
        """
        presets_path = presets_path or Path(__file__).parent.parent / "config" / "presets.json"
        
        result = {"saved": 0, "failed": 0, "errors": [], "by_category": {}}
        
        try:
            # 读取现有 presets
            if presets_path.exists():
                with open(presets_path, encoding="utf-8") as f:
                    data = json.load(f)
            else:
                data = {"categories": []}
            
            # 建立分类索引
            cat_map = {c["id"]: c for c in data.get("categories", [])}
            
            # 自动创建缺失的常用分类（20+内置分类）
            default_cats = {
                "welcome": "欢迎词",
                "welcome_vip": "VIP欢迎",
                "thanks": "感谢词",
                "thanks_gift": "感谢礼物",
                "thanks_follow": "感谢关注",
                "recommend": "推荐词",
                "product_intro": "产品介绍",
                "product_feature": "产品卖点",
                "price": "价格说明",
                "guide": "下单引导",
                "guide_cart": "购物车引导",
                "guide_coupon": "优惠券",
                "interaction": "互动话术",
                "qa": "问答回复",
                "joke": "幽默调侃",
                "story": "故事讲述",
                "emotion_happy": "开心氛围",
                "urgency": "催单 urgency",
                "farewell": "告别话术",
                "chat": "闲聊"
            }
            for cid, label in default_cats.items():
                if cid not in cat_map:
                    new_cat = {"id": cid, "label": label, "mode": "random", "lines": []}
                    data.setdefault("categories", []).append(new_cat)
                    cat_map[cid] = new_cat
            
            async with self._lock:
                id_set = set(record_ids)
                to_save = [r for r in self.records if r.id in id_set]
                
                for session in to_save:
                    target_id = override_category or session.category or "chat"
                    target_cat = cat_map.get(target_id)
                    if not target_cat:
                        result["errors"].append(f"分类 {target_id} 不存在")
                        result["failed"] += 1
                        continue
                    
                    line_text = session.ai_reply.strip()
                    if not line_text:
                        continue
                    
                    # 检查重复（兼容字符串和对象格式）
                    existing_texts = set()
                    for ln in target_cat.get("lines", []):
                        if isinstance(ln, str):
                            existing_texts.add(ln)
                        elif isinstance(ln, dict):
                            existing_texts.add(ln.get("text", ""))
                    
                    if line_text in existing_texts:
                        result["errors"].append(f"重复: {line_text[:20]}...")
                        continue
                    
                    # 保存为对象格式（带音色元数据）
                    target_cat.setdefault("lines", []).append({
                        "text": line_text,
                        "voice_id": session.voice_id,
                        "style_id": session.style_id,
                        "character_id": session.character_id,
                        "emotion": session.emotion,
                        "mp3_filename": session.mp3_filename,
                        "saved_at": time.time(),
                    })
                    
                    result["saved"] += 1
                    result["by_category"][target_id] = result["by_category"].get(target_id, 0) + 1
                    session.saved = True
                    session.saved_to_category = target_id
            
            # 写回文件
            with open(presets_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            result["errors"].append(str(e))
            result["failed"] = len(record_ids) - result["saved"]
        
        return result
    
    async def clear(self, keep_saved: bool = True):
        """清空本次录制"""
        async with self._lock:
            if keep_saved:
                self.records = [r for r in self.records if r.saved]
            else:
                # 清理所有未保存的MP3
                for r in self.records:
                    if r.mp3_filename and not r.saved:
                        mp3_path = self.data_dir.parent / "tts_minimax" / r.mp3_filename
                        if mp3_path.exists():
                            try:
                                mp3_path.unlink()
                            except Exception:
                                pass
                self.records = []
    
    def _load_session(self):
        """加载本次会话的历史（从磁盘恢复，防止重启丢失）"""
        session_file = self.data_dir / "current_session.json"
        if session_file.exists():
            try:
                with open(session_file, encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data.get("records", []):
                        self.records.append(RecordedSession(**item))
                logger.info(f"Loaded {len(self.records)} records from previous session")
            except Exception as e:
                logger.warning(f"Failed to load session: {e}")
    
    async def persist(self):
        """持久化到磁盘（ graceful shutdown 时调用）"""
        session_file = self.data_dir / "current_session.json"
        async with self._lock:
            try:
                data = {
                    "timestamp": time.time(),
                    "enabled": self.enabled,
                    "records": [r.to_dict() for r in self.records]
                }
                with open(session_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"Failed to persist session: {e}")
    
    async def get_stats(self) -> Dict:
        """获取统计信息"""
        async with self._lock:
            tag_counts = {}
            saved_count = 0
            for r in self.records:
                if r.saved:
                    saved_count += 1
                for tag in r.auto_tags:
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1
            
            return {
                "total": len(self.records),
                "saved": saved_count,
                "unsaved": len(self.records) - saved_count,
                "enabled": self.enabled,
                "max_records": self.max_records,
                "tag_distribution": tag_counts
            }
