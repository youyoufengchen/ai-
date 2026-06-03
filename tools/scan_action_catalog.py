"""
动作库扫描工具 — scan_action_catalog.py

功能：
  1. 扫描 assets/动作库/ 目录下所有 .glb 文件
  2. 与 config/action_catalog.json 对比，找出未注册的新文件
  3. 为新文件生成草稿条目（需人工补充 triggers 字段）
  4. 可选：直接追加到 catalog（--write）

用法：
  python tools/scan_action_catalog.py              # 只显示差异
  python tools/scan_action_catalog.py --write      # 自动追加草稿到catalog
  python tools/scan_action_catalog.py --list       # 列出所有已注册动作
"""

import json
import sys
import re
from pathlib import Path

ASSETS_DIR = Path("assets/动作库")
CATALOG_PATH = Path("config/action_catalog.json")


def load_catalog() -> dict:
    with open(CATALOG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_catalog(data: dict):
    with open(CATALOG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[OK] Saved to {CATALOG_PATH}")


def scan_glb_files() -> list[Path]:
    if not ASSETS_DIR.exists():
        print(f"[ERROR] Directory not found: {ASSETS_DIR}")
        sys.exit(1)
    return sorted(ASSETS_DIR.rglob("*.glb"))


def file_to_relative(path: Path) -> str:
    """把绝对路径转换为相对于 assets/动作库/ 的路径"""
    return str(path.relative_to(ASSETS_DIR)).replace("\\", "/")


def generate_id_from_path(rel_path: str) -> str:
    """从文件路径生成唯一ID，如 '情绪反应/打招呼/挥手.glb' → 'qingxu_dazhaohu_huishou'"""
    name = Path(rel_path).stem.lower()
    name = re.sub(r'[^a-z0-9\u4e00-\u9fff]', '_', name)
    name = re.sub(r'_+', '_', name).strip('_')
    return name[:40]


def infer_category(rel_path: str) -> str:
    parts = rel_path.split("/")
    if len(parts) >= 2:
        return "/".join(parts[:-1])
    return "未分类"


def make_draft_entry(rel_path: str) -> dict:
    """生成草稿条目，triggers需要人工填写"""
    entry_id = generate_id_from_path(rel_path)
    filename = Path(rel_path).stem
    category = infer_category(rel_path)

    return {
        "id": entry_id,
        "file": rel_path,
        "description": f"【待填写】{filename}",
        "triggers": [
            f"【待填写】请描述此动作的触发场景",
            f"{filename}"
        ],
        "category": category,
        "duration": 2.0,
        "loop": False,
        "tags": ["todo"],
        "emotion": "neutral",
        "priority": 1,
        "_draft": True
    }


def main():
    write_mode = "--write" in sys.argv
    list_mode  = "--list"  in sys.argv

    catalog = load_catalog()
    registered_files = {a["file"] for a in catalog.get("actions", [])}

    if list_mode:
        print(f"\n{'─'*60}")
        print(f"已注册动作 ({len(catalog['actions'])} 个):")
        print(f"{'─'*60}")
        for a in catalog["actions"]:
            draft_mark = " [DRAFT]" if a.get("_draft") else ""
            print(f"  {a['id']:<30} {a['file']}{draft_mark}")
        return

    glb_files = scan_glb_files()
    all_relative = [file_to_relative(f) for f in glb_files]

    unregistered = [p for p in all_relative if p not in registered_files]
    missing_files = [r for r in registered_files
                     if not (ASSETS_DIR / r).exists()]

    print(f"\n{'─'*60}")
    print(f"扫描结果：{ASSETS_DIR}")
    print(f"{'─'*60}")
    print(f"  磁盘GLB文件：{len(glb_files)} 个")
    print(f"  Catalog已注册：{len(catalog['actions'])} 个")
    print(f"  未注册（新增）：{len(unregistered)} 个")
    print(f"  注册但不存在（已删除）：{len(missing_files)} 个")

    if missing_files:
        print(f"\n[WARN] 以下文件已在catalog注册但磁盘上找不到：")
        for f in missing_files:
            print(f"  ✗ {f}")

    if not unregistered:
        print("\n[OK] 所有GLB文件均已注册，无需更新。")
        return

    print(f"\n未注册的文件（草稿已生成，需补充triggers字段）：")
    drafts = []
    for rel in unregistered:
        draft = make_draft_entry(rel)
        drafts.append(draft)
        print(f"  + {rel}")
        print(f"    → id: {draft['id']}")

    if write_mode:
        catalog["actions"].extend(drafts)
        save_catalog(catalog)
        print(f"\n[OK] 已追加 {len(drafts)} 个草稿条目到 catalog。")
        print("[!] 请打开 config/action_catalog.json，找到 _draft:true 的条目，")
        print("    补充 triggers（触发场景）和 description 字段，然后删除 _draft 字段。")
    else:
        print(f"\n提示：运行 python tools/scan_action_catalog.py --write 自动追加草稿")


if __name__ == "__main__":
    main()
