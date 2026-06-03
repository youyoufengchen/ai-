#!/usr/bin/env python
"""
手动下载 sentence-transformers 模型（使用国内镜像）
"""
import os
import sys

# 设置 Hugging Face 国内镜像
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'

from sentence_transformers import SentenceTransformer

model_name = 'paraphrase-multilingual-MiniLM-L12-v2'
print(f"正在下载模型: {model_name}")
print(f"使用镜像: https://hf-mirror.com")

try:
    model = SentenceTransformer(model_name)
    print(f"✓ 模型下载成功！")
    print(f"模型缓存位置: {model.cache_folder}")
except Exception as e:
    print(f"✗ 下载失败: {e}")
    sys.exit(1)
