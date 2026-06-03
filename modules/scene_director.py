"""
SceneDirector: 场景调度器，状态机 + 事件循环 + 广播指令
"""
import asyncio
import json
import logging
import random
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from modules.core import (
    HostState, EventPriority, Event, EventQueueManager, PopupManager, WSHub, PRIORITY_MAP
)
from modules.config_manager import ConfigManager
from modules.ai_service import AIService
from modules.tts_service import TTSService, MiniMaxTTSService, EdgeTTSService, BrowserTTSFallback
from modules.dialogue_queue import DialogueQueueManager
from modules.session_recorder import SessionRecorder
from modules.douyin_danmaku import DanmakuEvent, DanmakuType

logger = logging.getLogger("server")


class SceneDirector:
    """
    增强版场景调度器：
    - 状态机管理（idle/waiting/playing/speaking/processing）
    - 事件队列驱动（优先级队列）
    - 弹窗并发控制
    - 指令序列生成与广播
    
    指令协议（前端 app.js 消费）：
      { "action": "set_state", "state": "idle" }
      { "action": "play_video", "url": "...", "loop": false, "next_state": "idle" }
      { "action": "show_hand_item", "image": "..." }
      { "action": "hide_hand_item" }
      { "action": "show_table_product", "image": "...", "video": "..." }
      { "action": "hide_table_product" }
      { "action": "show_popup", "type": "A|B|C|D", "content": {...}, "duration_ms": 8000 }
      { "action": "speak", "text": "...", "audio_url": null }
      { "action": "highlight_shelf", "slot_id": "A1" }
      { "action": "play_effect", "effect": "order_celebration" }
    """

    def __init__(self, cfg: ConfigManager, hub: WSHub, event_queue: EventQueueManager,
                 popup_mgr: PopupManager, ai: AIService, tts: TTSService,
                 dialogue_queue: DialogueQueueManager,
                 edge_tts: Optional["EdgeTTSService"] = None,
                 minimax_tts: Optional["MiniMaxTTSService"] = None,
                 session_recorder: Optional["SessionRecorder"] = None,
                 action_planner = None):
        self.cfg = cfg
        self.hub = hub
        self.event_queue = event_queue
        self.popup_mgr = popup_mgr
        self.ai = ai
        self.tts = tts
        self.edge_tts = edge_tts or EdgeTTSService()
        self.minimax_tts = minimax_tts or MiniMaxTTSService()
        self.dialogue_queue = dialogue_queue
        self.session_recorder = session_recorder
        
        # 【Action Flow】动作规划器
        from modules.ai_action_planner import AIActionPlanner, create_action_planner
        self.action_planner = action_planner or create_action_planner(ai, cfg)
        
        # 为DialogueQueue设置广播函数（用于发送动作流指令）
        if self.dialogue_queue:
            self.dialogue_queue.set_broadcast_handler(
                lambda msg: asyncio.create_task(self.hub.broadcast(msg))
            )
            # 设置Action Flow回调
            self.dialogue_queue.on_action_plan_ready = self._on_action_plan_ready
            self.dialogue_queue.on_3d_execution_complete = self._on_3d_execution_complete
        
        # 状态机
        self.state = HostState.IDLE
        self.current_task: Optional[asyncio.Task] = None
        self._processing = False
        self._stop_event = asyncio.Event()
        
        # 打断标志（高优先级事件可打断当前播放）
        self._interrupted = False
        self._interrupt_event = asyncio.Event()
        
        # 说话互斥锁：确保同时只有一路语音在播放
        self._speaking_lock = asyncio.Lock()
        
        # 跳过当前播放的事件
        self._skip_event = asyncio.Event()
        
        # 当前事件的动作数据（由_handle_event注入）
        self._current_action_data: Optional[Dict] = None
        
        # 上一次成功播放的动作计划（AI关闭时复用）
        self._last_action_plan: Optional[Any] = None
        
        # 当前风格
        self._current_style = "classical"

        # 事件话术模板（从 presets.json 中 system=True 的分类加载）
        self._event_templates: Dict[str, List[str]] = {}
        self._load_event_templates()

        # 关键词意图映射（用于AI意图识别）
        self.intent_keywords = {
            "product_query": ["多少钱", "价格", "怎么卖", "介绍一下", "这个茶", "怎么样"],
            "order_placed": ["已拍", "下单了", "买了", "付款了"],
            "gift_big": ["嘉年华", "火箭", "飞机"],
            "gift_small": ["小心心", "玫瑰花", "啤酒"],
            "urgent_question": ["怎么买", "在哪拍", "链接", "小黄车"],
            "user_enter": ["来了", "刚进", "关注"],
        }
    
    def _load_event_templates(self):
        """从 presets.json 加载 system=True 的事件话术分类"""
        try:
            presets_path = Path(__file__).parent.parent / "config" / "presets.json"
            with open(presets_path, encoding="utf-8") as f:
                data = json.load(f)
            for cat in data.get("categories", []):
                cat_id = cat.get("id", "")
                lines = [
                    (l["text"] if isinstance(l, dict) else l)
                    for l in cat.get("lines", []) if (l["text"] if isinstance(l, dict) else l).strip()
                ]
                # system=True + event_type：事件触发话术（礼物/下单/欢迎等）
                if cat.get("system") and cat.get("event_type") and lines:
                    self._event_templates[cat["event_type"]] = lines
                # id=chat：AI关闭时的闲聊话术
                if cat_id == "chat" and lines:
                    self._event_templates["chat"] = lines
            logger.info(f"Event templates loaded: {list(self._event_templates.keys())}")
        except Exception as e:
            logger.warning(f"Failed to load event templates: {e}")

    def _pick_event_template(self, event_type: str, **vars) -> str:
        """随机取一条话术模板，替换 {username}/{gift_name}/{sku_name} 占位符"""
        lines = self._event_templates.get(event_type, [])
        if not lines:
            return ""
        tpl = random.choice(lines)
        for k, v in vars.items():
            tpl = tpl.replace("{" + k + "}", str(v))
        return tpl

    def reload_event_templates(self):
        """运营修改 presets.json 后可调用此方法热重载"""
        self._event_templates.clear()
        self._load_event_templates()

    def _resolve_gift_tier(self, gift_name: str, gift_value: int) -> str:
        """根据礼物名称/价值判断所属档位，返回 intent 字符串
        优先级： name_map 精确匹配 > value_thresholds 区间判断 > 默认 gift_small
        """
        tiers_cfg = self.cfg.main.get("gift_tiers", {})
        # 名称精确匹配
        name_map = tiers_cfg.get("name_map", {})
        if gift_name in name_map:
            return name_map[gift_name]
        # 价值区间匹配
        for band in tiers_cfg.get("value_thresholds", []):
            lo = band.get("min", 0)
            hi = band.get("max")  # None 表示无上限
            if gift_value >= lo and (hi is None or gift_value < hi):
                return band["tier"]
        # 默认小礼物
        return "gift_small"

    def set_state(self, new_state: HostState):
        """设置状态机状态"""
        old_state = self.state
        self.state = new_state
        if old_state != new_state:
            logger.info(f"State: {old_state.name} -> {new_state.name}")
            # 广播状态变更给前端
            asyncio.create_task(self.hub.broadcast({
                "action": "set_state",
                "state": new_state.name
            }))
    
    async def start_event_loop(self):
        """启动事件处理循环"""
        self._processing = True
        last_dialogue_check = 0
        # 启动定时任务后台协程（骨骼动画模式下简化）
        # asyncio.create_task(self._auto_promote_loop(), name="auto_promote")
        # asyncio.create_task(self._schedule_loop(), name="schedule_watcher")
        
        while self._processing:
            try:
                # 清理过期弹窗
                expired = await self.popup_mgr.cleanup_expired()
                if expired:
                    logger.info(f"Cleaned up {len(expired)} expired popups")
                
                # 检查对话队列（每秒检查一次）
                now = asyncio.get_event_loop().time()
                if now - last_dialogue_check > 1.0:
                    await self._check_dialogue_queue()
                    last_dialogue_check = now
                
                # 获取下一个事件
                event = await self.event_queue.get_next()
                if event:
                    await self._handle_event(event)
                else:
                    # 无事件时短暂休眠
                    await asyncio.sleep(0.1)
                    
            except Exception as e:
                logger.error(f"Event loop error: {e}")
                await asyncio.sleep(0.5)
    
    def _estimate_speech_duration(self, text: str, rate: float = 1.0, audio_url: Optional[str] = None) -> float:
        """优先用实际音频时长（MiniMax返回的extra_info.audio_length），否则估算。
        估算：中文约3.8字/秒（保守），加0.8秒缓冲，避免下一条提前覆盖。
        """
        # 优先：实际时长
        if audio_url:
            try:
                real = self.minimax_tts.get_duration(audio_url)
                if real and real > 0:
                    return real + 0.3  # 0.3s 余量
            except Exception:
                pass
        char_count = len(text.strip())
        base_duration = char_count / 3.8
        duration = base_duration / max(rate, 0.5)
        return max(duration + 0.8, 1.5)  # 最少1.5秒

    def _get_config(self, key: str, default=None):
        """获取配置：优先 main.json 的 feature_flags，再 main.json 顶层，最后硬编码默认值"""
        defaults = {
            "pause_playback": False,
            "tts_rate": 1.0,
            "tts_volume": 0.8,
            "enable_ai_response": True,
            "enable_auto_welcome": True,
            "enable_gift_effects": True,
            "enable_danmaku": True,
            "enable_order_response": True,
            "enable_direct_broadcast": False,
            "prevent_interruption": True,
        }
        # 1) 优先从 feature_flags 读（控制台可热改）
        flags = (self.cfg.main or {}).get("feature_flags", {})
        if key in flags:
            return flags[key]
        # 2) main.json 顶层（兼容 tts_rate 等）
        if key in (self.cfg.main or {}):
            return self.cfg.main[key]
        # 3) 默认值
        if default is not None:
            return default
        return defaults.get(key)

    async def _check_dialogue_queue(self):
        """检查对话队列，播放待回复的对话"""
        # 播报暂停模式：跳过本次播报
        if self._get_config("pause_playback", False):
            return
        # 锁被占用说明有语音正在播放，非紧急时跳过本次检查
        if self._speaking_lock.locked():
            return

        next_item = self.dialogue_queue.get_next_to_play()
        if not next_item:
            return

        # 紧急插队暂不支持打断（前端插队会在当前播完后立即播放，已足够快）
        is_emergency = next_item.interrupt_current

        # 标记为播放中
        await self.dialogue_queue.mark_playing(next_item.id)

        # 持有互斥锁：等待前一条播完后才开始
        mp3_filename = ""
        async with self._speaking_lock:
            self.set_state(HostState.SPEAKING)
            try:
                # 播放说话动作
                await self.hub.broadcast({
                    "action": "play_video",
                    "url": self._video("talk"),
                    "loop": False,
                    "next_state": "idle",
                    "next_video": self._video("idle"),
                })

                # 语音播报（wait=False，锁由本块管理）
                tts_rate = self._get_config("tts_rate", 1.0)

                spoken_result = await self._speak_with_tts(
                    text=next_item.reply,
                    use_ai=False,
                    username=next_item.username,
                    message=next_item.message,
                    wait=False,
                    emotion=next_item.emotion
                )
                
                # 解析返回结果（可能是text或(text, audio_url)元组）
                if isinstance(spoken_result, tuple) and len(spoken_result) == 2:
                    spoken_text, audio_url = spoken_result
                else:
                    spoken_text = spoken_result
                    audio_url = getattr(self, '_last_speak_audio_url', None)
                
                # 提取MP3文件名（从audio_url如 /cache/tts_minimax/xxx.mp3）
                mp3_filename = ""
                if audio_url:
                    parts = audio_url.split('/')
                    if parts:
                        mp3_filename = parts[-1]

                # 【Action Flow】回填 audio_url 和实际时长到 item，再广播执行计划
                wait_text = spoken_text if spoken_text else next_item.reply
                actual_duration = self._estimate_speech_duration(wait_text, 1.0, audio_url=audio_url)
                if next_item.action_plan:
                    next_item.audio_url = audio_url
                    next_item.audio_duration = actual_duration
                    next_item.action_plan.audio_duration = actual_duration
                    # 单独广播 execute_action_flow（带真实audio_url和时长）
                    await self.hub.broadcast({
                        "action": "execute_action_flow",
                        "dialogue_id": next_item.id,
                        "plan": next_item.action_plan.to_dict(),
                        "audio_url": audio_url,
                        "audio_duration": actual_duration,
                    })
                    logger.info(f"[ActionFlow] Broadcasted plan for [{next_item.id}] "
                                f"audio_dur={actual_duration:.1f}s")

                # 等待实际播完（可被skip_event提前打断）
                duration = self._estimate_speech_duration(wait_text, tts_rate, audio_url=audio_url)
                logger.info(f"[DIALOGUE] {len(wait_text)}字 预计{duration:.1f}s: {wait_text[:40]}")
                self._skip_event.clear()
                try:
                    await asyncio.wait_for(self._skip_event.wait(), timeout=duration)
                    logger.info(f"[DIALOGUE] 跳过当前播放")
                except asyncio.TimeoutError:
                    pass  # 正常播完
                finally:
                    self._skip_event.clear()  # 确保下一条不受影响

            finally:
                await self.dialogue_queue.mark_completed(next_item.id)
                self.set_state(HostState.IDLE)
                # 录制本次会话（如果开启自动收录）
                if self.session_recorder and next_item.reply:
                    style_id = self.cfg.get_current_style()
                    char = self.cfg.get_character()
                    voice_id = char.get("styles", {}).get(style_id, {}).get("voice_id", "female-shaonv")
                    character_id = char.get("id", "") or "bao_qing"
                    await self.session_recorder.record(
                        user_message=next_item.message,
                        ai_reply=next_item.reply,
                        emotion=next_item.emotion or "happy",
                        style_id=style_id,
                        voice_id=voice_id,
                        character_id=character_id,
                        mp3_filename=mp3_filename
                    )
    
    async def _on_action_plan_ready(self, item, action_plan):
        """动作计划生成完成回调（dialogue_queue 生成 reply + plan 后触发）"""
        logger.info(f"[ActionFlow] Plan ready for [{item.id}]: "
                    f"{len(action_plan.actions)} actions, type={action_plan.trigger_type}")
        # 可在此做额外的预处理（如预加载GLB、提前高亮货架等）
        # 目前仅记录日志，实际广播在 mark_playing → _broadcast_action_flow_start 里完成

    async def _on_3d_execution_complete(self, item):
        """3D动作流执行完成回调（前端通知完成后触发）"""
        logger.info(f"[ActionFlow] 3D execution complete for [{item.id}]")
        # 动作流完成后的后续逻辑（如切回 idle、解除 busy 状态等）
        await self.hub.broadcast({
            "action": "play_action",
            "action_key": "idle",
            "loop": True,
        })

    def stop_event_loop(self):
        """停止事件处理循环"""
        self._processing = False
        self._stop_event.set()

    async def _auto_promote_loop(self):
        """
        定时商品推广 loop（骨骼动画模式简化版）
        从 skus.json 读取商品列表进行轮换推广
        """
        # 从配置获取SKU列表
        sku_list = list(self.cfg.skus.get("skus", {}).keys())
        if not sku_list:
            logger.info("[AutoPromote] no SKUs found, disabled")
            return

        sku_index = 0
        logger.info(f"[AutoPromote] loop started, SKUs={sku_list}")

        while self._processing:
            try:
                # 默认5分钟间隔
                await asyncio.sleep(300)

                if not self._processing:
                    break

                sku_id = sku_list[sku_index % len(sku_list)]
                sku_index += 1

                logger.info(f"[AutoPromote] triggered for SKU={sku_id}")
                await self.on_product_query(sku_id)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[AutoPromote] error: {e}")
                await asyncio.sleep(30)

    async def _schedule_loop(self):
        """
        时间段风格切换 watcher（骨骼动画模式简化版）
        从 main.json 读取 schedule 配置进行自动风格切换
        """
        last_style = self.cfg.get_current_style()
        logger.info(f"[Schedule] watcher started, current style={last_style}")

        while self._processing:
            try:
                await asyncio.sleep(60)

                if not self._processing:
                    break

                # 从 main.json 获取时间段配置（简化实现）
                schedule_rules = self.cfg.main.get("schedule", {})
                if not schedule_rules:
                    continue

                current_style = self.cfg.get_current_style()
                # TODO: 实现时间段匹配逻辑
                # 暂时简化，不自动切换

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Schedule] error: {e}")
                await asyncio.sleep(60)
    
    async def _handle_event(self, event: Event):
        """处理单个事件"""
        intent = event.intent
        data = event.data
        username = data.get("username", "")

        logger.info(f"Processing event: {intent} (priority={event.priority.value})")

        # ========== 事件处理简化（骨骼动画模式）==========
        # smart_chat 不走事件队列（它有自己的对话队列流程）
        if intent == "smart_chat":
            event_can_interrupt = False
        else:
            # 高优先级事件可以打断
            event_can_interrupt = event.priority.value <= 2
        
        # 高优先级事件（订单、大额礼物）可以打断当前播放
        can_interrupt = event_can_interrupt
        
        if can_interrupt and self.state in [HostState.PLAYING, HostState.SPEAKING]:
            # 检查全局防打断设置
            prevent_interruption = self._get_config("prevent_interruption", True)
            
            if prevent_interruption and event.priority.value > 1:
                # 防打断模式：等锁释放即等当前speak完成，天然安全
                logger.info(f"Prevent interruption: {intent} waiting for current speech to finish")
            else:
                logger.info(f"High priority event {intent} interrupting current playback")
                self._interrupted = True
                self._interrupt_event.set()
                # 短暂等待让当前任务响应中断
                await asyncio.sleep(0.1)
        
        # 根据意图分发处理
        handler_map = {
            "order_placed":   self.on_order_placed,
            "gift_super":     self.on_gift_super,
            "gift_big":       self.on_gift_big,
            "gift_small":     self.on_gift_small,
            "gift_tiny":      self.on_gift_tiny,
            "urgent_question": self.on_urgent_question,
            "product_query":  self.on_product_query,
            "style_switch":   self.on_style_switch,
            "general_chat":   self.on_general_chat,
            "smart_chat":     self.on_smart_chat,
            "user_enter":     self.on_user_enter,
            "like_received":  self.on_like_received,
        }
        
        handler = handler_map.get(intent)
        if handler:
            await handler(**data)
        else:
            logger.warning(f"No handler for intent: {intent}")
    
    async def _check_interrupt(self) -> bool:
        """检查是否被打断"""
        if self._interrupted:
            self._interrupted = False
            self._interrupt_event.clear()
            return True
        return False
    
    # ============== 新场景处理器 ==============

    async def on_gift_tiny(self, username: str, gift_name: str = '', count: int = 1, **kwargs):
        """等级：小心心/爱心等微蒙礼物 - 轻量回应，不弹窗"""
        count_str = f"×{count}" if count > 1 else ""
        ref = self._pick_event_template("gift_tiny", username=username, gift_name=gift_name)
        ref_hint = f"\n参考话术风格（可改写，不要照抄）：{ref}" if ref else ""
        msg = f"[微小礼物] {username}送来了{gift_name}{count_str}，简短温馨地表示感谢即可{ref_hint}"
        await self.dialogue_queue.add_message(
            username=username,
            message=msg,
            priority=8,
            tags=["gift", "gift_tiny"],
            source="gift"
        )

    async def on_gift_super(self, username: str, gift_name: str = '', value: int = 0, count: int = 1, **kwargs):
        """等级：崂年华/火箭等超级礼物 - 激情满满，播放特效+弹窗"""
        if self._get_config("enable_gift_effects", True):
            await self.hub.broadcast({"action": "play_effect", "effect": "gift_celebration_super"})

        await self.popup_mgr.request_popup(
            "A",
            {"text": f"🔥【超级大礼】{username} 上了 {gift_name}！"},
            12000,
            priority=10
        )

        count_str = f"×{count}" if count > 1 else ""
        ref = self._pick_event_template("gift_super", username=username, gift_name=gift_name)
        ref_hint = f"\n参考话术风格（可改写，不要照抄）：{ref}" if ref else ""
        msg = f"[超级大礼] {username}送来了{gift_name}{count_str}，价值{value}抖币！请极度兴奋激动地回应{ref_hint}"
        await self.dialogue_queue.add_message(
            username=username,
            message=msg,
            priority=1,
            tags=["gift", "gift_super"],
            source="gift"
        )

    async def on_gift_big(self, username: str, gift_name: str = '', value: int = 0, count: int = 1, **kwargs):
        """大额礼物处理 - 走AI对话队列生成个性化感谢话术和动作流"""
        if self._get_config("enable_gift_effects", True):
            await self.hub.broadcast({"action": "play_effect", "effect": "gift_celebration_big"})

        await self.popup_mgr.request_popup(
            "A",
            {"text": f"感谢 {username} 的{gift_name}！大气！"},
            8000,
            priority=8
        )

        count_str = f"×{count}" if count > 1 else ""
        ref = self._pick_event_template("gift_big", username=username, gift_name=gift_name)
        ref_hint = f"\n参考话术风格（可改写，不要照抄）：{ref}" if ref else ""
        msg = f"[大额礼物] {username}送来了{gift_name}{count_str}，价值{value}抖币，请用热情感谢的方式回应{ref_hint}"
        await self.dialogue_queue.add_message(
            username=username,
            message=msg,
            priority=2,
            tags=["gift", "gift_big"],
            source="gift"
        )
    
    async def on_gift_small(self, username: str, gift_name: str = '', count: int = 1, **kwargs):
        """小额礼物处理 - 走AI对话队列生成个性化感谢话术和动作流"""
        if self._get_config("enable_gift_effects", True):
            await self.hub.broadcast({"action": "play_effect", "effect": "gift_celebration_small"})

        count_str = f"×{count}" if count > 1 else ""
        await self.popup_mgr.request_popup(
            "A",
            {"text": f"感谢 {username} 的{gift_name}{count_str}"},
            5000,
            priority=4
        )

        ref = self._pick_event_template("gift_small", username=username, gift_name=gift_name)
        ref_hint = f"\n参考话术风格（可改写，不要照抄）：{ref}" if ref else ""
        msg = f"[礼物] {username}送来了{gift_name}{count_str}，请用温暖的方式感谢{ref_hint}"
        await self.dialogue_queue.add_message(
            username=username,
            message=msg,
            priority=6,
            tags=["gift", "gift_small"],
            source="gift"
        )
    
    async def on_urgent_question(self, username: str, question: str = '', **kwargs):
        """紧急提问处理（带购买意向的关键词）"""
        sku_id = self.cfg.find_sku_by_keyword(question)
        
        if sku_id:
            # 骨骼动画模式简化：直接查询商品，无需action_mgr触发判定
            await self.on_product_query(sku_id)
        else:
            # 通用回答：播 talk 动作组视频
            await self._play_action_videos(self._current_action_data, priority=7, can_interrupt=False)
            
            popup_id = await self.popup_mgr.request_popup(
                "D",
                {"question": question, "answer": "客官稍等，坊主这就为您介绍~"},
                10000,
                priority=7
            )
            
            text = f"{username}客官问得好，{question}..."
            await self._speak_with_tts(text, wait=True)
    
    async def on_general_chat(self, username: str, message: str = '', **kwargs):
        """普通聊天处理"""
        import random
        responses = [
            f"{username}客官说得在理~",
            f"{username}客官眼光独到！",
            f"{username}客官请喝茶~",
        ]
        text = random.choice(responses)
        await self._play_action_videos(self._current_action_data, priority=8, can_interrupt=False)
        await self._speak_with_tts(text, wait=True)
    
    async def on_like_received(self, username: str, count: int = 0, **kwargs):
        """点赞处理"""
        if count >= 10:
            await self._play_action_videos(self._current_action_data, priority=9, can_interrupt=False)
            text = f"感谢各位客官的{count}个赞！"
            await self._speak_with_tts(text, wait=True)
    
    # ============== AI增强方法 ==============
    
    async def _speak_with_tts(self, text: str, use_ai: bool = False, username: str = "", message: str = "", sku: Optional[Dict] = None, wait: bool = True, emotion: Optional[str] = None):
        """
        说话（带TTS集成）。wait=True 时持有 _speaking_lock 直到播完，
        保证同时只有一路语音，不会相互打断。
        """
        # 先在锁外完成 AI 生成和 TTS 合成（耗时但不占播放权）
        final_text = text
        ai_emotion = emotion  # 外部直接传入的 emotion（来自 dialogue item）
        if use_ai and self.ai.api_key:
            char = self.cfg.get_character()
            style_id = self.cfg.get_current_style()
            ai_response = await self.ai.chat(
                user_message=message or text,
                username=username or "客官",
                character=char,
                style_id=style_id,
                sku=sku
            )
            if ai_response:
                if isinstance(ai_response, tuple):
                    final_text, ai_emotion = ai_response
                else:
                    final_text = ai_response

        tts_rate = self._get_config("tts_rate", 1.0)

        # 从 characters.json 读取当前风格的 voice_settings（speed/pitch）
        char = self.cfg.get_character()
        style_id = self.cfg.get_current_style()
        voice_settings = char.get("styles", {}).get(style_id, {}).get("voice_settings", {})

        # TTS朗读文本：过滤掉括号内的情绪动作（如"（掩唇轻笑）"），只显示在字幕不朗读
        import re as _re
        tts_text = _re.sub(r'[（(][^）)]{1,10}[）)]', '', final_text).strip()
        if not tts_text:
            tts_text = final_text  # 过滤后为空则用原文

        audio_url = None
        viseme_timeline = None  # 火山TTS口型时间轴数据
        tts_engine = self._get_config("tts_engine", "minimax")

        if tts_engine == "browser":
            pass  # 强制用浏览器TTS，不合成音频文件
        elif tts_engine == "edge":
            audio_url = await self.edge_tts.synthesize(
                tts_text, style_id, rate=tts_rate, voice_settings=voice_settings
            )
        elif tts_engine == "volcengine":
            if self.tts.app_id and self.tts.token:
                tts_result = await self.tts.synthesize(
                    tts_text, style_id, rate=tts_rate, voice_settings=voice_settings
                )
                if tts_result:
                    audio_url = tts_result["url"]
                    viseme_timeline = tts_result.get("viseme_timeline")
        else:
            # minimax（默认）：依次降级
            audio_url = await self.minimax_tts.synthesize(
                tts_text, style_id, rate=tts_rate, voice_settings=voice_settings,
                emotion=ai_emotion
            )
            if not audio_url and self.tts.app_id and self.tts.token:
                tts_result = await self.tts.synthesize(
                    tts_text, style_id, rate=tts_rate, voice_settings=voice_settings
                )
                if tts_result:
                    audio_url = tts_result["url"]
                    viseme_timeline = tts_result.get("viseme_timeline")
            if not audio_url:
                audio_url = await self.edge_tts.synthesize(
                    tts_text, style_id, rate=tts_rate, voice_settings=voice_settings
                )

        if wait:
            # 播报暂停模式：直接跳过，不播报
            if self._get_config("pause_playback", False):
                return final_text
            # 获取互斥锁：等待上一条播完才能开始
            async with self._speaking_lock:
                # 再次检查（等锁期间可能被暂停）
                if self._get_config("pause_playback", False):
                    return final_text
                self.set_state(HostState.SPEAKING)
                tts_volume = self._get_config("tts_volume", 0.8)
                mute_tts = self._get_config("mute_tts", False)
                # 获取当前对话项的 dialogue_id 和 action_plan（供收藏绑定动作流）
                _cur = self.dialogue_queue._current_item if self.dialogue_queue else None
                _plan_dict = _cur.action_plan.to_dict() if _cur and _cur.action_plan else None
                await self.hub.broadcast({
                    "action": "speak",
                    "text": final_text,
                    "tts_text": tts_text,
                    "audio_url": audio_url,
                    "viseme_timeline": viseme_timeline,
                    "rate": tts_rate,
                    "volume": tts_volume,
                    "muted": mute_tts,
                    "dialogue_id": _cur.id if _cur else None,
                    "action_plan": _plan_dict,
                    "browser_tts_config": BrowserTTSFallback.get_config(style_id, rate=tts_rate, volume=tts_volume, voice_settings=voice_settings) if not audio_url else None
                })
                duration = self._estimate_speech_duration(final_text, tts_rate, audio_url=audio_url)
                logger.info(f"[SPEAK] {len(final_text)}字 预计{duration:.1f}s: {final_text[:40]}")
                await asyncio.sleep(duration)
                self.set_state(HostState.IDLE)
            # 返回实际使用的文本和音频URL（供录音使用）
            return final_text, audio_url
        else:
            # wait=False：调用方自己持锁，这里只负责广播
            # 记录本次audio_url，供调用方_estimate_speech_duration查询实际时长
            self._last_speak_audio_url = audio_url
            tts_volume = self._get_config("tts_volume", 0.8)
            mute_tts = self._get_config("mute_tts", False)
            _cur = self.dialogue_queue._current_item if self.dialogue_queue else None
            _plan_dict = _cur.action_plan.to_dict() if _cur and _cur.action_plan else None
            await self.hub.broadcast({
                "action": "speak",
                "text": final_text,
                "tts_text": tts_text,
                "audio_url": audio_url,
                "viseme_timeline": viseme_timeline,
                "rate": tts_rate,
                "volume": tts_volume,
                "muted": mute_tts,
                "dialogue_id": _cur.id if _cur else None,
                "action_plan": _plan_dict,
                "browser_tts_config": BrowserTTSFallback.get_config(
                    self.cfg.get_current_style(),
                    rate=tts_rate, volume=tts_volume,
                    voice_settings=self.cfg.get_character().get("styles", {}).get(
                        self.cfg.get_current_style(), {}).get("voice_settings", {})
                ) if not audio_url else None
            })

        return final_text
    
    async def on_smart_chat(self, username: str, message: str, session_id: str = "default", **kwargs):
        """
        智能聊天（AI+TTS）- 使用对话队列
        
        流程：
        1. 检查AI开关
        2. 添加到对话队列，AI异步生成回复
        3. 回复生成后进入待播放队列
        4. 按顺序播放
        """
        # 检查AI回复开关：关闭时走presets固定话术
        if not self._get_config("enable_ai_response", True):
            await self._speak_from_presets(username, message)
            return
        
        # 意图识别
        intent = await self.ai.recognize_intent(message, self.intent_keywords)
        
        # 如果是商品查询，尝试匹配SKU
        sku_id = None
        tags = ["chat"]
        if intent in ["product_query", "urgent_question"]:
            sku_id = self.cfg.find_sku_by_keyword(message)
            if sku_id:
                tags.append("product")
                # 商品查询走商品展示流程（独立处理）
                # 手动解析 product_query 的 action_data（fetch_turn/fetch_return/present 序列）
                # 骨骼动画模式简化：直接查询商品
                await self.on_product_query(sku_id)
                return
        
        # 同步直接播报模式到对话队列
        self.dialogue_queue.direct_broadcast = self._get_config("enable_direct_broadcast", False)
        
        # 添加到对话队列，AI异步生成回复
        item_id = await self.dialogue_queue.add_message(
            username=username,
            message=message,
            priority=7,  # 普通聊天优先级
            tags=tags,
            source="danmaku",
            sku_id=sku_id
        )
        
        logger.info(f"Smart chat added to queue: [{item_id}] {username}: {message[:30]}...")
    
    async def _speak_from_presets(self, username: str, message: str):
        """
        AI关闭时的回复逻辑：
        1. 从 presets.json 的 chat 分类取一条话术直接说
        2. 动作复用上次的 action_plan；没有则保持默认动作
        """
        # 取话术：优先 chat 分类，兜底通用闲聊
        # _event_templates 里的条目可能是纯字符串或 {text, action_plan} 对象
        raw_lines = self._event_templates.get("chat", [])
        raw_lines = [l for l in raw_lines if (l.get("text","").strip() if isinstance(l, dict) else l.strip())]
        if not raw_lines:
            for fallback in ("thanks", "interaction", "recommend"):
                raw_lines = [l for l in self._event_templates.get(fallback, [])
                             if (l.get("text","").strip() if isinstance(l, dict) else l.strip())]
                if raw_lines:
                    break

        chosen_plan = None
        if not raw_lines:
            text = f"{username}客官说得是~"
        else:
            import random
            chosen = random.choice(raw_lines)
            if isinstance(chosen, dict):
                text = chosen.get("text", "")
                chosen_plan = chosen.get("action_plan")   # 话术自带的 action_plan
            else:
                text = chosen
            text = text.replace("{username}", username)

        logger.info(f"[NoAI] speak from presets: {text[:40]}")

        import uuid as _uuid
        # 优先用话术自带的 action_plan，否则复用上次的
        plan_to_use = chosen_plan or (self._last_action_plan.to_dict() if self._last_action_plan else None)
        if plan_to_use and self.dialogue_queue._broadcast_fn:
            await self.hub.broadcast({
                "action": "execute_action_flow",
                "dialogue_id": "preset_" + _uuid.uuid4().hex[:6],
                "plan": plan_to_use if isinstance(plan_to_use, dict) else plan_to_use.to_dict()
            })

        # 直接 TTS 播报（不走 AI 生成）
        await self._speak_with_tts(text, use_ai=False, username=username)

    # ============== 原有场景处理器（增强版） ==============

    # ---------- 角色视频解析 ----------
    def _video(self, action: str) -> str:
        """根据当前风格获取动作视频路径（旧接口，向后兼容）"""
        char = self.cfg.get_character()
        style_id = self.cfg.get_current_style()
        style = char.get("styles", {}).get(style_id, {})
        videos = style.get("videos", {})
        return videos.get(action, videos.get("idle", ""))

    def _resolve_video_path(self, video_file: str) -> str:
        """把动作组里的视频文件名解析为前端可访问的相对路径"""
        # 视频文件统一放在 assets/host/ 下
        return f"assets/host/{video_file}"

    async def _play_action_videos(self, action_data: Optional[Dict],
                                   priority: int = 5,
                                   can_interrupt: bool = False):
        """
        骨骼动画模式：发送动作触发事件给前端，由前端骨骼动画系统处理
        （原视频调度器已移除）
        """
        # 骨骼动画模式下，动作由前端根据意图自动规划
        # 这里发送一个事件通知前端触发相应动作
        await self.hub.broadcast({
            "action": "trigger_animation",
            "priority": priority,
            "can_interrupt": can_interrupt,
            "timestamp": asyncio.get_event_loop().time()
        })
        logger.debug(f"[ACTION] animation trigger sent (priority={priority})")

    # ---------- 场景：用户进入 ----------
    async def on_user_enter(self, username: str, **kwargs):
        if not self._get_config("enable_auto_welcome", True):
            logger.debug("Auto welcome disabled, skipping user enter")
            return
        
        char = self.cfg.get_character()
        style = char["styles"][self.cfg.get_current_style()]
        greetings = style.get("greetings", ["客官里面请"])
        # 取第一条做演示，后续可加入随机/轮换
        text = greetings[0].replace("{name}", username or "")

        # 播欢迎动作组视频
        await self._play_action_videos(self._current_action_data, priority=9, can_interrupt=False)
        await self._speak_with_tts(text, wait=True)

    # ---------- 场景：商品询问 ----------
    async def on_product_query(self, sku_id: str = '', **kwargs):
        sku = self.cfg.get_sku(sku_id)
        if not sku:
            logger.warning(f"SKU not found: {sku_id}")
            return

        # 1. 闪烁货架位置 - 从shelves数组中查找匹配的sku_id
        scene = self.cfg.get_scene()
        shelf_id = ""
        npc_target_pos = None
        
        # 获取sku的shelf_id（如A1/A2/A3）
        target_shelf_id = sku.get("shelf_id", "")
        
        # 在shelves中查找匹配的货架
        for shelf in scene.get("shelves", []):
            if shelf.get("id") == target_shelf_id:
                shelf_id = shelf["id"]
                npc_target_pos = shelf.get("npc_stop_point", {})
                break
        
        # 如果没找到，尝试通过product匹配（兼容旧格式）
        if not shelf_id:
            for shelf in scene.get("shelves", []):
                product = shelf.get("product", {})
                if product and product.get("sku_id") == sku_id:
                    shelf_id = shelf["id"]
                    npc_target_pos = shelf.get("npc_stop_point", {})
                    break
        
        if shelf_id:
            await self.hub.broadcast({"action": "highlight_shelf", "shelf_id": shelf_id})
            logger.info(f"[ProductQuery] 高亮货架 {shelf_id} for SKU {sku_id}")
        else:
            logger.warning(f"[ProductQuery] 未找到SKU {sku_id} 对应的货架，shelf_id={target_shelf_id}")

        # 从 action_data 取出序列视频（fetch_turn / fetch_return / present）
        ad = self._current_action_data or {}
        seq_videos = ad.get("videos", [])
        def _get_seq_video(idx: int, fallback_key: str) -> str:
            if idx < len(seq_videos):
                return self._resolve_video_path(seq_videos[idx]["file"])
            return self._video(fallback_key)
        
        def _get_min_duration(idx: int, default: float) -> float:
            if idx < len(seq_videos):
                return seq_videos[idx].get("min_duration", 0) or default
            return default

        # 2. 转身去拿（通过调度器，可被高优先级打断）
        await self.video_scheduler.play_action(
            videos=[{"url": _get_seq_video(0, "fetch_turn"), "loop": False,
                     "min_duration": _get_min_duration(0, 2.0)}],
            priority=4, can_interrupt=True,
        )
        logger.info("[ACTION] product_query step 1/3: fetch_turn")
        await asyncio.sleep(_get_min_duration(0, 2.0))

        # 4. 显示手持商品 + 拿回动画
        await self.hub.broadcast({"action": "show_hand_item", "image": sku["assets"]["hand"]})
        await self.video_scheduler.play_action(
            videos=[{"url": _get_seq_video(1, "fetch_return"), "loop": False,
                     "min_duration": _get_min_duration(1, 1.5)}],
            priority=4, can_interrupt=True,
        )
        logger.info("[ACTION] product_query step 2/3: fetch_return")
        await asyncio.sleep(_get_min_duration(1, 1.5))

        # 5. 桌面展示 + 介绍视频（loop）
        await self.hub.broadcast({"action": "hide_hand_item"})
        await self.hub.broadcast({
            "action": "show_table_product",
            "image": sku["assets"]["table"],
            "video": sku["assets"]["video"],
        })
        await self.video_scheduler.play_action(
            videos=[{"url": _get_seq_video(2, "present"), "loop": True, "min_duration": 5.0}],
            priority=4, can_interrupt=True,
        )
        logger.info("[ACTION] product_query step 3/3: present")

        # 6. 弹窗显示价格信息卡（类型 B）
        single_price = sku["price_tiers"]["single"]["price"]
        cart_pos = sku.get("platforms", {}).get("douyin", {}).get("cart_position", 1)
        await self.hub.broadcast({
            "action": "show_popup",
            "type": "B",
            "duration_ms": 12000,
            "content": {
                "title": sku["name"],
                "items": [
                    {"label": "价格", "value": f"¥{single_price}", "highlight": True},
                    {"label": "规格", "value": sku.get("popup_data", {})
                                                 .get("basic_info", {})
                                                 .get("spec", "")},
                    {"label": "产地", "value": sku.get("popup_data", {})
                                                 .get("basic_info", {})
                                                 .get("origin", "")},
                ],
                "footer": f"小黄车第 {cart_pos} 个 ↓",
            },
        })

        # 7. AI生成介绍语 + TTS合成（价格防幻觉）
        await self._speak_with_tts(
            text=f"客官好眼力，这{sku['name']}只需{single_price}两~",
            use_ai=True,
            username="客官",
            message=f"介绍一下{sku['name']}",
            sku=sku
        )

    # ---------- 场景：下单感谢 ----------
    async def on_order_placed(self, username: str, sku_id: str = '', **kwargs):
        if not self._get_config("enable_order_response", True):
            logger.debug("Order response disabled, skipping")
            return
        sku = self.cfg.get_sku(sku_id)
        sku_name = sku.get("name", "商品") if sku else "商品"

        await self.hub.broadcast({"action": "play_effect", "effect": "order_celebration"})
        await self.hub.broadcast({
            "action": "show_popup",
            "type": "A",
            "duration_ms": 5000,
            "content": {"text": f"🎉 {username} 下单了 {sku_name}！"},
        })

        ref = self._pick_event_template("order_placed", username=username, sku_name=sku_name)
        ref_hint = f"\n参考话术风格（可改写，不要照抄）：{ref}" if ref else ""
        msg = f"[下单] {username}刚刚购买了{sku_name}，请热情庆祝并感谢{ref_hint}"
        await self.dialogue_queue.add_message(
            username=username,
            message=msg,
            priority=1,
            tags=["order"],
            source="order",
            sku_id=sku_id
        )

    # ---------- 场景：风格切换 ----------
    async def on_style_switch(self, old_style: str = '', new_style: str = '', **kwargs):
        char = self.cfg.get_character()
        styles = char.get("styles", {})
        if new_style not in styles:
            logger.warning(f"Unknown style: {new_style}")
            return

        # 过渡台词（使用AI生成更自然的切换语）
        switching = char.get("style_switching", {})
        transitions = switching.get("transition_dialogues", {})
        key = f"{old_style}_to_{new_style}"
        default_line = f"切换到{styles[new_style]['name']}模式~"
        line = transitions.get(key, [default_line])[0]
        
        # 使用AI生成风格切换语（如果AI可用）
        if self.ai.api_key:
            ai_line = await self.ai.chat(
                user_message=f"切换到{styles[new_style]['name']}风格",
                username="",
                character=char,
                style_id=new_style,
                sku=None
            )
            if ai_line:
                line = ai_line[0] if isinstance(ai_line, tuple) else ai_line

        # 播放切换视频（如果有）
        switch_video = self._video("style_switch")
        if switch_video:
            await self.hub.broadcast({
                "action": "play_video",
                "url": switch_video,
                "loop": False,
                "next_state": "idle",
                "next_video": self._video("idle"),
            })
        else:
            await self.hub.broadcast({
                "action": "play_video",
                "url": self._video("idle"),
                "loop": True,
            })
        
        # 同步风格（骨骼动画模式下简化）
        self._current_style = new_style
        
        # 播放切换语音
        await self.hub.broadcast({
            "action": "speak",
            "text": line,
            "style_changed": new_style,
        })
        logger.info(f"Style switched: {old_style} -> {new_style}")

    # ---------- 场景：礼物感谢 ----------
    async def on_gift_received(self, username: str, gift_name: str, count: int, is_big: bool = False):
        """
        礼物感谢
        
        Args:
            is_big: 是否是大礼物（价值>=100抖币）
        """
        # 立即中断当前播放
        effect = "gift_celebration_big" if is_big else "gift_celebration_small"
        await self.hub.broadcast({"action": "play_effect", "effect": effect})
        
        # 播放感谢视频
        await self.hub.broadcast({
            "action": "play_video",
            "url": self._video("thanks_gift"),
            "loop": False,
            "next_state": "idle",
            "next_video": self._video("idle"),
        })
        
        # AI生成感谢语
        await self._speak_with_tts(
            text=f"感谢{username}客官的{count}个{gift_name}！",
            use_ai=True,
            username=username,
            message=f"收到{count}个{gift_name}"
        )
        
        # 大礼物额外显示弹窗
        if is_big:
            await self.hub.broadcast({
                "action": "show_popup",
                "type": "A",
                "duration_ms": 8000,
                "content": {"text": f"感谢 {username} 的大礼！"},
            })

    # ---------- 初始化场景 ----------
    async def init_scene(self):
        scene = self.cfg.get_scene()
        await self.hub.broadcast({
            "action": "init_scene",
            "scene": scene,
            "current_style": self.cfg.get_current_style(),
            "skus": self.cfg.skus,
        })
        await self.hub.broadcast({
            "action": "play_video",
            "url": self._video("idle"),
            "loop": True,
        })
        self.set_state(HostState.IDLE)
        logger.info("Scene initialized, state set to IDLE")

    # ---------- 弹幕事件处理 ----------
    async def handle_danmaku(self, event: DanmakuEvent):
        """处理弹幕事件，转换为系统意图"""
        # 检查弹幕抓取开关（关闭后所有弹幕事件都被忽略）
        if not self._get_config("enable_danmaku", True):
            logger.debug(f"Danmaku disabled, dropping event: {event.type.value}")
            return

        logger.info(f"Danmaku: [{event.type.value}] {event.username}: {event.content or event.gift_name}")
        
        if event.type == DanmakuType.CHAT:
            # 普通弹幕 - 智能意图识别
            if DouyinDanmakuCrawler.is_product_query(event.content):
                # 商品查询
                sku_id = self.cfg.find_sku_by_keyword(event.content)
                if sku_id:
                    await self.event_queue.submit("product_query", {"sku_id": sku_id}, priority=4)
                else:
                    # 未匹配到SKU，用AI智能回复
                    await self.event_queue.submit("smart_chat", {
                        "username": event.username,
                        "message": event.content
                    }, priority=7)
            elif DouyinDanmakuCrawler.is_order_placed(event.content):
                # 下单确认
                sku_id = self.cfg.find_sku_by_keyword(event.content) or "tea_001"  # 默认第一个
                await self.event_queue.submit("order_placed", {
                    "username": event.username,
                    "sku_id": sku_id
                }, priority=1)
            else:
                # 普通聊天
                await self.event_queue.submit("smart_chat", {
                    "username": event.username,
                    "message": event.content
                }, priority=8)
        
        elif event.type == DanmakuType.GIFT:
            # 礼物事件：按配置表判断档位
            tier = self._resolve_gift_tier(event.gift_name, event.gift_value)
            tier_priority = {"gift_super": 1, "gift_big": 2, "gift_small": 5, "gift_tiny": 8}
            await self.event_queue.submit(tier, {
                "username": event.username,
                "gift_name": event.gift_name,
                "value": event.gift_value,
                "count": event.gift_count
            }, priority=tier_priority.get(tier, 5))
            logger.info(f"[GIFT] {event.username} 送 {event.gift_name}({event.gift_value}抖币) 判定为 {tier}")
        
        elif event.type == DanmakuType.ENTER:
            # 用户进入
            await self.event_queue.submit("user_enter", {
                "username": event.username
            }, priority=6)
        
        elif event.type == DanmakuType.LIKE:
            # 点赞（批量处理，降低频率）
            await self.event_queue.submit("like_received", {
                "username": event.username,
                "count": 1
            }, priority=9)
    
    # ========== Action Flow 回调方法 ==========
    
    async def _on_action_plan_ready(self, item, action_plan):
        """动作计划生成完成回调"""
        logger.info(f"[SceneDirector] Action plan ready for dialogue {item.id}: "
                   f"{len(action_plan.actions)} actions")
        # 可以在这里添加额外的处理，如预加载资源通知等
    
    async def _on_3d_execution_complete(self, item):
        """3D动作流执行完成回调"""
        logger.info(f"[SceneDirector] 3D execution completed for dialogue {item.id}")
        # 记录上一次动作计划，供AI关闭时复用
        if item.action_plan:
            self._last_action_plan = item.action_plan
    
    async def interrupt_current_action_flow(self, reason: str = "emergency"):
        """打断当前动作流（用于高优先级事件）"""
        if self.dialogue_queue:
            current = self.dialogue_queue._current_item
            if current and current.action_plan:
                await self.dialogue_queue.on_action_flow_interrupted(
                    current.id, reason
                )
                logger.info(f"[SceneDirector] Interrupted action flow: {reason}")

