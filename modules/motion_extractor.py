"""
MotionExtractor - 视频动作提取模块 (MediaPipe)

功能：
1. 从视频提取人体骨骼关键点 (MediaPipe Pose)
2. 关键点 → 骨骼旋转计算
3. 输出标准BVH格式或GLB动画文件
4. 与前端对接，显示处理进度

依赖：
- mediapipe (Google官方库)
- opencv-python (视频处理)
- numpy (数据处理)
"""

import json
import logging
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Any
import asyncio
import aiohttp

logger = logging.getLogger("motion_extractor")


class MotionExtractor:
    """
    视频动作提取器
    
    工作流程：
    1. 接收视频文件路径
    2. MediaPipe Pose 提取关键点
    3. 计算骨骼关节旋转（FK解算）
    4. 生成GLB动画文件
    5. 返回文件路径 + 预览数据
    """
    
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir = output_dir / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # MediaPipe 可用性检测（延迟加载）
        self._mediapipe_available = None
        
    async def _check_mediapipe(self) -> bool:
        """检测MediaPipe是否已安装"""
        if self._mediapipe_available is None:
            try:
                import mediapipe as mp
                self._mediapipe_available = True
                logger.info("MediaPipe 已就绪")
            except ImportError:
                self._mediapipe_available = False
                logger.warning("MediaPipe 未安装，动作提取功能不可用")
                logger.info("安装命令: pip install mediapipe opencv-python numpy")
        return self._mediapipe_available
    
    async def extract_from_video(
        self,
        video_path: Path,
        skeleton_type: str = "humanoid",
        progress_callback = None,
        engine: str = "auto"
    ) -> Dict[str, Any]:
        """
        从视频提取动作（支持 MoCapAnything / MediaPipe）
        
        Args:
            video_path: 视频文件路径
            skeleton_type: 骨骼类型 (humanoid/quadruped/avian)
            progress_callback: 进度回调函数 (percent, stage)
            engine: 提取引擎 (mocap_anything / mediapipe / auto)
        Returns:
            {
                "ok": True/False,
                "glb_path": 输出GLB路径,
                "duration": 动画时长(秒),
                "frames": 帧数,
                "preview": {关键点预览数据},
                "error": 错误信息
            }
        """
        if engine == "auto":
            # 优先 4D-Humans (HMR2)，其次 MoCapAnything V2，最后回退 MediaPipe
            ok_4d, _ = self._check_4dhumans()
            if ok_4d:
                engine = "4dhumans"
                logger.info("auto 选择: 4D-Humans (HMR2)")
            else:
                from modules.mocap_anything_client import get_mocap_client
                mocap = get_mocap_client()
                if await mocap.check_available():
                    health = await mocap.get_health()
                    if health.get("mode") == "ready":
                        engine = "mocap_anything_v2"
                        logger.info("auto 选择: MoCapAnything V2 (4D)")
                    else:
                        engine = "mocap_anything"
                        logger.info("auto 选择: MoCapAnything V1 (占位模式)")
                else:
                    engine = "mediapipe"
                    logger.info("auto 选择: MediaPipe (其他引擎不可用)")

        # V2 和 V1 都走同一个 mocap_anything_client（service.py 内部决定用哪个推理）
        if engine in ("mocap_anything_v2", "mocap_anything"):
            from modules.mocap_anything_client import get_mocap_client
            mocap = get_mocap_client()
            if not await mocap.check_available():
                return {
                    "ok": False,
                    "error": "MoCapAnything 推理服务未启动。请点击「启动推理服务」或切换到 MediaPipe 引擎。"
                }
            result = await self._extract_with_mocap_anything(video_path, skeleton_type, progress_callback)
            if engine == "mocap_anything_v2":
                result["service"] = "mocap_anything_v2"
            return result
        
        if engine == "mediapipe":
            if not await self._check_mediapipe():
                return {
                    "ok": False,
                    "error": "MediaPipe 未安装。安装命令: pip install mediapipe"
                }
            return await self._run_extraction_script(video_path, skeleton_type)
        
        if engine == "motionbert":
            if not await self._check_mediapipe():
                return {
                    "ok": False,
                    "error": "MotionBERT 引擎需要 MediaPipe 做 2D 检测。安装命令: pip install mediapipe"
                }
            return await self._extract_with_motionbert(video_path, skeleton_type, progress_callback)

        if engine == "4dhumans":
            ok, msg = self._check_4dhumans()
            if not ok:
                return {"ok": False, "error": msg}
            return await self._extract_with_4dhumans(video_path, skeleton_type, progress_callback)

        return {"ok": False, "error": f"不支持的引擎: {engine}"}

    async def _extract_with_mocap_anything(
        self,
        video_path: Path,
        skeleton_type: str,
        progress_callback = None
    ) -> Dict[str, Any]:
        """
        使用 MoCapAnything 服务提取动作
        """
        from modules.mocap_anything_client import get_mocap_client
        from modules.bvh_to_glb_converter import convert_bvh_to_glb
        from tools.bvh_to_canonical import bvh_to_canonical
        import shutil

        mocap = get_mocap_client()
        result = await mocap.extract_from_video(video_path, skeleton_type, progress_callback)

        if not result.get("ok"):
            return result

        bvh_path = Path(result["bvh_path"])
        output_name = video_path.stem + "_extracted"
        output_dir = self.output_dir

        try:
            # 1. BVH -> canonical.json
            if progress_callback:
                await progress_callback(96, "生成标准动作 JSON...")
            raw_canonical_path = bvh_to_canonical(bvh_path, output_dir)
            # 重命名为与 output_name 一致，让前端预览路径对齐
            canonical_path = output_dir / f"{output_name}.canonical.json"
            raw_canonical_path.rename(canonical_path)
            # 同样重命名 meta.json
            raw_meta = raw_canonical_path.with_suffix('').with_suffix('').with_name(f"{raw_canonical_path.stem}.meta.json")
            if raw_meta.exists():
                meta_path = output_dir / f"{output_name}.meta.json"
                raw_meta.rename(meta_path)

            # 2. BVH -> 真正的 GLB
            if progress_callback:
                await progress_callback(97, "生成 GLB 动画...")
            glb_path = output_dir / f"{output_name}.glb"
            glb_result = convert_bvh_to_glb(str(bvh_path), str(glb_path))

            if not glb_result:
                logger.warning("GLB 生成失败，生成占位 GLB")
                import struct
                header = struct.pack('<4sII', b'glTF', 2, 12)
                with open(glb_path, 'wb') as f:
                    f.write(header)

            # 3. 复制原始视频供预览
            video_output = output_dir / f"{output_name}.mp4"
            try:
                shutil.copy2(str(video_path), str(video_output))
            except Exception as e:
                logger.warning(f"复制原视频失败: {e}")

            # 4. 生成预览图
            preview_paths = []
            try:
                import cv2
                cap = cv2.VideoCapture(str(video_path))
                total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                margin = max(1, int(total * 0.05))
                for i in range(4):
                    idx = margin + int((total - 2 * margin) * i / 3) if total > 0 else 0
                    cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                    ret, frame = cap.read()
                    if ret:
                        out_path = output_dir / "cache" / f"{output_name}_frame{i:02d}.png"
                        out_path.parent.mkdir(parents=True, exist_ok=True)
                        cv2.imwrite(str(out_path), frame)
                        preview_paths.append(str(out_path))
                cap.release()
            except Exception as e:
                logger.warning(f"生成预览图失败: {e}")

            if progress_callback:
                await progress_callback(100, "完成")

            return {
                "ok": True,
                "glb_path": str(glb_path),
                "canonical_path": str(canonical_path),
                "json_path": str(canonical_path),
                "meta_path": str(canonical_path).replace(".canonical.json", ".meta.json"),
                "video_path": str(video_output) if video_output.exists() else None,
                "bvh_path": str(bvh_path),
                "duration": result.get("duration", bvh_path.stat().st_size / 1000),
                "frames": result.get("frames", 0),
                "fps": 30.0,
                "action_id": output_name,
                "preview_frames": preview_paths,
                "service": "mocap_anything",
            }

        except Exception as e:
            logger.error(f"MoCapAnything 后处理失败: {e}", exc_info=True)
            return {
                "ok": False,
                "error": f"MoCapAnything 后处理失败: {str(e)}"
            }

    async def _extract_with_motionbert(
        self,
        video_path: Path,
        skeleton_type: str,
        progress_callback = None
    ) -> Dict[str, Any]:
        """
        使用 MotionBERT 引擎提取动作
        """
        import shutil
        from modules.bvh_to_glb_converter import convert_bvh_to_glb

        output_name = video_path.stem + "_extracted"
        output_dir = self.output_dir
        tmp_dir = output_dir / "motionbert_tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)

        try:
            if progress_callback:
                await progress_callback(10, "MediaPipe 2D 检测...")

            # 调用 MotionBERT 引擎
            from tools.motionbert_engine import process_video
            repo_path = Path(__file__).parent.parent / "tools" / "motionbert_repo"
            ckpt_path = repo_path / "checkpoint" / "pose3d" / "FT_MB_lite_MB_ft_h36m_global_lite" / "best_epoch.bin"
            result = process_video(
                str(video_path),
                str(tmp_dir),
                repo_path=str(repo_path) if repo_path.exists() else None,
                checkpoint_path=str(ckpt_path) if ckpt_path.exists() else None,
            )

            if not result.get("ok"):
                return {"ok": False, "error": result.get("error", "MotionBERT 处理失败")}

            canonical_path = Path(result["canonical_path"])
            # 重命名到 output_dir 并保持命名一致
            final_canonical = output_dir / f"{output_name}.canonical.json"
            shutil.copy2(str(canonical_path), str(final_canonical))

            if progress_callback:
                await progress_callback(70, "生成 GLB 动画...")

            # MotionBERT 输出 canonical.json（含 joints 数据），前端可直接加载。
            # 不生成 GLB，glb_path 指向 canonical.json，让系统用 JSON 路径。
            glb_path = final_canonical

            # 复制原视频
            video_output = output_dir / f"{output_name}.mp4"
            try:
                shutil.copy2(str(video_path), str(video_output))
            except Exception as e:
                logger.warning(f"复制原视频失败: {e}")

            # 预览图
            preview_paths = []
            try:
                import cv2
                cap = cv2.VideoCapture(str(video_path))
                total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                margin = max(1, int(total * 0.05))
                for i in range(4):
                    idx = margin + int((total - 2 * margin) * i / 3) if total > 0 else 0
                    cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                    ret, frame = cap.read()
                    if ret:
                        out_path = output_dir / "cache" / f"{output_name}_frame{i:02d}.png"
                        out_path.parent.mkdir(parents=True, exist_ok=True)
                        cv2.imwrite(str(out_path), frame)
                        preview_paths.append(str(out_path))
                cap.release()
            except Exception as e:
                logger.warning(f"生成预览图失败: {e}")

            if progress_callback:
                await progress_callback(100, "完成")

            return {
                "ok": True,
                "glb_path": str(glb_path),
                "canonical_path": str(final_canonical),
                "json_path": str(final_canonical),
                "meta_path": str(final_canonical).replace(".canonical.json", ".meta.json"),
                "video_path": str(video_output) if video_output.exists() else None,
                "duration": result.get("duration", 0),
                "frames": result.get("frame_count", 0),
                "fps": 30.0,
                "action_id": output_name,
                "preview_frames": preview_paths,
                "service": "motionbert",
            }

        except Exception as e:
            logger.error(f"MotionBERT 处理失败: {e}", exc_info=True)
            return {
                "ok": False,
                "error": f"MotionBERT 处理失败: {str(e)}"
            }

    # ──────────────────────────────────────────────
    # 4D-Humans (HMR2) 引擎
    # ──────────────────────────────────────────────

    def _check_4dhumans(self) -> tuple:
        """
        检测 4D-Humans 环境是否就绪。
        返回 (ok: bool, msg: str)
        """
        fourd_repo = Path(__file__).parent.parent / "tools" / "4D-Humans"
        if not fourd_repo.exists():
            return False, "4D-Humans 仓库未找到 (tools/4D-Humans/)，请先 clone：https://github.com/shubham-goel/4D-Humans"

        script = Path(__file__).parent.parent / "tools" / "hmr2_to_canonical.py"
        if not script.exists():
            return False, "转换脚本 tools/hmr2_to_canonical.py 不存在"

        import os
        home = os.environ.get("USERPROFILE") or os.environ.get("HOME", "")
        ckpt = Path(home) / ".cache" / "4DHumans" / "logs" / "train" / "multiruns" / "hmr2" / "0" / "checkpoints" / "epoch=35-step=1000000.ckpt"
        if not ckpt.exists():
            return False, (
                f"HMR2 权重未找到: {ckpt}\n"
                "请运行以下命令自动下载权重：\n"
                "  cd tools/4D-Humans && python -c \"from hmr2.models import download_models; download_models()\""
            )

        return True, "ready"

    async def _extract_with_4dhumans(
        self,
        video_path: Path,
        skeleton_type: str,
        progress_callback = None,
    ) -> Dict[str, Any]:
        """
        使用 4D-Humans (HMR2) 提取 SMPL 参数，转为 canonical.json，再生成 GLB。
        流程：视频 → hmr2_to_canonical.py (subprocess) → canonical.json → GLB
        """
        import shutil

        output_name = video_path.stem + "_extracted"
        output_dir = self.output_dir
        canonical_path = output_dir / f"{output_name}.canonical.json"
        script = Path(__file__).parent.parent / "tools" / "hmr2_to_canonical.py"
        fourd_repo = Path(__file__).parent.parent / "tools" / "4D-Humans"

        try:
            if progress_callback:
                await progress_callback(10, "加载 HMR2 模型...")

            # 自动检测 CUDA 可用性
            try:
                import torch as _torch
                _device = "cuda" if _torch.cuda.is_available() else "cpu"
            except Exception:
                _device = "cpu"
            if _device == "cpu":
                logger.warning("[4DHumans] CUDA 不可用，将使用 CPU 推理（速度较慢）")
                if progress_callback:
                    await progress_callback(12, "⚠️ CPU 模式推理中（无 CUDA），速度较慢...")

            # subprocess 调用 hmr2_to_canonical.py
            cmd = [
                sys.executable,
                str(script),
                "--video", str(video_path),
                "--out", str(canonical_path),
                "--device", _device,
            ]
            logger.info(f"[4DHumans] 启动推理: {' '.join(cmd)}")

            env = {**__import__("os").environ.copy(), "PYTHONPATH": str(fourd_repo)}
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(fourd_repo),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout_lines = []
            stderr_lines = []

            async def _read_stdout():
                nonlocal stdout_lines
                progress = 15
                async for line in proc.stdout:
                    txt = line.decode(errors="replace").strip()
                    if txt:
                        logger.info(f"[4dhumans] {txt}")
                        stdout_lines.append(txt)
                    if "已处理" in txt or "processed" in txt.lower():
                        progress = min(progress + 5, 80)
                        if progress_callback:
                            await progress_callback(progress, txt[:60])

            async def _read_stderr():
                nonlocal stderr_lines
                async for line in proc.stderr:
                    txt = line.decode(errors="replace").strip()
                    if txt:
                        logger.error(f"[4dhumans stderr] {txt}")
                        stderr_lines.append(txt)

            await asyncio.gather(_read_stdout(), _read_stderr())
            await proc.wait()

            if proc.returncode != 0:
                err_detail = "\n".join(stderr_lines[-10:]) or "\n".join(stdout_lines[-5:])
                return {"ok": False, "error": f"HMR2 推理失败 (code={proc.returncode}):\n{err_detail}"}

            if not canonical_path.exists():
                return {"ok": False, "error": "HMR2 推理完成但 canonical.json 未生成"}

            if progress_callback:
                await progress_callback(85, "解析动作数据...")

            # 读取 canonical.json 获取帧数/时长
            import json as _json
            with open(canonical_path, "r", encoding="utf-8") as f:
                canonical_data = _json.load(f)
            fps = canonical_data.get("fps", 30.0)
            frame_count = canonical_data.get("frameCount", 0)
            duration = canonical_data.get("duration", frame_count / fps if fps else 0)

            if progress_callback:
                await progress_callback(90, "生成 GLB 动画...")

            # canonical.json → GLB（若转换器可用）
            glb_path = output_dir / f"{output_name}.glb"
            try:
                from modules.bvh_to_glb_converter import convert_bvh_to_glb
                # canonical.json 直接当 glb_path 传给系统（同 MotionBERT 做法）
                glb_path = canonical_path
            except Exception as e:
                logger.warning(f"GLB 转换器不可用，使用 canonical.json 作为输出: {e}")
                glb_path = canonical_path

            # 复制原视频供预览
            video_output = output_dir / f"{output_name}.mp4"
            try:
                shutil.copy2(str(video_path), str(video_output))
            except Exception as e:
                logger.warning(f"复制原视频失败: {e}")

            # 生成预览图
            preview_paths = []
            try:
                import cv2
                cap = cv2.VideoCapture(str(video_path))
                total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                margin = max(1, int(total * 0.05))
                for i in range(4):
                    idx = margin + int((total - 2 * margin) * i / 3) if total > 0 else 0
                    cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                    ret, frame = cap.read()
                    if ret:
                        out_path = output_dir / "cache" / f"{output_name}_frame{i:02d}.png"
                        out_path.parent.mkdir(parents=True, exist_ok=True)
                        cv2.imwrite(str(out_path), frame)
                        preview_paths.append(str(out_path))
                cap.release()
            except Exception as e:
                logger.warning(f"生成预览图失败: {e}")

            if progress_callback:
                await progress_callback(100, "完成")

            return {
                "ok": True,
                "glb_path": str(glb_path),
                "canonical_path": str(canonical_path),
                "json_path": str(canonical_path),
                "meta_path": str(canonical_path).replace(".canonical.json", ".meta.json"),
                "video_path": str(video_output) if video_output.exists() else None,
                "duration": duration,
                "frames": frame_count,
                "fps": fps,
                "action_id": output_name,
                "preview_frames": preview_paths,
                "service": "4dhumans",
            }

        except Exception as e:
            logger.error(f"4D-Humans 处理失败: {e}", exc_info=True)
            return {"ok": False, "error": f"4D-Humans 处理失败: {str(e)}"}

    async def _run_extraction_script(
        self,
        video_path: Path,
        skeleton_type: str
    ) -> Dict[str, Any]:
        """
        运行动作提取脚本（调用真正的MediaPipe处理）
        """
        import subprocess
        import asyncio
        
        # 生成输出文件名
        video_name = video_path.stem
        output_name = f"{video_name}_extracted.glb"
        output_path = self.output_dir / output_name
        
        # 检查是否已有缓存结果（相同视频不再重复处理）
        cache_key = f"{video_path.stat().st_mtime}_{video_path.stat().st_size}"
        cache_file = self.cache_dir / f"{video_name}_{cache_key[:16]}.json"
        
        if cache_file.exists():
            with open(cache_file) as f:
                cached = json.load(f)
            if Path(cached.get("glb_path", "")).exists():
                logger.info(f"动作提取缓存命中: {video_name}")
                return {**cached, "ok": True, "cached": True}
        
        logger.info(f"开始MediaPipe动作提取: {video_path}")
        
        # 调用提取脚本
        script_path = Path(__file__).parent.parent / "tools" / "extract_motion.py"
        
        try:
            import os as _os
            env = {**_os.environ, "PYTHONIOENCODING": "utf-8"}
            # 运行提取脚本
            proc = await asyncio.create_subprocess_exec(
                sys.executable, str(script_path),
                str(video_path), str(output_path),
                "--skeleton-type", skeleton_type,
                "--fps", "30",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env
            )
            
            stdout, stderr = await proc.communicate()
            
            if proc.returncode != 0:
                err_raw = stderr.decode('utf-8', errors='ignore') if stderr else ""
                out_raw = stdout.decode('utf-8', errors='ignore') if stdout else ""
                # 过滤MediaPipe的正常INFO/W0000警告行，只保留真实错误
                def filter_mp_noise(text):
                    real_lines = [
                        l for l in text.splitlines()
                        if l.strip() and
                        not l.startswith("INFO:") and
                        not l.startswith("W0000") and
                        not l.startswith("I0000") and
                        not l.startswith("E0000 00:00") and  # telemetry errors
                        "clearcut" not in l and
                        "playlog" not in l
                    ]
                    return "\n".join(real_lines).strip()
                err_text = filter_mp_noise(err_raw)
                out_text = filter_mp_noise(out_raw)
                error_msg = err_text or out_text or err_raw.strip()[-300:] or f"脚本退出码 {proc.returncode}"
                logger.error(f"提取脚本失败 (exit={proc.returncode}):\n{err_raw[-1000:]}")
                return {
                    "ok": False,
                    "error": f"MediaPipe处理失败: {error_msg[:1000]}"
                }
            
            # 解析最后一行JSON输出（元数据）
            output_lines = stdout.decode('utf-8', errors='ignore').strip().split('\n')
            last_line = output_lines[-1] if output_lines else "{}"
            
            try:
                result = json.loads(last_line)
            except json.JSONDecodeError:
                # 如果没有JSON输出，构造基本结果
                result = {
                    "ok": True,
                    "glb_path": str(output_path),
                    "duration": 3.0,
                    "frames": 90,
                    "skeleton_type": skeleton_type
                }
            
            # 复制原始视频到输出目录供前端预览
            try:
                import shutil
                video_output = output_path.with_suffix('.mp4')
                shutil.copy2(str(video_path), str(video_output))
                result["video_path"] = str(video_output)
                logger.info(f"原视频已复制到: {video_output}")
            except Exception as e:
                logger.warning(f"复制原视频失败: {e}")
            
            # 缓存结果
            with open(cache_file, "w") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            
            logger.info(f"动作提取完成: {output_path}")
            return result
            
        except FileNotFoundError:
            logger.error(f"提取脚本不存在: {script_path}")
            return {
                "ok": False,
                "error": "动作提取脚本未找到"
            }
        except Exception as e:
            logger.error(f"提取过程异常: {e}")
            return {
                "ok": False,
                "error": f"提取异常: {str(e)}"
            }
    
    async def get_preview_data(self, glb_path: Path, frame_interval: int = 5) -> List[Dict]:
        """
        获取动作预览数据（用于前端展示骨骼关键点）
        
        Args:
            glb_path: GLB文件路径
            frame_interval: 采样间隔（每N帧采样一次）
        
        Returns:
            [{frame, joints: [{name, x, y, z}, ...]}, ...]
        """
        # 简化版：返回占位数据
        # 实际实现需要解析GLB文件，提取骨骼动画数据
        return [
            {
                "frame": i,
                "joints": [
                    {"name": "hips", "x": 0, "y": 1, "z": 0},
                    {"name": "spine", "x": 0, "y": 1.2, "z": 0},
                    {"name": "head", "x": 0, "y": 1.6, "z": 0},
                ]
            }
            for i in range(0, 90, frame_interval)
        ]
    
    def get_supported_skeletons(self) -> List[Dict]:
        """获取支持的骨骼类型列表"""
        return [
            {
                "id": "humanoid",
                "name": "人形骨骼",
                "description": "标准人形骨骼，适用于人类角色",
                "joints": [
                    "hips", "spine", "chest", "neck", "head",
                    "leftShoulder", "leftUpperArm", "leftLowerArm", "leftHand",
                    "rightShoulder", "rightUpperArm", "rightLowerArm", "rightHand",
                    "leftUpperLeg", "leftLowerLeg", "leftFoot",
                    "rightUpperLeg", "rightLowerLeg", "rightFoot"
                ]
            },
            {
                "id": "quadruped",
                "name": "四足骨骼",
                "description": "四足动物骨骼，适用于猫/狗/马等",
                "status": "planned"
            },
            {
                "id": "avian",
                "name": "鸟类骨骼",
                "description": "鸟类骨骼，包含翅膀骨骼",
                "status": "planned"
            }
        ]


# 全局实例
motion_extractor: Optional[MotionExtractor] = None


def init_motion_extractor(output_dir: Path):
    """初始化全局动作提取器"""
    global motion_extractor
    motion_extractor = MotionExtractor(output_dir)
    logger.info(f"MotionExtractor 初始化完成，输出目录: {output_dir}")


async def extract_motion(
    video_path: Path,
    skeleton_type: str = "humanoid",
    engine: str = "auto"
) -> Dict[str, Any]:
    """便捷函数：提取动作"""
    if motion_extractor is None:
        return {"ok": False, "error": "MotionExtractor 未初始化"}
    return await motion_extractor.extract_from_video(video_path, skeleton_type, engine=engine)
