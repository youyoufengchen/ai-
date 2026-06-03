"""
宝青坊 - 虚拟主播主服务（精简入口）

核心逻辑已拆分到 modules/ 下：
- modules/core.py            枚举/事件/队列/弹窗/WSHub
- modules/config_manager.py  配置加载与管理
- modules/scene_director.py  场景调度器
- modules/http_routes.py     HTTP 路由层
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

# 强制无缓冲输出
sys.stdout.reconfigure(line_buffering=True)
print("[Boot] Server starting...", flush=True)

# 加载 .env
from dotenv import load_dotenv
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
    print(f"[Config] Loaded environment from {env_path}", flush=True)
else:
    print(f"[Config] .env file not found at {env_path}, using system environment", flush=True)

import time

def _timed_import(label, import_fn):
    print(f"[Boot] Importing {label}...", flush=True)
    t0 = time.time()
    try:
        result = import_fn()
        print(f"[Boot] {label} imported in {time.time()-t0:.2f}s", flush=True)
        return result
    except Exception as e:
        print(f"[Boot] FAILED to import {label}: {e}", flush=True)
        raise

print("[Boot] Importing websockets...", flush=True)
import websockets
# 兼容新旧版本 websockets：14+ 使用 ServerConnection，旧版用 WebSocketServerProtocol
try:
    from websockets.asyncio.server import ServerConnection as WebSocketServerProtocol
except ImportError:
    from websockets.server import WebSocketServerProtocol

from aiohttp import web

# 导入拆分后的模块（带诊断）
print("[Boot] Importing core modules...", flush=True)
from modules.core import WSHub, EventQueueManager, PopupManager

print("[Boot] Importing config_manager...", flush=True)
from modules.config_manager import ConfigManager

print("[Boot] Importing scene_director...", flush=True)
from modules.scene_director import SceneDirector

print("[Boot] Importing http_routes...", flush=True)
from modules.http_routes import build_http_app

print("[Boot] Importing ai_service...", flush=True)
from modules.ai_service import AIService

print("[Boot] Importing tts_service...", flush=True)
from modules.tts_service import TTSService, MiniMaxTTSService, EdgeTTSService

print("[Boot] Importing dialogue_queue...", flush=True)
from modules.dialogue_queue import DialogueQueueManager, create_dialogue_queue_manager

print("[Boot] Importing ai_action_planner...", flush=True)
from modules.ai_action_planner import create_action_planner

print("[Boot] Importing session_recorder...", flush=True)
from modules.session_recorder import SessionRecorder

print("[Boot] Importing douyin_danmaku...", flush=True)
from modules.douyin_danmaku import (
    DanmakuEvent, DanmakuType,
    create_danmaku_crawler,
)

# ============== 日志配置 ==============
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("server")

# ============== 路径常量 ==============
ROOT_DIR = Path(__file__).parent
CONFIG_DIR = ROOT_DIR / "config"


# ============== WebSocket 服务 ==============
async def ws_handler(ws: WebSocketServerProtocol, hub: WSHub, director: SceneDirector):
    await hub.register(ws)
    try:
        await director.init_scene()
        async for raw in ws:
            try:
                msg = json.loads(raw)
                msg_type = msg.get("type") or msg.get("action", "")

                if msg_type == "action_flow_completed":
                    # 前端 ActionFlowExecutor 执行完毕 → 通知后端 dialogue_queue
                    # 优先用 dialogue_id（queue的key），plan_id作备用
                    item_id = msg.get("dialogue_id") or msg.get("plan_id")
                    logger.info(f"[WS] action_flow_completed: dialogue={item_id}")
                    if director.dialogue_queue and item_id:
                        await director.dialogue_queue.on_action_flow_completed(item_id)

                elif msg_type == "action_flow_execution_started":
                    plan_id = msg.get("plan_id") or msg.get("dialogue_id")
                    logger.debug(f"[WS] action_flow_execution_started: plan={plan_id}")

                else:
                    logger.debug(f"WS recv: {msg_type} {str(msg)[:120]}")

            except Exception as e:
                logger.warning(f"WS message error: {e}")
    except websockets.ConnectionClosed:
        pass
    finally:
        await hub.unregister(ws)


# ============== 主入口 ==============
async def main():
    print("[Boot] main() started", flush=True)
    
    # 初始化配置
    print("[Boot] [1/10] Loading config...", flush=True)
    logger.info("[1/10] 正在加载配置...")
    try:
        cfg = ConfigManager(CONFIG_DIR)
        print(f"[Boot] [2/10] Config loaded: {len(cfg.skus)} SKUs", flush=True)
        logger.info(f"[2/10] 配置加载完成: {len(cfg.skus)}个商品, {len(cfg.scenes.get('scenes', {}))}个场景")
    except Exception as e:
        print(f"[Boot] Config failed: {e}", flush=True)
        logger.error(f"配置加载失败: {e}", exc_info=True)
        raise

    # 初始化AI和TTS服务
    print("[Boot] [3/10] Initializing AI service...", flush=True)
    logger.info("[3/10] 正在初始化AI服务...")
    ai_service = AIService()
    print("[Boot] [4/10] Initializing TTS service...", flush=True)
    logger.info("[4/10] 正在初始化TTS服务...")
    tts_service = TTSService()
    minimax_tts = MiniMaxTTSService()
    edge_tts_service = EdgeTTSService()

    if ai_service.api_key:
        logger.info("  ✓ AI Service (DeepSeek) enabled")
    else:
        logger.warning("  ✗ AI Service disabled - set DEEPSEEK_API_KEY to enable")

    if tts_service.app_id and tts_service.token:
        logger.info("  ✓ TTS Service (Volcengine) enabled")
    else:
        logger.warning("  ✗ TTS Service disabled - set VOLC_TTS_APPID and VOLC_TTS_TOKEN to enable")

    # 初始化Action Planner（AI动作规划器）
    logger.info("[5/10] 正在初始化Action Planner...")
    action_planner = create_action_planner(ai_service, cfg)
    logger.info("  ✓ AIActionPlanner initialized")
    
    # 初始化对话队列管理器
    logger.info("[6/10] 正在初始化对话队列...")
    dialogue_queue = create_dialogue_queue_manager(ai_service, tts_service, cfg, action_planner)
    logger.info("  ✓ DialogueQueueManager initialized")

    # 初始化会话录制器
    logger.info("[7/10] 正在初始化会话录制器...")
    session_recorder = SessionRecorder(max_records=500)
    logger.info("  ✓ SessionRecorder initialized")

    # 核心组件
    logger.info("[8/10] 正在初始化核心组件...")
    hub = WSHub()
    event_queue = EventQueueManager(cfg.main)
    popup_mgr = PopupManager()
    
    # 初始化场景调度器
    logger.info("[9/10] 正在初始化场景调度器...")
    try:
        director = SceneDirector(
            cfg, hub, event_queue, popup_mgr,
            ai_service, tts_service, dialogue_queue,
            edge_tts=edge_tts_service, minimax_tts=minimax_tts,
            session_recorder=session_recorder,
            action_planner=action_planner,
        )
        logger.info("  ✓ SceneDirector initialized")
    except Exception as e:
        logger.error(f"SceneDirector初始化失败: {e}", exc_info=True)
        raise

    # 回调：对话变更时广播
    async def on_dialogue_changed(item=None):
        status = dialogue_queue.get_queue_status()
        await hub.broadcast({"action": "dialogue_queue_updated", "queue_status": status})

    dialogue_queue.on_item_added = on_dialogue_changed
    dialogue_queue.on_item_updated = on_dialogue_changed
    dialogue_queue.on_item_removed = on_dialogue_changed
    dialogue_queue.on_queue_changed = on_dialogue_changed

    # 网络配置
    server_cfg = cfg.main.get("server", {})
    http_host = server_cfg.get("http_host", "0.0.0.0")
    http_port = server_cfg.get("http_port", 8080)
    ws_host = server_cfg.get("websocket_host", "0.0.0.0")
    ws_port = server_cfg.get("websocket_port", 8765)

    # 读取弹幕平台配置
    douyin_room_id = None
    try:
        pf_path = ROOT_DIR / "config" / "platforms.json"
        if pf_path.exists():
            with open(pf_path, 'r', encoding='utf-8') as f:
                pf_cfg = json.load(f)
            dy_cfg = pf_cfg.get("douyin", {})
            if dy_cfg.get("enabled") and dy_cfg.get("room_id"):
                douyin_room_id = str(dy_cfg["room_id"]).strip()
                logger.info(f"Douyin room_id from config: {douyin_room_id}")
    except Exception as e:
        logger.warning(f"Failed to read platform config: {e}")

    danmaku_crawler = create_danmaku_crawler(room_id=douyin_room_id)

    # 启动 HTTP 服务
    app = build_http_app(
        cfg, director, event_queue, popup_mgr,
        ai_service, tts_service, dialogue_queue,
        hub, session_recorder, danmaku_crawler=danmaku_crawler,
    )
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, http_host, http_port)
    await site.start()
    logger.info(f"HTTP server: http://localhost:{http_port}")

    # 启动 WebSocket 服务
    async def _ws(ws):
        await ws_handler(ws, hub, director)

    ws_server = await websockets.serve(_ws, ws_host, ws_port)
    logger.info(f"WebSocket: ws://localhost:{ws_port}")

    # 启动实时动捕服务器（Phase 5）
    try:
        from modules.motion_capture_server import init_motion_capture_server, get_motion_capture_server
        motion_server = init_motion_capture_server(host=ws_host, port=8766)
        mc_started = await motion_server.start()
        if mc_started:
            logger.info("🎥 Motion capture server: ws://localhost:8766")
    except Exception as e:
        logger.warning(f"Motion capture server failed to start: {e}")

    # 启动事件处理循环
    async def safe_event_loop():
        try:
            await director.start_event_loop()
        except asyncio.CancelledError:
            logger.info("Event loop cancelled")
        except Exception as e:
            logger.error(f"Event loop crashed: {e}", exc_info=True)
            # 尝试重启
            logger.info("Attempting to restart event loop...")
            await asyncio.sleep(1)
            await safe_event_loop()

    event_loop_task = asyncio.create_task(safe_event_loop())
    logger.info("Event processing loop started")

    logger.info("Server ready. Open http://localhost:%d in browser.", http_port)

    # 绑定弹幕事件处理器
    @danmaku_crawler.on(DanmakuType.CHAT)
    async def on_chat(event: DanmakuEvent):
        await director.handle_danmaku(event)

    @danmaku_crawler.on(DanmakuType.GIFT)
    async def on_gift(event: DanmakuEvent):
        await director.handle_danmaku(event)

    @danmaku_crawler.on(DanmakuType.ENTER)
    async def on_enter(event: DanmakuEvent):
        await director.handle_danmaku(event)

    @danmaku_crawler.on(DanmakuType.LIKE)
    async def on_like(event: DanmakuEvent):
        await director.handle_danmaku(event)

    logger.info("Danmaku crawler ready (not started). Click '开始直播' in control panel to start.")

    # 永不退出
    live_state = app.get("live_state", {"task": None, "running": False})
    try:
        await asyncio.Future()
    except asyncio.CancelledError:
        logger.info("Shutting down...")
    finally:
        director.stop_event_loop()
        event_loop_task.cancel()
        if live_state["task"]:
            live_state["task"].cancel()
        try:
            await event_loop_task
            if live_state["task"]:
                await live_state["task"]
        except asyncio.CancelledError:
            pass
        ws_server.close()
        await ws_server.wait_closed()
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server stopped.")
