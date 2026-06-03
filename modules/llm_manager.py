"""
大模型接口管理系统
支持多种大模型提供商的统一接口，安全的密钥管理
"""

import json
import hashlib
import base64
from typing import Dict, Any, Optional, List
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
import aiohttp
import asyncio
import os
from pathlib import Path

class ModelProvider(Enum):
    """支持的模型提供商"""
    OPENAI = "openai"
    DEEPSEEK = "deepseek"
    CLAUDE = "claude"
    QWEN = "qwen"
    GLM = "glm"
    LOCAL = "local"

@dataclass
class ModelConfig:
    """模型配置"""
    provider: ModelProvider
    model_name: str
    api_key: str
    api_base: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 2000
    timeout: int = 30
    extra_params: Dict[str, Any] = None

class LLMAdapter(ABC):
    """大模型适配器基类"""
    
    def __init__(self, config: ModelConfig):
        self.config = config
    
    @abstractmethod
    async def chat_completion(self, messages: List[Dict[str, str]], **kwargs) -> Dict[str, Any]:
        """聊天完成接口"""
        pass
    
    @abstractmethod
    async def validate_config(self) -> bool:
        """验证配置是否有效"""
        pass

class OpenAIAdapter(LLMAdapter):
    """OpenAI适配器"""
    
    async def chat_completion(self, messages: List[Dict[str, str]], **kwargs) -> Dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json"
        }
        
        api_base = self.config.api_base or "https://api.openai.com/v1"
        url = f"{api_base}/chat/completions"
        
        data = {
            "model": self.config.model_name,
            "messages": messages,
            "temperature": kwargs.get("temperature", self.config.temperature),
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens)
        }
        
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.config.timeout)) as session:
            async with session.post(url, headers=headers, json=data) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"OpenAI API error: {response.status} - {error_text}")
                
                return await response.json()
    
    async def validate_config(self) -> bool:
        try:
            test_messages = [{"role": "user", "content": "test"}]
            result = await self.chat_completion(test_messages, max_tokens=5)
            return "choices" in result
        except:
            return False

class DeepSeekAdapter(LLMAdapter):
    """DeepSeek适配器"""
    
    async def chat_completion(self, messages: List[Dict[str, str]], **kwargs) -> Dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json"
        }
        
        api_base = self.config.api_base or "https://api.deepseek.com"
        url = f"{api_base}/chat/completions"
        
        data = {
            "model": self.config.model_name,
            "messages": messages,
            "temperature": kwargs.get("temperature", self.config.temperature),
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens)
        }
        
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.config.timeout)) as session:
            async with session.post(url, headers=headers, json=data) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"DeepSeek API error: {response.status} - {error_text}")
                
                return await response.json()
    
    async def validate_config(self) -> bool:
        try:
            test_messages = [{"role": "user", "content": "test"}]
            result = await self.chat_completion(test_messages, max_tokens=5)
            return "choices" in result
        except:
            return False

class ClaudeAdapter(LLMAdapter):
    """Claude适配器"""
    
    async def chat_completion(self, messages: List[Dict[str, str]], **kwargs) -> Dict[str, Any]:
        headers = {
            "x-api-key": self.config.api_key,
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01"
        }
        
        api_base = self.config.api_base or "https://api.anthropic.com"
        url = f"{api_base}/v1/messages"
        
        # Claude需要转换消息格式
        system_message = ""
        user_messages = []
        
        for msg in messages:
            if msg["role"] == "system":
                system_message = msg["content"]
            else:
                user_messages.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })
        
        data = {
            "model": self.config.model_name,
            "messages": user_messages,
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "temperature": kwargs.get("temperature", self.config.temperature)
        }
        
        if system_message:
            data["system"] = system_message
        
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.config.timeout)) as session:
            async with session.post(url, headers=headers, json=data) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"Claude API error: {response.status} - {error_text}")
                
                result = await response.json()
                # 转换为统一格式
                return {
                    "choices": [{
                        "message": {
                            "content": result.get("content", [{}])[0].get("text", ""),
                            "role": "assistant"
                        }
                    }],
                    "usage": result.get("usage", {})
                }
    
    async def validate_config(self) -> bool:
        try:
            test_messages = [{"role": "user", "content": "test"}]
            result = await self.chat_completion(test_messages, max_tokens=5)
            return "choices" in result
        except:
            return False

