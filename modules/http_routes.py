"""
HTTP 路由层：build_http_app 及全部 handler
"""
import json
import logging
import os
import sys
import asyncio
import time
import datetime
import hashlib
import subprocess
import uuid
import zipfile
import re
from pathlib import Path
from typing import Any, Dict, Optional, List

import aiohttp
from aiohttp import web

from modules.core import (
    EventPriority, EventQueueManager, PopupManager, WSHub, PRIORITY_MAP
)
from modules.config_manager import ConfigManager
from modules.scene_director import SceneDirector
from modules.ai_service import AIService
from modules.tts_service import TTSService, MiniMaxTTSService, EdgeTTSService
from modules.dialogue_queue import DialogueQueueManager
from modules.session_recorder import SessionRecorder
from modules.cache_cleaner import CacheCleaner
from modules.platform_product_adapter import create_platform_product_manager, MockPlatformAdapter
from modules.douyin_minigame import DouyinMiniGameAdapter, init_minigame_adapter, get_minigame_adapter
from modules.voice_chat_manager import VoiceChatManager, init_voice_manager, get_voice_manager, VoiceMode
from modules.voice_queue_manager import VoiceQueueManager, init_voice_queue_manager, get_voice_queue_manager, VoiceFeature

logger = logging.getLogger("server")
ROOT_DIR = Path(__file__).parent.parent
CONFIG_DIR = ROOT_DIR / "config"
FRONTEND_DIR = ROOT_DIR / "frontend"
ASSETS_DIR   = ROOT_DIR / "assets"


def _safe_extract_zip(zip_file: zipfile.ZipFile, target_dir: Path):
    """
    安全解压zip文件，防止Zip Slip路径遍历攻击
    
    检查每个文件路径，确保不会解压到目标目录之外
    """
    target_dir = target_dir.resolve()
    
    for member in zip_file.namelist():
        # 解析成员路径
        member_path = Path(member)
        
        # 检查路径是否包含..或绝对路径
        if member.startswith('/') or '..' in member_path.parts:
            logger.warning(f"[ZipSecurity] 跳过危险路径: {member}")
            continue
        
        # 计算最终路径
        final_path = (target_dir / member).resolve()
        
        # 确保最终路径在目标目录内
        try:
            final_path.relative_to(target_dir)
        except ValueError:
            logger.warning(f"[ZipSecurity] 路径越界，跳过: {member}")
            continue
        
        # 安全路径，执行解压
        zip_file.extract(member, target_dir)


