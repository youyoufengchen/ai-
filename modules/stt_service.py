"""
语音识别服务 (STT)
支持多种提供商：
- openai: OpenAI Whisper API
- local_whisper: 本地 Whisper (无需API，免费)
- aliyun: 阿里云语音识别
- xfyun: 讯飞语音识别
- tencent: 腾讯云语音识别
"""
import asyncio
import base64
import io
import logging
import tempfile
import os
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)

class STTService:
    """语音识别服务"""
    
    def __init__(self):
        self.provider = "local_whisper"  # 默认使用本地Whisper（免费）
        self.api_key = None
        self.api_base = None
        self._local_model = None  # 本地模型缓存
        self._load_config()
    
    def _load_config(self):
        """从配置文件加载STT设置"""
        try:
            import json
            config_path = Path(__file__).parent.parent / "config" / "main.json"
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                stt_config = config.get("stt", {})
                self.provider = stt_config.get("provider", "openai")
                from modules.secrets_manager import get_secret
                self.api_key = stt_config.get("api_key") or get_secret("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
                self.api_base = stt_config.get("api_base") or get_secret("OPENAI_API_BASE")
        except Exception as e:
            logger.warning(f"加载STT配置失败: {e}")
            from modules.secrets_manager import get_secret
            self.api_key = get_secret("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    
    async def transcribe(self, audio_base64: str, language: str = "zh") -> Optional[str]:
        """
        将音频转换为文字
        
        Args:
            audio_base64: base64编码的音频数据
            language: 语言代码 (zh/en/ja等)
        
        Returns:
            识别出的文字，失败返回None
        """
        try:
            # 解码base64音频
            audio_bytes = base64.b64decode(audio_base64)
            
            # 路由到对应的提供商
            if self.provider == "openai":
                return await self._transcribe_openai(audio_bytes, language)
            elif self.provider == "local_whisper":
                return await self._transcribe_local(audio_bytes, language)
            elif self.provider == "aliyun":
                return await self._transcribe_aliyun(audio_bytes, language)
            elif self.provider == "xfyun":
                return await self._transcribe_xfyun(audio_bytes, language)
            elif self.provider == "tencent":
                return await self._transcribe_tencent(audio_bytes, language)
            else:
                logger.error(f"不支持的STT提供商: {self.provider}")
                return None
                
        except Exception as e:
            logger.error(f"语音识别失败: {e}")
            return None
    
    async def _transcribe_openai(self, audio_bytes: bytes, language: str) -> Optional[str]:
        """使用 OpenAI Whisper 识别"""
        try:
            import openai
            
            if not self.api_key:
                logger.error("OpenAI API Key 未设置")
                return None
            
            client = openai.AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.api_base or "https://api.openai.com/v1"
            )
            
            # 创建临时文件保存音频
            with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name
            
            try:
                # 调用 Whisper API
                with open(tmp_path, "rb") as audio_file:
                    response = await client.audio.transcriptions.create(
                        model="whisper-1",
                        file=audio_file,
                        language=language,
                        response_format="text"
                    )
                
                text = response.strip() if response else None
                if text:
                    logger.info(f"STT识别成功: {text[:50]}...")
                return text
                
            finally:
                # 清理临时文件
                try:
                    os.unlink(tmp_path)
                except:
                    pass
                    
        except Exception as e:
            logger.error(f"OpenAI Whisper 识别失败: {e}")
            return None
    
    async def _transcribe_local(self, audio_bytes: bytes, language: str) -> Optional[str]:
        """使用本地Whisper识别（无需API，完全免费）"""
        try:
            import whisper
            
            # 延迟加载模型（第一次使用时加载）
            if self._local_model is None:
                logger.info("正在加载本地Whisper模型 (base)...")
                # 可选: tiny, base, small, medium, large
                # base 是速度和准确率的平衡
                self._local_model = whisper.load_model("base")
                logger.info("本地Whisper模型加载完成")
            
            # 保存音频到临时文件
            with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name
            
            try:
                # 识别
                result = self._local_model.transcribe(
                    tmp_path,
                    language="zh" if language == "zh" else language,
                    fp16=False  # CPU运行用False
                )
                
                text = result.get("text", "").strip()
                if text:
                    logger.info(f"本地STT识别成功: {text[:50]}...")
                return text if text else None
                
            finally:
                try:
                    os.unlink(tmp_path)
                except:
                    pass
                    
        except ImportError:
            logger.error("未安装whisper包，请运行: pip install openai-whisper")
            return None
        except Exception as e:
            logger.error(f"本地Whisper识别失败: {e}")
            return None
    
    async def _transcribe_aliyun(self, audio_bytes: bytes, language: str) -> Optional[str]:
        """阿里云语音识别"""
        try:
            # 需要安装: pip install aliyun-python-sdk-nls-cloud-meta
            # 或使用REST API直接调用
            import requests
            
            from modules.secrets_manager import get_secret
            access_key = get_secret("ALIYUN_ACCESS_KEY_ID") or os.getenv("ALIYUN_ACCESS_KEY_ID")
            access_secret = get_secret("ALIYUN_ACCESS_KEY_SECRET") or os.getenv("ALIYUN_ACCESS_KEY_SECRET")
            app_key = get_secret("ALIYUN_NLS_APP_KEY") or os.getenv("ALIYUN_NLS_APP_KEY")
            
            if not all([access_key, access_secret, app_key]):
                logger.error("阿里云语音识别配置不完整，请设置环境变量")
                return None
            
            # 阿里云语音识别API
            url = "https://nls-gateway.cn-shanghai.aliyuncs.com/stream/v1/asr"
            
            headers = {
                "X-NLS-Token": self._get_aliyun_token(access_key, access_secret),
                "Content-type": "application/octet-stream",
                "X-NLS-AppKey": app_key
            }
            
            # 转换格式（阿里云需要特定格式）
            wav_bytes = self._convert_to_wav(audio_bytes)
            
            response = requests.post(url, headers=headers, data=wav_bytes, timeout=30)
            result = response.json()
            
            if result.get("status") == 20000000:
                text = result.get("result", "").strip()
                logger.info(f"阿里云STT识别成功: {text[:50]}...")
                return text
            else:
                logger.error(f"阿里云识别失败: {result}")
                return None
                
        except Exception as e:
            logger.error(f"阿里云语音识别失败: {e}")
            return None
    
    def _get_aliyun_token(self, access_key: str, access_secret: str) -> str:
        """获取阿里云Token（简化版，实际需要实现签名）"""
        # 这里简化处理，实际需要根据阿里云文档实现签名
        # 参考: https://help.aliyun.com/document_detail/72138.html
        return "placeholder_token"
    
    def _convert_to_wav(self, audio_bytes: bytes) -> bytes:
        """将音频转换为WAV格式（部分服务需要）"""
        try:
            # 使用pydub转换
            from pydub import AudioSegment
            
            # 假设输入是webm
            audio = AudioSegment.from_file(io.BytesIO(audio_bytes), format="webm")
            
            # 转换为WAV
            wav_io = io.BytesIO()
            audio.export(wav_io, format="wav")
            return wav_io.getvalue()
            
        except ImportError:
            logger.warning("未安装pydub，无法转换音频格式")
            return audio_bytes
        except Exception as e:
            logger.error(f"音频格式转换失败: {e}")
            return audio_bytes
    
    async def _transcribe_xfyun(self, audio_bytes: bytes, language: str) -> Optional[str]:
        """讯飞语音识别（WebSocket接口）"""
        # 讯飞需要WebSocket连接，实现较复杂
        logger.warning("讯飞语音识别尚未实现，请使用其他提供商")
        return None
    
    async def _transcribe_tencent(self, audio_bytes: bytes, language: str) -> Optional[str]:
        """腾讯云语音识别"""
        try:
            from tencentcloud.common import credential
            from tencentcloud.common.profile.client_profile import ClientProfile
            from tencentcloud.common.profile.http_profile import HttpProfile
            from tencentcloud.asr.v20190614 import asr_client, models
            
            from modules.secrets_manager import get_secret
            secret_id = get_secret("TENCENT_SECRET_ID") or os.getenv("TENCENT_SECRET_ID")
            secret_key = get_secret("TENCENT_SECRET_KEY") or os.getenv("TENCENT_SECRET_KEY")
            
            if not all([secret_id, secret_key]):
                logger.error("腾讯云语音识别配置不完整")
                return None
            
            cred = credential.Credential(secret_id, secret_key)
            http_profile = HttpProfile()
            client_profile = ClientProfile()
            client_profile.httpProfile = http_profile
            
            client = asr_client.AsrClient(cred, "ap-guangzhou", client_profile)
            
            req = models.SentenceRecognitionRequest()
            req.SourceType = 1  # 语音数据
            req.VoiceFormat = "webm"
            req.Data = base64.b64encode(audio_bytes).decode()
            req.DataLen = len(audio_bytes)
            
            resp = client.SentenceRecognition(req)
            
            text = resp.Result
            if text:
                logger.info(f"腾讯云STT识别成功: {text[:50]}...")
            return text
            
        except ImportError:
            logger.error("未安装腾讯云SDK，请运行: pip install tencentcloud-sdk-python")
            return None
        except Exception as e:
            logger.error(f"腾讯云语音识别失败: {e}")
            return None
    
    async def transcribe_with_timestamp(self, audio_base64: str, language: str = "zh") -> dict:
        """
        带时间戳的语音识别（用于长语音）
        
        Returns:
            {
                "text": "完整文字",
                "segments": [
                    {"start": 0.0, "end": 2.5, "text": "片段文字"}
                ]
            }
        """
        try:
            audio_bytes = base64.b64decode(audio_base64)
            
            import openai
            
            if not self.api_key:
                return {"text": None, "segments": [], "error": "API Key未设置"}
            
            client = openai.AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.api_base or "https://api.openai.com/v1"
            )
            
            with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name
            
            try:
                with open(tmp_path, "rb") as audio_file:
                    response = await client.audio.transcriptions.create(
                        model="whisper-1",
                        file=audio_file,
                        language=language,
                        response_format="verbose_json",
                        timestamp_granularities=["segment"]
                    )
                
                return {
                    "text": response.text,
                    "segments": [
                        {
                            "start": s.start,
                            "end": s.end,
                            "text": s.text
                        }
                        for s in response.segments
                    ]
                }
                
            finally:
                try:
                    os.unlink(tmp_path)
                except:
                    pass
                    
        except Exception as e:
            logger.error(f"带时间戳识别失败: {e}")
            return {"text": None, "segments": [], "error": str(e)}

# 全局实例
_stt_service = None

def get_stt_service() -> STTService:
    """获取STT服务实例"""
    global _stt_service
    if _stt_service is None:
        _stt_service = STTService()
    return _stt_service
