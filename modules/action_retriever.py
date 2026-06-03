"""
Action Retriever — 动作库检索引擎

两种检索模式（自动降级）：
1. 向量语义检索：安装 sentence-transformers 后自动启用，精度高
2. 关键词TF-IDF检索：无需额外依赖，开箱即用，精度中等

使用方法：
    retriever = ActionRetriever("config/action_catalog.json")
    result = retriever.search("给观众展示这款茶叶", top_k=3)
    best = result[0]  # {"id": "present_twohand", "file": "...", "score": 0.91}
"""

import json
import math
import logging
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any

logger = logging.getLogger("action_retriever")

# ── 向量检索开关（手动控制）──────────────────────────────────────────────
_VECTOR_ENABLED = True

# 导入延迟到实际使用时
_VECTOR_AVAILABLE = None  # None=未检查, True=可用, False=不可用

def _check_vector_available():
    """检查向量检索是否可用（fastembed，不依赖 torch）"""
    global _VECTOR_AVAILABLE
    if _VECTOR_AVAILABLE is not None:
        return _VECTOR_AVAILABLE
    
    if not _VECTOR_ENABLED:
        _VECTOR_AVAILABLE = False
        logger.info("[Retriever] Vector search disabled by config")
        return False
    
    try:
        from fastembed import TextEmbedding
        import numpy as np
        _VECTOR_AVAILABLE = True
        logger.info("[Retriever] fastembed available, vector search enabled")
    except ImportError as e:
        _VECTOR_AVAILABLE = False
        logger.warning(f"[Retriever] fastembed not available: {e}")
    
    return _VECTOR_AVAILABLE


class ActionEntry:
    """动作库中的一个条目"""
    def __init__(self, data: Dict):
        self.id: str = data["id"]
        self.file: str = data["file"]
        self.skeleton_type: str = data.get("skeleton_type", "humanoid")
        self.description: str = data.get("description", "")
        self.triggers: List[str] = data.get("triggers", [])
        self.tags: List[str] = data.get("tags", [])
        self.category: str = data.get("category", "")
        self.duration: float = data.get("duration", 2.0)
        self.loop: bool = data.get("loop", False)
        self.emotion: str = data.get("emotion", "neutral")
        self.priority: int = data.get("priority", 1)
        self.shelf_height: Optional[str] = data.get("shelf_height")
        # 拼接所有可检索文本
        self._search_text = " ".join(
            self.triggers + [self.description] + self.tags + [self.category]
        )
        self._vector = None  # 向量检索时填充

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "file": self.file,
            "skeleton_type": self.skeleton_type,
            "description": self.description,
            "duration": self.duration,
            "loop": self.loop,
            "emotion": self.emotion,
            "tags": self.tags,
            "shelf_height": self.shelf_height,
        }


