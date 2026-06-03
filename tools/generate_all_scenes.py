"""
批量生成所有直播间场景
一键运行生成：环形剧场、悬浮展示馆、古风雅阁

使用方法:
    blender --background --python tools/generate_all_scenes.py
    
或分别生成:
    blender --background --python tools/generate_theater_scene.py
    blender --background --python tools/generate_showcase_scene.py
    blender --background --python tools/generate_temple_scene.py
"""

import bpy
import sys
import os

# 将项目目录添加到路径
project_path = "D:/新建文件夹 (2)"
if project_path not in sys.path:
    sys.path.insert(0, project_path)

# 导入各个生成器
try:
    from tools.generate_theater_scene import main as gen_theater
    from tools.generate_showcase_scene import main as gen_showcase
    from tools.generate_temple_scene import main as gen_temple
    GENERATORS_AVAILABLE = True
except ImportError as e:
    print(f"⚠️ 部分生成器导入失败: {e}")
    GENERATORS_AVAILABLE = False

def update_scenes_json():
    """合并所有场景配置到 scenes.json"""
    import json
    
    config_dir = "D:/新建文件夹 (2)/config"
    scenes_path = os.path.join(config_dir, "scenes.json")
    
    # 读取现有配置
    if os.path.exists(scenes_path):
        with open(scenes_path, 'r', encoding='utf-8') as f:
            scenes_data = json.load(f)
    else:
        scenes_data = {"scenes": {}}
    
    # 读取各场景配置
    scene_configs = []
    scene_files = [
        ("theater_ring", "assets/scenes/theater_ring/scene_config.json"),
        ("showcase_luxury", "assets/scenes/showcase_luxury/scene_config.json"),
        ("temple_classical", "assets/scenes/temple_classical/scene_config.json"),
    ]
    
    for scene_id, config_file in scene_files:
        config_path = os.path.join(project_path, config_file)
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                # 添加场景模板配置
                config['bg_image'] = f"/assets/scenes/bg_{scene_id}.jpg"
                config['environment'] = scene_id
                config['created_at'] = "2026-06-03T00:00:00Z"
                config['updated_at'] = "2026-06-03T00:00:00Z"
                scenes_data['scenes'][scene_id] = config
                print(f"✅ 已导入: {scene_id}")
        else:
            print(f"⚠️ 配置文件不存在: {config_path}")
    
    # 保存合并后的配置
    os.makedirs(config_dir, exist_ok=True)
    with open(scenes_path, 'w', encoding='utf-8') as f:
        json.dump(scenes_data, f, ensure_ascii=False, indent=2)
    
    print(f"\n📝 场景配置已更新: {scenes_path}")
    return scenes_data

def main():
    print("=" * 70)
    print("🎬 直播间场景批量生成器")
    print("=" * 70)
    
    if not GENERATORS_AVAILABLE:
        print("\n❌ 错误: 无法导入场景生成器")
        print("请确保以下文件存在:")
        print("  - tools/generate_theater_scene.py")
        print("  - tools/generate_showcase_scene.py")
        print("  - tools/generate_temple_scene.py")
        return
    
    scenes = [
        ("环形剧场", gen_theater),
        ("悬浮展示馆", gen_showcase),
        ("古风雅阁", gen_temple),
    ]
    
    success_count = 0
    
    for name, generator in scenes:
        print(f"\n{'─' * 70}")
        print(f"🎯 正在生成: {name}")
        print(f"{'─' * 70}")
        try:
            # 每次生成前清理场景
            bpy.ops.object.select_all(action='SELECT')
            bpy.ops.object.delete(use_global=False)
            
            generator()
            success_count += 1
            print(f"✅ {name} 生成成功")
        except Exception as e:
            print(f"❌ {name} 生成失败: {e}")
            import traceback
            traceback.print_exc()
    
    print(f"\n{'=' * 70}")
    print(f"📊 生成结果: {success_count}/{len(scenes)} 个场景成功")
    print(f"{'=' * 70}")
    
    if success_count > 0:
        print("\n🔄 正在合并场景配置...")
        try:
            update_scenes_json()
            print("\n✨ 全部完成！")
            print("\n生成的场景:")
            print("  1. 🏛️  环形剧场 (theater_ring)")
            print("     - 6个玻璃展示柜环绕中央主播位")
            print("     - 暖色调奢华风格")
            print("  2. 🌃 悬浮展示馆 (showcase_luxury)")
            print("     - 8个悬浮玻璃罩，青橙霓虹灯光")
            print("     - 赛博朋克风格，适合精品展示")
            print("  3. 🏮 古风雅阁 (temple_classical)")
            print("     - 朱红柱子、博古架、茶席案几")
            print("     - 中式古典，含表演台")
            print("\n📁 输出目录: assets/scenes/")
            print("🎮 重启服务后，在编辑器中选择新场景即可使用")
        except Exception as e:
            print(f"⚠️ 配置合并失败: {e}")

if __name__ == "__main__":
    main()
