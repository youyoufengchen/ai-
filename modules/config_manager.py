"""
配置加载与管理：main / skus / characters / scenes
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger("server")


class ConfigManager:
    """配置文件加载与热更新"""

    def __init__(self, config_dir: Path):
        self.config_dir = config_dir
        self.main: Dict[str, Any] = {}
        self.skus: Dict[str, Any] = {}
        self.characters: Dict[str, Any] = {}
        self.scenes: Dict[str, Any] = {}
        self.load_all()

    def load_all(self):
        self.main       = self._load("main.json")
        self.skus       = self._load_skus()
        self.characters = self._load("characters.json")
        self.scenes     = self._load("scenes.json")
        logger.info(
            f"Config loaded: scene={self.main.get('meta', {}).get('current_scene')}, "
            f"style={self.main.get('meta', {}).get('current_style')}, "
            f"SKUs={len(self.skus)}, scenes={len(self.scenes.get('scenes', {}))}"
        )

    def _load(self, filename: str) -> Dict[str, Any]:
        path = self.config_dir / filename
        if not path.exists():
            logger.error(f"Config not found: {path}")
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _load_skus(self) -> Dict[str, Any]:
        """
        加载SKU配置，支持两种格式：
        1. 多商品映射格式（推荐）: {"tea_001": {"id": "tea_001", ...}, ...}
        2. 单商品格式（旧格式）: {"id": "", "name": "...", ...}
        """
        path = self.config_dir / "skus.json"
        if not path.exists():
            logger.warning(f"SKUs config not found: {path}")
            return {}
        
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # 判断格式
            if not data:
                return {}
            
            # 如果是列表格式，转换为映射格式
            if isinstance(data, list):
                return {item.get("id", f"sku_{i}"): item for i, item in enumerate(data) if item.get("id")}
            
            # 如果是单商品格式（有id字段但不是嵌套结构）
            if isinstance(data, dict) and "id" in data and "name" in data:
                # 单商品格式，包装成映射格式
                sku_id = data.get("id") or "default"
                return {sku_id: data}
            
            # 已经是多商品映射格式
            if isinstance(data, dict):
                return data
            
            return {}
            
        except Exception as e:
            logger.error(f"Failed to load SKUs: {e}")
            return {}

    # ---- style ----
    def get_current_style(self) -> str:
        return self.main.get("meta", {}).get("current_style", "classical")

    def set_current_style(self, style_id: str):
        self.main["meta"]["current_style"] = style_id

    # ---- character ----
    def get_character(self, char_id: str = "bao_qing") -> Dict[str, Any]:
        return self.characters.get(char_id, {})

    # ---- sku ----
    def get_sku(self, sku_id: str) -> Dict[str, Any]:
        """获取单个SKU信息"""
        if not sku_id:
            return {}
        sku = self.skus.get(sku_id, {})
        # 确保返回包含id字段
        if sku and not sku.get("id"):
            sku["id"] = sku_id
        return sku

    def get_all_skus(self) -> Dict[str, Any]:
        """获取所有SKU映射"""
        return self.skus

    def find_sku_by_keyword(self, text: str) -> str:
        """根据关键词查找SKU ID"""
        if not text:
            return ""
        text = str(text).lower()
        for sku_id, sku in self.skus.items():
            # 检查keywords字段（字符串或列表）
            keywords = sku.get("keywords", [])
            if isinstance(keywords, str):
                keywords = [keywords]
            for kw in keywords:
                if kw and str(kw).lower() in text:
                    return sku_id
            # 也检查商品名称
            name = sku.get("name", "")
            if name and str(name).lower() in text:
                return sku_id
        return ""

    def find_sku_by_name(self, name: str) -> str:
        """根据商品名称查找SKU ID（精确匹配或部分匹配）"""
        if not name:
            return ""
        name = str(name).lower()
        for sku_id, sku in self.skus.items():
            sku_name = str(sku.get("name", "")).lower()
            if name == sku_name or name in sku_name:
                return sku_id
        return ""

    # ---- scene ----
    def get_scene(self) -> Dict[str, Any]:
        scenes_data = self.scenes.get("scenes", {})
        current = self.scenes.get("meta", {}).get("current_scene", "default_tea_shop")
        return scenes_data.get(current, {})

    def get_scene_by_id(self, scene_id: str) -> Dict[str, Any]:
        return self.scenes.get("scenes", {}).get(scene_id, {})

    def get_all_scenes(self) -> Dict[str, Any]:
        return self.scenes.get("scenes", {})

    def get_groups(self) -> List[Dict[str, Any]]:
        return self.scenes.get("groups", [])

    def save_groups(self, groups: List[Dict[str, Any]]):
        self.scenes["groups"] = groups

    def move_scene_to_group(self, scene_id: str, group_id: str):
        scenes = self.scenes.get("scenes", {})
        if scene_id in scenes:
            scenes[scene_id]["group"] = group_id

    def set_scene_order(self, scene_id: str, order: int):
        scenes = self.scenes.get("scenes", {})
        if scene_id in scenes:
            scenes[scene_id]["order"] = order

    def set_current_scene(self, scene_id: str):
        if "meta" not in self.scenes:
            self.scenes["meta"] = {}
        self.scenes["meta"]["current_scene"] = scene_id

    def save_scenes(self) -> bool:
        path = self.config_dir / "scenes.json"
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.scenes, f, ensure_ascii=False, indent=2)
            logger.info(f"Scenes saved to {path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save scenes: {e}")
            return False