class ActionRetriever:
    """
    动作库检索引擎

    初始化时从 action_catalog.json 加载所有动作，
    构建关键词索引（始终可用）和向量索引（可选）。
    检索时支持按 skeleton_type 前置过滤，确保动作与角色骨骼兼容。
    """

    SHELF_HEIGHT_KEYWORDS = {
        "high":  ["高处", "顶层", "高层", "头顶", "最高", "上面"],
        "mid":   ["中间", "中层", "平行", "正面", "正常高度"],
        "low":   ["低处", "低层", "底层", "下面", "俯身"],
        "floor": ["地面", "地板", "最低", "地上"],
    }

    def __init__(self, catalog_path: str, embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2"):
        self.catalog_path = Path(catalog_path)
        self.actions: List[ActionEntry] = []
        self._idf: Dict[str, float] = {}
        self._model = None
        self._use_vector = False
        self.skeleton_types: Dict = {}

        self._load_skeleton_types()
        self._load_catalog()
        self._build_keyword_index()

        # 向量检索：优先从项目目录加载本地模型（支持打包分发）
        # 注意：首次加载459MB模型需要2-5分钟，如卡住请重启或禁用向量检索
        # 修改 _VECTOR_ENABLED = True 启用向量检索
        if _check_vector_available():
            logger.info(f"[Retriever] Initializing vector index with model: {embedding_model}")
            self._init_vector_index(embedding_model)
        else:
            logger.info("[Retriever] Vector search disabled (set _VECTOR_ENABLED=True to enable with 459MB model)")

    # ── 加载 ──────────────────────────────────────────────────────────────

    def _load_skeleton_types(self):
        sk_path = self.catalog_path.parent / "skeleton_types.json"
        if sk_path.exists():
            with open(sk_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.skeleton_types = data.get("types", {})
            logger.info(f"[Retriever] Loaded {len(self.skeleton_types)} skeleton types")
        else:
            logger.warning("[Retriever] skeleton_types.json not found, skeleton filtering disabled")

    def _load_catalog(self):
        if not self.catalog_path.exists():
            raise FileNotFoundError(f"Action catalog not found: {self.catalog_path}")
        with open(self.catalog_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        all_actions = data.get("actions", [])
        # 过滤掉被禁用的动作（enabled=False），AI规划动作流时不会选用
        enabled_actions = [a for a in all_actions if a.get("enabled", True)]
        skipped = len(all_actions) - len(enabled_actions)
        self.actions = [ActionEntry(a) for a in enabled_actions]
        logger.info(f"[Retriever] Loaded {len(self.actions)} actions from catalog"
                    + (f" (skipped {skipped} disabled)" if skipped else ""))

    def reload(self):
        """热重载 catalog（运行时增加动作后调用）"""
        self.actions = []
        self._load_skeleton_types()
        self._load_catalog()
        self._build_keyword_index()
        if self._use_vector:
            self._build_vector_index()
        logger.info("[Retriever] Catalog reloaded")

    # ── 关键词索引（TF-IDF）──────────────────────────────────────────────

    def _tokenize(self, text: str) -> List[str]:
        """简单中文分词：按字符2-gram + 整词"""
        text = text.lower().strip()
        tokens = re.findall(r'[\u4e00-\u9fff]{1,4}|[a-z_]+', text)
        bigrams = [text[i:i+2] for i in range(len(text)-1) if '\u4e00' <= text[i] <= '\u9fff']
        return list(set(tokens + bigrams))

    def _build_keyword_index(self):
        """构建 IDF 表"""
        N = len(self.actions)
        df: Dict[str, int] = {}
        for entry in self.actions:
            tokens = set(self._tokenize(entry._search_text))
            for t in tokens:
                df[t] = df.get(t, 0) + 1
        self._idf = {t: math.log((N + 1) / (cnt + 1)) + 1 for t, cnt in df.items()}

    def _tfidf_score(self, query: str, entry: ActionEntry) -> float:
        query_tokens = self._tokenize(query)
        doc_tokens = self._tokenize(entry._search_text)
        doc_freq = {}
        for t in doc_tokens:
            doc_freq[t] = doc_freq.get(t, 0) + 1
        score = 0.0
        for t in query_tokens:
            if t in doc_freq:
                tf = doc_freq[t] / max(len(doc_tokens), 1)
                idf = self._idf.get(t, 1.0)
                score += tf * idf
        # 标准化
        norm = math.sqrt(sum((self._idf.get(t, 1.0) ** 2) for t in set(query_tokens)))
        return score / max(norm, 1e-9)

    # ── 向量索引（可选）──────────────────────────────────────────────────

    def _init_vector_index(self, model_name: str):
        """后台线程加载向量模型（fastembed），不阻塞启动"""
        import threading
        
        def load_model():
            try:
                from fastembed import TextEmbedding
                logger.info(f"[Retriever] Loading fastembed model: {model_name}")
                model = TextEmbedding(model_name=model_name)
                self._model = model
                self._build_vector_index()
                self._use_vector = True
                logger.info(f"[Retriever] Vector index ready ({model_name}), switched to vector mode")
            except Exception as e:
                logger.warning(f"[Retriever] Failed to load model: {e}, staying on keyword mode")
        
        thread = threading.Thread(target=load_model, name="retriever-model-loader")
        thread.daemon = True
        thread.start()
        logger.info(f"[Retriever] Model loading started in background, using keyword mode until ready")

    def _build_vector_index(self):
        import numpy as np
        texts = [a._search_text for a in self.actions]
        embeddings = list(self._model.embed(texts))
        for i, entry in enumerate(self.actions):
            vec = embeddings[i]
            norm = np.linalg.norm(vec)
            entry._vector = vec / norm if norm > 0 else vec

    def _cosine_score(self, query: str, entry: ActionEntry) -> float:
        import numpy as np
        if entry._vector is None:
            return 0.0
        q_vec = list(self._model.embed([query]))[0]
        norm = np.linalg.norm(q_vec)
        q_vec = q_vec / norm if norm > 0 else q_vec
        return float(np.dot(q_vec, entry._vector))

    # ── 约束过滤 ─────────────────────────────────────────────────────────

    def _filter_by_constraints(
        self,
        candidates: List[ActionEntry],
        constraints: Dict,
    ) -> List[ActionEntry]:
        """过滤不满足硬性约束的动作"""
        result = []
        for entry in candidates:
            # 货架高度约束
            if "shelf_height" in constraints and entry.shelf_height:
                if entry.shelf_height != constraints["shelf_height"]:
                    continue
            # 情绪约束（软约束，仅过滤明显冲突）
            if "emotion" in constraints:
                allowed = constraints["emotion"]
                if entry.emotion not in (allowed, "neutral"):
                    continue
            result.append(entry)
        return result if result else candidates  # 如果过滤后为空则返回全部

    # ── 主检索接口 ────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        top_k: int = 5,
        skeleton_type: Optional[str] = None,
        category_filter: Optional[str] = None,
        constraints: Optional[Dict] = None,
        shelf_height_from_text: bool = True,
    ) -> List[Dict]:
        """
        主检索接口

        Args:
            query:            自然语言查询，如 "走向货架取高处商品展示给观众"
            top_k:            返回候选数量
            skeleton_type:    骨骼类型前置过滤，如 "humanoid" / "quadruped"
            category_filter:  限定类别，如 "交互动作/取物"
            constraints:      硬性约束 {"shelf_height": "high", "emotion": "happy"}
            shelf_height_from_text: 是否自动从query推断货架高度

        Returns:
            [{id, file, skeleton_type, description, score, ...}, ...]  按 score 降序
        """
        candidates = self.actions

        # ── 骨骼类型前置过滤（最高优先级，不命中不降级）──────────────
        if skeleton_type:
            filtered = [a for a in candidates if a.skeleton_type == skeleton_type]
            if filtered:
                candidates = filtered
            else:
                logger.warning(f"[Retriever] No actions for skeleton_type='{skeleton_type}', ignoring filter")

        # 类别过滤
        if category_filter:
            candidates = [a for a in candidates if a.category.startswith(category_filter)]
            if not candidates:
                candidates = self.actions

        # 自动从文本推断货架高度约束
        auto_constraints = dict(constraints or {})
        if shelf_height_from_text and "shelf_height" not in auto_constraints:
            for height, kws in self.SHELF_HEIGHT_KEYWORDS.items():
                if any(kw in query for kw in kws):
                    auto_constraints["shelf_height"] = height
                    break

        # 约束过滤
        if auto_constraints:
            candidates = self._filter_by_constraints(candidates, auto_constraints)

        # 打分
        scored: List[Tuple[float, ActionEntry]] = []
        for entry in candidates:
            if self._use_vector:
                score = self._cosine_score(query, entry)
            else:
                score = self._tfidf_score(query, entry)
            # priority 加成（优先级高的略微提分）
            score += entry.priority * 0.02
            scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)

        results = []
        for score, entry in scored[:top_k]:
            d = entry.to_dict()
            d["score"] = round(score, 4)
            results.append(d)

        if results:
            logger.debug(
                f"[Retriever] query='{query}' → best='{results[0]['id']}' score={results[0]['score']:.3f}"
            )
        return results

    def get_by_id(self, action_id: str) -> Optional[Dict]:
        """按ID精确获取动作"""
        for entry in self.actions:
            if entry.id == action_id:
                return entry.to_dict()
        return None

    def get_by_shelf_height(self, height: str, skeleton_type: str = "humanoid") -> Optional[Dict]:
        """按货架高度获取最合适的取物动作"""
        results = self.search(
            "取货架商品",
            top_k=1,
            skeleton_type=skeleton_type,
            category_filter="交互动作/取物",
            constraints={"shelf_height": height},
        )
        return results[0] if results else self.get_by_id("reach_mid")

    def get_compatible_actions(self, skeleton_type: str) -> List[Dict]:
        """获取某骨骼类型的所有可用动作（用于角色注册时统计）"""
        return [
            a.to_dict()
            for a in self.actions
            if a.skeleton_type == skeleton_type
        ]

    def get_skeleton_types(self) -> List[str]:
        """返回 catalog 中实际出现的骨骼类型列表"""
        return list({a.skeleton_type for a in self.actions})

    def list_all(self) -> List[Dict]:
        """列出所有已注册动作（用于管理界面）"""
        return [
            {
                "id": a.id,
                "file": a.file,
                "description": a.description,
                "category": a.category,
                "tags": a.tags,
                "triggers_count": len(a.triggers),
            }
            for a in self.actions
        ]

    @property
    def mode(self) -> str:
        return "vector" if self._use_vector else "keyword"
