"""
MoCapAnything 异步任务管理

支持：
- 任务状态跟踪（pending / processing / completed / failed）
- 超时清理
- 结果文件管理
"""

import uuid
import shutil
import asyncio
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Optional, List
from datetime import datetime, timedelta

from config import OUTPUT_DIR, TASK_TIMEOUT, CLEANUP_INTERVAL

logger = logging.getLogger("mocap_tasks")


@dataclass
class Task:
    id: str
    status: str  # pending / processing / completed / failed
    created_at: datetime
    video_path: Optional[Path] = None
    result_path: Optional[Path] = None
    error: Optional[str] = None
    progress: int = 0  # 0-100
    meta: Dict = field(default_factory=dict)


class TaskManager:
    def __init__(self):
        self.tasks: Dict[str, Task] = {}
        self._cleanup_task = None

    async def start(self):
        """启动后台清理任务"""
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop(self):
        """停止后台清理任务"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

    async def _cleanup_loop(self):
        """定期清理过期任务"""
        while True:
            await asyncio.sleep(CLEANUP_INTERVAL)
            self._cleanup_expired()

    def _cleanup_expired(self):
        """清理超时任务和文件"""
        now = datetime.now()
        expired = [
            tid for tid, task in self.tasks.items()
            if now - task.created_at > timedelta(seconds=TASK_TIMEOUT)
        ]
        for tid in expired:
            task = self.tasks.pop(tid, None)
            if task:
                self._remove_task_files(task)
                logger.info(f"清理过期任务: {tid}")

    def _remove_task_files(self, task: Task):
        """删除任务相关文件"""
        for path in [task.video_path, task.result_path]:
            if path and path.exists():
                try:
                    if path.is_dir():
                        shutil.rmtree(path)
                    else:
                        path.unlink()
                except Exception as e:
                    logger.warning(f"删除文件失败 {path}: {e}")

    def create_task(self, video_path: Path) -> Task:
        """创建新任务"""
        tid = str(uuid.uuid4())
        task = Task(
            id=tid,
            status="pending",
            created_at=datetime.now(),
            video_path=video_path,
        )
        self.tasks[tid] = task
        logger.info(f"创建任务 {tid}: {video_path}")
        return task

    def get_task(self, tid: str) -> Optional[Task]:
        """获取任务"""
        return self.tasks.get(tid)

    def update_status(self, tid: str, status: str, error: Optional[str] = None):
        """更新任务状态"""
        task = self.tasks.get(tid)
        if task:
            task.status = status
            if error:
                task.error = error
            logger.info(f"任务 {tid} 状态 -> {status}")

    def update_progress(self, tid: str, progress: int):
        """更新任务进度"""
        task = self.tasks.get(tid)
        if task:
            task.progress = min(100, max(0, progress))

    def set_result(self, tid: str, result_path: Path):
        """设置任务结果"""
        task = self.tasks.get(tid)
        if task:
            task.result_path = result_path
            task.status = "completed"
            task.progress = 100
            logger.info(f"任务 {tid} 完成: {result_path}")

    def to_dict(self, tid: str) -> Optional[Dict]:
        """任务序列化"""
        task = self.tasks.get(tid)
        if not task:
            return None
        return {
            "id": task.id,
            "status": task.status,
            "progress": task.progress,
            "created_at": task.created_at.isoformat(),
            "error": task.error,
            "has_result": task.result_path is not None and task.result_path.exists(),
            "meta": task.meta,
        }


# 全局任务管理器
task_manager = TaskManager()
