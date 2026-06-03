"""
动作自动打标签工具 — autotag_actions.py

功能：
  1. 扫描 action_catalog.json 中 _draft:true 或 triggers 为空的条目
  2. 对每个动作 GLB 渲染 4 帧截图（调用已有前端预览能力，或 headless 渲染）
  3. 调用配置的大模型 Vision API 分析截图，自动生成 description + triggers
  4. 写回 catalog，删除 _draft 标记

用法：
  python tools/autotag_actions.py                    # 处理所有草稿条目
  python tools/autotag_actions.py --id reach_high    # 处理指定动作
  python tools/autotag_actions.py --all              # 重新生成所有条目的标签
  python tools/autotag_actions.py --dry-run          # 只预览，不写入

依赖：
  pip install aiohttp python-dotenv Pillow
  需要通过前端配置界面设置大模型API密钥
"""

import asyncio
import base64
import json
import os
import sys
import argparse
import logging
from pathlib import Path
from typing import Optional

try:
    import aiohttp
except ImportError:
    print("[ERROR] 缺少依赖：pip install aiohttp")
    sys.exit(1)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("autotag")

CATALOG_PATH   = Path("config/action_catalog.json")
ASSETS_DIR     = Path("assets/动作库")
DEEPSEEK_API   = "https://api.deepseek.com/v1/chat/completions"
SKELETON_TYPES = ["humanoid", "quadruped", "avian", "custom"]


