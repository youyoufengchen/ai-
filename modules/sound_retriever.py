"""
Sound Retriever — 音效库语义检索引擎

与 ActionRetriever 同架构，支持：
1. 关键词 TF-IDF 检索（默认可用）
2. 向量语义检索（安装 fastembed 后自动启用）

使用方法：
    retriever = SoundRetriever("config/sound_catalog.json")
    result = retriever.search("生气低吼", top_k=3)
    best = result[0]  # {"id": "sfx_angry_growl", "file": "...", "score": 0.91}
"""

import json
import math
import logging
import re
from pathlib import Path
from typing import List, Dict, Optional, Any

logger = logging.getLogger("sound_retriever")

# 延迟检查向量可用性
_VECTOR_AVAILABLE = None


def _check_vector_available():
    global _VECTOR_AVAILABLE
    if _VECTOR_AVAILABLE is not None:
        return _VECTOR_AVAILABLE
    try:
        from fastembed import TextEmbedding
        import numpy as np
        _VECTOR_AVAILABLE = True
    except ImportError:
        _VECTOR_AVAILABLE = False
    return _VECTOR_AVAILABLE


class SoundEntry:
    """音效库中的一个条目"""

    def __init__(self, data: Dict):
        self.id: str = data["id"]
        self.file: str = data["file"]
        self.category: str = data.get("category", "")
        self.display_name: str = data.get("display_name", "")
        self.triggers: List[str] = data.get("triggers", [])
        self.tags: List[str] = data.get("tags", [])
        self.description: str = data.get("description", "")
        self.duration_s: float = data.get("duration_s", 1.0)
        self.loop: bool = data.get("loop", False)
        self.volume_multiplier: float = data.get("volume_multiplier", 1.0)
        self.emotion_tag: Optional[str] = data.get("emotion_tag")
        self.form_restriction: Optional[str] = data.get("form_restriction")
        self.scene_restriction: Optional[str] = data.get("scene_restriction")

        # 拼接所有可检索文本
        self._search_text = " ".join(
            self.triggers
            + [self.display_name, self.description]
            + self.tags
            + [self.category]
            + ([self.emotion_tag] if self.emotion_tag else [])
        )
        self._vector = None

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "file": self.file,
            "category": self.category,
            "display_name": self.display_name,
            "duration_s": self.duration_s,
            "loop": self.loop,
            "emotion_tag": self.emotion_tag,
            "form_restriction": self.form_restriction,
        }


