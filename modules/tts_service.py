"""
TTS语音合成服务

降级链（优先级从高到低）：
1. MiniMax TTS（需 MINIMAX_API_KEY + MINIMAX_GROUP_ID，音质最自然）
2. 火山引擎 TTS（需 VOLC_TTS_APPID + VOLC_TTS_TOKEN）
3. Edge TTS（微软语音，免费，无需 key）
4. 浏览器 Web Speech API（最低兜底）
"""

import logging
import os
import hashlib
from typing import Dict, Any, Optional
from pathlib import Path
import aiohttp
import base64

logger = logging.getLogger("tts_service")

class TTSService:
    """
    火山引擎TTS服务封装
    
    需要环境变量：
    - VOLC_TTS_APPID: 应用ID
    - VOLC_TTS_TOKEN: 访问令牌
    """
    
    API_BASE = "https://openspeech.bytedance.com/api/v1/tts"

    # 音色映射表（火山引擎标准语音合成，免费200万字/月）
    DEFAULT_VOICE_MAP = {
        "classical": "BV001_streaming",   # 通用女声 - 温柔
        "cute":      "BV002_streaming",   # 甜美女声 - 活泼嗲妹
        "dominant":  "BV007_streaming",   # 知性女声 - 御姐
    }

    # 使用标准语音合成集群（非豆包）
    CLUSTER = "volcano_tts"
    
    def __init__(
        self,
        app_id: Optional[str] = None,
        token: Optional[str] = None,
        voice_map: Optional[Dict[str, str]] = None
    ):
        # 优先从配置中心读取，其次环境变量
        from modules.secrets_manager import get_secret
        self.app_id = app_id or get_secret("VOLC_TTS_APPID") or os.getenv("VOLC_TTS_APPID")
        self.token = token or get_secret("VOLC_TTS_TOKEN") or os.getenv("VOLC_TTS_TOKEN")
        self.voice_map = voice_map or self.DEFAULT_VOICE_MAP
        
        # 音频缓存目录
        self.cache_dir = Path(__file__).parent.parent / "cache" / "tts"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        if not self.app_id or not self.token:
            logger.warning("VOLC_TTS_APPID or VOLC_TTS_TOKEN not set, TTS will use browser fallback")
    
    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer; {self.token}",
            "Content-Type": "application/json"
        }
    
    def _get_cache_path(self, text: str, voice: str) -> Path:
        """根据文本和音色生成缓存路径"""
        # 取前50字做hash，避免文件名过长
        text_hash = hashlib.md5(f"{text}:{voice}".encode()).hexdigest()[:16]
        return self.cache_dir / f"{voice}_{text_hash}.mp3"
    
    async def synthesize(
        self,
        text: str,
        style_id: str = "classical",
        use_cache: bool = True,
        rate: float = 1.0,
        voice_settings: Optional[Dict[str, Any]] = None,
        with_viseme: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        合成语音
        
        Args:
            text: 要合成的文本
            style_id: 风格ID（对应不同音色）
            use_cache: 是否使用缓存
            with_viseme: 是否请求返回 viseme 时间轴（口型同步数据）
        
        Returns:
            {
                "url": "/cache/tts/xxx.mp3",
                "viseme_timeline": [...] or None
            }
            或 None（失败时）
        """
        if not self.app_id or not self.token:
            logger.debug("TTS service not configured")
            return None
        
        voice = self.voice_map.get(style_id, "zh_female_qingxin")
        cache_path = self._get_cache_path(text, voice)
        
        # 检查缓存（同时检查 viseme 缓存）
        viseme_cache_path = cache_path.with_suffix('.viseme.json')
        if use_cache and cache_path.exists():
            logger.debug(f"TTS cache hit: {cache_path}")
            cached_viseme = None
            if viseme_cache_path.exists():
                try:
                    import json as _json
                    cached_viseme = _json.loads(viseme_cache_path.read_text(encoding='utf-8'))
                    logger.debug(f"TTS viseme cache hit: {len(cached_viseme)} frames")
                except Exception:
                    pass
            return {"url": f"/cache/tts/{cache_path.name}", "viseme_timeline": cached_viseme}
        
        # 调用API合成
        vs = voice_settings or {}
        speed_ratio = rate * vs.get("speed", 1.0)
        pitch_ratio  = 1.0 + vs.get("pitch", 0.0) * 0.1  # pitch: -1~1 -> 0.9~1.1
        payload = {
            "app": {
                "appid": self.app_id,
                "token": self.token,
                "cluster": self.CLUSTER
            },
            "user": {
                "uid": "virtual_host_001"
            },
            "audio": {
                "voice_type": voice,
                "encoding": "mp3",
                "speed_ratio": round(speed_ratio, 2),
                "volume_ratio": 1.0,
                "pitch_ratio": round(pitch_ratio, 2),
            },
            "request": {
                "reqid": str(hash(text) % 100000000),
                "text": text,
                "operation": "query",
                **({
                    "with_frontend": 1,
                    "frontend_type": "unitTson"
                } if with_viseme else {})
            }
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.API_BASE,
                    headers=self._get_headers(),
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error(f"TTS API error: {resp.status} - {error_text}")
                        return None
                    
                    result = await resp.json()
                    
                    # 火山TTS成功码是3000（非标准，不是0）
                    if result.get("code") not in (0, 3000):
                        logger.error(f"TTS API error: {result.get('message')}")
                        return None
                    
                    # 解码base64音频数据
                    audio_data = result.get("data") or result.get("audio", {}).get("data", "")
                    audio_bytes = base64.b64decode(audio_data)
                    
                    # 保存到缓存
                    cache_path.write_bytes(audio_bytes)
                    
                    # 提取 viseme 时间轴（火山引擎 unitTson 格式）— 提前提取以便缓存
                    viseme_timeline = None
                    try:
                        addition = result.get("addition") or {}
                        frontend_data = addition.get("frontend") or result.get("frontend")
                        if frontend_data:
                            import json as _json
                            raw = frontend_data if isinstance(frontend_data, list) else _json.loads(frontend_data)
                            viseme_timeline = raw
                            logger.debug(f"TTS viseme: {len(viseme_timeline)} frames")
                            # 缓存 viseme 数据到独立 JSON 文件
                            viseme_cache_path.write_text(
                                _json.dumps(viseme_timeline, ensure_ascii=False),
                                encoding='utf-8'
                            )
                    except Exception as e_v:
                        logger.debug(f"TTS viseme parse skip: {e_v}")
                    
                    # LRU 缓存清理（异步触发，不阻塞）
                    try:
                        from modules.cache_manager import get_cache_manager
                        get_cache_manager().cleanup()
                    except Exception:
                        pass
                    
                    logger.info(f"TTS synthesized: {len(audio_bytes)} bytes, viseme={'yes' if viseme_timeline else 'no'}")
                    return {"url": f"/cache/tts/{cache_path.name}", "viseme_timeline": viseme_timeline}
                    
        except Exception as e:
            logger.error(f"TTS synthesis error: {e}")
            return None

    async def synthesize_url(self, text: str, **kwargs) -> Optional[str]:
        """向后兼容的简化接口，只返回URL字符串"""
        result = await self.synthesize(text, **kwargs)
        return result["url"] if result else None

    def clear_cache(self, max_age_days: int = 7):
        """清理过期缓存"""
        import time
        now = time.time()
        max_age_seconds = max_age_days * 24 * 3600
        
        cleared = 0
        for file_path in self.cache_dir.glob("*.mp3"):
            if now - file_path.stat().st_mtime > max_age_seconds:
                file_path.unlink()
                cleared += 1
        
        logger.info(f"Cleared {cleared} old TTS cache files")
        return cleared


class MiniMaxTTSService:
    """
    MiniMax TTS 服务封装（T2A v2接口，音质自然有情感）

    需要环境变量：
    - MINIMAX_API_KEY: API Key
    - MINIMAX_GROUP_ID: Group ID
    """

    API_URL = "https://api.minimax.chat/v1/t2a_v2"

    # 各风格音色映射（MiniMax内置音色）
    VOICE_MAP = {
        "classical": "female-shaonv",    # 少女音 - 温柔古典
        "cute":      "female-tianmei",   # 甜美音 - 活泼嗲妹
        "dominant":  "female-yujie",     # 御姐音 - 高冷成熟
    }

    # 情感映射
    EMOTION_MAP = {
        "classical": "happy",
        "cute":      "happy",
        "dominant":  "neutral",
    }

    def __init__(self):
        # 优先从配置中心读取，其次环境变量
        from modules.secrets_manager import get_secret
        self.api_key   = get_secret("MINIMAX_API_KEY") or os.getenv("MINIMAX_API_KEY")
        self.group_id  = get_secret("MINIMAX_GROUP_ID") or os.getenv("MINIMAX_GROUP_ID")
        self.cache_dir = Path(__file__).parent.parent / "cache" / "tts_minimax"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        # URL -> 实际音频时长（秒），用于精确等待
        self.audio_durations: Dict[str, float] = {}
        if not self.api_key or not self.group_id:
            logger.warning("MINIMAX_API_KEY or MINIMAX_GROUP_ID not set")

    def _duration_path(self, mp3_path: Path) -> Path:
        return mp3_path.with_suffix('.dur')

    def get_duration(self, url: Optional[str]) -> Optional[float]:
        """根据audio_url查询实际时长（秒），不可用返回None"""
        if not url:
            return None
        if url in self.audio_durations:
            return self.audio_durations[url]
        # 尝试从.dur边车文件读取（针对缓存命中）
        try:
            name = url.split('/')[-1]
            dur_file = self.cache_dir / (name.rsplit('.', 1)[0] + '.dur')
            if dur_file.exists():
                d = float(dur_file.read_text().strip())
                self.audio_durations[url] = d
                return d
        except Exception:
            pass
        return None

    def _get_cache_path(self, text: str, voice: str, emotion: str) -> Path:
        key = f"{text}:{voice}:{emotion}"
        h = hashlib.md5(key.encode()).hexdigest()[:16]
        return self.cache_dir / f"mm_{voice}_{h}.mp3"

    async def synthesize(
        self,
        text: str,
        style_id: str = "classical",
        use_cache: bool = True,
        rate: float = 1.0,
        voice_settings: Optional[Dict[str, Any]] = None,
        emotion: Optional[str] = None
    ) -> Optional[str]:
        if not self.api_key or not self.group_id:
            return None

        vs       = voice_settings or {}
        speed    = round(rate * vs.get("speed", 1.0), 2)
        voice    = self.VOICE_MAP.get(style_id, "female-shaonv")
        # 外部传入的 emotion 优先（由 AI 动态决定），否则用风格默认值
        _valid_emotions = {"happy", "sad", "angry", "fearful", "disgusted", "surprised", "neutral"}
        _raw_emotion = (emotion or "").strip().lower()
        emotion = _raw_emotion if _raw_emotion in _valid_emotions else self.EMOTION_MAP.get(style_id, "happy")
        cache_path = self._get_cache_path(text, voice, emotion)

        if use_cache and cache_path.exists():
            logger.debug(f"MiniMax TTS cache hit: {cache_path.name}")
            return f"/cache/tts_minimax/{cache_path.name}"

        payload = {
            "model": "speech-02-hd",
            "text": text,
            "stream": False,
            "voice_setting": {
                "voice_id": voice,
                "speed":    speed,
                "emotion":  emotion,
            },
            "audio_setting": {
                "audio_sample_rate": 32000,
                "bitrate":           128000,
                "format":            "mp3",
            }
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type":  "application/json",
        }
        params = {"GroupId": self.group_id} if self.group_id else {}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.API_URL, headers=headers, params=params, json=payload,
                    timeout=aiohttp.ClientTimeout(total=20)
                ) as resp:
                    if resp.status != 200:
                        logger.error(f"MiniMax TTS HTTP {resp.status}: {await resp.text()}")
                        return None
                    j = await resp.json()
                    # 成功：base_resp.status_code == 0
                    if j.get("base_resp", {}).get("status_code") != 0:
                        logger.error(f"MiniMax TTS error: {j.get('base_resp')}")
                        return None
                    audio_hex = j.get("data", {}).get("audio")
                    if not audio_hex:
                        logger.error("MiniMax TTS: empty audio data")
                        return None
                    # MiniMax T2A v2 返回 hex 编码的音频数据
                    cache_path.write_bytes(bytes.fromhex(audio_hex))
                    
                    # LRU 缓存清理
                    try:
                        from modules.cache_manager import get_cache_manager
                        get_cache_manager().cleanup()
                    except Exception:
                        pass
                    
                    # 提取实际音频时长（毫秒），写入边车文件供缓存命中读取
                    audio_len_ms = (j.get("extra_info") or {}).get("audio_length")
                    url = f"/cache/tts_minimax/{cache_path.name}"
                    if isinstance(audio_len_ms, (int, float)) and audio_len_ms > 0:
                        dur_s = audio_len_ms / 1000.0
                        self.audio_durations[url] = dur_s
                        try:
                            self._duration_path(cache_path).write_text(f"{dur_s:.3f}")
                        except Exception:
                            pass
                        logger.info(f"MiniMax TTS synthesized: {cache_path.name} ({style_id}, speed={speed}, dur={dur_s:.2f}s)")
                    else:
                        logger.info(f"MiniMax TTS synthesized: {cache_path.name} ({style_id}, speed={speed})")
                    return url
        except Exception as e:
            logger.error(f"MiniMax TTS synthesis error: {e}")
            return None

    def clear_cache(self, max_age_days: int = 7):
        import time
        now = time.time()
        cleared = 0
        for f in self.cache_dir.glob("*.mp3"):
            if now - f.stat().st_mtime > max_age_days * 86400:
                f.unlink()
                cleared += 1
        logger.info(f"MiniMax TTS: cleared {cleared} cache files")
        return cleared


class EdgeTTSService:
    """
    Edge TTS 服务封装（微软语音，完全免费，无需 API Key）
    
    使用 edge-tts 库调用微软在线语音合成
    pip install edge-tts
    """

    # 各风格音色映射（微软神经网络语音）
    VOICE_MAP = {
        "classical": "zh-CN-XiaoxiaoNeural",   # 晓晓 - 温婉，适合古风
        "cute":      "zh-CN-XiaoyiNeural",     # 小艺 - 活泼，适合嗲妹
        "dominant":  "zh-CN-YunyangNeural",    # 云扬 - 沉稳有力，适合御姐/高冷
    }

    def __init__(self):
        self.cache_dir = Path(__file__).parent.parent / "cache" / "tts_edge"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._available = None  # 延迟检测

    async def _check_available(self) -> bool:
        if self._available is None:
            try:
                import edge_tts  # noqa
                self._available = True
            except ImportError:
                self._available = False
                logger.warning("edge-tts not installed, run: pip install edge-tts")
        return self._available

    def _get_cache_path(self, text: str, voice: str, rate_str: str) -> Path:
        key = f"{text}:{voice}:{rate_str}"
        h = hashlib.md5(key.encode()).hexdigest()[:16]
        return self.cache_dir / f"{voice}_{h}.mp3"

    async def synthesize(
        self,
        text: str,
        style_id: str = "classical",
        use_cache: bool = True,
        rate: float = 1.0,
        voice_settings: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """
        合成语音，返回 /cache/tts_edge/xxx.mp3 URL 或 None
        """
        if not await self._check_available():
            return None

        import edge_tts

        vs = voice_settings or {}
        speed = rate * vs.get("speed", 1.0)
        # edge-tts rate 格式："+10%" / "-10%"，相对于默认速度
        rate_pct = int((speed - 1.0) * 100)
        rate_str = f"+{rate_pct}%" if rate_pct >= 0 else f"{rate_pct}%"

        # pitch: voice_settings.pitch  -1~1  -> "-5Hz" ~ "+5Hz"
        pitch_hz = int(vs.get("pitch", 0.0) * 5)
        pitch_str = f"+{pitch_hz}Hz" if pitch_hz >= 0 else f"{pitch_hz}Hz"

        voice = self.VOICE_MAP.get(style_id, "zh-CN-XiaoxiaoNeural")
        cache_path = self._get_cache_path(text, voice, rate_str)

        if use_cache and cache_path.exists():
            logger.debug(f"Edge TTS cache hit: {cache_path.name}")
            return f"/cache/tts_edge/{cache_path.name}"

        try:
            communicate = edge_tts.Communicate(
                text=text,
                voice=voice,
                rate=rate_str,
                pitch=pitch_str,
            )
            await communicate.save(str(cache_path))
            
            # LRU 缓存清理
            try:
                from modules.cache_manager import get_cache_manager
                get_cache_manager().cleanup()
            except Exception:
                pass
            
            logger.info(f"Edge TTS synthesized: {cache_path.name} ({style_id}, rate={rate_str})")
            return f"/cache/tts_edge/{cache_path.name}"
        except Exception as e:
            logger.error(f"Edge TTS synthesis error: {e}")
            return None

    def clear_cache(self, max_age_days: int = 7):
        import time
        now = time.time()
        cleared = 0
        for f in self.cache_dir.glob("*.mp3"):
            if now - f.stat().st_mtime > max_age_days * 86400:
                f.unlink()
                cleared += 1
        logger.info(f"Edge TTS: cleared {cleared} cache files")
        return cleared


class BrowserTTSFallback:
    """
    浏览器端TTS降级方案
    
    当火山TTS不可用时，前端可用Web Speech API
    这个类提供配置信息给前端
    """
    
    # Web Speech API 语音映射
    VOICE_MAP = {
        "classical": "zh-CN-XiaoxiaoNeural",  # 微软晓晓，偏正式
        "cute": "zh-CN-XiaoyiNeural",          # 微软小艺，偏活泼
        "dominant": "zh-CN-YunxiNeural",       # 微软云希，偏稳重
    }
    
    @classmethod
    def get_voice_for_style(cls, style_id: str) -> str:
        return cls.VOICE_MAP.get(style_id, "zh-CN-XiaoxiaoNeural")
    
    @classmethod
    def get_config(cls, style_id: str, rate: float = 1.0, volume: float = 1.0,
                   voice_settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """获取浏览器TTS配置，合并 voice_settings 里的 speed/pitch"""
        vs = voice_settings or {}
        return {
            "enabled": True,
            "voice": cls.get_voice_for_style(style_id),
            "rate": round(rate * vs.get("speed", 1.0), 2),
            "pitch": 1.0 + vs.get("pitch", 0.0) * 0.1,
            "volume": volume,
        }
