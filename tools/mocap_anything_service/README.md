# MoCapAnything 推理服务

本项目提供 MoCapAnything 的 FastAPI 微服务封装，支持：
- 视频上传
- GPU 异步推理（BVH 输出）
- 任务状态查询
- 结果下载

## 快速开始

### 1. 克隆 MoCapAnything 代码

```bash
cd tools/mocap_anything_service
git clone https://github.com/animotionlab26/MocapAnything.git mocap_repo
```

### 2. 安装依赖

```bash
# 创建独立环境（推荐）
python -m venv .venv_mocap
source .venv_mocap/bin/activate  # Linux/Mac
# .venv_mocap\Scripts\activate  # Windows

pip install -r requirements.txt
```

### 3. 配置 MoCapAnything 推理入口

编辑 `config.py`，填写 MoCapAnything 仓库路径和推理参数：

```python
MOCAP_REPO_PATH = "./mocap_repo"
MOCAP_CHECKPOINT = "./checkpoints/mocapanything.ckpt"
DEVICE = "cuda"  # 或 "cpu"
```

### 4. 启动服务

```bash
python service.py
# 或
uvicorn service:app --host 0.0.0.0 --port 8767 --workers 1
```

服务默认监听 `http://localhost:8767`。

## API 文档

启动服务后访问 `http://localhost:8767/docs` 查看 Swagger UI。

### 核心接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| POST | `/upload` | 上传视频开始推理 |
| GET | `/task/{task_id}` | 查询任务状态 |
| GET | `/result/{task_id}/download` | 下载 BVH 结果 |

### 示例

```bash
# 上传视频
curl -X POST -F "video=@demo.mp4" \
  http://localhost:8767/upload

# 查询状态
curl http://localhost:8767/task/<task_id>

# 下载结果
curl -O http://localhost:8767/result/<task_id>/download
```

## 与主项目集成

主项目通过 `modules/mocap_anything_client.py` 与本服务通信。默认配置：

```python
MOCAP_ANYTHING_BASE_URL = "http://localhost:8767"
```

修改 `modules/mocap_anything_client.py` 中的配置即可切换服务地址。

## 注意事项

- MoCapAnything 需要 **CUDA GPU**，显存建议 ≥ 8GB
- 推理时间较长（30秒视频约需 1-3 分钟）
- 服务默认单 worker，避免 GPU 内存冲突
- 可通过 `max_file_size` 限制上传视频大小

## 目录结构

```
tools/mocap_anything_service/
├── README.md
├── requirements.txt
├── service.py          # FastAPI 服务入口
├── config.py           # 服务配置
├── tasks.py            # 异步任务队列
├── mocap_repo/         # MoCapAnything 源码（git clone）
└── checkpoints/        # 模型权重
```
