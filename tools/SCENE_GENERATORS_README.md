# 🎬 直播间场景生成器使用指南

## 快速开始

### 一键生成所有场景
```bash
cd "D:/新建文件夹 (2)"
blender --background --python tools/generate_all_scenes.py
```

### 或分别生成单个场景
```bash
# 环形剧场 (P0 - 最通用)
blender --background --python tools/generate_theater_scene.py

# 悬浮展示馆 (P1 - 玻璃罩展示)
blender --background --python tools/generate_showcase_scene.py

# 古风雅阁 (P4 - 文化风格)
blender --background --python tools/generate_temple_scene.py
```

---

## 📂 生成的文件结构

```
assets/scenes/
├── theater_ring/
│   ├── scene.gltf          # 3D场景文件
│   ├── scene.bin           # 几何数据
│   └── scene_config.json   # 场景配置
├── showcase_luxury/
│   ├── scene.gltf
│   ├── scene.bin
│   └── scene_config.json
└── temple_classical/
    ├── scene.gltf
    ├── scene.bin
    └── scene_config.json
```

---

## 🎨 三个场景特点

### 1. 🏛️ 环形剧场 (theater_ring)
- **风格**: 暖色调奢华风格
- **特点**: 6个玻璃展示柜环形排列，中央主播位
- **适用**: 多SKU展示、通用直播间
- **灯光**: 暖白环形补光
- **AI适配**: 主播在中心，到每个展示柜距离相等，路径规划简单

### 2. 🌃 悬浮展示馆 (showcase_luxury)
- **风格**: 赛博朋克 / 青橙霓虹
- **特点**: 8个悬浮玻璃罩，发光底座，双列排布
- **适用**: 高端精品、数码产品、限量商品
- **灯光**: 青色/橙色/白色三色氛围灯
- **AI适配**: 主播在中央平台，两侧展示罩对称，机器人后方通道隐蔽

### 3. 🏮 古风雅阁 (temple_classical)
- **风格**: 中式古典 / 朱红金饰
- **特点**: 朱红柱子、博古架、茶席案几、表演台
- **适用**: 文创、茶叶、汉服、国潮
- **灯光**: 暖色灯笼光
- **AI适配**: 含独立表演台（2m×2m），支持变身/舞蹈动作，机器人屏风后隐藏

---

## 🔧 配置说明

### scenes.json 自动更新
运行批量生成脚本后，会自动将新场景合并到 `config/scenes.json`，包含：

```json
{
  "scenes": {
    "theater_ring": {
      "name": "环形剧场",
      "environment": "theater_ring",
      "host_position_3d": {"x": 0, "y": 0.15, "z": 0},
      "objects": [...],  // 展示柜、停靠点配置
      "slots": [...]     // 2D商品槽位
    }
  }
}
```

### NPC 停靠点配置
每个展示柜都配置了 `npc_stop_point`：
```json
{
  "npc_stop_point": {
    "position": [x, 0, z],      // NPC站立位置
    "look_at": [x, 1.0, z]      // 视线方向（展示柜）
  }
}
```

AI 动作规划器会读取这些点位，自动规划：
1. `walk_normal` 走到停靠点
2. `reach_mid/high/low` 取货动作
3. `present` 展示给观众

---

## 🎮 在编辑器中使用

1. **启动后端服务**
   ```bash
   python server.py
   ```

2. **打开场景编辑器**
   - 访问 `http://localhost:8080/studio-editor-v2.html`

3. **选择新场景**
   - 在场景下拉菜单中选择：
     - 🏛️ 环形剧场
     - 🌃 悬浮展示馆
     - 🏮 古风雅阁

4. **查看3D效果**
   - 点击"3D预览"加载 GLTF 场景
   - 拖拽视角查看布局
   - 点击展示柜查看停靠点

---

## 🛠️ 自定义修改

### 修改展示柜数量/位置
编辑对应场景的生成器文件：
```python
# 例如 generate_theater_scene.py
DISPLAY_CABINETS = [
    {"angle": 0, "radius": 3.5, "height": 1.8, "shelves": 3, "sku": "product_01"},
    # 添加或修改这里
]
```

### 修改配色风格
```python
COLORS = {
    'floor': (0.12, 0.10, 0.08),  # RGB 0-1
    'accent': (0.85, 0.65, 0.25), # 主色调
    # ...
}
```

### 修改主播位置
```python
def build_host_platform():
    # 修改 location 参数
    bpy.ops.mesh.primitive_cylinder_add(
        location=(0, 0, 0.15)  # x, y, z
    )
```

---

## 📋 常见问题

**Q: Blender 报 "找不到模块" 错误？**
A: 确保在 Blender 的 Python 环境中安装了必要的库，或使用 `--background` 模式运行。

**Q: 场景生成后看不清/太暗？**
A: 修改 `build_lighting()` 函数中的 `energy` 参数，增大灯光强度。

**Q: 想添加更多装饰物？**
A: 在生成器中添加新的 `build_xxx()` 函数，在主流程中调用。

**Q: 玻璃材质不透明？**
A: 确保导出的 GLTF 包含材质设置，在前端使用 Three.js 的 `transparent: true` 渲染。

---

## 🎯 下一步建议

1. **运行生成器** 创建3个场景文件
2. **在编辑器中预览** 验证布局和灯光
3. **配置商品SKU** 绑定到各个展示柜
4. **测试AI取货流程** 验证 NPC 路径规划
5. **直播测试** 完整跑一遍带货流程

---

**生成时间**: 2026-06-03
**适用版本**: 项目 P0-P4 完成版
