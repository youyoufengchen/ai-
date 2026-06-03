"""
缓存管理模块 — 提供 LRU 清理策略

用于管理 TTS 音频文件缓存，防止磁盘空间无限增长。
"""

import os
import time
import logging
from pathlib import Path
from typing import List, Tuple, Optional
from dataclasses import dataclass

logger = logging.getLogger("cache_manager")


@dataclass
class CacheEntry:
    """缓存条目"""
    path: Path
    size: int
    mtime: float
    atime: float  # 最后访问时间


class TTSCacheManager:
    """
    TTS 缓存管理器
    
    支持两种清理策略:
    1. 数量限制 (max_files): 保留最近访问的 N 个文件
    2. 容量限制 (max_size_mb): 保留最近访问的文件，直到总大小低于阈值
    
    默认策略: 500个文件 或 2GB，先触发的为准
    """
    
    DEFAULT_MAX_FILES = 500
    DEFAULT_MAX_SIZE_MB = 2048  # 2GB
    
    def __init__(
        self,
        max_files: int = DEFAULT_MAX_FILES,
        max_size_mb: int = DEFAULT_MAX_SIZE_MB,
        cache_dirs: Optional[List[Path]] = None
    ):
        self.max_files = max_files
        self.max_size_bytes = max_size_mb * 1024 * 1024
        
        # 默认缓存目录
        if cache_dirs is None:
            root = Path(__file__).parent.parent / "cache"
            self.cache_dirs = [
                root / "tts",           # 火山引擎
                root / "tts_minimax",   # MiniMax
                root / "tts_edge",      # Edge TTS
            ]
        else:
            self.cache_dirs = cache_dirs
    
    def _get_cache_entries(self, directory: Path) -> List[CacheEntry]:
        """获取目录中所有缓存条目，按访问时间排序"""
        entries = []
        
        if not directory.exists():
            return entries
        
        for file_path in directory.glob("*.mp3"):
            try:
                stat = file_path.stat()
                # 尝试获取最后访问时间，如果不支持则使用修改时间
                atime = getattr(stat, 'st_atime', stat.st_mtime)
                entries.append(CacheEntry(
                    path=file_path,
                    size=stat.st_size,
                    mtime=stat.st_mtime,
                    atime=atime
                ))
            except OSError as e:
                logger.warning(f"无法读取文件状态 {file_path}: {e}")
        
        # 按最后访问时间排序（最晚访问的在前面）
        return sorted(entries, key=lambda e: e.atime, reverse=True)
    
    def _cleanup_directory(
        self,
        directory: Path,
        max_files: Optional[int] = None,
        max_size_bytes: Optional[int] = None
    ) -> Tuple[int, int]:
        """
        清理单个目录
        
        Returns:
            (删除文件数, 释放字节数)
        """
        max_f = max_files or self.max_files
        max_b = max_size_bytes or self.max_size_bytes
        
        entries = self._get_cache_entries(directory)
        
        if not entries:
            return 0, 0
        
        # 计算当前总大小
        total_size = sum(e.size for e in entries)
        total_files = len(entries)
        
        logger.info(
            f"缓存目录 {directory.name}: "
            f"{total_files} 文件, {total_size / 1024 / 1024:.1f} MB"
        )
        
        # 决定是否需要清理
        need_cleanup = total_files > max_f or total_size > max_b
        
        if not need_cleanup:
            return 0, 0
        
        # 计算需要删除的文件
        deleted = 0
        freed = 0
        current_size = total_size
        current_files = total_files
        
        # 从最少访问的开始删除
        for entry in reversed(entries):
            # 如果已经满足所有条件，停止
            if current_files <= max_f and current_size <= max_b:
                break
            
            try:
                entry.path.unlink()
                deleted += 1
                freed += entry.size
                current_size -= entry.size
                current_files -= 1
                logger.debug(f"删除缓存: {entry.path.name}")
            except OSError as e:
                logger.warning(f"无法删除缓存文件 {entry.path}: {e}")
        
        return deleted, freed
    
    def cleanup(
        self,
        max_files: Optional[int] = None,
        max_size_mb: Optional[int] = None
    ) -> dict:
        """
        执行 LRU 清理
        
        Returns:
            统计信息字典
        """
        max_b = (max_size_mb or self.max_size_bytes // (1024 * 1024)) * 1024 * 1024
        
        total_deleted = 0
        total_freed = 0
        details = {}
        
        for cache_dir in self.cache_dirs:
            if not cache_dir.exists():
                continue
            
            deleted, freed = self._cleanup_directory(
                cache_dir,
                max_files=max_files,
                max_size_bytes=max_b
            )
            
            total_deleted += deleted
            total_freed += freed
            details[cache_dir.name] = {
                "deleted": deleted,
                "freed_mb": round(freed / 1024 / 1024, 2)
            }
        
        summary = {
            "total_deleted": total_deleted,
            "total_freed_mb": round(total_freed / 1024 / 1024, 2),
            "by_directory": details
        }
        
        if total_deleted > 0:
            logger.info(
                f"LRU 清理完成: 删除 {total_deleted} 个文件, "
                f"释放 {summary['total_freed_mb']} MB"
            )
        else:
            logger.debug("LRU 清理: 无需清理")
        
        return summary
    
    def get_stats(self) -> dict:
        """获取缓存统计信息"""
        stats = {
            "directories": {},
            "total_files": 0,
            "total_size_mb": 0
        }
        
        for cache_dir in self.cache_dirs:
            if not cache_dir.exists():
                continue
            
            entries = self._get_cache_entries(cache_dir)
            size = sum(e.size for e in entries)
            
            stats["directories"][cache_dir.name] = {
                "files": len(entries),
                "size_mb": round(size / 1024 / 1024, 2),
                "path": str(cache_dir)
            }
            stats["total_files"] += len(entries)
            stats["total_size_mb"] += round(size / 1024 / 1024, 2)
        
        return stats
    
    def update_access_time(self, file_path: Path):
        """
        更新文件访问时间（用于 LRU 排序）
        
        在提供文件时调用，确保 LRU 策略准确
        """
        try:
            if file_path.exists():
                # 更新访问时间
                now = time.time()
                os.utime(file_path, (now, file_path.stat().st_mtime))
        except OSError:
            pass


# 全局单例
_cache_manager = None


def get_cache_manager() -> TTSCacheManager:
    """获取全局缓存管理器实例"""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = TTSCacheManager()
    return _cache_manager


def cleanup_tts_cache(max_files: int = 500, max_size_mb: int = 2048) -> dict:
    """
    便捷函数：清理 TTS 缓存
    
    Args:
        max_files: 每个目录最大保留文件数
        max_size_mb: 每个目录最大容量 (MB)
    
    Returns:
        清理统计信息
    """
    manager = get_cache_manager()
    return manager.cleanup(max_files=max_files, max_size_mb=max_size_mb)


def get_tts_cache_stats() -> dict:
    """获取 TTS 缓存统计"""
    return get_cache_manager().get_stats()
