"""
敏感配置管理器 - SecretsManager
集中管理外部云服务 API 密钥（TTS、STT 等）
保存到 config/secrets.json，支持环境变量 fallback
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, Optional

class SecretsManager:
    """管理外部云服务密钥，优先从配置文件读取，其次环境变量"""
    
    def __init__(self, config_dir: Path):
        self.config_dir = config_dir
        self.secrets_file = config_dir / "secrets.json"
        self._secrets: Dict[str, Any] = {}
        self._load()
    
    def _load(self):
        """加载已保存的密钥"""
        if self.secrets_file.exists():
            try:
                with open(self.secrets_file, 'r', encoding='utf-8') as f:
                    self._secrets = json.load(f)
            except Exception as e:
                print(f"[SecretsManager] 加载失败: {e}")
                self._secrets = {}
        else:
            self._secrets = {}
    
    def save(self, secrets: Dict[str, Any]):
        """保存密钥（会覆盖旧配置）"""
        self._secrets = secrets
        self.config_dir.mkdir(parents=True, exist_ok=True)
        with open(self.secrets_file, 'w', encoding='utf-8') as f:
            json.dump(secrets, f, ensure_ascii=False, indent=2)
        return True
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取密钥，优先级：
        1. 配置文件（用户通过UI设置）
        2. 环境变量（.env 或系统环境）
        3. default
        """
        # 优先配置文件（用户显式设置）
        if key in self._secrets:
            return self._secrets[key]
        # 其次环境变量
        env_val = os.getenv(key)
        if env_val is not None:
            return env_val
        return default
    
    KNOWN_KEYS = {
        'VOLC_TTS_APPID','VOLC_TTS_TOKEN',
        'MINIMAX_API_KEY','MINIMAX_GROUP_ID',
        'OPENAI_API_KEY','OPENAI_API_BASE',
        'ALIYUN_ACCESS_KEY_ID','ALIYUN_ACCESS_KEY_SECRET','ALIYUN_NLS_APP_KEY',
        'TENCENT_SECRET_ID','TENCENT_SECRET_KEY',
        'DEEPSEEK_API_KEY',
    }

    def get_all(self) -> Dict[str, Any]:
        """获取所有已知凭证（配置文件优先，其次环境变量）"""
        result = {}
        for key in self.KNOWN_KEYS:
            val = self._secrets.get(key) or os.getenv(key)
            if val:
                result[key] = val
        return result
    
    def update(self, updates: Dict[str, Any]):
        """部分更新（只更新传入的key，不删除其他）"""
        self._secrets.update(updates)
        return self.save(self._secrets)

# 全局实例
_secrets_manager: Optional[SecretsManager] = None

def get_secrets_manager() -> SecretsManager:
    """获取全局 SecretsManager 实例"""
    global _secrets_manager
    if _secrets_manager is None:
        config_dir = Path(__file__).parent.parent / "config"
        _secrets_manager = SecretsManager(config_dir)
    return _secrets_manager

# 便捷函数，模块直接调用
def get_secret(key: str, default: Any = None) -> Any:
    """快捷获取单个密钥"""
    return get_secrets_manager().get(key, default)
