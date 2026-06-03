"""
MoCapAnything FastAPI 推理服务

提供：
- 视频上传 → BVH 推理
- 任务状态查询
- 结果下载

使用方法：
    cd tools/mocap_anything_service
    python service.py
    # 或
    uvicorn service:app --host 0.0.0.0 --port 8767

注意事项：
- 需要先克隆 MoCapAnything 代码到 mocap_repo/ 目录
- 需要配置 config.py 中的模型路径
- GPU 推理建议单 worker
"""

import sys
import logging
import asyncio
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional

# 添加 MoCapAnything 仓库到路径（如果存在）
MOCAP_REPO = Path(__file__).parent / "mocap_repo"
if MOCAP_REPO.exists():
    sys.path.insert(0, str(MOCAP_REPO))

from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

import subprocess
import shutil
import tempfile
from config import (
    HOST, PORT, MAX_FILE_SIZE,
    UPLOAD_DIR, OUTPUT_DIR,
    MOCAP_REPO_PATH, MOCAP_CHECKPOINT, MOCAP_CONFIG, DEVICE, FP16, WORKERS,
)
from tasks import task_manager, TaskManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
)
logger = logging.getLogger("mocap_service")

# ──────────────────────────────
# 生命周期管理
# ──────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    await task_manager.start()
    logger.info(f"MoCapAnything 服务启动: http://{HOST}:{PORT}")
    yield
    await task_manager.stop()
    logger.info("MoCapAnything 服务已停止")

app = FastAPI(
    title="MoCapAnything 推理服务",
    description="端到端视频到3D骨骼动画推理 API",
    version="1.0.0",
    lifespan=lifespan,
)

# ──────────────────────────────
# 推理模块（占位，需接入 MoCapAnything）
# ──────────────────────────────

_mocap_model = None

def _check_repo_ready() -> tuple[bool, str]:
    """检查 MoCapAnything 仓库和权重是否就绪"""
    if not MOCAP_REPO_PATH.exists():
        return False, f"仓库未找到: {MOCAP_REPO_PATH}"
    inference_script = MOCAP_REPO_PATH / "inference" / "video2pose2rot.py"
    if not inference_script.exists():
        return False, f"推理脚本未找到: {inference_script}"
    ckpt_root = MOCAP_REPO_PATH / "checkpoints" / "video2pose2rot"
    if not ckpt_root.exists():
        return False, f"模型权重未找到: {ckpt_root}（请下载 checkpoints/）"
    return True, "ready"


async def load_mocap_model():
    """兼容旧接口：返回 True 表示可用（权重通过 subprocess 调用，不预加载）"""
    global _mocap_model
    if _mocap_model is not None:
        return _mocap_model
    ok, msg = _check_repo_ready()
    if ok:
        _mocap_model = True
        logger.info("MoCapAnything V2 仓库就绪（subprocess 模式）")
    else:
        logger.warning(f"MoCapAnything 未就绪: {msg}")
    return _mocap_model