def load_catalog() -> dict:
    with open(CATALOG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_catalog(data: dict):
    with open(CATALOG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"Catalog saved → {CATALOG_PATH}")


def encode_image(image_path: Path) -> str:
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def find_preview_images(action_id: str) -> list[Path]:
    """
    查找已渲染的预览图（命名规则：{action_id}_frame*.png）
    如果没有预览图，返回空列表（此时使用纯文本分析）
    """
    preview_dir = Path("cache/action_previews")
    if not preview_dir.exists():
        return []
    frames = sorted(preview_dir.glob(f"{action_id}_frame*.png"))
    return frames[:4]


async def call_llm_vision(
    action_entry: dict,
    image_paths: list[Path],
) -> Optional[dict]:
    """
    调用配置的大模型Vision API生成动作标签

    如果有截图：多模态分析
    如果没有截图：根据文件路径和ID做纯文本推断
    """
    try:
        # 导入大模型管理器
        sys.path.append(str(Path(__file__).parent.parent))
        from modules.llm_manager import get_llm_manager
        
        manager = get_llm_manager()
        adapter = manager.get_active_adapter()
        
        if not adapter:
            logger.error("没有可用的LLM配置，请先在配置界面添加大模型")
            return None
        
        action_id   = action_entry["id"]
        file_path   = action_entry.get("file", "")
        skeleton_tp = action_entry.get("skeleton_type", "humanoid")

        # ── 构造 prompt ──────────────────────────────────────────────────
        system_prompt = """你是一个3D虚拟人物动作分析专家，专门为直播带货NPC的动作库生成标签。
你需要根据动作信息，从直播NPC的使用视角生成触发场景描述。
请务必只返回合法JSON，不要有任何其他文字。"""

        if image_paths:
            user_content = [
                {
                    "type": "text",
                    "text": f"""这是从真实人体动作视频中均匀采样的 {len(image_paths)} 帧截图。
动作文件路径：{file_path}
骨骼类型：{skeleton_tp}

请仔细观察截图中人物的动作，返回以下JSON（只返回JSON，不要其他文字）：
{{
  "description": "一句话描述这个动作（15字以内）",
  "triggers": [
    "触发场景1（直播NPC在什么情况下播放此动作，要具体）",
    "触发场景2",
    "触发场景3",
    "触发场景4",
    "触发场景5",
    "触发场景6",
    "触发场景7",
    "触发场景8"
  ],
  "emotion": "neutral/happy/sad/surprised/excited/friendly 之一",
  "skeleton_type": "{skeleton_tp}",
  "suggested_category": "推荐的动作库分类名称（如已有分类不合适可新建，用中文，例如：招牌动作/日常互动/动物动作/运动技能等）"
}}"""
                }
            ]
            for img_path in image_paths:
                b64 = encode_image(img_path)
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"}
                })
        else:
            # 无截图，纯文本推断
            path_parts = file_path.replace("\\", "/").split("/")
            user_content = f"""根据以下动作文件信息，推断这个3D角色动作的用途，生成直播NPC触发场景标签。

动作ID：{action_id}
文件路径：{file_path}
目录层级：{" > ".join(path_parts)}
骨骼类型：{skeleton_tp}

请返回JSON格式（只返回JSON，不要其他文字）：
{{
  "description": "一句话描述这个动作（15字以内）",
  "triggers": [
    "触发场景1（直播NPC在什么情况下播放此动作）",
    "触发场景2",
    "触发场景3",
    "触发场景4",
    "触发场景5",
    "触发场景6",
    "触发场景7",
    "触发场景8"
  ],
  "emotion": "neutral/happy/sad/surprised/excited/friendly 之一",
  "skeleton_type": "{skeleton_tp}",
  "suggested_category": "推荐分类（已有分类不合适时可新建，中文，如：招牌动作/日常互动/动物动作/运动技能）"
}}"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_content},
        ]

        try:
            result = await adapter.chat_completion(messages, max_tokens=400, temperature=0.3)
            
            if "choices" not in result:
                logger.error(f"LLM API 返回格式错误: {result}")
                return None
            
            raw = result["choices"][0]["message"]["content"].strip()
            # 提取JSON（有时模型会包裹在```json```中）
            if "```" in raw:
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            return json.loads(raw.strip())
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error for {action_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"LLM API call failed for {action_id}: {e}")
            return None
            
    except Exception as e:
        logger.error(f"初始化LLM管理器失败: {e}")
        return None


async def process_entry(entry: dict, dry_run: bool) -> Optional[dict]:
    action_id = entry["id"]
    logger.info(f"Processing: {action_id}")

    image_paths = find_preview_images(action_id)
    if image_paths:
        logger.info(f"  Found {len(image_paths)} preview frames")
    else:
        logger.info(f"  No preview images, using text inference")

    result = await call_llm_vision(entry, image_paths)
    if not result:
        logger.warning(f"  Skipped {action_id} (API failed)")
        return None

    logger.info(f"  description: {result.get('description', '')}")
    logger.info(f"  triggers: {len(result.get('triggers', []))} items")

    if dry_run:
        logger.info(f"  [DRY RUN] Would update {action_id}")
        return None

    # 更新条目
    updated = dict(entry)
    updated["description"] = result.get("description", entry.get("description", ""))
    updated["triggers"]    = result.get("triggers", entry.get("triggers", []))
    updated["emotion"]     = result.get("emotion", entry.get("emotion", "neutral"))
    updated.pop("_draft", None)  # 移除草稿标记
    return updated


async def main():
    parser = argparse.ArgumentParser(description="动作自动打标签工具")
    parser.add_argument("--id",      help="只处理指定动作ID")
    parser.add_argument("--all",     action="store_true", help="重新生成所有条目标签")
    parser.add_argument("--dry-run", action="store_true", help="只预览，不写入")
    args = parser.parse_args()

    # 初始化LLM管理器
    try:
        sys.path.append(str(Path(__file__).parent.parent))
        from modules.llm_manager import get_llm_manager, init_llm_manager
        await init_llm_manager()
        
        manager = get_llm_manager()
        adapter = manager.get_active_adapter()
        
        if not adapter:
            logger.error("没有可用的LLM配置")
            logger.error("请先访问 /llm-config.html 配置大模型API")
            sys.exit(1)
            
        logger.info(f"使用LLM配置: {adapter.config.provider.value} - {adapter.config.model_name}")
        
    except Exception as e:
        logger.error(f"初始化LLM管理器失败: {e}")
        sys.exit(1)

    catalog = load_catalog()
    actions = catalog.get("actions", [])

    # 确定要处理的条目
    if args.id:
        targets = [a for a in actions if a["id"] == args.id]
        if not targets:
            logger.error(f"未找到动作 ID: {args.id}")
            sys.exit(1)
    elif args.all:
        targets = actions
    else:
        # 默认：只处理草稿或 triggers 为空的
        targets = [
            a for a in actions
            if a.get("_draft") or not a.get("triggers") or
               any("待填写" in t for t in a.get("triggers", []))
        ]

    if not targets:
        logger.info("没有需要处理的条目（所有动作已有标签）")
        logger.info("使用 --all 强制重新生成所有标签")
        return

    logger.info(f"待处理条目：{len(targets)} 个")
    if args.dry_run:
        logger.info("[DRY RUN 模式] 不会写入任何文件")

    # 逐个处理（避免API限速）
    updated_map = {}
    for entry in targets:
        updated = await process_entry(entry, args.dry_run)
        if updated:
            updated_map[updated["id"]] = updated
        await asyncio.sleep(0.5)  # 限速

    if updated_map and not args.dry_run:
        # 合并回 catalog
        for i, action in enumerate(catalog["actions"]):
            if action["id"] in updated_map:
                catalog["actions"][i] = updated_map[action["id"]]
        save_catalog(catalog)
        logger.info(f"[OK] 已更新 {len(updated_map)} 个动作标签")
    elif updated_map:
        logger.info(f"[DRY RUN] 共 {len(updated_map)} 个条目可更新")


if __name__ == "__main__":
    asyncio.run(main())
