"""
AI对话服务 - DeepSeek API集成

核心功能：
- 多风格人设对话生成（从 characters.json 读取 prompt_personality）
- 全局直播上下文（当前商品、在线人数、近期问题）
- 价格信息防幻觉（模板+后校验）
- 上下文管理（全局共享最近10轮）
- 意图识别增强（关键词+AI fallback）
"""

import logging
import os
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
import aiohttp
import re

logger = logging.getLogger("ai_service")


@dataclass
class DialogueContext:
    """对话上下文"""
    role: str  # user / assistant
    content: str
    timestamp: float = field(default_factory=lambda: __import__('time').time())


class LiveContext:
    """
    全局直播上下文 - 主播知道居小的事情
    """
    def __init__(self):
        self.current_sku: Optional[Dict] = None
        self.recent_skus: List[Dict] = []
        self.viewer_count: int = 0
        self.recent_questions: List[str] = []
        self.order_count_session: int = 0
        self.style_id: str = "classical"

    def set_sku(self, sku: Optional[Dict]):
        self.current_sku = sku
        if sku and sku not in self.recent_skus:
            self.recent_skus.append(sku)
            if len(self.recent_skus) > 3:
                self.recent_skus.pop(0)

    def add_question(self, q: str):
        self.recent_questions.append(q)
        if len(self.recent_questions) > 5:
            self.recent_questions.pop(0)

    def to_prompt_snippet(self) -> str:
        parts = []
        if self.current_sku:
            name  = self.current_sku.get('name', '')
            price = self.current_sku.get('price') \
                    or self.current_sku.get('price_tiers', {}).get('single', {}).get('price', 0)
            parts.append(f"当前展示商品：{name}（{price}元）")
        if self.viewer_count:
            parts.append(f"当前在线：{self.viewer_count}人")
        if self.order_count_session:
            parts.append(f"本场已成交：{self.order_count_session}单")
        if self.recent_questions:
            parts.append(f"刚才的问题：{'  /  '.join(self.recent_questions[-3:])}")
        return "\n".join(parts) if parts else ""


