"""
MoCapAnything 推理服务配置

请根据实际环境修改以下配置。
"""

from pathlib import Path

# 服务配置
HOST = "0.0.0.0"
PORT = 8767
WORKERS = 1  # GPU 推理建议单 worker

# 文件上传限制
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500 MB
UPLOAD_DIR = Path(__file__).parent / "uploads"
OUTPUT_DIR = Path(__file__).parent / "outputs"

# MoCapAnything 配置
MOCAP_REPO_PATH = Path(__file__).parent / "mocap_repo"
MOCAP_CHECKPOINT = Path(__file__).parent / "checkpoints" / "mocapanything.ckpt"
MOCAP_CONFIG = Path(__file__).parent / "checkpoints" / "config.yaml"
DEVICE = "cuda"  # "cuda" 或 "cpu"
FP16 = True

# 任务队列
TASK_TIMEOUT = 600  # 秒
CLEANUP_INTERVAL = 3600  # 秒，清理过期任务
