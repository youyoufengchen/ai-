"""
Self-Healing System - 系统自愈机制

监控关键模块健康状态，发现问题自动尝试修复：
- TTS 服务健康检查
- 动作规划服务检查
- 缓存状态监控
- 内存泄漏防护
"""

import asyncio
import gc
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class HealthCheck:
    """健康检查结果"""
    module: str
    status: str  # 'healthy', 'warning', 'critical', 'unknown'
    message: str
    last_check: float
    metrics: Dict = None


class SelfHealingManager:
    """
    系统自愈管理器

    功能：
    1. 定期检查关键模块健康状态
    2. 发现问题自动尝试修复
    3. 记录自愈历史
    4. 提供健康状态 API
    """

    def __init__(self, check_interval: int = 60):
        self.check_interval = check_interval  # 检查间隔（秒）
        self._checks: Dict[str, Callable] = {}
        self._healers: Dict[str, Callable] = {}
        self._history: List[Dict] = []
        self._last_results: Dict[str, HealthCheck] = {}
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._start_time = time.time()

    def register_check(self, module: str, check_fn: Callable[[], HealthCheck]):
        """注册健康检查函数"""
        self._checks[module] = check_fn
        logger.info(f"[SelfHealing] Registered health check: {module}")

    def register_healer(self, module: str, heal_fn: Callable[[], bool]):
        """注册自愈修复函数"""
        self._healers[module] = heal_fn
        logger.info(f"[SelfHealing] Registered healer: {module}")

    async def start(self):
        """启动自愈监控循环"""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("[SelfHealing] Monitoring started")

    async def stop(self):
        """停止自愈监控"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[SelfHealing] Monitoring stopped")

    async def _monitor_loop(self):
        """监控主循环"""
        while self._running:
            try:
                await self._run_checks()
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[SelfHealing] Monitor loop error: {e}")
                await asyncio.sleep(5)  # 出错后短间隔重试

    async def _run_checks(self):
        """执行所有健康检查"""
        for module, check_fn in self._checks.items():
            try:
                if asyncio.iscoroutinefunction(check_fn):
                    result = await check_fn()
                else:
                    result = check_fn()

                self._last_results[module] = result

                # 需要修复
                if result.status in ('warning', 'critical'):
                    await self._attempt_heal(module, result)

            except Exception as e:
                logger.error(f"[SelfHealing] Check failed for {module}: {e}")
                self._last_results[module] = HealthCheck(
                    module=module,
                    status='unknown',
                    message=f'Check error: {e}',
                    last_check=time.time(),
                )

    async def _attempt_heal(self, module: str, check: HealthCheck):
        """尝试修复问题"""
        healer = self._healers.get(module)
        if not healer:
            logger.warning(f"[SelfHealing] No healer for {module}, status: {check.status}")
            return

        logger.info(f"[SelfHealing] Attempting to heal {module}: {check.message}")

        try:
            if asyncio.iscoroutinefunction(healer):
                success = await healer()
            else:
                success = healer()

            self._history.append({
                'timestamp': time.time(),
                'module': module,
                'issue': check.message,
                'success': success,
            })

            if success:
                logger.info(f"[SelfHealing] Healed {module} successfully")
            else:
                logger.warning(f"[SelfHealing] Failed to heal {module}")

        except Exception as e:
            logger.error(f"[SelfHealing] Healer error for {module}: {e}")
            self._history.append({
                'timestamp': time.time(),
                'module': module,
                'issue': check.message,
                'success': False,
                'error': str(e),
            })

    def get_health_report(self) -> Dict:
        """获取健康报告"""
        healthy_count = sum(1 for r in self._last_results.values() if r.status == 'healthy')
        total_count = len(self._last_results)

        return {
            'status': 'healthy' if healthy_count == total_count else 'degraded',
            'uptime': time.time() - self._start_time,
            'checks': {m: {
                'status': r.status,
                'message': r.message,
                'last_check': r.last_check,
                'metrics': r.metrics,
            } for m, r in self._last_results.items()},
            'summary': {
                'total': total_count,
                'healthy': healthy_count,
                'warning': sum(1 for r in self._last_results.values() if r.status == 'warning'),
                'critical': sum(1 for r in self._last_results.values() if r.status == 'critical'),
            },
            'recent_heals': self._history[-10:],  # 最近10次修复记录
        }


# ═══════════════════════════════════════════════════════════
#  内置健康检查函数
# ═══════════════════════════════════════════════════════════

def check_tts_health() -> HealthCheck:
    """检查 TTS 服务健康状态"""
    try:
        from modules.cache_manager import get_tts_cache_stats
        stats = get_tts_cache_stats()

        total_files = sum(s['file_count'] for s in stats.values())
        total_size_mb = sum(s['total_size_mb'] for s in stats.values())

        metrics = {
            'total_files': total_files,
            'total_size_mb': total_size_mb,
            'providers': len(stats),
        }

        # 判断健康状态
        if total_size_mb > 2048:  # > 2GB
            return HealthCheck(
                module='tts',
                status='critical',
                message=f'Cache oversized: {total_size_mb:.1f}MB',
                last_check=time.time(),
                metrics=metrics,
            )
        elif total_size_mb > 1024:  # > 1GB
            return HealthCheck(
                module='tts',
                status='warning',
                message=f'Cache large: {total_size_mb:.1f}MB',
                last_check=time.time(),
                metrics=metrics,
            )

        return HealthCheck(
            module='tts',
            status='healthy',
            message=f'OK: {total_files} files, {total_size_mb:.1f}MB',
            last_check=time.time(),
            metrics=metrics,
        )

    except Exception as e:
        return HealthCheck(
            module='tts',
            status='unknown',
            message=f'Check failed: {e}',
            last_check=time.time(),
        )


def check_memory_health() -> HealthCheck:
    """检查内存使用情况"""
    try:
        import psutil
        process = psutil.Process()
        mem_mb = process.memory_info().rss / 1024 / 1024
        system_mem = psutil.virtual_memory()

        metrics = {
            'process_mb': mem_mb,
            'system_percent': system_mem.percent,
        }

        if system_mem.percent > 90:
            return HealthCheck(
                module='memory',
                status='critical',
                message=f'System memory critical: {system_mem.percent}%',
                last_check=time.time(),
                metrics=metrics,
            )
        elif mem_mb > 2048:  # 进程 > 2GB
            return HealthCheck(
                module='memory',
                status='warning',
                message=f'Process memory high: {mem_mb:.0f}MB',
                last_check=time.time(),
                metrics=metrics,
            )

        return HealthCheck(
            module='memory',
            status='healthy',
            message=f'OK: {mem_mb:.0f}MB, system {system_mem.percent}%',
            last_check=time.time(),
            metrics=metrics,
        )

    except ImportError:
        return HealthCheck(
            module='memory',
            status='unknown',
            message='psutil not installed',
            last_check=time.time(),
        )


def check_disk_health() -> HealthCheck:
    """检查磁盘空间"""
    try:
        import shutil
        stat = shutil.disk_usage('.')
        free_gb = stat.free / (1024**3)
        total_gb = stat.total / (1024**3)
        used_percent = (stat.used / stat.total) * 100

        metrics = {
            'free_gb': free_gb,
            'total_gb': total_gb,
            'used_percent': used_percent,
        }

        if free_gb < 1:  # < 1GB
            return HealthCheck(
                module='disk',
                status='critical',
                message=f'Disk full: {free_gb:.1f}GB free',
                last_check=time.time(),
                metrics=metrics,
            )
        elif free_gb < 5:  # < 5GB
            return HealthCheck(
                module='disk',
                status='warning',
                message=f'Disk low: {free_gb:.1f}GB free',
                last_check=time.time(),
                metrics=metrics,
            )

        return HealthCheck(
            module='disk',
            status='healthy',
            message=f'OK: {free_gb:.1f}GB free / {total_gb:.1f}GB',
            last_check=time.time(),
            metrics=metrics,
        )

    except Exception as e:
        return HealthCheck(
            module='disk',
            status='unknown',
            message=f'Check failed: {e}',
            last_check=time.time(),
        )


# ═══════════════════════════════════════════════════════════
#  内置修复函数
# ═══════════════════════════════════════════════════════════

def heal_tts_cache() -> bool:
    """修复 TTS 缓存问题"""
    try:
        from modules.cache_manager import cleanup_tts_cache
        result = cleanup_tts_cache(max_files=400, max_size_mb=1536)
        logger.info(f"[SelfHealing] TTS cache cleaned: {result}")
        return result['total_removed'] > 0
    except Exception as e:
        logger.error(f"[SelfHealing] TTS heal failed: {e}")
        return False


def heal_memory() -> bool:
    """修复内存问题"""
    try:
        gc.collect()
        logger.info("[SelfHealing] GC executed")
        return True
    except Exception as e:
        logger.error(f"[SelfHealing] Memory heal failed: {e}")
        return False


# ═══════════════════════════════════════════════════════════
#  全局实例
# ═══════════════════════════════════════════════════════════

_self_healing_manager: Optional[SelfHealingManager] = None


def get_self_healing_manager() -> SelfHealingManager:
    """获取全局自愈管理器实例"""
    global _self_healing_manager
    if _self_healing_manager is None:
        _self_healing_manager = SelfHealingManager()

        # 注册内置检查
        _self_healing_manager.register_check('tts', check_tts_health)
        _self_healing_manager.register_check('memory', check_memory_health)
        _self_healing_manager.register_check('disk', check_disk_health)

        # 注册内置修复
        _self_healing_manager.register_healer('tts', heal_tts_cache)
        _self_healing_manager.register_healer('memory', heal_memory)

    return _self_healing_manager


async def start_self_healing():
    """启动系统自愈"""
    manager = get_self_healing_manager()
    await manager.start()


async def stop_self_healing():
    """停止系统自愈"""
    manager = get_self_healing_manager()
    await manager.stop()


def get_health_status() -> Dict:
    """获取健康状态"""
    manager = get_self_healing_manager()
    return manager.get_health_report()