def build_http_app(
    cfg: ConfigManager, 
    director: SceneDirector, 
    event_queue: EventQueueManager, 
    popup_mgr: PopupManager,
    ai: AIService,
    tts: TTSService,
    dialogue_queue: DialogueQueueManager,
    hub: "WSHub" = None,
    session_recorder: Optional["SessionRecorder"] = None,
    danmaku_crawler = None
) -> web.Application:
    app = web.Application()
    
    # 追踪本进程启动的 MoCapAnything 推理服务
    mocap_service_process: Dict[str, Any] = {"proc": None, "pid": None}
    
    # ═══════════════════════════════════════════════════════════
    #  安全中间件
    # ═══════════════════════════════════════════════════════════
    
    @web.middleware
    async def security_middleware(request, handler):
        """安全响应头中间件"""
        response = await handler(request)
        
        # 安全响应头
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        
        # CORS 头（允许本地开发环境）
        origin = request.headers.get('Origin', '')
        allowed_origins = ['http://localhost:8080', 'http://127.0.0.1:8080']
        if origin in allowed_origins:
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        
        return response
    
    @web.middleware
    async def request_validation_middleware(request, handler):
        """请求验证中间件"""
        # 验证Content-Type
        if request.method in ('POST', 'PUT', 'PATCH'):
            content_type = request.headers.get('Content-Type', '')
            
            # 检查JSON请求大小（防止过大请求）
            if 'application/json' in content_type:
                try:
                    content_length = int(request.headers.get('Content-Length', 0))
                    if content_length > 10 * 1024 * 1024:  # 10MB限制
                        return web.json_response(
                            {"ok": False, "error": "请求体过大"}, 
                            status=413
                        )
                except ValueError:
                    pass
        
        return await handler(request)
    
    # 注册安全中间件
    app.middlewares.append(security_middleware)
    app.middlewares.append(request_validation_middleware)
    
    # TTS缓存目录
    CACHE_DIR     = ROOT_DIR / "cache" / "tts"
    CACHE_DIR_EDGE = ROOT_DIR / "cache" / "tts_edge"
    CACHE_DIR_EDGE.mkdir(parents=True, exist_ok=True)

    # 初始化平台商品管理器 - 直接加载 platforms.json
    platform_config = {}
    try:
        platform_config_path = ROOT_DIR / "config" / "platforms.json"
        if platform_config_path.exists():
            with open(platform_config_path, 'r', encoding='utf-8') as f:
                platform_config = json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load platforms.json: {e}")
    platform_product_manager = create_platform_product_manager(platform_config)
    
    # 初始化抖音直播玩法适配器
    douyin_minigame_config = platform_config.get("douyin_minigame", {})
    minigame_adapter = init_minigame_adapter(douyin_minigame_config)
    
    # 集成STT服务到MiniGame语音处理（用于观众语音互动识别）
    try:
        from .stt_service import get_stt_service
        minigame_adapter.set_stt_service(get_stt_service())
    except Exception as e:
        logger.warning(f"MiniGame STT集成失败（语音互动将返回空结果）: {e}")
    
    # 初始化语音排队管理器（支持排队系统）
    voice_queue_manager = init_voice_queue_manager()
    
    # 注册语音排队事件处理器
    async def on_voice_queue_event(event_type, data):
        """处理语音排队事件"""
        if event_type == "user_joined_queue":
            logger.info(f"[VoiceQueue] {data['username']} 加入排队 #{data['position']}")
            # 广播给直播间控制台
            await hub.broadcast({
                "action": "voice_queue_update",
                "type": "user_joined",
                "data": data
            })
            
        elif event_type == "request_accepted":
            logger.info(f"[VoiceQueue] {data['username']} 的请求被接受")
            # NPC播报
            await event_queue.submit(
                "voice_call_start",
                {
                    "username": data['username'],
                    "feature": data['feature'],
                    "max_duration": data['max_duration']
                },
                priority=EventPriority.HIGH
            )
            
        elif event_type == "voice_transcribed":
            logger.info(f"[VoiceQueue] {data['username']}: {data['text']}")
            # 触发NPC回复
            await event_queue.submit(
                "voice_chat",
                {
                    "username": data['username'],
                    "message": data['text'],
                    "session_id": data.get('session_id')
                },
                priority=EventPriority.USER_CHAT
            )
            
        elif event_type == "session_ended":
            logger.info(f"[VoiceQueue] 会话结束: {data['username']}, 时长{data['duration']}s")
    
    voice_queue_manager.on_event(on_voice_queue_event)

    async def index(request):
        # index.html 已不存在，直接转到控制台
        raise web.HTTPFound("/control")
    
    async def control_panel(request):
        """运营控制面板（v3 骨骼动画版）"""
        return web.FileResponse(FRONTEND_DIR / "control.html")

    async def llm_config_page(request):
        """LLM配置页面"""
        return web.FileResponse(FRONTEND_DIR / "llm-config.html")

    async def scene_editor(request):
        """场景编辑器（v2 骨骼动画工作台）"""
        return web.FileResponse(FRONTEND_DIR / "studio-editor-v2.html")

    async def products_page(request):
        """商品管理系统"""
        return web.FileResponse(FRONTEND_DIR / "products.html")

    async def live_scene(request):
        """3D直播间场景"""
        return web.FileResponse(FRONTEND_DIR / "live-scene.html")

    async def settings_page(request):
        """配置中心"""
        return web.FileResponse(FRONTEND_DIR / "settings.html")

    async def get_config(request):
        """前端启动时拉取一份配置快照"""
        return web.json_response({
            "main": cfg.main,
            "skus": cfg.skus,
            "characters": cfg.characters,
        })

    async def reload_config(request):
        cfg.load_all()
        await director.init_scene()
        return web.json_response({"ok": True})

    async def test_trigger(request):
        """
        测试触发器：
        POST /api/test/trigger
        Body: {"intent": "user_enter|product_query|order_placed|style_switch|gift_big|gift_small|urgent_question|general_chat|like_received", ...}
        """
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)

        intent = data.get("intent")
        logger.info(f"Test trigger: {data}")
        
        # 提取数据（移除intent字段）
        event_data = {k: v for k, v in data.items() if k != "intent"}
        
        # 提交到事件队列
        accepted = await event_queue.submit(intent, event_data)
        
        if not accepted:
            return web.json_response({
                "ok": False, 
                "error": "event rejected (queue full or rate limited)"
            }, status=503)

        return web.json_response({"ok": True, "queued": True})
    
    async def get_queue_status(request):
        """获取事件队列状态"""
        status = await event_queue.get_queue_status()
        return web.json_response(status)
    
    async def get_popup_status(request):
        """获取弹窗状态"""
        popups = await popup_mgr.get_active_popups()
        return web.json_response({
            "active_popups": popups,
            "max_popups": popup_mgr.MAX_POPUPS
        })
    
    async def get_system_status(request):
        """获取系统整体状态"""
        queue_status = await event_queue.get_queue_status()
        popup_status = await popup_mgr.get_active_popups()
        return web.json_response({
            "state": director.state.name,
            "queue": queue_status,
            "popups": popup_status,
            "current_style": cfg.get_current_style(),
        })

    async def ai_chat(request):
        """
        AI聊天API（用于前端直接调用或测试）
        POST /api/ai/chat
        Body: {"message": "用户消息", "username": "客官", "sku_id": "可选"}
        """
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)
        
        message = data.get("message", "")
        username = data.get("username", "客官")
        sku_id = data.get("sku_id")
        
        if not message:
            return web.json_response({"ok": False, "error": "message required"}, status=400)
        
        # 获取SKU信息（如果提供）
        sku = cfg.get_sku(sku_id) if sku_id else None
        char = cfg.get_character()
        style_id = cfg.get_current_style()
        
        # 调用AI生成回复
        response = await ai.chat(
            user_message=message,
            username=username,
            character=char,
            style_id=style_id,
            sku=sku
        )
        text_out, emotion_out = response if isinstance(response, tuple) else (response, "happy")
        
        return web.json_response({
            "ok": True,
            "response": text_out,
            "style": style_id,
            "sku_used": sku_id if sku else None
        })
    
    async def tts_synthesize(request):
        """
        TTS合成API
        POST /api/tts/synthesize
        Body: {"text": "要合成的文本"}
        Returns: {"audio_url": "/cache/tts/xxx.mp3"}
        """
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)
        
        text = data.get("text", "")
        if not text:
            return web.json_response({"ok": False, "error": "text required"}, status=400)
        
        # 调用TTS合成
        audio_url = await tts.synthesize(text, cfg.get_current_style())
        
        if audio_url:
            return web.json_response({
                "ok": True,
                "audio_url": audio_url,
                "browser_fallback": False
            })
        else:
            # TTS失败，返回浏览器降级方案配置
            return web.json_response({
                "ok": True,
                "audio_url": None,
                "browser_fallback": True,
                "tts_config": BrowserTTSFallback.get_config(cfg.get_current_style())
            })

    async def switch_style(request):
        """
        切换主播风格
        POST /api/style/switch
        Body: {"style": "classical|cute|dominant"}
        """
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)
        
        new_style = data.get("style", "")
        valid_styles = ["classical", "cute", "dominant"]
        
        if new_style not in valid_styles:
            return web.json_response({
                "ok": False, 
                "error": f"invalid style, must be one of {valid_styles}"
            }, status=400)
        
        # 更新配置
        old_style = cfg.get_current_style()
        cfg.main["current_style"] = new_style
        
        # 触发风格切换场景
        await director.on_style_switch(old_style, new_style)
        
        return web.json_response({
            "ok": True,
            "old_style": old_style,
            "new_style": new_style,
            "character": cfg.get_character().get("name", "未知")
        })

    async def receive_webhook(request):
        """
        Webhook接收端点（用于抖音开放平台或第三方订单推送）
        POST /webhook/douyin
        """
        try:
            data = await request.json()
            logger.info(f"Webhook received: {data.get('event_type', 'unknown')}")
            
            event_type = data.get("event_type", "")
            
            # 处理订单事件
            if event_type == "order.placed":
                order_data = data.get("order", {})
                username = order_data.get("buyer_nickname", "神秘客官")
                sku_id = order_data.get("sku_id", "tea_001")
                
                # 提交到事件队列
                await event_queue.submit("order_placed", {
                    "username": username,
                    "sku_id": sku_id,
                    "order_id": order_data.get("order_id", "")
                }, priority=1)
                
                return web.json_response({"ok": True, "message": "Order event queued"})
            
            # 其他事件...
            return web.json_response({"ok": True, "message": "Event received"})
            
        except Exception as e:
            logger.error(f"Webhook error: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    # 场景管理API
    async def get_scenes(request):
        """获取所有场景配置（含分组）"""
        return web.json_response({
            "scenes": cfg.get_all_scenes(),
            "groups": cfg.get_groups(),
            "current_scene": cfg.scenes.get("meta", {}).get("current_scene", "default_tea_shop")
        })
    
    async def save_scenes(request):
        """保存场景配置"""
        try:
            data = await request.json()
            cfg.scenes = data
            success = cfg.save_scenes()
            if success:
                return web.json_response({"ok": True})
            else:
                return web.json_response({"ok": False, "error": "Save failed"}, status=500)
        except Exception as e:
            logger.error(f"Save scenes error: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)
    
    async def get_scene_templates(request):
        """扫描 assets/scenes/ 目录，返回所有3D场景模型清单。
        只包含有 manifest.json + scene.gltf 的真正3D场景，不包含HDRi全景背景图。
        """
        try:
            scenes_root = Path(__file__).parent.parent / "assets" / "scenes"
            templates = []
            if scenes_root.exists():
                for sub in sorted(scenes_root.iterdir()):
                    if not sub.is_dir():
                        continue
                    
                    # 必须包含 manifest.json
                    manifest_path = sub / "manifest.json"
                    if not manifest_path.exists():
                        continue
                    
                    # 必须包含 scene.gltf 才是真正的3D场景（不是HDRi）
                    gltf_path = sub / "scene.gltf"
                    if not gltf_path.exists():
                        continue
                    
                    try:
                        with open(manifest_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        # 强制 id 与目录名一致
                        data["id"] = sub.name
                        # 缩略图相对路径（如果存在）
                        thumb_path = sub / "thumb.png"
                        if thumb_path.exists():
                            data.setdefault("thumbnail", f"/assets/scenes/{sub.name}/thumb.png")
                        templates.append(data)
                    except Exception as e:
                        logger.warning(f"Skip invalid manifest {manifest_path}: {e}")
            return web.json_response({"ok": True, "templates": templates})
        except Exception as e:
            logger.error(f"get_scene_templates error: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)
    
    async def upload_scene(request):
        """
        上传自定义场景文件（.glb / .gltf / .zip）
        POST /api/scenes/upload  multipart/form-data
        字段：file=<场景文件>  name=<场景显示名>
        自动创建 assets/scenes/<dir_name>/manifest.json
        并在 scenes.json 中注册新场景条目。
        """
        import re, zipfile, time
        scenes_root = ROOT_DIR / "assets" / "scenes"
        # 文件大小限制：50MB
        MAX_FILE_SIZE = 50 * 1024 * 1024
        
        try:
            reader = await request.multipart()
            file_field = None
            display_name = ""
            content = b""
            async for field in reader:
                if field.name == "file":
                    file_field = field
                    orig_filename = field.filename or "scene.glb"
                    # 读取文件内容（带大小限制）
                    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
                    while True:
                        chunk = await field.read_chunk(65536)
                        if not chunk:
                            break
                        content += chunk
                        # 检查大小限制
                        if len(content) > MAX_FILE_SIZE:
                            return web.json_response(
                                {"ok": False, "error": f"文件过大，最大支持{MAX_FILE_SIZE//1024//1024}MB"}, 
                                status=413
                            )
                        # 检查大小限制
                        if len(content) > MAX_FILE_SIZE:
                            return web.json_response(
                                {"ok": False, "error": f"文件过大，最大支持{MAX_FILE_SIZE//1024//1024}MB"}, 
                                status=413
                            )
                elif field.name == "name":
                    display_name = (await field.read()).decode("utf-8", errors="ignore").strip()

            if not content:
                return web.json_response({"ok": False, "error": "No file received"}, status=400)

            ext = Path(orig_filename).suffix.lower()
            safe_base = re.sub(r"[^\w\-]", "_", Path(orig_filename).stem)[:32]
            dir_name = f"{safe_base}_{int(time.time()) % 100000}"
            target_dir = scenes_root / dir_name
            target_dir.mkdir(parents=True, exist_ok=True)

            if ext == ".zip":
                # 安全解压到目标目录（防止Zip Slip攻击）
                zip_path = target_dir / "upload.zip"
                zip_path.write_bytes(content)
                with zipfile.ZipFile(zip_path, "r") as zf:
                    _safe_extract_zip(zf, target_dir)
                zip_path.unlink(missing_ok=True)
                # 找主 gltf/glb 文件
                gltf_file = next((f for f in target_dir.rglob("*.gltf")), None) or \
                            next((f for f in target_dir.rglob("*.glb")), None)
                if gltf_file:
                    rel = gltf_file.relative_to(scenes_root)
                    gltf_url = f"/assets/scenes/{rel.as_posix()}"
                else:
                    gltf_url = f"/assets/scenes/{dir_name}/scene.gltf"
            else:
                # 直接保存 GLB/GLTF
                scene_file = target_dir / f"scene{ext}"
                scene_file.write_bytes(content)
                gltf_url = f"/assets/scenes/{dir_name}/scene{ext}"

            # 写 manifest.json
            if not display_name:
                display_name = safe_base.replace("_", " ")
            manifest = {
                "id": dir_name,
                "name": display_name,
                "description": f"自定义上传场景: {orig_filename}",
                "icon": "🏟️",
                "type": "gltf",
                "gltf_url": gltf_url,
            }
            (target_dir / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            # 在 scenes.json 注册新场景
            scene_id = f"scene_{dir_name}"
            all_scenes = cfg.get_all_scenes()
            all_scenes[scene_id] = {
                "name": display_name,
                "description": f"上传自 {orig_filename}",
                "environment": dir_name,
                "host_position": {"x": 50, "y": 75, "scale": 1},
                "host_position_3d": {"x": 0.0, "y": 0.0, "z": 0.0},
                "slots": [],
                "objects": [],
                "created_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
            }
            cfg.scenes["scenes"] = all_scenes
            cfg.save_scenes()

            logger.info(f"[SceneUpload] Saved {len(content)} bytes → {target_dir}, scene_id={scene_id}")
            return web.json_response({
                "ok": True,
                "scene_id": scene_id,
                "dir_name": dir_name,
                "gltf_url": gltf_url,
                "display_name": display_name,
            })
        except Exception as e:
            logger.error(f"upload_scene error: {e}", exc_info=True)
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def upload_prop(request):
        """
        上传自定义道具文件（.glb / .gltf / .zip）
        POST /api/props/upload  multipart/form-data
        字段：file=<道具文件>  name=<道具显示名>  group=<分组ID>
        自动保存到 assets/props/<filename>
        """
        import re, zipfile, time
        props_root = ROOT_DIR / "assets" / "props"
        props_root.mkdir(parents=True, exist_ok=True)
        # 文件大小限制：50MB
        MAX_FILE_SIZE = 50 * 1024 * 1024
        
        try:
            reader = await request.multipart()
            file_field = None
            display_name = ""
            group_id = "default"
            content = b""
            
            async for field in reader:
                if field.name == "file":
                    file_field = field
                    orig_filename = field.filename or "prop.glb"
                    # 读取文件内容（带大小限制）
                    while True:
                        chunk = await field.read_chunk(65536)
                        if not chunk:
                            break
                        content += chunk
                        # 检查大小限制
                        if len(content) > MAX_FILE_SIZE:
                            return web.json_response(
                                {"ok": False, "error": f"文件过大，最大支持{MAX_FILE_SIZE//1024//1024}MB"}, 
                                status=413
                            )
                elif field.name == "name":
                    display_name = (await field.read()).decode("utf-8", errors="ignore").strip()
                elif field.name == "group":
                    group_id = (await field.read()).decode("utf-8", errors="ignore").strip() or "default"

            if not content:
                return web.json_response({"ok": False, "error": "No file received"}, status=400)

            ext = Path(orig_filename).suffix.lower()
            safe_base = re.sub(r"[^\w\-]", "_", Path(orig_filename).stem)[:32]
            file_name = f"{safe_base}_{int(time.time()) % 100000}{ext}"
            target_path = props_root / file_name

            # 处理 zip 文件
            if ext == ".zip":
                # 创建临时目录
                temp_dir = props_root / f"temp_{int(time.time())}"
                temp_dir.mkdir(parents=True, exist_ok=True)
                
                zip_path = temp_dir / "upload.zip"
                zip_path.write_bytes(content)
                with zipfile.ZipFile(zip_path, "r") as zf:
                    _safe_extract_zip(zf, temp_dir)
                zip_path.unlink(missing_ok=True)
                
                # 找主 gltf/glb 文件
                gltf_file = next((f for f in temp_dir.rglob("*.gltf")), None) or \
                            next((f for f in temp_dir.rglob("*.glb")), None)
                if gltf_file:
                    # 移动主文件到 props 根目录
                    target_path = props_root / f"{safe_base}_{int(time.time()) % 100000}{gltf_file.suffix}"
                    gltf_file.rename(target_path)
                    # 复制依赖文件（贴图等）
                    for dep_file in temp_dir.rglob("*"):
                        if dep_file.is_file() and dep_file != gltf_file:
                            dep_target = props_root / dep_file.name
                            try:
                                dep_file.rename(dep_target)
                            except:
                                pass  # 文件可能已存在
                else:
                    # 没有找到 gltf，保留 zip
                    target_path = props_root / f"{safe_base}_{int(time.time()) % 100000}.zip"
                    target_path.write_bytes(content)
                
                # 清理临时目录
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)
            else:
                # 直接保存 GLB/GLTF
                target_path.write_bytes(content)

            if not display_name:
                display_name = safe_base.replace("_", " ")

            # 生成道具ID和URL
            prop_id = f"prop_{safe_base}_{int(time.time()) % 100000}"
            prop_url = f"/assets/props/{target_path.name}"
            
            logger.info(f"[PropUpload] Saved {len(content)} bytes → {target_path}, prop_id={prop_id}")
            return web.json_response({
                "ok": True,
                "prop_id": prop_id,
                "name": display_name,
                "file_url": prop_url,
                "file_name": target_path.name,
                "group": group_id,
            })
        except Exception as e:
            logger.error(f"upload_prop error: {e}", exc_info=True)
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def list_props(request):
        """获取所有已上传的道具文件列表"""
        try:
            props_root = ROOT_DIR / "assets" / "props"
            props = []
            if props_root.exists():
                for f in sorted(props_root.iterdir()):
                    if f.is_file() and f.suffix.lower() in (".glb", ".gltf", ".zip"):
                        props.append({
                            "id": f"prop_{f.stem}",
                            "name": f.stem.replace("_", " ").title(),
                            "file_name": f.name,
                            "file_url": f"/assets/props/{f.name}",
                            "size": f.stat().st_size,
                        })
            return web.json_response({"ok": True, "props": props})
        except Exception as e:
            logger.error(f"list_props error: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def get_groups(request):
        """获取所有分组"""
        return web.json_response({
            "ok": True,
            "groups": cfg.get_groups(),
            "scenes": cfg.get_all_scenes()
        })
    
    async def save_groups(request):
        """保存分组配置（创建/重命名/删除/更新折叠状态）"""
        try:
            data = await request.json()
            groups = data.get("groups", [])
            cfg.save_groups(groups)
            cfg.save_scenes()
            return web.json_response({"ok": True})
        except Exception as e:
            logger.error(f"Save groups error: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)
    
    async def move_scene_group(request):
        """移动场景到指定分组"""
        try:
            data = await request.json()
            scene_id = data.get("scene_id")
            group_id = data.get("group_id")
            if not scene_id or not group_id:
                return web.json_response({"ok": False, "error": "Missing scene_id or group_id"}, status=400)
            cfg.move_scene_to_group(scene_id, group_id)
            cfg.save_scenes()
            return web.json_response({"ok": True})
        except Exception as e:
            logger.error(f"Move scene error: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)
    
    async def reorder_scenes(request):
        """重新排序场景（包括跨分组移动）"""
        try:
            data = await request.json()
            orders = data.get("orders", {})  # {scene_id: {group_id, order}}
            for scene_id, info in orders.items():
                cfg.move_scene_to_group(scene_id, info.get("group_id", "default"))
                cfg.set_scene_order(scene_id, info.get("order", 0))
            cfg.save_scenes()
            return web.json_response({"ok": True})
        except Exception as e:
            logger.error(f"Reorder scenes error: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)
    
    async def apply_scene(request):
        """应用场景到直播间"""
        try:
            data = await request.json()
            scene_id = data.get("scene_id")
            
            if not scene_id:
                return web.json_response({"ok": False, "error": "scene_id required"}, status=400)
            
            scene = cfg.get_scene_by_id(scene_id)
            if not scene:
                return web.json_response({"ok": False, "error": "Scene not found"}, status=404)
            
            # 设置当前场景
            cfg.set_current_scene(scene_id)
            cfg.save_scenes()
            
            # 广播场景变更到所有客户端
            await hub.broadcast({
                "action": "scene_changed",
                "scene_id": scene_id,
                "scene": scene
            })
            
            logger.info(f"Scene applied: {scene_id}")
            return web.json_response({
                "ok": True,
                "scene_id": scene_id,
                "scene_name": scene.get("name", scene_id)
            })
            
        except Exception as e:
            logger.error(f"Apply scene error: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)
    
    # 对话队列管理API（动作管理API已移除 - 骨骼动画模式）
    async def get_dialogue_queue(request):
        """获取对话队列状态"""
        return web.json_response(dialogue_queue.get_queue_status())
    
    async def cancel_dialogue(request):
        """取消/忽略某个对话"""
        try:
            data = await request.json()
            item_id = data.get("id")
            success = await dialogue_queue.cancel_item(item_id)
            return web.json_response({"ok": success})
        except Exception as e:
            logger.error(f"Cancel dialogue error: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)
    
    async def emergency_dialogue(request):
        """设置为紧急插队"""
        try:
            data = await request.json()
            item_id = data.get("id")
            success = await dialogue_queue.set_emergency(item_id)
            return web.json_response({"ok": success})
        except Exception as e:
            logger.error(f"Emergency dialogue error: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)
    
    async def reorder_dialogue(request):
        """手动调整对话顺序"""
        try:
            data = await request.json()
            item_ids = data.get("ids", [])
            await dialogue_queue.reorder_items(item_ids)
            return web.json_response({"ok": True})
        except Exception as e:
            logger.error(f"Reorder dialogue error: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)
    
    async def toggle_playback_pause(request):
        """暂停/恢复播报（不影响队列积累和事件处理）- 骨骼动画模式简化"""
        try:
            data = await request.json()
            pause = data.get("pause", True)
            # action_mgr已移除，使用director内部状态
            if pause:
                # 暂停：打断当前播报sleep + 通知前端停止音频
                director._skip_event.set()
                await hub.broadcast({"action": "stop_speak"})
                logger.info("Playback paused")
            else:
                # 恢复：清除skip_event，防止下一条立即被跳过
                director._skip_event.clear()
                logger.info("Playback resumed")
            return web.json_response({"ok": True, "paused": pause})
        except Exception as e:
            logger.error(f"Toggle playback pause error: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def skip_current_dialogue(request):
        """跳到下一条（打断当前播放）"""
        try:
            await dialogue_queue.skip_current()
            if director._speaking_lock.locked():
                # 有正在播的：设event打断，对话队列finally里会clear
                director._skip_event.set()
                await hub.broadcast({"action": "stop_speak"})
            else:
                # 没在播：直接不处理，skip_event保持clear
                pass
            return web.json_response({"ok": True})
        except Exception as e:
            logger.error(f"Skip current error: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def prev_dialogue(request):
        """重播上一条（打断当前，插队播上一条）"""
        try:
            if not dialogue_queue.history:
                return web.json_response({"ok": False, "error": "no history"})
            last = dialogue_queue.history[-1]
            # 先打断当前播放
            await dialogue_queue.skip_current()
            if director._speaking_lock.locked():
                director._skip_event.set()
                await hub.broadcast({"action": "stop_speak"})
                await asyncio.sleep(0.15)  # 等finally里clear掉skip_event
            # 插队播上一条
            item_id = await dialogue_queue.add_manual(
                text=last.reply,
                username=last.username,
                emergency=True
            )
            return web.json_response({"ok": True, "id": item_id, "text": last.reply})
        except Exception as e:
            logger.error(f"Prev dialogue error: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)
    
    async def manual_dialogue(request):
        """手动添加话术（跳过AI生成）"""
        try:
            data = await request.json()
            text = data.get("text", "").strip()
            emergency = data.get("emergency", False)
            if not text:
                return web.json_response({"ok": False, "error": "text is empty"}, status=400)
            
            item_id = await dialogue_queue.add_manual(
                text=text,
                username="坊主",
                emergency=emergency
            )
            return web.json_response({"ok": True, "id": item_id})
        except Exception as e:
            logger.error(f"Manual dialogue error: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)
    
    async def get_global_config(request):
        """获取全局配置 - 骨骼动画模式简化版"""
        try:
            # 返回硬编码配置（替代action_mgr.global_config）
            return web.json_response({
                "ok": True,
                "config": {
                    "pause_playback": False,
                    "tts_rate": 1.0,
                    "tts_volume": 0.8,
                    "mute_tts": False,
                    "enable_ai_response": True,
                    "enable_auto_welcome": True,
                    "enable_gift_effects": True,
                    "prevent_interruption": True,
                    "enable_danmaku": True,
                    "enable_order_response": True,
                    "enable_direct_broadcast": False,
                }
            })
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)
    
    async def clear_dialogue_queue(request):
        """清空对话队列 + 事件流"""
        try:
            dialogue_queue.clear_all()
            # 同时清空事件队列
            async with event_queue._lock:
                event_queue.queue.clear()
                event_queue.recent_events.clear()
            await hub.broadcast({"action": "dialogue_queue_updated", "queue_status": dialogue_queue.get_queue_status()})
            queue_status = await event_queue.get_queue_status()
            await hub.broadcast({"action": "queue_status", **queue_status})
            return web.json_response({"ok": True})
        except Exception as e:
            logger.error(f"Clear queue error: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)
    
    async def emergency_reset(request):
        """紧急重置：停止当前播放、清空队列、回到IDLE"""
        try:
            # 清空对话队列
            dialogue_queue.clear_all()
            # 打断当前事件
            director._interrupted = True
            director._interrupt_event.set()
            # 重置状态
            director.set_state(HostState.IDLE)
            # 播放待机视频
            current_style = cfg.get_current_style()
            idle_video = director._video("idle")
            await hub.broadcast({
                "action": "play_video",
                "url": idle_video,
                "loop": True
            })
            await hub.broadcast({"action": "dialogue_queue_updated", "queue_status": dialogue_queue.get_queue_status()})
            logger.warning("Emergency reset triggered")
            return web.json_response({"ok": True})
        except Exception as e:
            logger.error(f"Emergency reset error: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)
    
    # 路由
    app.router.add_get("/", index)
    app.router.add_get("/llm-config", llm_config_page)
    app.router.add_get("/control", control_panel)
    app.router.add_get("/editor", scene_editor)
    app.router.add_get("/products", products_page)
    app.router.add_get("/live-scene", live_scene)
    app.router.add_get("/settings", settings_page)
    app.router.add_get("/api/scenes", get_scenes)
    app.router.add_post("/api/scenes", save_scenes)
    app.router.add_post("/api/scenes/upload", upload_scene)
    app.router.add_get("/api/scene-templates", get_scene_templates)
    app.router.add_post("/api/props/upload", upload_prop)
    app.router.add_get("/api/props", list_props)
    app.router.add_get("/api/groups", get_groups)
    app.router.add_post("/api/groups", save_groups)
    app.router.add_post("/api/scenes/move", move_scene_group)
    app.router.add_post("/api/scenes/reorder", reorder_scenes)
    app.router.add_post("/api/scene/apply", apply_scene)

    async def scene_command(request):
        """场景控制指令（摄像机/聚焦等）→ 广播到所有 live-scene 客户端"""
        try:
            data = await request.json()
            command = data.get("command")
            if not command:
                return web.json_response({"ok": False, "error": "command required"}, status=400)
            await hub.broadcast({
                "action": "scene_command",
                "command": command,
                "shelf_id": data.get("shelf_id"),
                "ratio": data.get("ratio"),
                "params": {k: v for k, v in data.items() if k != "command"},
            })
            logger.info(f"Scene command broadcast: {command}")
            return web.json_response({"ok": True, "command": command})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    app.router.add_post("/api/scene/command", scene_command)

    async def switch_character(request):
        """切换NPC角色 → 广播到所有 live-scene 客户端"""
        try:
            data = await request.json()
            character_id = data.get("character_id")
            if not character_id:
                return web.json_response({"ok": False, "error": "character_id required"}, status=400)
            
            # 验证角色ID格式
            if not re.match(r'^[a-zA-Z0-9_\-\u4e00-\u9fa5]+$', character_id):
                return web.json_response({"ok": False, "error": "character_id包含非法字符"}, status=400)
            
            await hub.broadcast({
                "action": "switch_character",
                "character_id": character_id,
            })
            logger.info(f"[CharSwitch] 切换角色: {character_id}")
            return web.json_response({"ok": True, "character_id": character_id})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    app.router.add_post("/api/character/switch", switch_character)
    app.router.add_get("/api/config", get_config)
    app.router.add_get("/api/status/queue", get_queue_status)
    app.router.add_get("/api/status/popups", get_popup_status)
    app.router.add_get("/api/status/system", get_system_status)
    app.router.add_post("/api/ai/chat", ai_chat)
    app.router.add_post("/api/tts/synthesize", tts_synthesize)
    app.router.add_post("/api/style/switch", switch_style)
    app.router.add_post("/api/config/reload", reload_config)
    app.router.add_post("/api/test/trigger", test_trigger)
    # 原actions.json相关API已移除 - 骨骼动画模式
    
    async def remove_event_item(request):
        """忽略事件队列中的某个事件"""
        try:
            data = await request.json()
            event_id = data.get("event_id", "")
            ok = await event_queue.remove_event(event_id)
            return web.json_response({"ok": ok})
        except Exception as e:
            logger.error(f"Remove event error: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def move_up_event_item(request):
        """将事件队列中的某个事件上移一位"""
        try:
            data = await request.json()
            event_id = data.get("event_id", "")
            ok = await event_queue.reorder_event_up(event_id)
            return web.json_response({"ok": ok})
        except Exception as e:
            logger.error(f"Move up event error: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    app.router.add_post("/api/event/remove", remove_event_item)
    app.router.add_post("/api/event/moveup", move_up_event_item)
    app.router.add_get("/api/dialogue", get_dialogue_queue)
    app.router.add_post("/api/dialogue/cancel", cancel_dialogue)
    app.router.add_post("/api/dialogue/emergency", emergency_dialogue)
    app.router.add_post("/api/dialogue/reorder", reorder_dialogue)
    app.router.add_post("/api/playback/pause", toggle_playback_pause)
    app.router.add_post("/api/dialogue/skip", skip_current_dialogue)
    app.router.add_post("/api/dialogue/prev", prev_dialogue)
    app.router.add_post("/api/dialogue/manual", manual_dialogue)
    # 原/api/actions/global路由已移除
    app.router.add_post("/api/queue/clear", clear_dialogue_queue)
    app.router.add_post("/api/emergency/reset", emergency_reset)

    # 用字典封装可变状态（避免 nonlocal 语法问题）
    live_state = {"task": None, "running": False}
    app["live_state"] = live_state  # 暴露给外部访问

    # ========== 直播开始/停止 API ==========
    async def live_start(request):
        """开始直播（启动弹幕抓取）"""
        try:
            try:
                data = await request.json()
            except Exception:
                data = {}
            simulate = data.get("simulate", False)
            if live_state["running"]:
                return web.json_response({"ok": True, "message": "已在直播中", "running": True})
            danmaku_crawler.is_running = True
            if simulate:
                # 取消旧任务
                if live_state["task"] and not live_state["task"].done():
                    live_state["task"].cancel()
                    try:
                        await asyncio.wait_for(asyncio.shield(live_state["task"]), timeout=2)
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        pass
                live_state["task"] = asyncio.create_task(danmaku_crawler._simulate_danmaku())
                live_state["running"] = True
                logger.info("[直播] 模拟弹幕模式已启动")
                return web.json_response({"ok": True, "message": "模拟弹幕模式已启动", "running": True, "mode": "simulate"})
            else:
                # 取消旧任务
                if live_state["task"] and not live_state["task"].done():
                    live_state["task"].cancel()
                    try:
                        await asyncio.wait_for(asyncio.shield(live_state["task"]), timeout=2)
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        pass
                live_state["task"] = asyncio.create_task(danmaku_crawler.start())
                live_state["running"] = True
                mode = "real" if danmaku_crawler.room_id else "simulate"
                logger.info(f"[直播] 弹幕抓取已启动 mode={mode}")
                return web.json_response({"ok": True, "message": f"直播已开始 ({mode})", "running": True, "mode": mode})
        except Exception as e:
            logger.error(f"Live start error: {e}", exc_info=True)
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def live_stop(request):
        """停止直播（停止弹幕抓取，清空队列）"""
        try:
            if danmaku_crawler:
                danmaku_crawler.is_running = False
            t = live_state["task"]
            if t and not t.done():
                t.cancel()
                try:
                    await asyncio.wait_for(asyncio.shield(t), timeout=2)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass
            live_state["task"] = None
            live_state["running"] = False
            # 清空队列
            try:
                async with event_queue._lock:
                    event_queue.queue.clear()
                    event_queue.recent_events.clear()
            except Exception:
                pass
            try:
                dialogue_queue.clear_all()
            except Exception:
                pass
            logger.info("[直播] 已停止弹幕抓取，队列已清空")
            return web.json_response({"ok": True, "message": "直播已停止", "running": False})
        except Exception as e:
            logger.error(f"Live stop error: {e}", exc_info=True)
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def live_status(request):
        """获取直播状态"""
        try:
            room_id = getattr(danmaku_crawler, "room_id", None) if danmaku_crawler else None
            return web.json_response({
                "ok": True,
                "running": live_state.get("running", False),
                "room_id": room_id,
                "mode": "real" if room_id else "simulate"
            })
        except Exception as e:
            logger.error(f"live_status error: {e}")
            return web.json_response({"ok": False, "running": False, "mode": "simulate", "error": str(e)}, status=200)

    app.router.add_post("/api/live/start", live_start)
    app.router.add_post("/api/live/stop", live_stop)
    app.router.add_get("/api/live/status", live_status)

    async def get_presets(request):
        """获取预设话术分类列表"""
        presets_path = ROOT_DIR / "config" / "presets.json"
        try:
            with open(presets_path, encoding="utf-8") as f:
                data = json.load(f)
            return web.json_response(data)
        except Exception as e:
            return web.json_response({"categories": []}, status=200)

    async def save_presets(request):
        """保存预设话术"""
        presets_path = ROOT_DIR / "config" / "presets.json"
        try:
            data = await request.json()
            with open(presets_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            # 热重载 director 的事件话术模板
            if hasattr(director, "reload_event_templates"):
                director.reload_event_templates()
            return web.json_response({"ok": True})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    app.router.add_get("/api/presets", get_presets)
    app.router.add_post("/api/presets", save_presets)

    # ========== actions.json API已移除 - 骨骼动画模式 ==========
    # 原get_actions_config和save_actions_config函数已删除

    # ========== 产品(SKU) CRUD API ==========
    async def get_skus(request):
        """获取所有产品列表，返回 {skus: [...]} 格式"""
        skus_path = ROOT_DIR / "config" / "skus.json"
        try:
            with open(skus_path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "skus" not in data:
                # 旧格式：dict of sku_id→item，转成列表
                skus_list = [{"id": k, **v} if isinstance(v, dict) else v for k, v in data.items()]
            elif isinstance(data, dict) and "skus" in data:
                skus_list = data["skus"]
            elif isinstance(data, list):
                skus_list = data
            else:
                skus_list = []
            return web.json_response({"ok": True, "skus": skus_list})
        except Exception:
            return web.json_response({"ok": True, "skus": []})

    async def save_skus(request):
        """保存所有产品（整体替换）"""
        skus_path = ROOT_DIR / "config" / "skus.json"
        try:
            data = await request.json()
            with open(skus_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            # 热更新到 director
            if hasattr(director, 'cfg') and hasattr(director.cfg, 'reload'):
                director.cfg.reload()
            return web.json_response({"ok": True})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def save_sku_item(request):
        """保存/新增单个产品（PUT更新，POST新增）"""
        skus_path = ROOT_DIR / "config" / "skus.json"
        try:
            sku_id = request.match_info.get("sku_id")  # PUT 时有，POST 时无
            item = await request.json()
            if not sku_id:
                sku_id = item.get("id") or f"sku_{int(__import__('time').time())}"
            item["id"] = sku_id
            # 读现有数据（列表格式）
            try:
                with open(skus_path, encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, list):
                    skus_list = raw
                elif isinstance(raw, dict) and "skus" in raw:
                    skus_list = raw["skus"]
                else:
                    skus_list = [{"id": k, **v} for k, v in raw.items() if isinstance(v, dict)]
            except Exception:
                skus_list = []
            # 更新或追加
            idx = next((i for i, s in enumerate(skus_list) if s.get("id") == sku_id), -1)
            if idx >= 0:
                skus_list[idx] = item
            else:
                skus_list.append(item)
            with open(skus_path, "w", encoding="utf-8") as f:
                json.dump({"skus": skus_list}, f, ensure_ascii=False, indent=2)
            return web.json_response({"ok": True, "id": sku_id})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def delete_sku_item(request):
        """删除单个产品"""
        skus_path = ROOT_DIR / "config" / "skus.json"
        try:
            sku_id = request.match_info.get("sku_id")
            try:
                with open(skus_path, encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, list):
                    skus_list = raw
                elif isinstance(raw, dict) and "skus" in raw:
                    skus_list = raw["skus"]
                else:
                    skus_list = []
            except Exception:
                skus_list = []
            skus_list = [s for s in skus_list if s.get("id") != sku_id]
            with open(skus_path, "w", encoding="utf-8") as f:
                json.dump({"skus": skus_list}, f, ensure_ascii=False, indent=2)
            return web.json_response({"ok": True})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def ai_fill_product(request):
        """AI辅助补全商品信息：卖点、描述、属性"""
        try:
            body = await request.json()
            name     = body.get("name", "")
            category = body.get("category", "")
            attrs    = body.get("attributes", {})
            attrs_str = "\n".join(f"- {k}: {v or '(未填)'}" for k, v in attrs.items()) if attrs else "暂无"
            prompt = (
                f"你是一名专业电商选品顾问。请根据以下商品信息，补全商品的核心卖点和描述，返回JSON。\n"
                f"商品名称：{name}\n"
                f"商品分类：{category}\n"
                f"已知属性：\n{attrs_str}\n\n"
                f"请返回如下JSON格式（不要加```）：\n"
                f'{{"highlights":["卖点1","卖点2","卖点3"],'
                f'"description":"一段50字以内的商品介绍",'
                f'"attributes":{{"属性名":"属性值"}}}}\n'
                f"highlights要真实、具体、有吸引力，attributes补全已有空白项。"
            )
            result = await ai.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7
            )
            content = result.get("content", "").strip()
            # 尝试解析JSON
            import re as _re
            m = _re.search(r'\{.*\}', content, _re.DOTALL)
            if m:
                parsed = json.loads(m.group())
                return web.json_response({"ok": True, **parsed})
            return web.json_response({"ok": False, "error": "AI返回格式异常", "raw": content})
        except Exception as e:
            logger.error(f"ai_fill_product error: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def platform_fetch_product(request):
        """从平台拉取商品信息（目前返回提示，各平台需配置API Key后接入）"""
        try:
            body = await request.json()
            platform = body.get("platform", "")
            sku_id   = body.get("sku_id", "")
            # TODO: 各平台真实接入逻辑
            # 目前返回提示信息，引导用户到配置中心填写API Key
            platform_names = {
                "douyin": "抖音", "taobao": "淘宝/天猫",
                "jd": "京东", "kuaishou": "快手", "jushuitan": "聚水潭"
            }
            pname = platform_names.get(platform, platform)
            return web.json_response({
                "ok": False,
                "error": f"{pname} API 尚未接入，请在配置中心填写 AppKey/AppSecret 后重试，或手动录入商品信息"
            })
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    app.router.add_get("/api/skus", get_skus)
    app.router.add_post("/api/skus", save_sku_item)   # 新增
    app.router.add_post("/api/skus/save-all", save_skus)
    app.router.add_put("/api/skus/{sku_id}", save_sku_item)
    app.router.add_delete("/api/skus/{sku_id}", delete_sku_item)
    app.router.add_post("/api/product/ai-fill", ai_fill_product)
    app.router.add_post("/api/product/platform-fetch", platform_fetch_product)

    # ========== 平台商品同步 API ==========
    async def get_platforms(request):
        """获取所有可用的商品同步平台"""
        platforms = platform_product_manager.get_available_platforms()
        return web.json_response({
            "platforms": platforms,
            "mock_enabled": True  # 支持模拟数据模式
        })

    async def sync_platform_products(request):
        """同步指定平台的商品，并保存到skus.json"""
        try:
            data = await request.json()
            platform = data.get("platform", "douyin")
            room_id = data.get("room_id")
            use_mock = data.get("mock", False)
            save_to_config = data.get("save", True)  # 是否保存到skus.json

            if use_mock:
                # 使用模拟数据
                mock_adapter = MockPlatformAdapter({"enabled": True, "name": "模拟平台"})
                products = await mock_adapter.get_live_products(room_id)
                local_products = [platform_product_manager._convert_to_local(p) for p in products]
            else:
                # 真实平台同步
                result = await platform_product_manager.sync_platform_products(platform, room_id)
                if not result.get("success"):
                    return web.json_response(result)
                local_products = result.get("products", [])

            # 保存到skus.json
            if save_to_config and local_products:
                try:
                    skus_path = ROOT_DIR / "config" / "skus.json"

                    # 转换为skus.json格式（对象格式，以id为key）
                    skus_data = {}
                    shelf_slots = ["A1", "A2", "A3", "B1", "B2", "B3"]  # 默认货架位置

                    for idx, product in enumerate(local_products):
                        sku_id = product.get("id") or f"{platform}_{product.get('platform_id')}"
                        shelf_id = shelf_slots[idx % len(shelf_slots)] if idx < len(shelf_slots) else None

                        skus_data[sku_id] = {
                            "id": sku_id,
                            "name": product.get("name", ""),
                            "category": product.get("category", "tea"),
                            "price": product.get("price", 0),
                            "original_price": product.get("original_price", 0),
                            "stock": product.get("stock", 0),
                            "status": product.get("status", "active"),
                            "keywords": product.get("category", ""),
                            "description": "",
                            "image": product.get("image_url", ""),
                            "model": "",
                            "video": "",
                            "shelf_id": shelf_id,
                            "platform_id": product.get("platform_id", ""),
                            "platform": platform,
                            "detail_url": product.get("detail_url", ""),
                            "sync_time": product.get("sync_time", "")
                        }

                    # 写入skus.json
                    with open(skus_path, "w", encoding="utf-8") as f:
                        json.dump(skus_data, f, ensure_ascii=False, indent=2)

                    # 重新加载配置
                    cfg.load_all()

                    save_msg = f"，已保存 {len(skus_data)} 个商品到skus.json"
                    logger.info(f"[Sync] 商品同步完成{save_msg}")

                except Exception as save_error:
                    logger.error(f"[Sync] 保存skus.json失败: {save_error}")
                    save_msg = "，但保存到skus.json失败"

            return web.json_response({
                "success": True,
                "count": len(local_products),
                "platform": platform,
                "products": local_products,
                "message": f"成功获取 {len(local_products)} 个商品{save_msg if save_to_config else ''}"
            })

        except Exception as e:
            logger.error(f"Sync platform products error: {e}")
            return web.json_response({"success": False, "error": str(e)}, status=500)

    async def test_platform_connection(request):
        """测试平台连接"""
        try:
            data = await request.json()
            platform = data.get("platform", "douyin")
            result = await platform_product_manager.test_connection(platform)
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"success": False, "error": str(e)}, status=500)

    app.router.add_get("/api/platforms", get_platforms)
    app.router.add_post("/api/platforms/sync", sync_platform_products)
    app.router.add_post("/api/platforms/test", test_platform_connection)

    # ========== 主配置 (main.json) API ==========
    async def get_main_config(request):
        """获取主配置"""
        main_path = ROOT_DIR / "config" / "main.json"
        try:
            with open(main_path, encoding="utf-8") as f:
                data = json.load(f)
            return web.json_response(data)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def save_main_config(request):
        """保存主配置"""
        main_path = ROOT_DIR / "config" / "main.json"
        try:
            data = await request.json()
            with open(main_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return web.json_response({"ok": True})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    app.router.add_get("/api/main-config", get_main_config)
    app.router.add_post("/api/main-config", save_main_config)

    # ========== 角色(characters) API ==========
    async def get_characters(request):
        """获取角色配置"""
        chars_path = ROOT_DIR / "config" / "characters.json"
        try:
            with open(chars_path, encoding="utf-8") as f:
                data = json.load(f)
            return web.json_response(data)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def save_characters(request):
        """保存角色配置"""
        chars_path = ROOT_DIR / "config" / "characters.json"
        try:
            data = await request.json()
            with open(chars_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return web.json_response({"ok": True})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    app.router.add_get("/api/characters", get_characters)
    app.router.add_post("/api/characters", save_characters)

    # ========== 角色骨架列表 API (character_skeletons.json) ==========
    async def get_character_skeletons(request):
        """获取角色骨架列表（含模型文件路径）"""
        skeletons_path = ROOT_DIR / "config" / "character_skeletons.json"
        try:
            with open(skeletons_path, encoding="utf-8") as f:
                data = json.load(f)
            # 简化返回，只返回角色列表
            return web.json_response({
                "ok": True,
                "characters": data.get("characters", {})
            })
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    app.router.add_get("/api/character-skeletons", get_character_skeletons)

    # ========== 骨骼类型与重定向映射 API ==========
    async def get_skeleton_types(request):
        """获取骨骼类型配置和重定向映射表"""
        skeleton_types_path = ROOT_DIR / "config" / "skeleton_types.json"
        try:
            with open(skeleton_types_path, encoding="utf-8") as f:
                data = json.load(f)
            return web.json_response({
                "ok": True,
                "standard_types": data.get("types", {}),
                "retarget_maps": data.get("retarget_maps", {})
            })
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    app.router.add_get("/api/skeleton-types", get_skeleton_types)

    # ========== 配置中心页面路由 ==========
    async def settings_page(request):
        settings_file = FRONTEND_DIR / "settings.html"
        return web.FileResponse(settings_file)

    app.router.add_get("/settings", settings_page)

    # ========== 素材管理页面路由 ==========
    async def assets_manager_page(request):
        f = FRONTEND_DIR / "assets-manager.html"
        content = f.read_text(encoding="utf-8")
        return web.Response(text=content, content_type="text/html",
                            headers={"Cache-Control": "no-cache, no-store, must-revalidate",
                                     "Pragma": "no-cache", "Expires": "0"})

    app.router.add_get("/assets", assets_manager_page)

    # ========== 语音互动页面路由 ==========
    async def voice_chat_page(request):
        """语音互动页面（旧版单个会话）"""
        voice_file = FRONTEND_DIR / "voice.html"
        if voice_file.exists():
            return web.FileResponse(voice_file)
        return web.Response(text="语音页面不存在", status=404)
    
    async def voice_join_page(request):
        """语音排队入口页面（新版固定入口）"""
        join_file = FRONTEND_DIR / "voice-join.html"
        if join_file.exists():
            return web.FileResponse(join_file)
        return web.Response(text="排队页面不存在", status=404)
    
    app.router.add_get("/voice/{session_id}", voice_chat_page)
    app.router.add_get("/voice/join", voice_join_page)  # 固定入口
    
    # ========== 语音排队系统 API ==========
    async def get_voice_queue(request):
        """获取排队状态"""
        try:
            request_id = request.query.get("request_id")
            status = voice_queue_manager.get_queue_status(request_id)
            status["ok"] = True
            return web.json_response(status)
        except Exception as e:
            logger.error(f"Get voice queue error: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)
    
    async def join_voice_queue(request):
        """加入语音排队队列"""
        try:
            data = await request.json()
            username = data.get("username", "匿名用户")
            user_id = data.get("user_id", str(uuid.uuid4())[:8])
            feature_type = data.get("feature", "message")  # message / call
            
            result = voice_queue_manager.join_queue(
                username=username,
                user_id=user_id,
                feature_type=feature_type
            )
            
            return web.json_response(result)
        except Exception as e:
            logger.error(f"Join voice queue error: {e}")
            return web.json_response({"success": False, "error": str(e)}, status=500)
    
    async def accept_voice_request(request):
        """主播接受语音请求"""
        try:
            data = await request.json()
            request_id = data.get("request_id")
            max_duration = data.get("max_duration", 60)
            
            result = voice_queue_manager.accept_request(request_id, max_duration)
            return web.json_response(result)
        except Exception as e:
            logger.error(f"Accept voice request error: {e}")
            return web.json_response({"success": False, "error": str(e)}, status=500)
    
    async def reject_voice_request(request):
        """主播拒绝语音请求"""
        try:
            data = await request.json()
            request_id = data.get("request_id")
            
            result = voice_queue_manager.reject_request(request_id)
            return web.json_response(result)
        except Exception as e:
            logger.error(f"Reject voice request error: {e}")
            return web.json_response({"success": False, "error": str(e)}, status=500)
    
    async def cancel_voice_request(request):
        """用户取消语音请求"""
        try:
            data = await request.json()
            request_id = data.get("request_id")
            
            result = voice_queue_manager.cancel_request(request_id)
            return web.json_response(result)
        except Exception as e:
            logger.error(f"Cancel voice request error: {e}")
            return web.json_response({"success": False, "error": str(e)}, status=500)
    
    async def update_voice_config(request):
        """更新语音系统配置"""
        try:
            data = await request.json()
            voice_queue_manager.update_config(
                voice_message_enabled=data.get("voice_message_enabled", True),
                voice_call_enabled=data.get("voice_call_enabled", True),
                default_call_duration=data.get("default_call_duration", 60),
                auto_accept=data.get("auto_accept", False)
            )
            return web.json_response({"ok": True})
        except Exception as e:
            logger.error(f"Update voice config error: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)
    
    # 注册语音排队API路由
    app.router.add_get("/api/voice/queue", get_voice_queue)
    app.router.add_post("/api/voice/join", join_voice_queue)
    app.router.add_post("/api/voice/accept", accept_voice_request)
    app.router.add_post("/api/voice/reject", reject_voice_request)
    app.router.add_post("/api/voice/cancel", cancel_voice_request)
    app.router.add_post("/api/voice/config", update_voice_config)
    
    # ========== 动作流控制 API ==========
    action_flows = []  # 内存存储动作流预设
    
    async def get_action_flows(request):
        """获取动作流预设列表"""
        return web.json_response({"ok": True, "flows": action_flows})
    
    async def save_action_flows(request):
        """保存动作流预设"""
        try:
            data = await request.json()
            nonlocal action_flows
            action_flows = data.get("flows", [])
            return web.json_response({"ok": True})
        except Exception as e:
            logger.error(f"Save action flows error: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)
    
    async def play_action_flow(request):
        """执行动作流"""
        try:
            data = await request.json()
            flow_id = data.get("flow_id")
            
            flow = next((f for f in action_flows if f.get("id") == flow_id), None)
            if not flow:
                return web.json_response({"ok": False, "error": "动作流不存在"}, status=404)
            
            # 发送动作流执行命令到WebSocket
            await hub.broadcast({
                "action": "play_action_flow",
                "flow": flow
            })
            
            return web.json_response({"ok": True, "message": f"开始执行动作流: {flow.get('name')}"})
        except Exception as e:
            logger.error(f"Play action flow error: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)
    
    async def play_quick_action(request):
        """执行快捷动作"""
        try:
            data = await request.json()
            action_key = data.get("action_key")
            priority = data.get("priority", "normal")
            
            # 发送动作命令到WebSocket
            await hub.broadcast({
                "action": "play_action",
                "data": {
                    "action_key": action_key,
                    "priority": priority
                }
            })
            
            return web.json_response({"ok": True})
        except Exception as e:
            logger.error(f"Play action error: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)
    
    async def stop_action(request):
        """停止当前动作"""
        try:
            await hub.broadcast({
                "action": "stop_action"
            })
            return web.json_response({"ok": True})
        except Exception as e:
            logger.error(f"Stop action error: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)
    
    app.router.add_get("/api/action-flows", get_action_flows)
    app.router.add_post("/api/action-flows", save_action_flows)
    app.router.add_post("/api/action-flows/play", play_action_flow)
    app.router.add_post("/api/action/play", play_quick_action)
    app.router.add_post("/api/action/stop", stop_action)
    
    # ========== 主播真人语音回复 API ==========
    # 导入STT服务
    from .stt_service import get_stt_service
    
    async def host_voice_reply(request):
        """主播语音回复 - NPC复述主播的话"""
        try:
            data = await request.json()
            base64_audio = data.get("audio")
            reply_to = data.get("reply_to")  # {username, message}
            
            if not base64_audio:
                return web.json_response({"ok": False, "error": "缺少音频数据"}, status=400)
            
            # STT语音识别 - 主播说什么NPC说什么
            stt = get_stt_service()
            transcribed_text = await stt.transcribe(base64_audio, language="zh")
            
            if not transcribed_text:
                return web.json_response({
                    "ok": False, 
                    "error": "语音识别失败，请重试"
                }, status=400)
            
            # 构建上下文（用于日志记录，NPC播报不需要context，直接说主播的话）
            context = ""
            if reply_to:
                context = f"回复{reply_to.get('username', '观众')}的评论: {reply_to.get('message', '')}"
            
            # 主播语音直接作为NPC播报内容（主播说什么NPC说什么）
            await event_queue.submit(
                "host_voice_reply",
                {
                    "text": transcribed_text,  # 主播说的内容
                    "original_audio": base64_audio,
                    "context": context,
                    "reply_to": reply_to,
                    "is_host_voice": True  # 标记为真人主播语音
                },
                priority=EventPriority.HIGH
            )
            
            # 广播给所有客户端
            await hub.broadcast({
                "action": "host_voice_received",
                "transcribed": transcribed_text[:50] + "...",
                "reply_to": reply_to
            })
            
            return web.json_response({
                "ok": True,
                "transcribed": transcribed_text,
                "message": f"语音已识别，NPC将复述: {transcribed_text[:30]}..."
            })
            
        except Exception as e:
            logger.error(f"Host voice reply error: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)
    
    app.router.add_post("/api/host/voice", host_voice_reply)
    
    # ========== 多平台配置 API ==========
    async def get_platforms(request):
        """获取所有平台配置"""
        try:
            platform_config_path = ROOT_DIR / "config" / "platforms.json"
            if platform_config_path.exists():
                with open(platform_config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                # 过滤掉以_开头的内部字段
                platforms = {k: v for k, v in data.items() if not k.startswith('_')}
                return web.json_response({"ok": True, "platforms": platforms})
            return web.json_response({"ok": True, "platforms": {}})
        except Exception as e:
            logger.error(f"Get platforms error: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)
    
    async def save_platforms(request):
        """保存平台配置"""
        try:
            data = await request.json()
            platforms = data.get("platforms", {})
            
            platform_config_path = ROOT_DIR / "config" / "platforms.json"
            # 读取原配置，保留_doc等元信息
            existing = {}
            if platform_config_path.exists():
                with open(platform_config_path, 'r', encoding='utf-8') as f:
                    existing = json.load(f)
            
            # 合并平台配置
            for k, v in platforms.items():
                existing[k] = v
            
            # 保存
            with open(platform_config_path, 'w', encoding='utf-8') as f:
                json.dump(existing, f, ensure_ascii=False, indent=2)
            
            # 重新加载平台管理器（热更新）
            try:
                from modules.platform_adapter import init_platform_manager
                init_platform_manager({k: v for k, v in existing.items() if not k.startswith('_')})
            except Exception as e:
                logger.warning(f"Reload platform manager failed: {e}")
            
            return web.json_response({"ok": True, "message": "保存成功，配置已热更新"})
        except Exception as e:
            logger.error(f"Save platforms error: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)
    
    app.router.add_get("/api/platforms", get_platforms)
    app.router.add_post("/api/platforms", save_platforms)
    
    # ========== 直播间模拟器 API ==========
    async def simulate_event(request):
        """模拟直播间事件（用于编辑器/控制台测试）

        请求支持两种格式：
        1) 顶层字段：{ "type":"danmaku", "username":"x", "content":"..." }
        2) 嵌套 data：{ "type":"danmaku", "data": {"username":"x", "content":"..."} }
        """
        try:
            payload = await request.json()
            event_type = payload.get("type", "unknown")
            # 兼容嵌套 data
            src = payload.get("data") if isinstance(payload.get("data"), dict) else payload

            event_data = {
                "username":  src.get("username", f"测试用户{int(time.time())%1000}"),
                "message":   src.get("message", src.get("content", "")),
                "content":   src.get("content", src.get("message", "")),
                "gift_type": src.get("gift_type", ""),
                "gift_name": src.get("gift_name", src.get("name", "")),
                "sku_name":  src.get("sku_name", ""),
                "amount":    src.get("amount", 0),
                "count":     src.get("count", 1),
            }

            # 映射前端事件类型 → 内部 intent
            if event_type == "gift":
                # 礼物档位复用 director 的配置化分级逻辑，与真实事件流保持一致
                gift_intent = director._resolve_gift_tier(
                    event_data.get("gift_name", ""),
                    int(event_data.get("amount", 0))
                )
            else:
                gift_intent = "gift_small"
            intent_map = {
                "chat":       "smart_chat",
                "danmaku":    "smart_chat",
                "user_enter": "user_enter",
                "like":       "like_received",
                "gift":       gift_intent,
                "order":      "order_placed",
                "follow":     "user_enter",
            }
            intent = intent_map.get(event_type, "general_chat")
            priority = PRIORITY_MAP.get(intent, EventPriority.GENERAL_CHAT)

            # 用 EventQueueManager.submit 提交
            accepted = await event_queue.submit(intent, event_data, priority=priority)

            # 广播给前端做实时事件流展示
            await hub.broadcast({
                "action": event_type,
                "data": event_data,
                "type": event_type,
            })

            logger.info(f"Simulated event: type={event_type} -> intent={intent} accepted={accepted}")
            return web.json_response({"ok": True, "intent": intent, "accepted": accepted})
        except Exception as e:
            logger.error(f"Simulate event error: {e}", exc_info=True)
            return web.json_response({"ok": False, "error": str(e)}, status=500)
    
    async def npc_action(request):
        """触发NPC动作（用于编辑器测试）"""
        try:
            data = await request.json()
            action = data.get("action", "idle")
            
            # 获取当前风格
            current_style = cfg.get_current_style() if hasattr(cfg, 'get_current_style') else "classical"
            
            # 广播动作指令到前端
            await hub.broadcast({
                "action": "npc_action",
                "npc_action": action,
                "style": current_style
            })
            
            logger.info(f"NPC action triggered: {action}, style: {current_style}")
            return web.json_response({"ok": True, "action": action, "style": current_style})
        except Exception as e:
            logger.error(f"NPC action error: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)
    
    app.router.add_post("/api/simulate/event", simulate_event)
    app.router.add_post("/api/npc/action", npc_action)

    # ========== 功能开关 API (替代旧的 /api/actions/global) ==========
    async def get_feature_flags(request):
        """获取所有功能开关状态"""
        try:
            main_path = cfg.config_dir / "main.json"
            with open(main_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return web.json_response({
                "ok": True,
                "flags": data.get("feature_flags", {})
            })
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    # 安全的配置键名校验正则
    _SAFE_KEY_PATTERN = re.compile(r'^[a-zA-Z0-9_\-]+$')
    
    async def set_feature_flag(request):
        """设置单个功能开关"""
        try:
            payload = await request.json()
            key = payload.get("key")
            value = bool(payload.get("value"))
            if not key:
                return web.json_response({"ok": False, "error": "key required"}, status=400)
            
            # 验证key格式（防止路径遍历和注入）
            if not _SAFE_KEY_PATTERN.match(key):
                return web.json_response({"ok": False, "error": "key包含非法字符"}, status=400)

            main_path = cfg.config_dir / "main.json"
            with open(main_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            data.setdefault("feature_flags", {})[key] = value
            with open(main_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            # 同步更新内存配置，立即生效
            cfg.main.setdefault("feature_flags", {})[key] = value
            logger.info(f"Feature flag updated: {key}={value}")
            return web.json_response({"ok": True, "key": key, "value": value})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    app.router.add_get("/api/feature-flags", get_feature_flags)
    app.router.add_post("/api/feature-flags", set_feature_flag)

    # ========== 事件→动作映射 API ==========
    async def get_event_action_map(request):
        try:
            main_path = cfg.config_dir / "main.json"
            with open(main_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return web.json_response({"ok": True, "map": data.get("event_action_map", {})})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def set_event_action_map(request):
        try:
            payload = await request.json()
            new_map = payload.get("map", {})
            main_path = cfg.config_dir / "main.json"
            with open(main_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            data["event_action_map"] = new_map
            with open(main_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return web.json_response({"ok": True})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    app.router.add_get("/api/event-action-map", get_event_action_map)
    app.router.add_post("/api/event-action-map", set_event_action_map)

    # ========== 手动触发动作 (广播到 live-scene) ==========
    async def play_action(request):
        """从控制台手动触发某个动作播放"""
        try:
            payload = await request.json()
            action_key = payload.get("action_key")
            file_path = payload.get("file_path")
            broadcast_data = {"action": "play_action", "data": {}}
            if action_key:
                broadcast_data["data"]["action_key"] = action_key
            if file_path:
                broadcast_data["data"]["file_path"] = file_path
            if hub:
                await hub.broadcast(broadcast_data)
            return web.json_response({"ok": True})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    app.router.add_post("/api/play-action", play_action)
    
    # ========== 编辑器素材库 API ==========
    USER_ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "user")
    os.makedirs(USER_ASSETS_DIR, exist_ok=True)
    
    ASSET_TYPE_MAP = {
        '.glb': '3d_model', '.gltf': '3d_model', '.obj': '3d_model', '.fbx': '3d_model',
        '.png': 'image', '.jpg': 'image', '.jpeg': 'image', '.webp': 'image',
        '.mp4': 'video', '.webm': 'video', '.mov': 'video',
    }
    
    async def upload_asset(request):
        """上传用户素材（3D模型/图片/视频）"""
        try:
            reader = await request.multipart()
            uploaded = []
            
            async for field in reader:
                if field.name != 'file':
                    continue
                filename = field.filename or 'unnamed'
                ext = os.path.splitext(filename)[1].lower()
                if ext not in ASSET_TYPE_MAP:
                    continue
                
                # 生成唯一文件名
                import hashlib
                import time as _time
                safe_name = hashlib.md5(f"{filename}{_time.time()}".encode()).hexdigest()[:12]
                save_name = f"{safe_name}_{filename}"
                save_path = os.path.join(USER_ASSETS_DIR, save_name)
                
                size = 0
                with open(save_path, 'wb') as f:
                    while True:
                        chunk = await field.read_chunk(8192)
                        if not chunk:
                            break
                        size += len(chunk)
                        f.write(chunk)
                
                uploaded.append({
                    "id": safe_name,
                    "name": filename,
                    "filename": save_name,
                    "url": f"/assets/user/{save_name}",
                    "type": ASSET_TYPE_MAP[ext],
                    "ext": ext,
                    "size": size
                })
                logger.info(f"Asset uploaded: {filename} ({size} bytes)")
            
            return web.json_response({"ok": True, "assets": uploaded})
        except Exception as e:
            logger.error(f"Upload asset error: {e}", exc_info=True)
            return web.json_response({"ok": False, "error": str(e)}, status=500)
    
    async def list_assets(request):
        """列出已上传的素材"""
        try:
            assets = []
            if os.path.isdir(USER_ASSETS_DIR):
                for fname in sorted(os.listdir(USER_ASSETS_DIR)):
                    fpath = os.path.join(USER_ASSETS_DIR, fname)
                    if not os.path.isfile(fpath):
                        continue
                    ext = os.path.splitext(fname)[1].lower()
                    if ext not in ASSET_TYPE_MAP:
                        continue
                    # filename格式: {hash}_{原始名称}
                    parts = fname.split('_', 1)
                    asset_id = parts[0] if len(parts) > 1 else fname
                    orig_name = parts[1] if len(parts) > 1 else fname
                    assets.append({
                        "id": asset_id,
                        "name": orig_name,
                        "filename": fname,
                        "url": f"/assets/user/{fname}",
                        "type": ASSET_TYPE_MAP[ext],
                        "ext": ext,
                        "size": os.path.getsize(fpath)
                    })
            return web.json_response({"ok": True, "assets": assets})
        except Exception as e:
            logger.error(f"List assets error: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)
    
    async def delete_asset(request):
        """删除素材"""
        try:
            asset_id = request.match_info.get('asset_id', '')
            for fname in os.listdir(USER_ASSETS_DIR):
                if fname.startswith(asset_id + '_'):
                    os.remove(os.path.join(USER_ASSETS_DIR, fname))
                    return web.json_response({"ok": True})
            return web.json_response({"ok": False, "error": "not found"}, status=404)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)
    
    app.router.add_post("/api/assets/upload", upload_asset)
    app.router.add_get("/api/assets", list_assets)
    app.router.add_delete("/api/assets/{asset_id}", delete_asset)
    
    # ========== 会话录制器 API（素材库） ==========
    if session_recorder:
        async def recorder_toggle(request):
            """开启/关闭自动收录"""
            data = await request.json()
            enabled = data.get("enabled", not session_recorder.enabled)
            session_recorder.enabled = enabled
            return web.json_response({"ok": True, "enabled": enabled})
        
        async def recorder_list(request):
            """获取录制列表，支持按标签过滤"""
            tag = request.query.get("tag")
            saved_only = request.query.get("saved")
            saved_only = {"true": True, "false": False}.get(saved_only, None)
            limit = int(request.query.get("limit", 100))
            records = await session_recorder.get_records(tag=tag, saved_only=saved_only, limit=limit)
            return web.json_response({"records": records})
        
        async def recorder_bulk_save(request):
            """批量保存选中会话到永久素材库（默认按各自分类，可强制覆盖）"""
            data = await request.json()
            record_ids = data.get("record_ids", [])
            override_category = data.get("override_category", "")  # 空=按各自的category分发
            if not record_ids:
                return web.json_response({"ok": False, "error": "record_ids required"}, status=400)
            result = await session_recorder.bulk_save_to_presets(
                record_ids, override_category=override_category)
            return web.json_response({"ok": True, **result})
        
        async def recorder_update_category(request):
            """更新单条记录的主分类（用户手动调整）"""
            data = await request.json()
            record_id = data.get("record_id", "")
            category = data.get("category", "")
            if not record_id or not category:
                return web.json_response({"ok": False, "error": "record_id and category required"}, status=400)
            ok = await session_recorder.update_category(record_id, category)
            return web.json_response({"ok": ok})
        
        async def recorder_clear(request):
            """清空本次录制（可选保留已保存的）"""
            data = await request.json() if request.can_read_body else {}
            keep_saved = data.get("keep_saved", True)
            await session_recorder.clear(keep_saved=keep_saved)
            return web.json_response({"ok": True, "kept_saved": keep_saved})
        
        async def recorder_stats(request):
            """获取录制统计"""
            stats = await session_recorder.get_stats()
            return web.json_response(stats)
        
        app.router.add_post("/api/recorder/toggle", recorder_toggle)
        app.router.add_get("/api/recorder/list", recorder_list)
        app.router.add_post("/api/recorder/bulk_save", recorder_bulk_save)
        app.router.add_post("/api/recorder/update_category", recorder_update_category)
        app.router.add_post("/api/recorder/clear", recorder_clear)
        app.router.add_get("/api/recorder/stats", recorder_stats)
    
    # ========== 智能NPC骨骼动画系统 API (v2) ==========
    try:
        from modules.system_initializer import initialize_system, get_system_health, quick_rescan
        from modules.action_planner import plan_actions
        
        async def api_system_initialize(request):
            """执行系统初始化"""
            try:
                data = await request.json()
                mode = data.get('mode', 'full')
                result = initialize_system(mode)
                return web.json_response(result)
            except Exception as e:
                logger.error(f"System initialize error: {e}")
                return web.json_response({"status": "error", "error": str(e)}, status=500)
        
        async def api_system_health(request):
            """获取系统健康状态"""
            try:
                health = get_system_health()
                return web.json_response(health)
            except Exception as e:
                logger.error(f"System health check error: {e}")
                return web.json_response({
                    "directories_ok": False,
                    "required_files_ok": False,
                    "manifest_ok": False,
                    "total_actions": 0,
                    "total_variants": 0,
                    "error": str(e)
                }, status=500)
        
        async def api_system_rescan(request):
            """快速重新扫描动作文件"""
            try:
                result = quick_rescan()
                return web.json_response(result)
            except Exception as e:
                logger.error(f"System rescan error: {e}")
                return web.json_response({"status": "error", "error": str(e)}, status=500)
        
        async def api_actions_tree(request):
            """获取动作库树形结构（统一从action_catalog.json读取）"""
            try:
                # 优先从action_catalog.json读取（包含完整元信息）
                catalog_path = ROOT_DIR / "config" / "action_catalog.json"
                manifest_path = cfg.config_dir.parent / "assets" / "动作库" / "action_manifest.json"
                
                # 读取catalog和manifest
                catalog_actions = {}
                if catalog_path.exists():
                    with open(catalog_path, 'r', encoding='utf-8') as f:
                        catalog = json.load(f)
                        for action in catalog.get("actions", []):
                            catalog_actions[action["id"]] = action
                
                manifest_actions = {}
                if manifest_path.exists():
                    with open(manifest_path, 'r', encoding='utf-8') as f:
                        manifest = json.load(f)
                        manifest_actions = manifest.get("actions", {})
                
                # 构建树形结构
                tree = []
                category_map = {}
                
                # 合并数据：以catalog为主，manifest为辅（用于文件路径）
                all_action_ids = set(catalog_actions.keys()) | set(manifest_actions.keys())
                
                for action_id in all_action_ids:
                    catalog_data = catalog_actions.get(action_id, {})
                    manifest_data = manifest_actions.get(action_id, {})
                    
                    # 优先使用catalog的分类，其次用manifest的
                    category = catalog_data.get("category") or manifest_data.get("category", "未分类")
                    if isinstance(category, list):
                        category = "/".join(category)
                    
                    parts = category.split("/")
                    
                    # 逐级构建树
                    current_level = tree
                    current_path = ""
                    
                    for i, part in enumerate(parts):
                        current_path = current_path + "/" + part if current_path else part
                        
                        if current_path not in category_map:
                            node = {
                                "name": part,
                                "icon": "📁",
                                "type": "folder",
                                "children": []
                            }
                            category_map[current_path] = node
                            current_level.append(node)
                        
                        current_level = category_map[current_path]["children"]
                    
                    # 添加动作到叶子节点
                    leaf_node = category_map.get(category)
                    if leaf_node:
                        # 获取文件路径（优先从manifest的variants，其次从catalog的file字段）
                        file_path = None
                        if manifest_data.get("variants"):
                            file_path = manifest_data["variants"][0]["file_path"]
                        else:
                            file_path = catalog_data.get("file", "")
                        
                        leaf_node["children"].append({
                            "name": catalog_data.get("name", action_id),
                            "path": file_path,
                            "file_path": file_path,
                            "action_name": catalog_data.get("name", action_id),
                            "id": action_id,
                            "triggers": catalog_data.get("triggers", []),
                            "description": catalog_data.get("description", ""),
                            "skeleton_type": catalog_data.get("skeleton_type", "humanoid"),
                            "_draft": catalog_data.get("_draft", False),
                            "enabled": catalog_data.get("enabled", True),
                            "emotion": catalog_data.get("emotion", "neutral"),
                            "icon": "🎞️",
                            "type": "action"
                        })
                
                return web.json_response({"tree": tree})
            
            except Exception as e:
                logger.error(f"Actions tree error: {e}")
                return web.json_response({"tree": [], "error": str(e)}, status=500)
        
        async def api_plan_actions(request):
            """
            AI动作规划接口（支持编辑器取货预览）
            POST /api/actions/plan
            Body:
              reply_text      : NPC回复文本（必填）
              dialogue_id     : 对话ID（可选，默认生成）
              emotion         : 情绪（默认 neutral）
              audio_duration  : 音频时长秒（可选）
              intent_override : 强制意图类型（可选，如 product_present）
              needs_fetch     : 是否需要取货（bool，可选）
              sku_id          : 指定商品ID（可选）
              shelf_id        : 指定货架ID（可选）
              shelf_position  : 货架3D坐标 {x,y,z}（可选，优先级高于自动查找）
            """
            try:
                data = await request.json()

                reply_text     = data.get("reply_text") or data.get("dialogue", "")
                dialogue_id    = data.get("dialogue_id") or f"preview_{int(__import__('time').time()*1000)}"
                emotion        = data.get("emotion", "neutral")
                audio_duration = data.get("audio_duration")
                intent_override= data.get("intent_override")
                needs_fetch    = data.get("needs_fetch", False)
                sku_id         = data.get("sku_id")
                shelf_id       = data.get("shelf_id")
                shelf_pos      = data.get("shelf_position")  # {x,y,z} 直接由前端提供

                # 获取 AIActionPlanner 实例（来自 director）
                planner = getattr(director, "action_planner", None)
                if planner is None:
                    # 兜底：构造临时实例
                    from modules.ai_action_planner import AIActionPlanner
                    planner = AIActionPlanner(ai, cfg)

                # 若前端提供了货架位置，临时注入到 scene_context
                if shelf_pos and shelf_id:
                    # 注入到场景缓存的 objects 中（不写磁盘，只影响本次规划）
                    ctx = planner.scene_context
                    ctx.invalidate()
                    scene = ctx._get_scene()
                    # 检查是否已存在
                    existing = next((o for o in scene.get("objects", []) if o.get("id") == shelf_id), None)
                    if existing:
                        existing["position"] = shelf_pos
                        if sku_id:
                            existing["sku_id"] = sku_id
                    else:
                        scene.setdefault("objects", []).append({
                            "id": shelf_id,
                            "type": "shelf",
                            "label": shelf_id,
                            "position": shelf_pos,
                            "sku_id": sku_id or "",
                        })

                # 构造 ParsedIntent 覆盖（intent_override 模式）
                if intent_override:
                    from modules.ai_action_planner import ParsedIntent, ActionPlan
                    import uuid
                    parsed = ParsedIntent(
                        intent_type=intent_override,
                        target_products=[sku_id] if sku_id else [],
                        needs_fetch=needs_fetch,
                        needs_present=True,
                        emotion=emotion,
                    )
                    skus = [sku_id] if sku_id else []
                    actions = planner._plan_actions_for_intent(parsed, skus, audio_duration)
                    sync_pts = planner._calculate_sync_points(actions, reply_text, audio_duration)
                    plan = ActionPlan(
                        id=str(uuid.uuid4())[:8],
                        dialogue_id=dialogue_id,
                        trigger_type=intent_override,
                        trigger_sku_id=sku_id,
                        trigger_emotion=emotion,
                        actions=actions,
                        sync_points=sync_pts,
                        estimated_duration=sum(a.duration for a in actions),
                        priority=2,
                        status="pending",
                    )
                else:
                    import asyncio
                    plan = asyncio.get_event_loop().run_until_complete(
                        planner.plan_for_dialogue(dialogue_id, reply_text, emotion, audio_duration)
                    ) if not __import__("asyncio").get_event_loop().is_running() else None
                    # 在异步上下文中直接 await
                    if plan is None:
                        plan = await planner.plan_for_dialogue(dialogue_id, reply_text, emotion, audio_duration)

                # 序列化
                import dataclasses
                plan_dict = dataclasses.asdict(plan)
                return web.json_response(plan_dict)

            except Exception as e:
                logger.error(f"Action planning error: {e}", exc_info=True)
                return web.json_response({"status": "error", "error": str(e)}, status=500)
        
        async def api_upload_action(request):
            """上传动作文件到指定分类目录"""
            try:
                reader = await request.multipart()
                
                file_field = await reader.next()
                if not file_field or file_field.name != 'file':
                    return web.json_response({"status": "error", "error": "No file field"}, status=400)
                
                # 获取表单数据
                category = request.query.get('category', '未分类')
                subcategory = request.query.get('subcategory', '')
                action_name = request.query.get('action_name', '新动作')
                variant_name = request.query.get('variant', '版本01_标准')
                
                # 安全检查：防止路径遍历
                import re
                safe_pattern = re.compile(r'^[\u4e00-\u9fa5a-zA-Z0-9_\-/]+$')
                if not safe_pattern.match(category):
                    return web.json_response({"status": "error", "error": "Invalid category"}, status=400)
                
                # 构建目标路径
                action_root = ROOT_DIR / "assets" / "动作库"
                if subcategory:
                    target_dir = action_root / category / subcategory / action_name
                else:
                    target_dir = action_root / category / action_name
                
                target_dir.mkdir(parents=True, exist_ok=True)
                
                # 文件名处理
                if not variant_name.endswith('.glb'):
                    variant_name += '.glb'
                
                target_path = target_dir / variant_name
                
                # 写入文件
                size = 0
                with open(target_path, 'wb') as f:
                    while True:
                        chunk = await file_field.read_chunk()
                        if not chunk:
                            break
                        size += len(chunk)
                        f.write(chunk)
                
                # 重新扫描动作库
                from modules.system_initializer import quick_rescan
                scan_result = quick_rescan()
                
                logger.info(f"[Upload] Saved {size} bytes to {target_path.relative_to(ROOT_DIR)}")
                
                return web.json_response({
                    "status": "ok",
                    "file": str(target_path.relative_to(ROOT_DIR)),
                    "size": size,
                    "scan_result": scan_result
                })
            except Exception as e:
                logger.error(f"Upload error: {e}")
                return web.json_response({"status": "error", "error": str(e)}, status=500)
        
        async def api_delete_action(request):
            """删除动作文件"""
            try:
                data = await request.json()
                file_path = data.get('file_path', '')
                
                if not file_path or '..' in file_path:
                    return web.json_response({"status": "error", "error": "Invalid path"}, status=400)
                
                target_path = ROOT_DIR / "assets" / "动作库" / file_path
                
                # 安全检查：确保在动作库目录内
                try:
                    target_path.relative_to(ROOT_DIR / "assets" / "动作库")
                except ValueError:
                    return web.json_response({"status": "error", "error": "Path outside action library"}, status=400)
                
                if target_path.exists():
                    target_path.unlink()
                    
                    # 重新扫描
                    from modules.system_initializer import quick_rescan
                    scan_result = quick_rescan()
                    
                    return web.json_response({
                        "status": "ok",
                        "deleted": file_path,
                        "scan_result": scan_result
                    })
                else:
                    return web.json_response({"status": "error", "error": "File not found"}, status=404)
            except Exception as e:
                logger.error(f"Delete error: {e}")
                return web.json_response({"status": "error", "error": str(e)}, status=500)
        
        # ========== 动作提取 API (MediaPipe) ==========
        async def api_motion_extract(request):
            """
            从视频提取骨骼动画
            POST /api/motion/extract
            
            Request:
                - video: multipart文件上传
                - skeleton_type: humanoid/quadruped/avian (默认humanoid)
                - engine: mediapipe / mocap_anything / auto (默认auto)
            
            Response:
                {
                    "ok": True/False,
                    "glb_path": 输出GLB路径,
                    "duration": 动画时长,
                    "frames": 帧数,
                    "preview": 关键点预览数据,
                    "error": 错误信息
                }
            """
            try:
                import tempfile
                from modules.motion_extractor import extract_motion, init_motion_extractor
                
                reader = await request.multipart()
                video_field = await reader.next()
                
                if not video_field or video_field.name != 'video':
                    return web.json_response({"ok": False, "error": "缺少video字段"}, status=400)
                
                # 读取视频数据
                video_data = await video_field.read()
                
                # 保存临时文件
                with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as f:
                    f.write(video_data)
                    temp_path = Path(f.name)
                
                # 获取参数
                skeleton_type = request.query.get('skeleton_type', 'humanoid')
                engine = request.query.get('engine', 'auto')
                
                # 确保提取器已初始化
                output_dir = ROOT_DIR / "cache" / "motion_extract"
                init_motion_extractor(output_dir)
                
                # 执行提取
                result = await extract_motion(temp_path, skeleton_type, engine=engine)
                
                # 清理临时文件
                temp_path.unlink(missing_ok=True)
                
                return web.json_response(result)
                
            except Exception as e:
                logger.error(f"Motion extract error: {e}")
                return web.json_response({"ok": False, "error": str(e)}, status=500)
        
        async def api_motion_engines(request):
            """
            获取可用的动作提取引擎状态
            GET /api/motion/engines
            """
            try:
                from modules.mocap_anything_client import get_mocap_client
                
                mocap = get_mocap_client()
                mocap_available = await mocap.check_available()
                mocap_health = await mocap.get_health() if mocap_available else {}
                mocap_mode = mocap_health.get("mode", "placeholder")  # "ready" | "placeholder"

                # MediaPipe 可用性检测
                mediapipe_available = False
                try:
                    import mediapipe
                    mediapipe_available = True
                except ImportError:
                    pass

                v2_ready = mocap_available and mocap_mode == "ready"

                # 4D-Humans (HMR2) 可用性检测
                import os as _os
                _home = _os.environ.get("USERPROFILE") or _os.environ.get("HOME", "")
                _ckpt = Path(_home) / ".cache" / "4DHumans" / "logs" / "train" / "multiruns" / "hmr2" / "0" / "checkpoints" / "epoch=35-step=1000000.ckpt"
                _fourd_repo = Path(__file__).parent.parent / "tools" / "4D-Humans"
                _fourd_script = Path(__file__).parent.parent / "tools" / "hmr2_to_canonical.py"
                fourd_available = _fourd_repo.exists() and _fourd_script.exists() and _ckpt.exists()
                fourd_error = "" if fourd_available else (
                    "权重未下载" if (_fourd_repo.exists() and _fourd_script.exists()) else
                    "仓库未找到 (tools/4D-Humans/)"
                )

                return web.json_response({
                    "ok": True,
                    "engines": [
                        {
                            "id": "4dhumans",
                            "name": "4D-Humans HMR2 (推荐)",
                            "available": fourd_available,
                            "description": "HMR 2.0 逐帧 SMPL 提取，转为标准骨骼动画 JSON，人体效果最佳",
                            "managed": False,
                            "error_hint": fourd_error,
                            "ckpt_path": str(_ckpt),
                            "repo_exists": _fourd_repo.exists(),
                        },
                        {
                            "id": "mocap_anything_v2",
                            "name": "MoCapAnything V2 (4D推理)",
                            "available": mocap_available,
                            "mode": mocap_mode,
                            "description": "TripoSG temporal + video2pose2rot 端到端，支持任意物种骨骼",
                            "managed": True,
                            "started_by_us": mocap_service_process["proc"] is not None,
                            "repo_status": mocap_health.get("repo_status", ""),
                        },
                        {
                            "id": "mocap_anything",
                            "name": "MoCapAnything V1 (占位)",
                            "available": mocap_available,
                            "mode": mocap_mode,
                            "description": "占位模式：生成挥手测试动画，验证链路用",
                            "managed": True,
                            "started_by_us": mocap_service_process["proc"] is not None,
                        },
                        {
                            "id": "mediapipe",
                            "name": "MediaPipe (CPU本地)",
                            "available": mediapipe_available,
                            "description": "33个关键点，本地实时推理，开箱即用",
                            "managed": False,
                        },
                        {
                            "id": "motionbert",
                            "name": "MotionBERT (2D→3D提升)",
                            "available": mediapipe_available,
                            "has_weights": (Path(__file__).parent.parent / "tools" / "motionbert_repo" / "checkpoint" / "pose3d" / "FT_MB_lite_MB_ft_h36m_global_lite" / "best_epoch.bin").exists(),
                            "description": "MediaPipe 2D 检测 + MotionBERT 3D 提升",
                            "managed": False,
                        },
                    ],
                    "recommended": "4dhumans" if fourd_available else ("mocap_anything_v2" if v2_ready else ("mocap_anything" if mocap_available else ("motionbert" if mediapipe_available else None))),
                })
            except Exception as e:
                logger.error(f"Motion engines error: {e}")
                return web.json_response({"ok": False, "error": str(e)}, status=500)
        
        def _kill_process_on_port(port: int):
            """杀掉占用指定端口的进程"""
            try:
                if os.name == 'nt':
                    import subprocess
                    # 查找占用端口的 PID
                    result = subprocess.run(
                        ['netstat', '-ano'],
                        capture_output=True, text=True, check=True
                    )
                    for line in result.stdout.splitlines():
                        if f':{port}' in line and 'LISTENING' in line:
                            parts = line.strip().split()
                            if len(parts) >= 5:
                                pid = parts[-1]
                                try:
                                    subprocess.run(['taskkill', '/F', '/PID', pid], check=False, capture_output=True)
                                    logger.info(f"已杀掉占用端口 {port} 的进程 PID={pid}")
                                except Exception:
                                    pass
                                    break
                else:
                    subprocess.run(f"lsof -ti:{port} | xargs kill -9", shell=True, check=False, capture_output=True)
            except Exception:
                pass

        async def api_motion_engine_start(request):
            """
            启动 MoCapAnything 推理服务
            POST /api/motion/engines/start
            """
            try:
                # 先清理可能残留的端口占用
                _kill_process_on_port(8767)
                await asyncio.sleep(0.5)
                
                # 检查是否已有外部或本进程启动的服务在运行
                from modules.mocap_anything_client import get_mocap_client
                mocap = get_mocap_client()
                if await mocap.check_available(force=True):
                    pid = mocap_service_process.get("pid")
                    return web.json_response({
                        "ok": True,
                        "message": "推理服务已在运行中",
                        "pid": pid,
                        "started_by_us": pid is not None,
                    })
                
                # 清理之前退出的进程记录
                if mocap_service_process["proc"] is not None:
                    old = mocap_service_process["proc"]
                    if old.poll() is not None:
                        mocap_service_process["proc"] = None
                        mocap_service_process["pid"] = None
                
                # 启动服务
                service_path = ROOT_DIR / "tools" / "mocap_anything_service" / "service.py"
                if not service_path.exists():
                    return web.json_response({
                        "ok": False,
                        "error": f"推理服务入口不存在: {service_path}\n请先克隆 MoCapAnything 代码并配置模型。",
                    }, status=500)
                
                # 检查依赖
                try:
                    import fastapi
                    import uvicorn
                except ImportError as ie:
                    return web.json_response({
                        "ok": False,
                        "error": f"缺少推理服务依赖: {ie.name}\n请在虚拟环境中执行: pip install fastapi uvicorn python-multipart aiofiles pydantic",
                    }, status=500)
                
                # Windows 下避免弹出控制台窗口；stdout/stderr 用 DEVNULL 防止 PIPE 死锁
                creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                proc = subprocess.Popen(
                    [sys.executable, str(service_path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    cwd=str(ROOT_DIR / "tools" / "mocap_anything_service"),
                    creationflags=creationflags,
                )
                mocap_service_process["proc"] = proc
                mocap_service_process["pid"] = proc.pid
                logger.info(f"MoCapAnything 推理服务已启动，PID={proc.pid}")
                
                # 等待 1 秒后检查进程是否已崩溃
                await asyncio.sleep(1)
                if proc.poll() is not None:
                    # 进程已退出，读取 stderr
                    stderr_data = b""
                    try:
                        _, stderr_data = proc.communicate(timeout=2)
                    except Exception:
                        pass
                    err_text = stderr_data.decode('utf-8', errors='ignore')[-800:] if stderr_data else "未知错误"
                    mocap_service_process["proc"] = None
                    mocap_service_process["pid"] = None
                    logger.error(f"推理服务启动后立即退出:\n{err_text}")
                    return web.json_response({
                        "ok": False,
                        "error": f"推理服务启动失败（进程已退出）:\n{err_text}",
                        "tip": "请检查 service.py 依赖是否安装完整，或在终端手动运行: python tools/mocap_anything_service/service.py",
                    }, status=500)
                
                # 重试 health 检测（最长等待 15 秒）
                for i in range(6):
                    await asyncio.sleep(2.5)
                    if await mocap.check_available(force=True):
                        return web.json_response({
                            "ok": True,
                            "message": "推理服务启动成功",
                            "pid": proc.pid,
                            "started_by_us": True,
                        })
                    # 再次检查进程是否还在
                    if proc.poll() is not None:
                        stderr_data = b""
                        try:
                            _, stderr_data = proc.communicate(timeout=2)
                        except Exception:
                            pass
                        err_text = stderr_data.decode('utf-8', errors='ignore')[-800:] if stderr_data else "未知错误"
                        mocap_service_process["proc"] = None
                        mocap_service_process["pid"] = None
                        return web.json_response({
                            "ok": False,
                            "error": f"推理服务运行中崩溃:\n{err_text}",
                        }, status=500)
                
                # 15 秒后仍无法连接，可能初始化较慢
                return web.json_response({
                    "ok": True,
                    "message": "推理服务进程已启动，正在初始化（约需10-30秒加载模型）...",
                    "pid": proc.pid,
                    "started_by_us": True,
                    "initializing": True,
                })
                
            except Exception as e:
                logger.error(f"启动推理服务失败: {e}", exc_info=True)
                return web.json_response({"ok": False, "error": str(e)}, status=500)
        
        async def api_motion_engine_stop(request):
            """
            停止由本进程启动的 MoCapAnything 推理服务
            POST /api/motion/engines/stop
            """
            try:
                if mocap_service_process["proc"] is None:
                    return web.json_response({
                        "ok": True,
                        "message": "没有由本进程管理的推理服务在运行",
                    })
                
                proc = mocap_service_process["proc"]
                pid = mocap_service_process["pid"]
                
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                
                mocap_service_process["proc"] = None
                mocap_service_process["pid"] = None
                logger.info(f"MoCapAnything 推理服务已停止 (PID={pid})")
                
                return web.json_response({
                    "ok": True,
                    "message": "推理服务已停止",
                    "pid": pid,
                })
            except Exception as e:
                logger.error(f"停止推理服务失败: {e}", exc_info=True)
                return web.json_response({"ok": False, "error": str(e)}, status=500)
        
        async def api_motion_skeletons(request):
            """获取支持的骨骼类型列表"""
            try:
                from modules.motion_extractor import motion_extractor, init_motion_extractor
                
                if motion_extractor is None:
                    output_dir = ROOT_DIR / "cache" / "motion_extract"
                    init_motion_extractor(output_dir)
                
                skeletons = motion_extractor.get_supported_skeletons()
                return web.json_response({"ok": True, "skeletons": skeletons})
                
            except Exception as e:
                logger.error(f"Get skeletons error: {e}")
                return web.json_response({"ok": False, "error": str(e)}, status=500)
        
        app.router.add_post("/api/motion/extract", api_motion_extract)
        app.router.add_get("/api/motion/engines", api_motion_engines)
        app.router.add_post("/api/motion/engines/start", api_motion_engine_start)
        app.router.add_post("/api/motion/engines/stop", api_motion_engine_stop)
        app.router.add_get("/api/motion/skeletons", api_motion_skeletons)
        
        # ========== 动作自动打标签 API (DeepSeek Vision) ==========
        async def api_motion_autotag(request):
            """
            自动分析动作文件，生成description和triggers
            POST /api/motion/autotag
            
            Request:
                - file_path: 动作文件路径（相对于assets/动作库）
                - action_id: 动作ID（可选，用于缓存）
            
            Response:
                {
                    "ok": True/False,
                    "description": "动作描述",
                    "triggers": ["触发词1", "触发词2", ...],
                    "emotion": "happy/sad/neutral",
                    "skeleton_type": "humanoid",
                    "error": 错误信息
                }
            """
            try:
                from tools.autotag_actions import load_catalog, call_llm_vision, find_preview_images
                
                data = await request.json()
                file_path = data.get('file_path', '')
                action_id = data.get('action_id', '')
                # 前端可直接传入extract_motion生成的截图路径列表
                preview_frames_raw = data.get('preview_frames', [])

                if not file_path:
                    return web.json_response({"ok": False, "error": "缺少file_path参数"}, status=400)

                resolved_id = action_id or Path(file_path).stem

                # 构建action_entry结构
                action_entry = {
                    "id": resolved_id,
                    "file": file_path,
                    "skeleton_type": data.get('skeleton_type', 'humanoid')
                }

                # 优先用前端传来的截图路径（真实视频帧），其次自动查找cache
                if preview_frames_raw:
                    image_paths = [Path(p) for p in preview_frames_raw if Path(p).exists()]
                else:
                    image_paths = find_preview_images(resolved_id)

                logger.info(f"Autotag [{resolved_id}]: {len(image_paths)} preview frames, "
                            f"{'Vision模式' if image_paths else '纯文本模式'}")

                # 初始化LLM管理器
                from modules.llm_manager import get_llm_manager, init_llm_manager
                await init_llm_manager()

                manager = get_llm_manager()
                adapter = manager.get_active_adapter()

                if not adapter:
                    return web.json_response({
                        "ok": False,
                        "error": "没有可用的LLM配置，请先访问 /llm-config.html 配置大模型API"
                    }, status=500)

                # 调用LLM Vision分析（有截图走多模态，无截图走纯文本）
                from tools.autotag_actions import call_llm_vision
                result = await call_llm_vision(action_entry, image_paths)

                if result:
                    mode = "vision" if image_paths else "text"
                    return web.json_response({
                        "ok": True,
                        "description": result.get("description", ""),
                        "triggers": result.get("triggers", []),
                        "emotion": result.get("emotion", "neutral"),
                        "skeleton_type": result.get("skeleton_type", "humanoid"),
                        "suggested_category": result.get("suggested_category", ""),
                        "source": f"{adapter.config.provider.value}_{mode}",
                        "used_frames": len(image_paths)
                    })
                else:
                    return web.json_response({
                        "ok": False,
                        "error": "分析失败，请检查大模型API配置"
                    }, status=500)
                
            except Exception as e:
                logger.error(f"Motion autotag error: {e}", exc_info=True)
                return web.json_response({"ok": False, "error": str(e)}, status=500)
        
        async def api_motion_drafts(request):
            """
            获取待打标签的动作列表（draft条目）
            GET /api/motion/drafts
            """
            try:
                from tools.autotag_actions import load_catalog
                
                catalog = load_catalog()
                drafts = []
                
                for action in catalog.get("actions", []):
                    # 判断是否是草稿：_draft标记 或 triggers为空
                    is_draft = action.get("_draft", False)
                    has_empty_triggers = not action.get("triggers") or len(action.get("triggers", [])) == 0
                    
                    if is_draft or has_empty_triggers:
                        drafts.append({
                            "id": action.get("id"),
                            "name": action.get("name", action.get("id")),
                            "file": action.get("file", ""),
                            "skeleton_type": action.get("skeleton_type", "humanoid"),
                            "is_draft": is_draft,
                            "triggers_count": len(action.get("triggers", []))
                        })
                
                return web.json_response({
                    "ok": True,
                    "drafts": drafts,
                    "count": len(drafts)
                })
                
            except Exception as e:
                logger.error(f"Get drafts error: {e}")
                return web.json_response({"ok": False, "error": str(e)}, status=500)
        
        async def api_motion_commit(request):
            """
            将草稿/已提取动作确认入库（更新catalog）
            POST /api/motion/commit
            
            Request:
                - id: 动作ID
                - file: 文件路径（相对动作库根）
                - name: 动作名称
                - description: 动作描述
                - triggers: 触发词列表
                - skeleton_type: 骨骼类型
                - emotion: 情绪（可选）
            """
            try:
                from tools.autotag_actions import load_catalog
                
                data = await request.json()
                action_id = data.get("id")
                if not action_id:
                    return web.json_response({"ok": False, "error": "缺少id参数"}, status=400)
                
                # 验证ID格式（防止注入），允许路径分隔符、点号和空格
                if not re.match(r'^[a-zA-Z0-9_\-\u4e00-\u9fa5/\. ]+$', action_id):
                    return web.json_response({"ok": False, "error": "id包含非法字符"}, status=400)
                
                catalog_path = ROOT_DIR / "config" / "action_catalog.json"
                catalog = load_catalog()
                actions = catalog.setdefault("actions", [])
                
                # 查找已有条目或新建
                existing = next((a for a in actions if a.get("id") == action_id), None)
                
                entry = existing or {"id": action_id}
                entry.update({
                    "name": data.get("name", action_id),
                    "file": data.get("file", entry.get("file", "")),
                    "description": data.get("description", ""),
                    "triggers": data.get("triggers", []),
                    "category": data.get("category", entry.get("category", "未分类")),
                    "skeleton_type": data.get("skeleton_type", entry.get("skeleton_type", "humanoid")),
                    "emotion": data.get("emotion", entry.get("emotion", "neutral")),
                    "enabled": data.get("enabled", entry.get("enabled", True)),
                    "_draft": data.get("_draft", entry.get("_draft", False)),
                    "committed_at": datetime.datetime.utcnow().isoformat() + "Z",
                })
                
                if not existing:
                    actions.append(entry)
                
                # 写回catalog
                with open(catalog_path, 'w', encoding='utf-8') as f:
                    json.dump(catalog, f, ensure_ascii=False, indent=2)
                
                logger.info(f"[Motion] Committed action: {action_id}")
                return web.json_response({"ok": True, "action": entry})
                
            except Exception as e:
                logger.error(f"Motion commit error: {e}", exc_info=True)
                return web.json_response({"ok": False, "error": str(e)}, status=500)
        
        async def api_motion_draft_detail(request):
            """获取单个草稿详情 GET /api/motion/draft/{id}"""
            try:
                from tools.autotag_actions import load_catalog
                action_id = request.match_info.get("id", "")
                catalog = load_catalog()
                action = next((a for a in catalog.get("actions", []) if a.get("id") == action_id), None)
                if not action:
                    return web.json_response({"ok": False, "error": "动作不存在"}, status=404)
                return web.json_response({"ok": True, "action": action})
            except Exception as e:
                return web.json_response({"ok": False, "error": str(e)}, status=500)
        
        async def api_triggers_suggest(request):
            """
            AI扩充触发词
            POST /api/catalog/triggers/suggest

            Request:
                - action_name     : 动作名称（如"折扇挑逗"）
                - action_id       : 动作ID（可选）
                - category        : 分类路径（如"情绪表达/挑逗"）
                - existing_triggers: 已有触发词列表（AI以此为基础扩充）
                - count           : 期望生成数量（默认12）

            Response:
                {
                    "ok": True,
                    "suggestions": ["触发词1", "触发词2", ...]
                }
            """
            try:
                data = await request.json()
                action_name      = data.get("action_name", "")
                action_id        = data.get("action_id", "")
                category         = data.get("category", "")
                existing         = data.get("existing_triggers", [])
                count            = min(int(data.get("count", 12)), 20)

                if not action_name and not action_id:
                    return web.json_response({"ok": False, "error": "缺少action_name"}, status=400)

                from modules.llm_manager import get_llm_manager, init_llm_manager
                await init_llm_manager()
                manager = get_llm_manager()
                adapter = manager.get_active_adapter()

                if not adapter:
                    return web.json_response({
                        "ok": False,
                        "error": "没有可用的LLM配置，请先访问 /llm-config.html 配置大模型API"
                    }, status=500)

                existing_str = "、".join(existing) if existing else "（暂无）"
                prompt = f"""你是一个NPC动作库管理专家。
现在需要为一个NPC动作补充"向量搜索触发词"，触发词的作用是：
当AI生成的NPC台词语义与触发词相近时，自动触发播放该动作。

动作信息：
- 动作名称：{action_name or action_id}
- 所属分类：{category or "未知"}
- 已有触发词：{existing_str}

请生成 {count} 个高质量触发词，要求：
1. 每个触发词是2-8个字的短语，描述"NPC在什么情境/情绪下会做出这个动作"
2. 覆盖多个角度：情绪状态、场景描述、动作效果、观众感受等
3. 不要重复已有触发词
4. 不要写动作的技术描述（如"举起右手"），要写场景语境（如"热情迎接观众"）
5. 使用口语化、直播间常见的表达方式

只输出JSON数组，不要任何解释，格式：
["触发词1", "触发词2", "触发词3", ...]"""

                result = await adapter.complete(prompt, max_tokens=400, temperature=0.8)
                text = (result or "").strip()

                # 提取JSON数组
                import re as _re
                arr_match = _re.search(r'\[.*?\]', text, _re.DOTALL)
                suggestions = []
                if arr_match:
                    try:
                        raw = json.loads(arr_match.group(0))
                        suggestions = [s.strip() for s in raw if isinstance(s, str) and s.strip()]
                    except Exception:
                        pass

                if not suggestions:
                    # 兜底：按行切割
                    for line in text.splitlines():
                        line = line.strip().strip('",，[]').strip()
                        if 2 <= len(line) <= 16:
                            suggestions.append(line)

                # 去重并限制数量
                seen = set(existing)
                unique = []
                for s in suggestions:
                    if s not in seen:
                        seen.add(s)
                        unique.append(s)
                    if len(unique) >= count:
                        break

                logger.info(f"[TriggerSuggest] {action_name}: {len(unique)} suggestions generated")
                return web.json_response({"ok": True, "suggestions": unique})

            except Exception as e:
                logger.error(f"Trigger suggest error: {e}", exc_info=True)
                return web.json_response({"ok": False, "error": str(e)}, status=500)

        # ========== Catalog 管理 API ==========

        async def api_catalog_actions_flat(request):
            """
            返回所有动作（含 triggers）的平铺列表，供素材管理页触发词Tab使用
            GET /api/catalog/actions?format=flat
            """
            try:
                catalog_path = ROOT_DIR / "config" / "action_catalog.json"
                if not catalog_path.exists():
                    return web.json_response({"ok": True, "actions": []})
                with open(catalog_path, "r", encoding="utf-8") as f:
                    catalog = json.load(f)
                actions = catalog.get("actions", [])
                # 只返回 format=flat 时的精简字段
                fmt = request.query.get("format", "")
                if fmt == "flat":
                    actions = [
                        {
                            "id": a.get("id", ""),
                            "display_name": a.get("name", a.get("id", "")),
                            "category": a.get("category", "未分类"),
                            "action_type": a.get("action_type", "animation"),
                            "skeleton_type": a.get("skeleton_type", "humanoid"),
                            "emotion": a.get("emotion", "neutral"),
                            "triggers": a.get("triggers", []),
                            "enabled": a.get("enabled", True),
                            "_draft": a.get("_draft", False),
                        }
                        for a in actions
                    ]
                return web.json_response({"ok": True, "actions": actions})
            except Exception as e:
                logger.error(f"Catalog actions error: {e}")
                return web.json_response({"ok": False, "error": str(e)}, status=500)

        async def api_catalog_triggers_batch(request):
            """
            批量保存触发词，并重建向量索引
            POST /api/catalog/triggers/batch
            Body: { "updates": [{"id": "action_id", "triggers": ["词1", "词2"]}, ...] }
            """
            try:
                data = await request.json()
                updates = data.get("updates", [])
                if not updates:
                    return web.json_response({"ok": False, "error": "updates 不能为空"}, status=400)

                catalog_path = ROOT_DIR / "config" / "action_catalog.json"
                if not catalog_path.exists():
                    return web.json_response({"ok": False, "error": "action_catalog.json 不存在"}, status=404)

                with open(catalog_path, "r", encoding="utf-8") as f:
                    catalog = json.load(f)

                actions = catalog.get("actions", [])
                update_map = {u["id"]: u["triggers"] for u in updates if "id" in u}
                updated_count = 0
                for action in actions:
                    aid = action.get("id", "")
                    if aid in update_map:
                        action["triggers"] = update_map[aid]
                        updated_count += 1

                with open(catalog_path, "w", encoding="utf-8") as f:
                    json.dump(catalog, f, ensure_ascii=False, indent=2)

                # 重建向量索引（如果ActionRetriever已初始化）
                rebuilt = False
                try:
                    from modules.action_retriever import ActionRetriever
                    retriever = ActionRetriever(catalog_path)
                    retriever.build_index()
                    rebuilt = True
                    logger.info(f"[Catalog] 向量索引已重建，更新了 {updated_count} 个动作的触发词")
                except Exception as e_idx:
                    logger.warning(f"[Catalog] 向量索引重建失败（非致命）: {e_idx}")

                return web.json_response({
                    "ok": True,
                    "updated": updated_count,
                    "index_rebuilt": rebuilt,
                    "message": f"已保存 {updated_count} 个动作的触发词" + ("，向量索引已重建" if rebuilt else "，索引重建跳过")
                })
            except Exception as e:
                logger.error(f"Catalog triggers batch error: {e}", exc_info=True)
                return web.json_response({"ok": False, "error": str(e)}, status=500)

        async def api_catalog_expressions_get(request):
            """
            获取表情库配置
            GET /api/catalog/expressions
            """
            try:
                expr_path = ROOT_DIR / "config" / "expression_catalog.json"
                if not expr_path.exists():
                    return web.json_response({"ok": True, "expression_sets": {}})
                with open(expr_path, "r", encoding="utf-8") as f:
                    catalog = json.load(f)
                return web.json_response({
                    "ok": True,
                    "expression_sets": catalog.get("expression_sets", {}),
                    "version": catalog.get("version", "1.0"),
                })
            except Exception as e:
                logger.error(f"Get expressions error: {e}")
                return web.json_response({"ok": False, "error": str(e)}, status=500)

        async def api_catalog_expressions_save(request):
            """
            新增或更新单个表情条目
            POST /api/catalog/expressions
            Body: {
                id, display_name, emotion_tag, form,
                implementation, morph_weights, animation_file,
                sounds, intensity_threshold, transition_duration_s
            }
            form 字段用于决定写入哪个 expression_set
            """
            try:
                data = await request.json()
                expr_id = data.get("id", "").strip()
                if not expr_id:
                    return web.json_response({"ok": False, "error": "缺少 id"}, status=400)
                if not re.match(r'^[a-zA-Z0-9_\-\u4e00-\u9fa5]+$', expr_id):
                    return web.json_response({"ok": False, "error": "id 包含非法字符"}, status=400)

                expr_path = ROOT_DIR / "config" / "expression_catalog.json"
                catalog = {}
                if expr_path.exists():
                    with open(expr_path, "r", encoding="utf-8") as f:
                        catalog = json.load(f)

                # 根据 form 字段映射到对应 expression_set
                form = data.get("form", "human")
                form_to_set = {
                    "human":       "human_npc_base",
                    "fox_partial": "fox_partial_expressions",
                    "fox_full":    "fox_full_expressions",
                    "robot":       "robot_display_expressions",
                }
                set_id = form_to_set.get(form, "human_npc_base")
                sets = catalog.setdefault("expression_sets", {})
                target_set = sets.setdefault(set_id, {
                    "display_name": set_id,
                    "applies_to_skeleton": "humanoid",
                    "applies_to_forms": [form],
                    "expressions": []
                })
                exprs = target_set.setdefault("expressions", [])

                # 构建表情条目
                entry = {
                    "id": expr_id,
                    "emotion_tag": data.get("emotion_tag", "neutral"),
                    "display_name": data.get("display_name", expr_id),
                    "implementation": data.get("implementation", "morph"),
                    "morph_weights": data.get("morph_weights", {}),
                    "transition_duration_s": float(data.get("transition_duration_s", 0.3)),
                    "intensity_threshold": float(data.get("intensity_threshold", 0.3)),
                    "sounds": data.get("sounds", {"on_enter": None}),
                }
                if data.get("animation_file"):
                    entry["animation_file"] = data["animation_file"]

                # 查找已有条目或新增
                existing_idx = next((i for i, e in enumerate(exprs) if e.get("id") == expr_id), None)
                if existing_idx is not None:
                    exprs[existing_idx] = entry
                else:
                    exprs.append(entry)

                with open(expr_path, "w", encoding="utf-8") as f:
                    json.dump(catalog, f, ensure_ascii=False, indent=2)

                logger.info(f"[Catalog] Expression saved: {expr_id} in set {set_id}")
                return web.json_response({"ok": True, "id": expr_id, "set_id": set_id})
            except Exception as e:
                logger.error(f"Save expression error: {e}", exc_info=True)
                return web.json_response({"ok": False, "error": str(e)}, status=500)

        async def api_catalog_effects_get(request):
            """
            获取特效库
            GET /api/catalog/effects
            """
            try:
                fx_path = ROOT_DIR / "config" / "effect_catalog.json"
                if not fx_path.exists():
                    return web.json_response({"ok": True, "effects": []})
                with open(fx_path, "r", encoding="utf-8") as f:
                    catalog = json.load(f)
                effects = catalog.get("effects", [])
                # 过滤掉 _comment 等元字段
                effects = [e for e in effects if isinstance(e, dict) and "id" in e]
                return web.json_response({"ok": True, "effects": effects})
            except Exception as e:
                logger.error(f"Get effects error: {e}")
                return web.json_response({"ok": False, "error": str(e)}, status=500)

        async def api_catalog_props_get(request):
            """
            获取道具库
            GET /api/catalog/props
            """
            try:
                prop_path = ROOT_DIR / "config" / "prop_catalog.json"
                if not prop_path.exists():
                    return web.json_response({"ok": True, "props": []})
                with open(prop_path, "r", encoding="utf-8") as f:
                    catalog = json.load(f)
                props = catalog.get("props", [])
                props = [p for p in props if isinstance(p, dict) and "id" in p]
                return web.json_response({"ok": True, "props": props})
            except Exception as e:
                logger.error(f"Get props error: {e}")
                return web.json_response({"ok": False, "error": str(e)}, status=500)

        # 注册 catalog 路由
        app.router.add_get("/api/catalog/actions", api_catalog_actions_flat)
        app.router.add_post("/api/catalog/triggers/batch", api_catalog_triggers_batch)
        app.router.add_get("/api/catalog/expressions", api_catalog_expressions_get)
        app.router.add_post("/api/catalog/expressions", api_catalog_expressions_save)
        app.router.add_get("/api/catalog/effects", api_catalog_effects_get)
        app.router.add_get("/api/catalog/props", api_catalog_props_get)
        logger.info("Registered /api/catalog/* routes")

        # ========== TTS 缓存管理 API ==========
        async def api_tts_cache_stats(request):
            """
            获取 TTS 缓存统计
            GET /api/cache/tts/stats
            """
            try:
                from modules.cache_manager import get_tts_cache_stats
                stats = get_tts_cache_stats()
                return web.json_response({"ok": True, "stats": stats})
            except Exception as e:
                logger.error(f"TTS cache stats error: {e}")
                return web.json_response({"ok": False, "error": str(e)}, status=500)

        async def api_tts_cache_cleanup(request):
            """
            手动触发 TTS 缓存 LRU 清理
            POST /api/cache/tts/cleanup
            Body: { "max_files": 500, "max_size_mb": 2048 } (可选)
            """
            try:
                from modules.cache_manager import cleanup_tts_cache
                body = await request.json() if request.can_read_body else {}
                max_files = body.get("max_files", 500)
                max_size_mb = body.get("max_size_mb", 2048)
                result = cleanup_tts_cache(max_files=max_files, max_size_mb=max_size_mb)
                return web.json_response({"ok": True, "result": result})
            except Exception as e:
                logger.error(f"TTS cache cleanup error: {e}")
                return web.json_response({"ok": False, "error": str(e)}, status=500)

        app.router.add_get("/api/cache/tts/stats", api_tts_cache_stats)
        app.router.add_post("/api/cache/tts/cleanup", api_tts_cache_cleanup)
        logger.info("Registered /api/cache/tts/* routes")

        # ========== 直播间事件模拟 API ==========
        async def api_live_simulate_event(request):
            """
            模拟直播间事件（弹幕/送礼/进入）
            POST /api/live/simulate_event
            Body: { "event_type": "danmu|gift|enter", "content": "...", "user_id": "..." }
            """
            try:
                body = await request.json()
                event_type = body.get("event_type", "danmu")
                content = body.get("content", "")
                user_id = body.get("user_id", f"sim_{int(time.time())}")

                # 构建标准事件格式
                event = {
                    "type": event_type,
                    "content": content,
                    "user_id": user_id,
                    "timestamp": body.get("timestamp", int(time.time() * 1000)),
                    "is_simulated": True,
                }

                # 添加到直播消息队列（如果 live_room 模块可用）
                try:
                    from modules.live_room import get_message_queue
                    queue = get_message_queue()
                    if queue:
                        queue.put(event)
                        logger.info(f"[Simulate] {event_type}: {content[:30]}...")
                except ImportError:
                    logger.debug("[Simulate] live_room module not available")

                # 广播到 WebSocket 连接
                try:
                    from modules.websocket_handler import broadcast_message
                    await broadcast_message({
                        "type": "live_event",
                        "data": event,
                    })
                except ImportError:
                    pass

                return web.json_response({
                    "ok": True,
                    "event": event,
                    "message": f"模拟{event_type}事件已发送",
                })
            except Exception as e:
                logger.error(f"Simulate event error: {e}")
                return web.json_response({"ok": False, "error": str(e)}, status=500)

        app.router.add_post("/api/live/simulate_event", api_live_simulate_event)
        logger.info("Registered /api/live/simulate_event")

        app.router.add_post("/api/motion/autotag", api_motion_autotag)
        app.router.add_get("/api/motion/drafts", api_motion_drafts)
        app.router.add_post("/api/motion/commit", api_motion_commit)
        app.router.add_get("/api/motion/draft/{id}", api_motion_draft_detail)
        app.router.add_post("/api/catalog/triggers/suggest", api_triggers_suggest)
        
        # 注册v2 API路由
        app.router.add_post("/api/system/initialize", api_system_initialize)
        app.router.add_get("/api/system/health", api_system_health)
        app.router.add_post("/api/system/rescan", api_system_rescan)

        # ========== 系统自愈 API ==========
        async def api_self_healing_status(request):
            """
            获取系统自愈健康状态
            GET /api/self-healing/status
            """
            try:
                from modules.self_healing import get_health_status
                report = get_health_status()
                return web.json_response({"ok": True, "report": report})
            except Exception as e:
                logger.error(f"Self-healing status error: {e}")
                return web.json_response({"ok": False, "error": str(e)}, status=500)

        async def api_self_healing_trigger(request):
            """
            手动触发自愈修复
            POST /api/self-healing/trigger
            Body: { "module": "tts|memory|disk", "dry_run": false }
            """
            try:
                body = await request.json()
                module = body.get("module")
                dry_run = body.get("dry_run", False)

                from modules.self_healing import get_self_healing_manager
                manager = get_self_healing_manager()

                # 执行指定检查
                if module and module in manager._checks:
                    check_fn = manager._checks[module]
                    if asyncio.iscoroutinefunction(check_fn):
                        check = await check_fn()
                    else:
                        check = check_fn()

                    if dry_run or check.status == 'healthy':
                        return web.json_response({
                            "ok": True,
                            "module": module,
                            "status": check.status,
                            "message": check.message,
                            "healed": False,
                        })

                    # 尝试修复
                    if module in manager._healers:
                        heal_fn = manager._healers[module]
                        if asyncio.iscoroutinefunction(heal_fn):
                            success = await heal_fn()
                        else:
                            success = heal_fn()

                        return web.json_response({
                            "ok": True,
                            "module": module,
                            "status": check.status,
                            "message": check.message,
                            "healed": success,
                        })

                # 全部检查
                await manager._run_checks()
                report = manager.get_health_report()
                return web.json_response({"ok": True, "report": report})

            except Exception as e:
                logger.error(f"Self-healing trigger error: {e}")
                return web.json_response({"ok": False, "error": str(e)}, status=500)

        app.router.add_get("/api/self-healing/status", api_self_healing_status)
        app.router.add_post("/api/self-healing/trigger", api_self_healing_trigger)
        logger.info("Registered /api/self-healing/* routes")
        app.router.add_get("/api/actions/tree", api_actions_tree)
        app.router.add_post("/api/actions/plan", api_plan_actions)
        app.router.add_post("/api/actions/upload", api_upload_action)
        app.router.add_post("/api/actions/delete", api_delete_action)
        
        # ========== 实时动捕 API ==========
        async def api_motion_capture_status(request):
            """
            获取动捕服务器状态
            GET /api/motion-capture/status
            """
            try:
                from modules.motion_capture_server import get_motion_capture_server
                server = get_motion_capture_server()
                
                if server:
                    status = server.get_status()
                    return web.json_response({"ok": True, **status})
                else:
                    return web.json_response({
                        "ok": True,
                        "running": False,
                        "message": "动捕服务器未初始化"
                    })
                    
            except Exception as e:
                logger.error(f"Motion capture status error: {e}")
                return web.json_response({"ok": False, "error": str(e)}, status=500)
        
        async def api_motion_capture_config(request):
            """
            获取动捕配置信息
            GET /api/motion-capture/config
            """
            return web.json_response({
                "ok": True,
                "ws_url": f"ws://{request.host.split(':')[0]}:8766",
                "frame_rate": 15,
                "supported_bones": [
                    "hips", "spine", "chest", "neck", "head",
                    "leftShoulder", "leftUpperArm", "leftLowerArm", "leftHand",
                    "rightShoulder", "rightUpperArm", "rightLowerArm", "rightHand",
                    "leftUpperLeg", "leftLowerLeg", "leftFoot",
                    "rightUpperLeg", "rightLowerLeg", "rightFoot"
                ]
            })
        
        app.router.add_get("/api/motion-capture/status", api_motion_capture_status)
        app.router.add_get("/api/motion-capture/config", api_motion_capture_config)
        
        logger.info("Registered v2 system APIs")
    
    except ImportError as e:
        logger.warning(f"V2 system modules not available: {e}")
    
    # ========== 多直播平台 Webhook 接入 ==========
    try:
        from modules.platform_adapter import init_platform_manager, get_platform_manager
        import json
        
        # 加载平台配置
        platform_config_path = ROOT_DIR / "config" / "platforms.json"
        platform_config = {}
        if platform_config_path.exists():
            with open(platform_config_path, 'r', encoding='utf-8') as f:
                platform_config = json.load(f)
        
        # 过滤掉以_开头的注释字段，只传平台配置
        platform_config = {k: v for k, v in platform_config.items() if not k.startswith('_')}
        # 初始化平台管理器
        platform_mgr = init_platform_manager(platform_config)
        
        # 注册统一webhook处理（动态路由 /webhook/{platform}）
        async def universal_webhook_handler(request):
            """统一webhook处理入口 /webhook/{platform}"""
            platform = request.match_info.get('platform', '')
            result = await platform_mgr.handle_webhook(platform, request)
            return web.json_response(result)
        
        # 注册动态路由 - 支持所有平台 /webhook/douyin, /webhook/wechat 等
        app.router.add_post("/webhook/{platform}", universal_webhook_handler)
        logger.info("Registered unified webhook: /webhook/{platform}")
        
        # 注册平台事件处理器 - 将平台事件转换为内部事件
        async def on_platform_event(event):
            """处理来自各平台的直播事件"""
            try:
                # 映射为内部事件类型
                event_mapping = {
                    "chat": "smart_chat",
                    "gift": "gift_received",
                    "enter": "user_enter",
                    "like": "like_received",
                    "follow": "follow_received",
                    "order": "order_placed"
                }
                
                internal_type = event_mapping.get(event.event_type)
                if not internal_type:
                    return
                
                # 构造事件数据
                event_data = {
                    "platform": event.platform,
                    "username": event.username,
                    "user_id": event.user_id,
                    "content": event.content,
                    "amount": event.amount,
                    "price": event.price,
                    "sku_id": event.sku_id,
                    "timestamp": event.timestamp.isoformat()
                }
                
                # 提交到事件队列
                priority = 5  # 默认优先级
                if event.event_type == "order":
                    priority = 1  # 订单最高优先级
                elif event.event_type == "gift":
                    priority = 2  # 礼物高优先级
                
                await event_queue.submit(internal_type, event_data, priority=priority)
                
                # 记录日志
                logger.info(f"[{event.platform}] {event.event_type}: {event.username} - {event.content[:30]}")
                
            except Exception as e:
                logger.error(f"Platform event handle error: {e}")
        
        if platform_mgr:
            platform_mgr.on_event(on_platform_event)
        
        logger.info("Multi-platform adapter initialized")
        
    except Exception as e:
        logger.error(f"Failed to initialize platform adapter: {e}")
        # 降级为原始单抖音webhook
        app.router.add_post("/webhook/douyin", receive_webhook)
    app.router.add_static("/frontend", FRONTEND_DIR, show_index=False)
    app.router.add_static("/assets", ASSETS_DIR, show_index=False)
    app.router.add_static("/cache/tts", CACHE_DIR, show_index=False)
    app.router.add_static("/cache/tts_edge", CACHE_DIR_EDGE, show_index=False)
    CACHE_DIR_MINIMAX = ROOT_DIR / "cache" / "tts_minimax"
    CACHE_DIR_MINIMAX.mkdir(parents=True, exist_ok=True)
    app.router.add_static("/cache/tts_minimax", CACHE_DIR_MINIMAX, show_index=False)
    CACHE_DIR_MOTION = ROOT_DIR / "cache" / "motion_extract"
    CACHE_DIR_MOTION.mkdir(parents=True, exist_ok=True)
    app.router.add_static("/cache/motion_extract", CACHE_DIR_MOTION, show_index=False)
    CACHE_DIR_PREVIEWS = ROOT_DIR / "cache" / "action_previews"
    CACHE_DIR_PREVIEWS.mkdir(parents=True, exist_ok=True)
    app.router.add_static("/cache/action_previews", CACHE_DIR_PREVIEWS, show_index=False)

    # ========== 缓存清理 ==========
    cache_cleaner = CacheCleaner(
        cache_dirs=[CACHE_DIR, CACHE_DIR_EDGE, CACHE_DIR_MINIMAX],
        max_files=500,
        max_age_hours=72,
    )
    # 启动时执行一次清理
    cache_cleaner.cleanup()

    async def cache_stats(request):
        return web.json_response(cache_cleaner.get_stats())

    async def cache_cleanup(request):
        results = cache_cleaner.cleanup()
        return web.json_response({"ok": True, "deleted": results})

    app.router.add_get("/api/cache/stats", cache_stats)
    app.router.add_post("/api/cache/cleanup", cache_cleanup)

    # ========== 大模型配置管理 API ==========
    async def api_llm_get_configs(request):
        """获取所有大模型配置"""
        try:
            from modules.llm_manager import get_llm_manager, init_llm_manager
            await init_llm_manager()
            manager = get_llm_manager()
            configs = manager.get_configs()
            return web.json_response({"ok": True, "configs": configs, "active_adapter": manager.active_adapter})
        except Exception as e:
            logger.error(f"Get LLM configs error: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def api_llm_save_config(request):
        """保存大模型配置（直接读写配置文件，避免api_key丢失）"""
        try:
            import json as _json, base64 as _b64
            from modules.llm_manager import get_llm_manager, init_llm_manager
            data = await request.json()
            
            config_id = data.get("config_id")
            if not config_id:
                return web.json_response({"ok": False, "error": "缺少config_id参数"}, status=400)
            
            provider   = data.get("provider", "")
            model_name = data.get("model_name", "")
            api_key    = data.get("api_key", "")
            if not provider or not model_name:
                return web.json_response({"ok": False, "error": "缺少provider或model_name"}, status=400)

            config_path = Path(__file__).parent.parent / "config" / "llm_configs.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 直接读取原始文件（保留加密的旧key）
            raw = {}
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    raw = _json.load(f)
            
            # 编辑时若没有传新key，保留旧的加密key
            old_entry = raw.get(config_id, {}) if isinstance(raw.get(config_id), dict) else {}
            encrypted_key = old_entry.get("api_key", "")
            if api_key:  # 有新key才加密覆盖
                encrypted_key = _b64.b64encode(api_key.encode()).decode()
            
            raw[config_id] = {
                "provider":    provider,
                "model_name":  model_name,
                "api_key":     encrypted_key,
                "api_base":    data.get("api_base") or None,
                "temperature": float(data.get("temperature", 0.7)),
                "max_tokens":  int(data.get("max_tokens", 2000)),
                "timeout":     int(data.get("timeout", 60)),
                "extra_params": data.get("extra_params", {}),
                "enabled": True,
            }
            
            # 如果没有激活的或激活的不存在，自动设为当前
            current_default = raw.get("default_adapter")
            valid_ids = [k for k, v in raw.items() if isinstance(v, dict)]
            if not current_default or current_default not in valid_ids:
                raw["default_adapter"] = config_id
            
            with open(config_path, 'w', encoding='utf-8') as f:
                _json.dump(raw, f, ensure_ascii=False, indent=2)
            
            # 重新初始化管理器让新配置生效
            await init_llm_manager()
            
            return web.json_response({"ok": True})
            
        except Exception as e:
            logger.error(f"Save LLM config error: {e}", exc_info=True)
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def api_llm_delete_config(request):
        """删除大模型配置（直接读写文件，避免api_key丢失）"""
        try:
            import json as _json
            from modules.llm_manager import get_llm_manager, init_llm_manager
            data = await request.json()
            config_id = data.get("config_id")
            if not config_id:
                return web.json_response({"ok": False, "error": "缺少config_id参数"}, status=400)

            config_path = Path(__file__).parent.parent / "config" / "llm_configs.json"
            raw = {}
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    raw = _json.load(f)

            if config_id not in raw or not isinstance(raw[config_id], dict):
                return web.json_response({"ok": False, "error": "配置不存在"}, status=404)

            del raw[config_id]

            # 如果被删的是当前默认，重新选一个
            if raw.get("default_adapter") == config_id:
                valid_ids = [k for k, v in raw.items() if isinstance(v, dict)]
                raw["default_adapter"] = valid_ids[0] if valid_ids else None

            with open(config_path, 'w', encoding='utf-8') as f:
                _json.dump(raw, f, ensure_ascii=False, indent=2)

            await init_llm_manager()
            return web.json_response({"ok": True})
        except Exception as e:
            logger.error(f"Delete LLM config error: {e}", exc_info=True)
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def api_llm_set_active(request):
        """设置激活的大模型配置（直接读写文件，避免api_key丢失）"""
        try:
            import json as _json
            from modules.llm_manager import get_llm_manager, init_llm_manager
            data = await request.json()
            config_id = data.get("config_id")
            if not config_id:
                return web.json_response({"ok": False, "error": "缺少config_id参数"}, status=400)

            config_path = Path(__file__).parent.parent / "config" / "llm_configs.json"
            raw = {}
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    raw = _json.load(f)

            if config_id not in raw or not isinstance(raw[config_id], dict):
                return web.json_response({"ok": False, "error": "配置不存在"}, status=404)

            raw["default_adapter"] = config_id

            with open(config_path, 'w', encoding='utf-8') as f:
                _json.dump(raw, f, ensure_ascii=False, indent=2)

            await init_llm_manager()
            return web.json_response({"ok": True})
        except Exception as e:
            logger.error(f"Set active LLM config error: {e}", exc_info=True)
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def api_llm_test_config(request):
        """测试大模型配置"""
        try:
            from modules.llm_manager import get_llm_manager
            data = await request.json()
            
            if not data:
                return web.json_response({"ok": False, "error": "缺少配置数据"}, status=400)
            
            manager = get_llm_manager()
            
            # 验证配置
            is_valid = await manager.validate_config(data)
            
            if is_valid:
                return web.json_response({"ok": True, "message": "配置测试成功"})
            else:
                return web.json_response({"ok": False, "error": "配置测试失败"})
            
        except Exception as e:
            logger.error(f"Test LLM config error: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    # 注册大模型配置API
    app.router.add_get("/api/llm/configs", api_llm_get_configs)
    app.router.add_post("/api/llm/save-config", api_llm_save_config)
    app.router.add_post("/api/llm/delete-config", api_llm_delete_config)
    app.router.add_post("/api/llm/set-active", api_llm_set_active)
    app.router.add_post("/api/llm/test-config", api_llm_test_config)

    # ========== 云服务密钥管理 API ==========
    async def api_secrets_get(request):
        """获取已保存的云服务密钥（不含敏感值，或只显示部分）"""
        try:
            from modules.secrets_manager import get_secrets_manager
            mgr = get_secrets_manager()
            # 只返回 key 是否存在，不返回真实值（防泄漏）
            all_secrets = mgr.get_all()
            masked = {}
            for k, v in all_secrets.items():
                if 'KEY' in k or 'TOKEN' in k or 'SECRET' in k:
                    s = str(v)
                    masked[k] = s[:4] + '****' + s[-4:] if len(s) > 8 else '****'
                else:
                    masked[k] = v
            return web.json_response({"ok": True, "secrets": masked})
        except Exception as e:
            logger.error(f"Get secrets error: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def api_secrets_save(request):
        """保存云服务密钥"""
        try:
            from modules.secrets_manager import get_secrets_manager
            data = await request.json()
            updates = data.get("secrets", {})
            # 只允许已知的凭证 key，防止任意写入
            from modules.secrets_manager import get_secrets_manager, SecretsManager
            mgr = get_secrets_manager()
            filtered = {k: v for k, v in updates.items() if k in SecretsManager.KNOWN_KEYS and v}
            mgr.update(filtered)
            return web.json_response({"ok": True})
        except Exception as e:
            logger.error(f"Save secrets error: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def api_secrets_test(request):
        """测试云服务连接（火山TTS、MiniMax等）"""
        try:
            from modules.secrets_manager import get_secrets_manager
            data = await request.json()
            service = data.get("service")  # 'volc_tts' or 'minimax'
            mgr = get_secrets_manager()

            if service == "volc_tts":
                app_id = mgr.get("VOLC_TTS_APPID", data.get("app_id", ""))
                token = mgr.get("VOLC_TTS_TOKEN", data.get("token", ""))
                if not app_id or not token:
                    return web.json_response({"ok": False, "error": "缺少 VOLC_TTS_APPID 或 TOKEN"})
                # 简单测试：构造请求头看能否获取token（实际可以发一个简短TTS请求）
                import aiohttp
                test_url = "https://openspeech.bytedance.com/api/v1/tts"
                headers = {"Authorization": f"Bearer;{token}", "Content-Type": "application/json"}
                payload = {"app": {"appid": app_id, "token": token, "cluster": "volcano_tts"}, 
                          "user": {"uid": "test"}, "audio": {"voice_type": "BV001", "encoding": "mp3"},
                          "request": {"reqid": "test123", "text": "你好", "operation": "query"}}
                async with aiohttp.ClientSession() as session:
                    async with session.post(test_url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as r:
                        if r.status in (200, 400):  # 400可能是参数错，但鉴权过了
                            return web.json_response({"ok": True, "message": "火山TTS连接正常"})
                        return web.json_response({"ok": False, "error": f"HTTP {r.status}"})

            elif service == "minimax":
                api_key = mgr.get("MINIMAX_API_KEY", data.get("api_key", ""))
                group_id = mgr.get("MINIMAX_GROUP_ID", data.get("group_id", ""))
                if not api_key or not group_id:
                    return web.json_response({"ok": False, "error": "缺少 MINIMAX_API_KEY 或 GROUP_ID"})
                import aiohttp
                test_url = f"https://api.minimax.chat/v1/user_info?GroupId={group_id}"
                headers = {"Authorization": f"Bearer {api_key}"}
                async with aiohttp.ClientSession() as session:
                    async with session.get(test_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as r:
                        if r.status == 200:
                            return web.json_response({"ok": True, "message": "MiniMax连接正常"})
                        return web.json_response({"ok": False, "error": f"HTTP {r.status}"})

            else:
                return web.json_response({"ok": False, "error": "未知的service类型"})

        except Exception as e:
            logger.error(f"Test secrets error: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    app.router.add_get("/api/secrets", api_secrets_get)
    app.router.add_post("/api/secrets", api_secrets_save)
    app.router.add_post("/api/secrets/test", api_secrets_test)

    # ========== 事件→动作映射 API ==========
    async def get_event_action_map(request):
        """获取 main.json 中的 event_action_map"""
        main_path = ROOT_DIR / "config" / "main.json"
        try:
            with open(main_path, encoding="utf-8") as f:
                data = json.load(f)
            return web.json_response({"ok": True, "map": data.get("event_action_map", {})})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def save_event_action_map(request):
        """保存 event_action_map 到 main.json"""
        main_path = ROOT_DIR / "config" / "main.json"
        try:
            body = await request.json()
            new_map = body.get("map", {})
            with open(main_path, encoding="utf-8") as f:
                data = json.load(f)
            data["event_action_map"] = new_map
            with open(main_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"[Config] event_action_map updated: {list(new_map.keys())}")
            return web.json_response({"ok": True})
        except Exception as e:
            logger.error(f"Save event_action_map error: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    app.router.add_get("/api/event-action-map", get_event_action_map)
    app.router.add_post("/api/event-action-map", save_event_action_map)

    # ========== 手动播放动作 API ==========
    async def play_action_api(request):
        """广播 play_action 到所有 live-scene 客户端"""
        try:
            data = await request.json()
            file_path = data.get("file_path") or data.get("action_key")
            if not file_path:
                return web.json_response({"ok": False, "error": "file_path required"}, status=400)
            await hub.broadcast({
                "action": "play_action",
                "file_path": file_path,
                "loop": data.get("loop", False),
            })
            logger.info(f"[Action] play_action broadcast: {file_path}")
            return web.json_response({"ok": True})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    app.router.add_post("/api/play-action", play_action_api)
    app.router.add_post("/api/action/play", play_action_api)

    # ========== NPC 恢复默认位置 API ==========
    async def npc_reset_position(request):
        """读取当前场景的 host_position_3d，广播 reset_npc_position 到 live-scene"""
        scenes_path = ROOT_DIR / "config" / "scenes.json"
        try:
            with open(scenes_path, encoding="utf-8") as f:
                scenes_data = json.load(f)
            scenes = scenes_data.get("scenes", {})
            current_id = scenes_data.get("current_scene", "")
            scene = scenes.get(current_id, {})
            pos = scene.get("host_position_3d", {"x": 0, "y": 0, "z": 0})
            await hub.broadcast({
                "action": "reset_npc_position",
                "position": pos,
                "scene_id": current_id,
            })
            logger.info(f"[NPC] reset_position broadcast: {pos} (scene={current_id})")
            return web.json_response({"ok": True, "position": pos})
        except Exception as e:
            logger.error(f"NPC reset position error: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    app.router.add_post("/api/npc/reset-position", npc_reset_position)

    # ========== 摄像机切换 API ==========
    async def switch_camera(request):
        """
        切换直播间摄像机视角，广播 switch_camera 到所有 live-scene 客户端
        POST /api/camera/switch
        Body: { "mode": "fixed|third_person|first_person|free", "preset": "facing_screen|overview|...", "offset": "default" }
        """
        try:
            data = await request.json()
            mode = data.get("mode", "fixed")
            preset = data.get("preset", "facing_screen")
            offset = data.get("offset", "default")
            await hub.broadcast({
                "action": "switch_camera",
                "mode": mode,
                "preset": preset,
                "offset": offset,
            })
            logger.info(f"[Camera] switch_camera broadcast: mode={mode} preset={preset}")
            return web.json_response({"ok": True, "mode": mode, "preset": preset})
        except Exception as e:
            logger.error(f"Switch camera error: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    app.router.add_post("/api/camera/switch", switch_camera)

    # ========== 产品视频播放 API ==========
    async def play_product_video(request):
        """
        在场景中播放/隐藏产品视频，广播 play_product_video 到 live-scene
        POST /api/scene/product-video
        Body: { "video_url": "/assets/videos/xxx.mp4", "shelf_id": "A1", "operation": "show|hide" }
        """
        try:
            data = await request.json()
            video_url = data.get("video_url", "")
            shelf_id = data.get("shelf_id", "")
            operation = data.get("operation", "show")
            if operation == "show" and not video_url:
                return web.json_response({"ok": False, "error": "video_url required for show"}, status=400)
            await hub.broadcast({
                "action": "play_product_video",
                "video_url": video_url,
                "shelf_id": shelf_id,
                "operation": operation,
            })
            logger.info(f"[Video] play_product_video: shelf={shelf_id} op={operation} url={video_url[:60] if video_url else ''}")
            return web.json_response({"ok": True, "operation": operation, "shelf_id": shelf_id})
        except Exception as e:
            logger.error(f"Play product video error: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    app.router.add_post("/api/scene/product-video", play_product_video)

    return app