class SoundRetriever:
    """
    音效库检索引擎

    初始化时从 sound_catalog.json 加载所有音效，
    构建关键词索引（始终可用）和向量索引（可选）。
    检索时支持按 category/emotion_tag/form_restriction 前置过滤。
    """

    def __init__(self, catalog_path: str = "config/sound_catalog.json"):
        self.catalog_path = Path(catalog_path)
        self.sounds: List[SoundEntry] = []
        self._idf: Dict[str, float] = {}
        self._model = None
        self._use_vector = False
        self._id_index: Dict[str, SoundEntry] = {}

        self._load_catalog()
        self._build_keyword_index()

        if _check_vector_available():
            self._init_vector_index()

    # ── 加载 ───────────────────────────────────────────────

    def _load_catalog(self):
        if not self.catalog_path.exists():
            logger.warning(f"Sound catalog not found: {self.catalog_path}")
            return
        with open(self.catalog_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for entry_data in data.get("sounds", []):
            entry = SoundEntry(entry_data)
            self.sounds.append(entry)
            self._id_index[entry.id] = entry
        logger.info(f"[SoundRetriever] Loaded {len(self.sounds)} sounds")

    def reload(self):
        """热重载 catalog"""
        self.sounds = []
        self._id_index = {}
        self._load_catalog()
        self._build_keyword_index()
        if self._use_vector:
            self._build_vector_index()
        logger.info("[SoundRetriever] Catalog reloaded")

    def get_by_id(self, sound_id: str) -> Optional[Dict]:
        entry = self._id_index.get(sound_id)
        return entry.to_dict() if entry else None

    # ── 关键词索引 ─────────────────────────────────────────

    def _tokenize(self, text: str) -> List[str]:
        text = text.lower().strip()
        tokens = re.findall(r'[\u4e00-\u9fff]{1,4}|[a-z_]+', text)
        bigrams = [text[i:i+2] for i in range(len(text)-1)
                   if '\u4e00' <= text[i] <= '\u9fff']
        return list(set(tokens + bigrams))

    def _build_keyword_index(self):
        N = len(self.sounds)
        df: Dict[str, int] = {}
        for entry in self.sounds:
            for t in set(self._tokenize(entry._search_text)):
                df[t] = df.get(t, 0) + 1
        self._idf = {t: math.log((N + 1) / (cnt + 1)) + 1
                     for t, cnt in df.items()}

    def _tfidf_score(self, query: str, entry: SoundEntry) -> float:
        q_tokens = self._tokenize(query)
        d_tokens = self._tokenize(entry._search_text)
        doc_freq: Dict[str, int] = {}
        for t in d_tokens:
            doc_freq[t] = doc_freq.get(t, 0) + 1
        score = 0.0
        for t in q_tokens:
            if t in doc_freq:
                tf = doc_freq[t] / max(len(d_tokens), 1)
                idf = self._idf.get(t, 1.0)
                score += tf * idf
        norm = math.sqrt(sum(self._idf.get(t, 1.0) ** 2
                             for t in set(q_tokens)))
        return score / max(norm, 1e-9)

    # ── 向量索引 ───────────────────────────────────────────

    def _init_vector_index(self):
        import threading
        def _build():
            try:
                from fastembed import TextEmbedding
                import numpy as np
                self._model = TextEmbedding(
                    model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
                )
                texts = [e._search_text for e in self.sounds]
                if texts:
                    vectors = list(self._model.embed(texts))
                    for entry, vec in zip(self.sounds, vectors):
                        entry._vector = np.array(vec)
                    self._use_vector = True
                    logger.info("[SoundRetriever] Vector index built")
            except Exception as e:
                logger.warning(f"[SoundRetriever] Vector init failed: {e}")
        threading.Thread(target=_build, daemon=True).start()

    def _build_vector_index(self):
        if not self._model:
            return
        import numpy as np
        texts = [e._search_text for e in self.sounds]
        if texts:
            vectors = list(self._model.embed(texts))
            for entry, vec in zip(self.sounds, vectors):
                entry._vector = np.array(vec)

    # ── 检索 ───────────────────────────────────────────────

    def search(
        self,
        query: str,
        top_k: int = 3,
        category_filter: Optional[str] = None,
        emotion_filter: Optional[str] = None,
        form_filter: Optional[str] = None,
    ) -> List[Dict]:
        """
        语义检索音效

        Args:
            query: 自然语言描述，如 "生气低吼" "开心笑声" "变身狐火"
            top_k: 返回数量
            category_filter: 限定类别（transform/emotion/action/...）
            emotion_filter: 限定情绪标签
            form_filter: 限定形态

        Returns:
            [{"id", "file", "score", ...}]
        """
        # 前置过滤
        candidates = self.sounds
        if category_filter:
            candidates = [s for s in candidates
                          if s.category == category_filter]
        if emotion_filter:
            candidates = [s for s in candidates
                          if not s.emotion_tag or s.emotion_tag == emotion_filter]
        if form_filter:
            candidates = [s for s in candidates
                          if not s.form_restriction or s.form_restriction == form_filter]

        if not candidates:
            return []

        # 向量检索
        if self._use_vector and self._model:
            try:
                return self._vector_search(query, candidates, top_k)
            except Exception:
                pass

        # 关键词回退
        scored = []
        for entry in candidates:
            score = self._tfidf_score(query, entry)
            if score > 0:
                d = entry.to_dict()
                d["score"] = score
                scored.append(d)
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    def _vector_search(
        self, query: str, candidates: List[SoundEntry], top_k: int
    ) -> List[Dict]:
        import numpy as np
        q_vec = np.array(list(self._model.embed([query]))[0])
        scored = []
        for entry in candidates:
            if entry._vector is None:
                continue
            sim = float(np.dot(q_vec, entry._vector) /
                        (np.linalg.norm(q_vec) * np.linalg.norm(entry._vector) + 1e-9))
            d = entry.to_dict()
            d["score"] = sim
            scored.append(d)
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    # ── 便捷方法 ───────────────────────────────────────────

    def search_emotion(self, emotion: str, form: Optional[str] = None) -> Optional[Dict]:
        """按情绪标签查找音效（form精确匹配优先 → 通用 → 语义检索）"""
        # 第1轮：优先找 form 精确匹配的
        if form:
            for entry in self.sounds:
                if entry.emotion_tag == emotion and entry.form_restriction == form:
                    return entry.to_dict()
        # 第2轮：找通用（无 form_restriction 限制）的
        for entry in self.sounds:
            if entry.emotion_tag == emotion and not entry.form_restriction:
                return entry.to_dict()
        # 第3轮：找任何 emotion 匹配的
        for entry in self.sounds:
            if entry.emotion_tag == emotion:
                return entry.to_dict()
        # 语义检索降级
        results = self.search(emotion, top_k=1, category_filter="emotion",
                              form_filter=form)
        return results[0] if results else None

    def search_transform(self, target_form: str) -> Optional[Dict]:
        """查找变身音效"""
        results = self.search(target_form, top_k=1, category_filter="transform")
        return results[0] if results else None
