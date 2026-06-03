"""
TTS 缓存 LRU 清理器
- 按最后访问时间排序
- 超过 max_files 时删除最旧的文件
- 可定期运行或手动触发
"""
import logging
import os
import time
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger("server")


class CacheCleaner:
    """LRU 策略清理 TTS 缓存目录"""

    def __init__(self, cache_dirs: List[Path], max_files: int = 500, max_age_hours: int = 72):
        """
        Args:
            cache_dirs: 需要清理的缓存目录列表
            max_files: 每个目录最多保留的文件数
            max_age_hours: 超过此小时数的文件直接删除
        """
        self.cache_dirs = cache_dirs
        self.max_files = max_files
        self.max_age_seconds = max_age_hours * 3600

    def cleanup(self) -> Dict[str, int]:
        """执行一次清理，返回每个目录删除的文件数"""
        results = {}
        for d in self.cache_dirs:
            if not d.exists():
                continue
            deleted = self._cleanup_dir(d)
            results[str(d.name)] = deleted
            if deleted > 0:
                logger.info(f"Cache cleanup: {d.name} - deleted {deleted} files")
        return results

    def _cleanup_dir(self, directory: Path) -> int:
        """清理单个目录"""
        files = []
        now = time.time()
        for f in directory.iterdir():
            if f.is_file():
                try:
                    stat = f.stat()
                    # 用 atime（最后访问时间），fallback 到 mtime
                    access_time = stat.st_atime or stat.st_mtime
                    files.append((f, access_time, stat.st_size))
                except OSError:
                    continue

        deleted = 0

        # 1. 删除过期文件
        for f, atime, _ in files:
            if (now - atime) > self.max_age_seconds:
                try:
                    f.unlink()
                    deleted += 1
                except OSError:
                    pass

        # 重新扫描剩余文件
        remaining = [(f, at, sz) for f, at, sz in files if f.exists()]
        remaining.sort(key=lambda x: x[1])  # 按访问时间升序（最旧在前）

        # 2. 如果数量超限，删除最旧的
        excess = len(remaining) - self.max_files
        if excess > 0:
            for f, _, _ in remaining[:excess]:
                try:
                    f.unlink()
                    deleted += 1
                except OSError:
                    pass

        return deleted

    def get_stats(self) -> Dict[str, Dict]:
        """获取缓存统计信息"""
        stats = {}
        for d in self.cache_dirs:
            if not d.exists():
                stats[d.name] = {"files": 0, "size_mb": 0}
                continue
            files = list(d.iterdir())
            total_size = sum(f.stat().st_size for f in files if f.is_file())
            stats[d.name] = {
                "files": len([f for f in files if f.is_file()]),
                "size_mb": round(total_size / (1024 * 1024), 2),
            }
        return stats