class AIService:
    """
    DeepSeek AI服务封装

    使用环境变量 DEEPSEEK_API_KEY 进行认证
    """

    API_BASE = "https://api.deepseek.com/v1"

    # 各风格口头禅和情绪动作
    STYLE_HINTS = {
        "classical": {
            "catchphrases": ["客官", "小店", "坊主", "这厢", "呢", "~"],
            "fillers":      ["（掩唇轻笑）", "（扇风轻摇）", "（微微颔首）", "（拂袖）"],
            "tone":         "温婉含蓄，偶有俏皮，句尾常带语气词",
        },
        "cute": {
            "catchphrases": ["嘛", "啦", "呢", "人家", "~"],
            "fillers":      ["（摇摇头）", "（歪头）", "（捂脸）"],
            "tone":         "软萌撒娇，句子短，爱用叠词",
        },
        "dominant": {
            "catchphrases": ["本坊主", "哼", "罢了"],
            "fillers":      ["（冷哼）", "（抬眼）", "（扫视）"],
            "tone":         "简短有力，命令口吻，不废话",
        },
    }

    def __init__(self, api_key: Optional[str] = None):
        from modules.secrets_manager import get_secret
        self.api_key = api_key or get_secret("DEEPSEEK_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
        if not self.api_key:
            logger.warning("DEEPSEEK_API_KEY not set, AI service will be disabled")

        # 全局对话历史（所有用户共享，最近 10 轮）
        self.global_history: List[DialogueContext] = []
        self.max_context = 10

        # 直播上下文
        self.live_ctx = LiveContext()

        # 价格校验正则
        self.price_pattern = re.compile(r'(\d+)[元块]')

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def _build_system_prompt(self, character: Dict[str, Any], style_id: str, sku: Optional[Dict] = None) -> str:
        style  = character.get("styles", {}).get(style_id, {})
        # 优先用 prompt_personality，干货字段
        persona = style.get("prompt_personality") or style.get("persona", "")
        hints   = self.STYLE_HINTS.get(style_id, self.STYLE_HINTS["classical"])

        # === 核心人设 ===
        prompt_parts = [
            "## 人设",
            persona,
            "",
            "## 说话风格",
            f"语气：{hints['tone']}",
            f"口头禅：{'  '.join(hints['catchphrases'])}",
            f"情绪动作（可在回复开头加）：{'  '.join(hints['fillers'])}",
            "",
            "## 直播场景话术规则",
            "1. 回复严格在 40 字以内，适合直播弹幕展示",
            "2. 如涉及价格必须用下方【商品信息】中的数字，绝不能编造",
            "3. 回复可在开头加一个情绪动作（括号内）提升代入感",
            "4. 遗忘广告语气，像对老朋友说话一样自然",
            "5. 禁止提到现代词（优惠码/链接/拍下/砍价等）",
            "6. 回复末尾必须加情感标签，格式：[e:情感]，从 happy/sad/angry/surprised/neutral 选一个",
            "   示例：（掩唇轻笑）客官好眼光~[e:happy]",
            "",
            "## 特殊场景识别",
            "- 消息以 [大额礼物] 开头：用户送了大礼物，必须热情洋溢、夸张感谢，情感标签用 happy 或 surprised",
            "- 消息以 [礼物] 开头：用户送了小礼物，温暖感谢即可，情感标签用 happy",
            "- 消息以 [下单] 开头：用户刚下单，热情庆祝、感谢并可简短介绍商品亮点，情感标签用 happy",
            "  以上三类消息，直接生成感谢话术，不要重复括号里的场景描述",
        ]

        # === 商品信息（防幻觉）===
        active_sku = sku or self.live_ctx.current_sku
        if active_sku:
            # 兼容新旧两种数据格式
            # 新格式：price / highlights / attributes / description
            # 旧格式：price_tiers / popup_data.highlights / popup_data.basic_info
            price_flat = active_sku.get("price", 0)
            p_single  = price_flat or active_sku.get("price_tiers", {}).get("single", {}).get("price", 0)
            p_double  = active_sku.get("price_tiers", {}).get("double", {}).get("price", 0)
            p_triple  = active_sku.get("price_tiers", {}).get("triple", {}).get("price", 0)

            # 规格/产地：优先新格式 attributes，回落旧格式 popup_data
            attributes_new = active_sku.get("attributes", {})
            spec   = attributes_new.get("规格") or attributes_new.get("spec") \
                     or active_sku.get("popup_data", {}).get("basic_info", {}).get("spec", "")
            origin = attributes_new.get("产地") or attributes_new.get("origin") \
                     or active_sku.get("popup_data", {}).get("basic_info", {}).get("origin", "")

            # 卖点：优先新格式 highlights 列表，回落旧格式 popup_data.highlights
            highlights_new = active_sku.get("highlights", [])
            highlight_old  = active_sku.get("popup_data", {}).get("highlights", [])
            highlights = highlights_new or highlight_old

            # 商品描述
            description = active_sku.get("description", "")

            info_lines = [
                "",
                "## 当前商品信息（价格必须精确，不可编造）",
                f"名称：{active_sku.get('name', '')}",
                f"价格：{p_single}元" if p_single else "",
                f"两件优惠：{p_double}元" if p_double else "",
                f"三件囤货：{p_triple}元" if p_triple else "",
                f"规格：{spec}" if spec else "",
                f"产地：{origin}" if origin else "",
            ]
            # 其余属性字段（产地/规格之外的）
            skip_keys = {"规格", "spec", "产地", "origin"}
            extra_attrs = [(k, v) for k, v in attributes_new.items() if k not in skip_keys and v]
            for k, v in extra_attrs[:6]:  # 最多注入6个属性，避免prompt过长
                info_lines.append(f"{k}：{v}")

            if highlights:
                info_lines.append(f"核心卖点：{'  /  '.join(highlights[:4])}")
            if description:
                info_lines.append(f"商品简介：{description[:80]}")  # 截断避免过长

            prompt_parts += [line for line in info_lines if line != ""]

        # === 直播现场上下文 ===
        ctx_snippet = self.live_ctx.to_prompt_snippet()
        if ctx_snippet:
            prompt_parts += ["", "## 直播现场信息", ctx_snippet]

        return "\n".join(filter(None, prompt_parts))

    def _validate_price_in_response(self, response: str, sku: Optional[Dict]) -> str:
        """后处理：校验响应中的价格是否与SKU一致，偏差>20%则修正"""
        if not sku:
            return response

        price_single = sku.get("price_tiers", {}).get("single", {}).get("price", 0)
        prices_found = self.price_pattern.findall(response)

        for price_str in prices_found:
            price_int = int(price_str)
            if abs(price_int - price_single) > (price_single * 0.2) and price_single > 0:
                logger.warning(f"Price hallucination detected: said {price_int}, actual {price_single}")
                response = response.replace(f"{price_int}元", f"{price_single}两")
                response = response.replace(f"{price_int}块", f"{price_single}两")

        return response

    async def chat(
        self,
        user_message: str,
        username: str,
        character: Dict[str, Any],
        style_id: str,
        sku: Optional[Dict] = None,
        session_id: str = "default"
    ) -> str:
        if not self.api_key:
            return self._fallback_response(user_message, style_id, sku)

        # 更新直播上下文
        self.live_ctx.style_id = style_id
        if sku:
            self.live_ctx.set_sku(sku)
        self.live_ctx.add_question(user_message)

        system_prompt = self._build_system_prompt(character, style_id, sku)

        # 全局共享历史（最近 max_context 轮）
        messages = [{"role": "system", "content": system_prompt}]
        for ctx in self.global_history[-self.max_context:]:
            messages.append({"role": ctx.role, "content": ctx.content})

        user_msg = f"[{username}]: {user_message}"
        messages.append({"role": "user", "content": user_msg})

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.API_BASE}/chat/completions",
                    headers=self._get_headers(),
                    json={
                        "model": "deepseek-chat",
                        "messages": messages,
                        "max_tokens": 80,
                        "temperature": 0.85,
                        "presence_penalty": 0.6,
                        "frequency_penalty": 0.3,
                    },
                    timeout=aiohttp.ClientTimeout(total=8)
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error(f"DeepSeek API error: {resp.status} - {error_text}")
                        return self._fallback_response(user_message, style_id, sku)

                    result = await resp.json()
                    ai_response = result["choices"][0]["message"]["content"]

                    # 价格校验
                    ai_response = self._validate_price_in_response(ai_response, sku or self.live_ctx.current_sku)

                    # 解析情感标签 [e:xxx]
                    emotion = "happy"
                    emo_match = re.search(r'\[e:(\w+)\]', ai_response)
                    if emo_match:
                        emotion = emo_match.group(1)
                        ai_response = ai_response[:emo_match.start()].strip()

                    # 写入全局历史（存净文本）
                    self.global_history.append(DialogueContext(role="user",      content=user_msg))
                    self.global_history.append(DialogueContext(role="assistant", content=ai_response))
                    if len(self.global_history) > self.max_context * 2:
                        self.global_history = self.global_history[-(self.max_context * 2):]

                    logger.debug(f"AI reply ({style_id}, e={emotion}): {ai_response[:50]}")
                    return ai_response.strip(), emotion

        except Exception as e:
            logger.error(f"AI chat error: {e}")
            return self._fallback_response(user_message, style_id, sku)

    def _fallback_response(self, user_message: str, style_id: str = "classical", sku: Optional[Dict] = None):
        """兜底回复（AI不可用时），按风格分化，返回 (text, emotion)"""
        active_sku = sku or self.live_ctx.current_sku
        if active_sku:
            price = active_sku.get("price_tiers", {}).get("single", {}).get("price", 0)
            name  = active_sku.get('name', '茶')
            if style_id == "dominant":
                return f"这{name}，{price}元，要要？", "neutral"
            elif style_id == "cute":
                return f"这{name}只要{price}元啊，超划算的啦~", "happy"
            else:
                return f"客官好眼力！这{name}单盒{price}两银子~", "happy"

        if style_id == "dominant":
            return "随便看，有思路再说。", "neutral"
        elif style_id == "cute":
            return "客官慢慢看啊，人家帮你介绍啦~", "happy"
        else:
            return "客官说得是~小店这茶都是上等货色！", "happy"

    async def recognize_intent(
        self,
        message: str,
        keywords_map: Dict[str, List[str]]
    ) -> str:
        """意图识别（关键词优先，AI fallback）"""
        message_lower = message.lower()
        for intent, keywords in keywords_map.items():
            for kw in keywords:
                if kw in message_lower:
                    return intent

        if not self.api_key:
            return "general_chat"

        prompt = f"""判断用户意图，从以下选项中选择最匹配的一个：
- product_query: 询问商品价格、规格、产地等
- order_placed: 下单、购买、已拍
- gift_big: 大额礼物、打赏
- gift_small: 小额礼物、小心心
- user_enter: 进入直播间、关注
- general_chat: 闲聊、打招呼、无明确意图

用户消息：{message}

只返回意图名称，不要解释。"""

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.API_BASE}/chat/completions",
                    headers=self._get_headers(),
                    json={
                        "model": "deepseek-chat",
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 20,
                        "temperature": 0.1,
                    },
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        intent = result["choices"][0]["message"]["content"].strip().lower()
                        intent = intent.replace("-", "_").replace(" ", "_")
                        if intent in keywords_map:
                            return intent
        except Exception as e:
            logger.warning(f"Intent recognition AI fallback failed: {e}")

        return "general_chat"

    def clear_context(self, session_id: str = "default"):
        """清除全局对话历史"""
        self.global_history.clear()
        logger.info("Global dialogue history cleared")