class LocalAdapter(LLMAdapter):
    """本地模型适配器（如Ollama）"""
    
    async def chat_completion(self, messages: List[Dict[str, str]], **kwargs) -> Dict[str, Any]:
        api_base = self.config.api_base or "http://localhost:11434"
        url = f"{api_base}/api/chat"
        
        # 转换消息格式为Ollama格式
        ollama_messages = []
        for msg in messages:
            ollama_messages.append({
                "role": msg["role"],
                "content": msg["content"]
            })
        
        data = {
            "model": self.config.model_name,
            "messages": ollama_messages,
            "options": {
                "temperature": kwargs.get("temperature", self.config.temperature),
                "num_predict": kwargs.get("max_tokens", self.config.max_tokens)
            }
        }
        
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.config.timeout)) as session:
            async with session.post(url, json=data) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"Local API error: {response.status} - {error_text}")
                
                result = await response.json()
                # 转换为统一格式
                return {
                    "choices": [{
                        "message": {
                            "content": result.get("message", {}).get("content", ""),
                            "role": "assistant"
                        }
                    }],
                    "usage": result.get("usage", {})
                }
    
    async def validate_config(self) -> bool:
        try:
            test_messages = [{"role": "user", "content": "test"}]
            result = await self.chat_completion(test_messages, max_tokens=5)
            return "choices" in result
        except:
            return False

