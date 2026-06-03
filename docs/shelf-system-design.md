# 货架（玻璃展柜）系统设计

## 1. 核心概念

每个场景中可以放置若干 **货架（Shelf）**，每个货架是一个旋转的透明玻璃罩，内部展示一件商品（2D贴图或3D模型）。NPC 接到"展示某商品"指令时，会根据货架编号寻路到对应停靠点，播放取物动画，玻璃罩附着到 NPC 手骨，展示完后放下并淡出。

## 2. 数据 Schema

存储于 `config/scenes.json` 每个场景下，新增字段 `shelves: []`（与已有的 `slots`/`objects` 并存，逐步迁移）。

```jsonc
{
  "shelves": [
    {
      "id": "shelf_01",                     // 唯一编号，NPC 寻路用
      "label": "1号位",                      // 显示名
      "position": [2.5, 0, -3.0],           // 货架底座世界坐标
      "rotation_y": 45,                     // 朝向（度）
      "case_size": {                        // 玻璃罩尺寸（米）
        "width": 0.8,
        "height": 1.2,
        "depth": 0.8
      },
      "spin": {                             // 玻璃罩内商品自转
        "enabled": true,
        "speed_deg_per_sec": 30,
        "axis": [0, 1, 0]                   // 旋转轴（默认绕Y）
      },
      "product": {                          // 绑定的商品（可为 null = 空货架）
        "sku_id": "basketball_001",
        "display_type": "3d_model",         // "3d_model" | "image_2d"
        "asset_path": "/assets/products/basketball/model.glb",
        "scale": 0.6,
        "offset_y": 0                       // 商品在罩内的垂直偏移
      },
      "npc_stop_point": {                   // NPC 停靠位
        "position": [2.5, 0, -1.8],         // NPC 站立位
        "look_at": [2.5, 1.0, -3.0]         // NPC 朝向（看向货架罩中心）
      }
    }
  ]
}
```

## 3. 渲染结构（Three.js）

```
ShelfRoot (Group, 位置+朝向)
├── Base (底座 — 短圆柱，金属感)
├── GlassCase (玻璃罩 — MeshPhysicalMaterial, transmission≈0.9, roughness≈0.05)
├── ProductPivot (商品旋转中心)
│   └── ProductMesh (sku 对应的 3D 模型 或 PlaneGeometry+贴图)
└── LabelTag (CSS2DObject — 显示编号 "1号位")
```

## 4. 行为状态机

每个货架对象暴露统一接口：

```js
shelf.attachToBone(bone)   // 把整个 ShelfRoot 从场景树移到 NPC 手骨节点下
shelf.detach()             // 还原到场景树原位置
shelf.fadeOut(durationMs)  // 透明度从 1→0，结束后 visible=false
shelf.fadeIn(durationMs)
shelf.setProduct(productConfig)  // 运行时切换展示物
```

## 5. 与 NPC 动作的协同

动作流（ActionFlow）规划器输出的序列示例：

```js
[
  { type: 'walk_to', target_shelf: 'shelf_03', duration: 2000 },
  { type: 'play_anim', clip: 'pick_up', duration: 1500 },
  { type: 'attach_shelf_to_hand', shelf_id: 'shelf_03', bone: 'mixamorigRightHand' },
  { type: 'play_anim', clip: 'show_to_camera', duration: 3000 },
  { type: 'speak', text: '这款篮球...', tts_url: '...' },  // 与上面动画并行
  { type: 'play_anim', clip: 'put_down', duration: 1500 },
  { type: 'detach_shelf', shelf_id: 'shelf_03', fade_out: true },
  { type: 'walk_to', target: 'home', duration: 2000 },
]
```

## 6. 后端 API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/scene/{id}/shelves` | 获取场景的货架列表 |
| POST | `/api/scene/{id}/shelves` | 新增货架 |
| PUT | `/api/scene/{id}/shelves/{shelf_id}` | 更新货架属性 |
| DELETE | `/api/scene/{id}/shelves/{shelf_id}` | 删除货架 |
| POST | `/api/scene/{id}/shelves/{shelf_id}/bind_product` | 绑定/换绑商品 |

## 7. 实施分阶段

1. **阶段A（本次）**：组件渲染 + 静态 demo 货架
2. **阶段B**：编辑器拖拽编辑 + 保存到 scenes.json
3. **阶段C**：NPC 寻路 + 取物附着 + 放下淡出
4. **阶段D**：ActionFlow 编排器接入 AI 回复，自动触发取货