async def run_mocap_inference(task_id: str, video_path: Path, output_path: Path):
    """
    执行 MoCapAnything V2 推理（video2pose2rot pipeline）。
    通过 subprocess 调用 mocap_repo/inference/video2pose2rot.py。
    """
    model = await load_mocap_model()
    if model is None:
        logger.warning("MoCapAnything 未就绪，生成占位 BVH 用于测试")
        _generate_placeholder_bvh(output_path)
        return

    # 1. 把视频帧提取到临时目录（video2pose2rot 需要 image_roots）
    frames_dir = OUTPUT_DIR / f"{task_id}_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    try:
        task_manager.update_progress(task_id, 15)
        ffmpeg_cmd = [
            "ffmpeg", "-y", "-i", str(video_path),
            "-vf", "fps=15,scale=720:-2",
            "-q:v", "2",
            str(frames_dir / "%06d.jpg"),
        ]
        proc = await asyncio.create_subprocess_exec(
            *ffmpeg_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg 帧提取失败: {stderr.decode()[-300:]}")
        frame_count = len(list(frames_dir.glob("*.jpg")))
        logger.info(f"[{task_id}] 提取 {frame_count} 帧")
        task_manager.update_progress(task_id, 35)

        # 2. 生成 wild 模式临时 config（覆盖 image_roots 和 save_dir）
        import yaml
        base_cfg_path = MOCAP_REPO_PATH / "configs" / "inference" / "inference_video2pose2rot.yaml"
        with open(base_cfg_path, "r") as f:
            cfg = yaml.safe_load(f)

        cfg["data"]["image_roots"] = [str(frames_dir.parent)]  # 父目录，脚本会递归找帧
        cfg["data"]["wild_flag"] = True
        cfg["data"]["retarget"]["toggle"] = True  # wild模式需要retarget引导骨架
        cfg["runtime"]["device"] = DEVICE
        infer_save_dir = OUTPUT_DIR / f"{task_id}_infer"
        cfg["output"]["save_dir"] = str(infer_save_dir)
        cfg["output"]["blender_path"] = None  # 不渲染视频，只输出 BVH

        tmp_cfg_path = OUTPUT_DIR / f"{task_id}_cfg.yaml"
        with open(tmp_cfg_path, "w") as f:
            yaml.dump(cfg, f)

        task_manager.update_progress(task_id, 45)

        # 3. subprocess 调用推理脚本
        inference_script = MOCAP_REPO_PATH / "inference" / "video2pose2rot.py"
        cmd = [
            "python", "-m", "inference.video2pose2rot",
            "--config", str(tmp_cfg_path),
        ]
        logger.info(f"[{task_id}] 启动推理: {' '.join(cmd)}")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(MOCAP_REPO_PATH),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        # 流式读取输出并更新进度
        progress = 45
        async for line in proc.stdout:
            txt = line.decode(errors="replace").strip()
            if txt:
                logger.info(f"[mocap] {txt}")
            if "Complete" in txt or "Saved" in txt:
                progress = min(progress + 10, 88)
                task_manager.update_progress(task_id, progress)

        await proc.wait()
        if proc.returncode != 0:
            raise RuntimeError(f"video2pose2rot 推理失败 (code={proc.returncode})")

        task_manager.update_progress(task_id, 90)

        # 4. 找到生成的 BVH 文件并复制到 output_path
        bvh_files = sorted(infer_save_dir.rglob("*.bvh"))
        if not bvh_files:
            raise RuntimeError("推理完成但未找到 BVH 输出文件")
        shutil.copy2(bvh_files[0], output_path)
        logger.info(f"[{task_id}] 推理完成 → {output_path}")

    finally:
        # 清理临时帧目录和 config
        if frames_dir.exists():
            shutil.rmtree(frames_dir, ignore_errors=True)
        tmp_cfg_path = OUTPUT_DIR / f"{task_id}_cfg.yaml"
        if tmp_cfg_path.exists():
            tmp_cfg_path.unlink(missing_ok=True)


def _generate_placeholder_bvh(output_path: Path):
    """生成一个完整人体骨骼占位 BVH（全身关节 + 简单挥手动作）"""
    import math

    # 骨骼层级定义：(关节名, 父关节, 相对于父关节的偏移)
    joints = [
        ("Hips", None, (0.0, 96.0, 0.0)),
        ("LeftUpLeg", "Hips", (8.0, -5.0, 0.0)),
        ("LeftLeg", "LeftUpLeg", (0.0, -45.0, 0.0)),
        ("LeftFoot", "LeftLeg", (0.0, -45.0, 0.0)),
        ("LeftToeBase", "LeftFoot", (0.0, -10.0, 15.0)),
        ("RightUpLeg", "Hips", (-8.0, -5.0, 0.0)),
        ("RightLeg", "RightUpLeg", (0.0, -45.0, 0.0)),
        ("RightFoot", "RightLeg", (0.0, -45.0, 0.0)),
        ("RightToeBase", "RightFoot", (0.0, -10.0, 15.0)),
        ("Spine", "Hips", (0.0, 12.0, 0.0)),
        ("Spine1", "Spine", (0.0, 12.0, 0.0)),
        ("Neck", "Spine1", (0.0, 12.0, 0.0)),
        ("Head", "Neck", (0.0, 8.0, 0.0)),
        ("LeftShoulder", "Spine1", (6.0, 4.0, 0.0)),
        ("LeftArm", "LeftShoulder", (10.0, 0.0, 0.0)),
        ("LeftForeArm", "LeftArm", (0.0, -28.0, 0.0)),
        ("LeftHand", "LeftForeArm", (0.0, -26.0, 0.0)),
        ("RightShoulder", "Spine1", (-6.0, 4.0, 0.0)),
        ("RightArm", "RightShoulder", (-10.0, 0.0, 0.0)),
        ("RightForeArm", "RightArm", (0.0, -28.0, 0.0)),
        ("RightHand", "RightForeArm", (0.0, -26.0, 0.0)),
    ]

    def write_hierarchy(f, joint_name, parent_name, depth=0):
        indent = "    " * depth
        for jname, jparent, joffset in joints:
            if jparent == joint_name:
                f.write(f"{indent}JOINT {jname}\n")
                f.write(f"{indent}{{\n")
                f.write(f"{indent}    OFFSET {joffset[0]:.2f} {joffset[1]:.2f} {joffset[2]:.2f}\n")
                f.write(f"{indent}    CHANNELS 3 Zrotation Xrotation Yrotation\n")
                # 递归写子关节
                write_hierarchy(f, jname, jname, depth + 1)
                # End Site 只给末端关节（没有子关节的）
                has_children = any(jp == jname for _, jp, _ in joints)
                if not has_children:
                    # 末端延伸一点
                    f.write(f"{indent}    End Site\n")
                    f.write(f"{indent}    {{\n")
                    f.write(f"{indent}        OFFSET 0.00 10.00 0.00\n")
                    f.write(f"{indent}    }}\n")
                f.write(f"{indent}}}\n")

    num_frames = 60
    frame_time = 0.0333333

    lines = []
    lines.append("HIERARCHY")
    lines.append("ROOT Hips")
    lines.append("{")
    lines.append("    OFFSET 0.00 0.00 0.00")
    lines.append("    CHANNELS 6 Xposition Yposition Zposition Zrotation Xrotation Yrotation")
    # 手动写 Hips 的直接子关节
    for jname, jparent, joffset in joints:
        if jparent == "Hips":
            lines.append(f"    JOINT {jname}")
            lines.append(f"    {{")
            lines.append(f"        OFFSET {joffset[0]:.2f} {joffset[1]:.2f} {joffset[2]:.2f}")
            lines.append(f"        CHANNELS 3 Zrotation Xrotation Yrotation")
            # 递归
            def rec(name, depth):
                ind = "    " * depth
                for cn, cp, co in joints:
                    if cp == name:
                        lines.append(f"{ind}JOINT {cn}")
                        lines.append(f"{ind}{{")
                        lines.append(f"{ind}    OFFSET {co[0]:.2f} {co[1]:.2f} {co[2]:.2f}")
                        lines.append(f"{ind}    CHANNELS 3 Zrotation Xrotation Yrotation")
                        rec(cn, depth + 1)
                        # End Site for leaf
                        has_c = any(p == cn for _, p, _ in joints)
                        if not has_c:
                            lines.append(f"{ind}    End Site")
                            lines.append(f"{ind}    {{")
                            lines.append(f"{ind}        OFFSET 0.00 10.00 0.00")
                            lines.append(f"{ind}    }}")
                        lines.append(f"{ind}}}")
            rec(jname, 2)
            has_c = any(p == jname for _, p, _ in joints)
            if not has_c:
                lines.append(f"        End Site")
                lines.append(f"        {{")
                lines.append(f"            OFFSET 0.00 10.00 0.00")
                lines.append(f"        }}")
            lines.append(f"    }}")
    lines.append("}")
    lines.append("MOTION")
    lines.append(f"Frames: {num_frames}")
    lines.append(f"Frame Time: {frame_time}")

    # 生成运动数据：右臂简单挥手 + 轻微 hips 移动
    for i in range(num_frames):
        t = i / num_frames
        # Hips: 位置 + 旋转 (6 channels)
        hx = math.sin(t * math.pi * 2) * 5.0  # 左右移动
        hy = 96.0
        hz = 0.0
        hrx, hry, hrz = 0.0, 0.0, 0.0

        # 其他关节旋转：基础都是0，只有右臂有动作
        # 关节顺序：按层级深度优先遍历
        # 每个非根关节3通道 (Zrot, Xrot, Yrot)
        vals = [hx, hy, hz, hrx, hry, hrz]  # Hips 6 channels

        # 简单挥手：右臂前后摆动
        right_arm_angle = math.sin(t * math.pi * 4) * 45.0  # 前后摆
        right_forearm_angle = math.sin(t * math.pi * 4 + 0.5) * 30.0

        for jname, jparent, _ in joints:
            if jname == "Hips":
                continue
            if jname == "RightArm":
                vals.extend([0.0, right_arm_angle, 0.0])
            elif jname == "RightForeArm":
                vals.extend([0.0, right_forearm_angle, 0.0])
            else:
                vals.extend([0.0, 0.0, 0.0])

        lines.append(" ".join(f"{v:.4f}" for v in vals))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ──────────────────────────────
# 后台推理 worker
# ──────────────────────────────

async def _process_task(task_id: str, video_path: Path):
    """后台处理任务"""
    task_manager.update_status(task_id, "processing")
    task_manager.update_progress(task_id, 10)

    output_path = OUTPUT_DIR / f"{task_id}.bvh"

    try:
        # 模拟/实际推理
        await run_mocap_inference(task_id, video_path, output_path)

        if output_path.exists():
            task_manager.set_result(task_id, output_path)
        else:
            raise RuntimeError("推理完成但输出文件不存在")

    except Exception as e:
        logger.error(f"任务 {task_id} 推理失败: {e}", exc_info=True)
        task_manager.update_status(task_id, "failed", error=str(e))


# ──────────────────────────────
# API 路由
# ──────────────────────────────

class UploadResponse(BaseModel):
    ok: bool
    task_id: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None


class TaskStatusResponse(BaseModel):
    ok: bool
    task_id: str
    status: str
    progress: int
    error: Optional[str] = None
    has_result: bool = False


@app.get("/health")
async def health():
    """健康检查"""
    model = await load_mocap_model()
    ok, msg = _check_repo_ready()
    return {
        "ok": True,
        "status": "ok",
        "model_loaded": model is not None,
        "mode": "ready" if ok else "placeholder",
        "engine": "MoCapAnything V2 (video2pose2rot)",
        "repo_status": msg,
    }


@app.post("/upload", response_model=UploadResponse)
async def upload_video(
    background_tasks: BackgroundTasks,
    video: UploadFile = File(...),
):
    """
    上传视频并开始 MoCapAnything 推理任务。
    
    Returns:
        task_id: 用于后续查询状态和下载结果
    """
    # 检查文件大小（粗略估计）
    content = await video.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(413, f"文件过大，最大支持 {MAX_FILE_SIZE/1024/1024:.0f} MB")

    # 保存上传文件
    task = task_manager.create_task(video_path=Path(""))
    video_path = UPLOAD_DIR / f"{task.id}_{video.filename}"
    with open(video_path, "wb") as f:
        f.write(content)

    # 更新任务视频路径
    task.video_path = video_path

    # 启动后台推理
    asyncio.create_task(_process_task(task.id, video_path))

    return UploadResponse(
        ok=True,
        task_id=task.id,
        message="任务已创建，正在推理中...",
    )


@app.get("/task/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    """查询任务状态和进度"""
    data = task_manager.to_dict(task_id)
    if not data:
        raise HTTPException(404, "任务不存在")

    return TaskStatusResponse(
        ok=True,
        task_id=task_id,
        status=data["status"],
        progress=data["progress"],
        error=data.get("error"),
        has_result=data.get("has_result", False),
    )


@app.get("/result/{task_id}/download")
async def download_result(task_id: str):
    """
    下载推理结果（BVH 文件）。
    
    如果任务未完成，返回 202 Accepted。
    """
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")

    if task.status == "failed":
        raise HTTPException(500, f"推理失败: {task.error}")

    if task.status != "completed" or not task.result_path:
        raise HTTPException(202, "推理进行中，请稍后重试")

    if not task.result_path.exists():
        raise HTTPException(500, "结果文件丢失")

    return FileResponse(
        path=task.result_path,
        media_type="application/octet-stream",
        filename=f"{task_id}_motion.bvh",
    )


# ──────────────────────────────
# 启动入口
# ──────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT, workers=WORKERS)
