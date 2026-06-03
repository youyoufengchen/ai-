"""
MoCapAnything 推理服务客户端

功能：
1. 服务发现：检测 localhost:8767 是否有 MoCapAnything 推理服务
2. 视频上传 + 推理请求
3. 结果拉取（轮询任务状态）
4. 失败时回退到 MediaPipe

环境要求：
- MoCapAnything 推理服务需单独部署（FastAPI，端口 8767）
- 服务部署指南见 tools/mocap_anything_service/README.md
"""

import json
import logging
import asyncio
import aiohttp
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger("mocap_anything")

MOCAP_SERVICE_URL = "http://localhost:8767"
MOCAP_SERVICE_TIMEOUT = 300  # 5分钟（推理可能很慢）


@dataclass
class MoCapServiceConfig:
    url: str = MOCAP_SERVICE_URL
    timeout: int = MOCAP_SERVICE_TIMEOUT
    enabled: bool = True


class MoCapAnythingClient:
    """
    MoCapAnything 推理服务客户端
    
    工作流程：
    1. 上传视频到推理服务（POST /extract）
    2. 轮询任务状态（GET /status/{task_id}）
    3. 下载结果（BVH + 预览图）
    4. 转换为系统格式（canonical.json + GLB）
    """
    
    def __init__(self, config: Optional[MoCapServiceConfig] = None):
        self.cfg = config or MoCapServiceConfig()
        self._available: Optional[bool] = None
        
    async def check_available(self, force: bool = False) -> bool:
        """检测推理服务是否可用"""
        if not force and self._available is not None:
            return self._available
        if not self.cfg.enabled:
            self._available = False
            return False
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(f"{self.cfg.url}/health") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        status = data.get("status", "")
                        self._available = status in ("ok", "ready")
                        if self._available:
                            logger.info(f"MoCapAnything 服务可用: {self.cfg.url}")
                        else:
                            logger.warning(f"MoCapAnything 服务返回非 ok 状态: {status}")
                        return self._available
        except Exception as e:
            logger.debug(f"MoCapAnything 服务检测失败: {e}")
        self._available = False
        return False
    
    async def get_health(self) -> Dict[str, Any]:
        """获取 /health 完整响应（含 mode / engine / repo_status 等字段）"""
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(f"{self.cfg.url}/health") as resp:
                    if resp.status == 200:
                        return await resp.json()
        except Exception as e:
            logger.debug(f"get_health 失败: {e}")
        return {"ok": False, "mode": "unavailable"}

    async def extract_from_video(
        self,
        video_path: Path,
        skeleton_type: str = "humanoid",
        progress_callback = None
    ) -> Dict[str, Any]:
        """
        上传视频并启动 MoCapAnything 推理
        
        Args:
            video_path: 本地视频文件路径
            skeleton_type: 骨骼类型（humanoid/quadruped/mechanical/...）
            progress_callback: 进度回调 (percent, stage)
        
        Returns:
            {
                "ok": True/False,
                "bvh_path": BVH文件路径,
                "canonical_path": canonical.json路径,
                "glb_path": GLB文件路径,
                "duration": 动画时长,
                "frames": 帧数,
                "service": "mocap_anything",
                "error": 错误信息
            }
        """
        if not await self.check_available():
            return {
                "ok": False,
                "error": "MoCapAnything 推理服务未启动或未响应。"
                         f"请先在另一终端运行: cd tools/mocap_anything_service && python service.py"
            }
        
        if progress_callback:
            await progress_callback(5, "上传视频到 MoCapAnything 服务...")
        
        try:
            # 1. 上传视频
            task_id = await self._upload_video(video_path, skeleton_type)
            if not task_id:
                return {"ok": False, "error": "上传视频到推理服务失败"}
            
            if progress_callback:
                await progress_callback(10, "推理中...（MoCapAnything，约需 30-120 秒）")
            
            # 2. 轮询等待完成
            result = await self._poll_task(task_id, progress_callback)
            if not result.get("ok"):
                return result
            
            # 3. 下载结果到本地
            local_result = await self._download_results(result, video_path.parent, progress_callback)
            return local_result
            
        except Exception as e:
            logger.error(f"MoCapAnything 推理异常: {e}", exc_info=True)
            return {"ok": False, "error": f"推理异常: {str(e)}"}
    
    async def _upload_video(self, video_path: Path, skeleton_type: str) -> Optional[str]:
        """上传视频，返回 task_id"""
        try:
            timeout = aiohttp.ClientTimeout(total=120)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                data = aiohttp.FormData()
                with open(video_path, "rb") as f:
                    data.add_field("video", f, filename=video_path.name, content_type="video/mp4")
                    
                    async with session.post(
                        f"{self.cfg.url}/upload",
                        data=data
                    ) as resp:
                        if resp.status != 200:
                            text = await resp.text()
                            logger.error(f"上传失败: {resp.status} {text}")
                            return None
                        result = await resp.json()
                        if not result.get("ok"):
                            logger.error(f"上传失败: {result}")
                            return None
                        return result.get("task_id")
        except Exception as e:
            logger.error(f"上传视频异常: {e}")
            return None
    
    async def _poll_task(
        self,
        task_id: str,
        progress_callback = None
    ) -> Dict[str, Any]:
        """轮询任务状态直到完成或失败"""
        max_wait = self.cfg.timeout
        poll_interval = 3
        elapsed = 0
        
        while elapsed < max_wait:
            try:
                timeout = aiohttp.ClientTimeout(total=10)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(f"{self.cfg.url}/task/{task_id}") as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if not data.get("ok"):
                                return {"ok": False, "error": data.get("error", "查询失败")}
                            
                            status = data.get("status", "pending")
                            progress = data.get("progress", 0)
                            stage_map = {
                                "pending": "等待处理...",
                                "processing": "GPU推理中...",
                                "completed": "推理完成",
                                "failed": "推理失败",
                            }
                            stage = stage_map.get(status, f"状态: {status}")
                            
                            if progress_callback:
                                # 映射 10%→90%
                                mapped = 10 + int(progress * 0.8)
                                await progress_callback(mapped, stage)
                            
                            if status == "completed":
                                return {
                                    "ok": True,
                                    "task_id": task_id,
                                    "has_result": data.get("has_result", False),
                                }
                            elif status == "failed":
                                return {
                                    "ok": False,
                                    "error": data.get("error", "推理失败")
                                }
                            # else: pending / processing
            except Exception as e:
                logger.debug(f"轮询异常: {e}")
            
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
        
        return {"ok": False, "error": f"推理超时（>{max_wait}秒）"}
    
    async def _download_results(
        self,
        result: Dict[str, Any],
        output_dir: Path,
        progress_callback = None
    ) -> Dict[str, Any]:
        """下载推理结果到本地"""
        if progress_callback:
            await progress_callback(90, "下载BVH结果...")
        
        task_id = result["task_id"]
        
        try:
            # 下载 BVH: GET /result/{task_id}/download
            bvh_path = output_dir / f"{task_id}.bvh"
            download_url = f"{self.cfg.url}/result/{task_id}/download"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(download_url) as resp:
                    if resp.status == 202:
                        # 结果还在生成中，不应出现（因为已经轮询到 completed）
                        return {"ok": False, "error": "结果文件尚未准备好"}
                    if resp.status != 200:
                        text = await resp.text()
                        return {"ok": False, "error": f"下载BVH失败: HTTP {resp.status} {text[:200]}"}
                    bvh_path.write_bytes(await resp.read())
            
            if progress_callback:
                await progress_callback(95, "转换格式...")
            
            return {
                "ok": True,
                "bvh_path": str(bvh_path),
                "task_id": task_id,
                "service": "mocap_anything",
            }
        except Exception as e:
            return {"ok": False, "error": f"下载结果异常: {e}"}


# 全局实例
_mocap_client: Optional[MoCapAnythingClient] = None


def get_mocap_client() -> MoCapAnythingClient:
    """获取全局 MoCapAnything 客户端"""
    global _mocap_client
    if _mocap_client is None:
        _mocap_client = MoCapAnythingClient()
    return _mocap_client


def init_mocap_client(config: Optional[MoCapServiceConfig] = None):
    """初始化全局客户端"""
    global _mocap_client
    _mocap_client = MoCapAnythingClient(config)
    logger.info("MoCapAnything 客户端已初始化")