class LLMManager:
    """大模型管理器"""
    
    def __init__(self, config_dir: Path):
        self.config_dir = config_dir
        self.config_file = config_dir / "llm_configs.json"
        self.adapters: Dict[str, LLMAdapter] = {}
        self.active_adapter: Optional[str] = None
        
        # 适配器映射
        self.adapter_classes = {
            ModelProvider.OPENAI: OpenAIAdapter,
            ModelProvider.DEEPSEEK: DeepSeekAdapter,
            ModelProvider.CLAUDE: ClaudeAdapter,
            ModelProvider.LOCAL: LocalAdapter
        }
    
    def _encrypt_key(self, api_key: str) -> str:
        """简单的加密存储（实际项目中应使用更安全的方法）"""
        # 这里使用简单的base64编码，实际应该使用AES等加密
        return base64.b64encode(api_key.encode()).decode()
    
    def _decrypt_key(self, encrypted_key: str) -> str:
        """解密API密钥"""
        try:
            return base64.b64decode(encrypted_key.encode()).decode()
        except:
            return ""
    
    async def load_configs(self):
        """加载配置"""
        if not self.config_file.exists():
            return
        
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 清空旧配置，防止已删除的配置残留
            self.adapters.clear()
            self.active_adapter = None
            
            for config_id, config_data in data.items():
                # 跳过非配置项（如 default_adapter 是字符串）
                if not isinstance(config_data, dict):
                    continue
                # enabled默认True（只要有provider和model_name就加载）
                if not config_data.get("enabled", True):
                    continue
                if not config_data.get("provider") or not config_data.get("model_name"):
                    continue
                provider = ModelProvider(config_data["provider"])
                config = ModelConfig(
                    provider=provider,
                    model_name=config_data["model_name"],
                    api_key=self._decrypt_key(config_data.get("api_key", "")),
                    api_base=config_data.get("api_base"),
                    temperature=config_data.get("temperature", 0.7),
                    max_tokens=config_data.get("max_tokens", 2000),
                    timeout=config_data.get("timeout", 30),
                    extra_params=config_data.get("extra_params", {})
                )
                
                adapter_class = self.adapter_classes.get(provider)
                if adapter_class:
                    self.adapters[config_id] = adapter_class(config)
            
            # 设置默认激活的适配器
            default_id = data.get("default_adapter")
            if default_id and default_id in self.adapters:
                self.active_adapter = default_id
                
        except Exception as e:
            print(f"加载LLM配置失败: {e}")
    
    async def save_configs(self, configs: Dict[str, Dict[str, Any]], default_adapter: str = None):
        """保存配置"""
        try:
            # 加密API密钥
            encrypted_configs = {}
            for config_id, config_data in configs.items():
                if not isinstance(config_data, dict):
                    encrypted_configs[config_id] = config_data
                    continue
                encrypted_config = config_data.copy()
                encrypted_config["enabled"] = True  # 强制写入enabled
                if "api_key" in encrypted_config and encrypted_config["api_key"]:
                    encrypted_config["api_key"] = self._encrypt_key(encrypted_config["api_key"])
                encrypted_configs[config_id] = encrypted_config
            
            # 添加默认适配器
            if default_adapter:
                encrypted_configs["default_adapter"] = default_adapter
            
            # 确保目录存在
            self.config_dir.mkdir(parents=True, exist_ok=True)
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(encrypted_configs, f, ensure_ascii=False, indent=2)
            
            # 重新加载配置
            await self.load_configs()
            
        except Exception as e:
            raise Exception(f"保存LLM配置失败: {e}")
    
    async def add_config(self, config_id: str, config: ModelConfig) -> bool:
        """添加配置"""
        try:
            adapter_class = self.adapter_classes.get(config.provider)
            if not adapter_class:
                return False
            
            adapter = adapter_class(config)
            
            # 验证配置
            if not await adapter.validate_config():
                return False
            
            self.adapters[config_id] = adapter
            
            # 如果没有激活的适配器，设置为默认
            if not self.active_adapter:
                self.active_adapter = config_id
            
            return True
            
        except Exception as e:
            print(f"添加LLM配置失败: {e}")
            return False
    
    def remove_config(self, config_id: str) -> bool:
        """删除配置"""
        if config_id in self.adapters:
            del self.adapters[config_id]
            
            # 如果删除的是激活的适配器，选择新的
            if self.active_adapter == config_id:
                self.active_adapter = next(iter(self.adapters.keys()), None)
            
            return True
        return False
    
    def set_active_adapter(self, config_id: str) -> bool:
        """设置激活的适配器"""
        if config_id in self.adapters:
            self.active_adapter = config_id
            return True
        return False
    
    def get_active_adapter(self) -> Optional[LLMAdapter]:
        """获取激活的适配器"""
        if self.active_adapter and self.active_adapter in self.adapters:
            return self.adapters[self.active_adapter]
        return None
    
    def get_configs(self) -> Dict[str, Dict[str, Any]]:
        """获取所有配置（不包含API密钥，但返回has_key标志）"""
        configs = {}
        for config_id, adapter in self.adapters.items():
            config = adapter.config
            configs[config_id] = {
                "provider": config.provider.value,
                "model_name": config.model_name,
                "api_base": config.api_base,
                "temperature": config.temperature,
                "max_tokens": config.max_tokens,
                "timeout": config.timeout,
                "extra_params": config.extra_params or {},
                "is_active": config_id == self.active_adapter,
                "has_key": bool(config.api_key)  # 是否有key，不返回值
            }
        return configs
    
    async def chat_completion(self, messages: List[Dict[str, str]], **kwargs) -> Dict[str, Any]:
        """使用激活的适配器进行聊天"""
        adapter = self.get_active_adapter()
        if not adapter:
            raise Exception("没有可用的LLM适配器")
        
        return await adapter.chat_completion(messages, **kwargs)
    
    async def validate_config(self, config_data: Dict[str, Any]) -> bool:
        """验证配置"""
        try:
            provider = ModelProvider(config_data["provider"])
            config = ModelConfig(
                provider=provider,
                model_name=config_data["model_name"],
                api_key=config_data["api_key"],
                api_base=config_data.get("api_base"),
                temperature=config_data.get("temperature", 0.7),
                max_tokens=config_data.get("max_tokens", 2000),
                timeout=config_data.get("timeout", 30),
                extra_params=config_data.get("extra_params", {})
            )
            
            adapter_class = self.adapter_classes.get(provider)
            if not adapter_class:
                return False
            
            adapter = adapter_class(config)
            return await adapter.validate_config()
            
        except Exception as e:
            print(f"验证LLM配置失败: {e}")
            return False

# 全局实例
_llm_manager: Optional[LLMManager] = None

def get_llm_manager() -> LLMManager:
    """获取全局LLM管理器实例"""
    global _llm_manager
    if _llm_manager is None:
        config_dir = Path(__file__).parent.parent / "config"
        _llm_manager = LLMManager(config_dir)
    return _llm_manager

async def init_llm_manager():
    """初始化LLM管理器"""
    manager = get_llm_manager()
    await manager.load_configs()
