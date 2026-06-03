# 宝青坊 直播间 NPC 系统 — 实施路线图

> 版本: v3.0  
> 更新日期: 2026-05-28  
> 状态: 持续迭代中

---

## 一、项目概览

整体技术栈：
- **后端**: Python (aiohttp + websockets) `server.py`（约 3200 行单文件）
- **前端**: 原生 HTML / Three.js / 多页面架构
- **直播页**: `live-scene.html` (NPC + 场景 + 弹幕飘屏)
- **控制台**: `control.html` (主控页，弹幕/动作/事件流)
- **场景编辑器**: `studio-editor-v2.html` (3D 场景/货架/角色/动作)
- **设置页**: `settings.html`

页面入口：

| 路由 | 用途 |
|------|------|
| `/` → `/control` | 默认重定向 |
| `/control` | 直播运营控制台 |
| `/live-scene` | 真实直播3D场景（OBS采集页） |
| `/editor` | 场景编辑器 v2 |
| `/settings` | 设置 |
| `/control-legacy` | 旧版控制台（保留） |

---

## 二、已完成功能 ✅

### 2.1 编辑器（studio-editor-v2.html）
- ✅ 主3D视口 + OrbitControls
- ✅ 自动加载默认 NPC（X Bot），相机距离自适应
- ✅ 左侧 sidebar：系统状态 + 场景选择器 + 应用模式 + 直播间联动
- ✅ 右侧 6 个 tab：
  - **🎬 动作库** — 加载动作树 + 播放预览
  - **🔗 事件绑定** — 事件→动作变体绑定 + 保存
  - **👤 角色** — 角色信息 + 风格列表 + 一键切换 + 3D小预览
  - **🛒 货架** — 场景货架管理 + 拖拽 + NPC停靠点编辑
  - **📋 层级** — 元素显示/隐藏
  - **🎯 ActionFlow** — NPC回复文本→动作流意图解析
- ✅ 顶部"系统初始化"对话框

### 2.2 真实场景加载
- ✅ 场景选择器（左侧 + 货架tab双向同步）
- ✅ GLTF 优先加载（路径 `/assets/scenes/{env}/scene.gltf`）
- ✅ Fallback 演示场景（茶室/办公室/演播室3种风格化地板+墙）
- ✅ `/api/scenes` 拉取真实场景配置

### 2.3 NPC 停靠点可视化
- ✅ 货架属性区折叠停靠点编辑面板
- ✅ 3D 标记：🟢站位球 + 🔴朝向球 + 黄色朝向线 + 蓝色路径线
- ✅ 自动计算 / 显示隐藏切换
- ✅ 输入框实时联动

### 2.4 直播间双向联动
- ✅ WebSocket 客户端（自动重连，5s 间隔）
- ✅ 接收：`scene_changed`、`trigger_animation`、`play_action`、`highlight_shelf`、`speak`、`set_state`
- ✅ 推送场景 → 调 `/api/scene/apply`
- ✅ 风格切换 → 调 `/api/style/switch`（服务器自动广播给 live-scene）
- ✅ `highlight_shelf` 自动定位货架

### 2.5 后端 API
- ✅ 配置：`/api/config/main`, `/api/config/characters`, `/api/config/skus`, `/api/config/reload`
- ✅ 场景：`/api/scenes`, `/api/scene/apply`, `/api/scenes/move`, `/api/scenes/reorder`
- ✅ 风格：`/api/style/switch`
- ✅ 动作：`/api/actions`, `/api/actions/tree`, `/api/action-templates`
- ✅ TTS：火山 / Edge / MiniMax 三套
- ✅ 平台：抖音弹幕抓取（PlatformAdapterManager）

---

## 三、已知问题与待优化 🚧

### 3.1 编辑器层

| 优先级 | 项目 | 说明 |
|--------|------|------|
| 🔴 高 | **场景3D资源缺失** | `assets/scenes/*/` 文件夹只有 manifest.json，没有 scene.gltf。需要批量生成或购买 |
| 🟡 中 | **角色 tab 风格切换重影** | 切换风格后，本地缓存的 current_style 已更新但服务器返回的状态可能不同步。建议改为服务器推送驱动 |
| 🟡 中 | **货架拖拽不会更新停靠点** | 拖动货架时，停靠点标记不会跟随移动。需要在 onCanvasMouseMove 中同步刷新 |
| 🟡 中 | **第一人称/跟随视角按钮无功能** | canvas 工具栏的按钮是占位 |
| 🟢 低 | **OrbitControls 与拖拽事件冲突偶现** | 极少数情况下右键拖拽会触发货架选中 |
| 🟢 低 | **重复加载场景时旧场景背景色未还原** | 切换场景后再切换，背景色会保留上一个 |

### 3.2 后端层

| 优先级 | 项目 | 说明 |
|--------|------|------|
| 🔴 高 | **server.py 过大（3200 行）** | 单文件包含 ConfigManager / WSHub / SceneDirector / 所有 HTTP handler。建议拆分到 modules/ |
| 🟡 中 | **WS 是单向广播** | `ws_handler` 收到消息只记日志，不处理。前端发送的 WS 消息无法触发后端逻辑（已通过 HTTP API 绕过） |
| 🟡 中 | **缺少 /api/test/event 模拟入口** | 编辑器没有快速测试事件触发的入口 |
| 🟢 低 | **server_err.log 60KB** | 错误日志已积累，需要定期清理或滚动 |

### 3.3 直播间（live-scene.html）

| 优先级 | 项目 | 说明 |
|--------|------|------|
| 🟡 中 | **场景资源缺失同样问题** | 走 fallback 场景，需要补 GLTF |
| 🟡 中 | **`init_scene` 广播未被编辑器响应** | 服务器启动时广播的 init_scene 在编辑器内未处理（编辑器自己拉取） |
| 🟢 低 | **NPC 停靠点未在直播间真实使用** | 停靠点已存到 scenes.json，但 NPC 走位逻辑未读取 |

### 3.4 资产层

| 优先级 | 项目 | 说明 |
|--------|------|------|
| 🔴 高 | **场景 GLTF 缺失** | `tea_room` / `modern_office` / `news_studio` / `news_studio` / `meeting_room_interior` / `virtual_studio` 都是空目录 |
| 🟡 中 | **HDR/EXR 环境光未利用** | `brown_photostudio_01_4k.exr`、`voortrekker_interior_4k.exr` 已下载但未在场景里挂载 |
| 🟡 中 | **TTS 缓存膨胀** | `cache/tts_minimax/` 已 400+ 文件，需要 LRU 清理策略 |

### 3.5 已规划但未启动（来自 roadmap v1）

| 阶段 | 状态 | 备注 |
|------|------|------|
| 阶段2 动作上传/管理UI | ⏳ | `/api/actions/tree` 已读，但缺上传/重命名/删除接口 |
| 阶段3 角色形态切换 | ⏳ | characters.json 已定义形态，但前端未实现切换UI |
| 阶段4 动画混合执行 | ⏳ | 当前动作库播放是单段，缺 crossfade / 队列 |
| 阶段5 AI 动作规划 | 🔵 部分 | ActionFlow tab 已有意图解析雏形，但未对接 GPT |
| 阶段6 多视角相机 | ⏳ | 工具栏按钮是占位 |
| 阶段7 IK/物理交互 | ⏳ | physics_catalog.json 未创建 |
| 阶段8 系统自愈 | 🔵 部分 | 健康检查已有，但缺自动恢复 |

---

## 四、近期建议优先级

### P0 — 影响可用性（立即）
1. **补充至少 1 个真实场景 GLTF**（茶室优先）— 否则编辑器和直播页都只能看 fallback
2. **货架拖拽时同步刷新停靠点标记**
3. **server.py 拆分** — 至少把 ConfigManager 和 SceneDirector 拆出去

### P1 — 体验提升（本周）
4. **编辑器加事件模拟入口**：弹幕/进入/送礼一键触发，方便调试
5. **HDR 环境光集成** — 把 EXR 用 RGBELoader 挂到 scene.environment
6. **TTS 缓存 LRU 清理**（限制最多保留 500 个文件）

### P2 — 功能扩展（本月）
7. **NPC 走到货架前** — 用 stop_point 实现真实走位
8. **第一人称/跟随视角真实实现**
9. **动画 crossfade** — 解决动作切换的硬切问题
10. **产品介绍视频在场景中播放**（VideoTexture）

### P3 — 远期（长线）
11. ActionFlow 对接 DeepSeek/GPT-4
12. 角色形态切换（人/猫/小孩）
13. IK 抓取系统
14. 系统自愈机制

---

## 五、目录结构现状

```
新建文件夹 (2)/
├── server.py                      # 主服务（3200行 ⚠️ 过大）
├── modules/
│   ├── ai_service.py             # DeepSeek
│   ├── tts_service.py            # 火山 TTS
│   ├── action_manager.py         # 动作管理
│   ├── dialogue_queue.py         # 对话队列
│   └── ...
├── frontend/
│   ├── live-scene.html           # ✅ 直播页
│   ├── control.html              # ✅ 控制台
│   ├── studio-editor-v2.html     # ✅ 编辑器（3400行）
│   ├── settings.html             # ✅ 设置
│   ├── studio-editor.html        # 🟡 旧版（可移除？）
│   ├── studio-editor.js          # 🟡 旧版逻辑（可移除？）
│   ├── control-legacy.html       # 🟡 旧版（可移除？）
│   ├── components/glass-case.js  # ✅ 玻璃柜组件
│   ├── core/                     # 待启用
│   └── libs/                     # Three.js 依赖
├── config/
│   ├── main.json
│   ├── characters.json           # ✅ 24种风格
│   ├── scenes.json               # ✅ 场景+货架
│   ├── skus.json
│   ├── platforms.json
│   └── actions.json
├── assets/
│   ├── 角色/X Bot.glb            # ✅ Mixamo默认
│   ├── 动作库/                   # ✅ 中文目录
│   ├── scenes/                   # ⚠️ GLTF 缺失
│   ├── host/                     # ✅ 视频NPC素材
│   └── products/                 # ✅ SKU素材
└── cache/
    ├── tts/
    ├── tts_edge/
    └── tts_minimax/              # ⚠️ 400+ 文件膨胀
```

---

## 六、NPC 表演系统完整架构（v3.0 新增）

> 基于 2026-05-28 技术讨论，明确了从"硬编码动作"到"智能动作资产管理平台"的完整演进路径。

### 6.1 总体设计原则

```
三条独立技术线，互不干扰，运行时叠加：

① 骨骼动画线   → 身体大动作（GLB动作库 + 动作检索引擎）
② 表情/口型线  → 面部细节（VRM BlendShape + 音素驱动）
③ 物理模拟线   → 头发/衣服/惯性（VRM Spring Bone + 程序动画）
```

### 6.2 角色格式迁移：GLB → VRM

**当前问题**：X Bot（普通GLB）无BlendShape、无物理配置、无口型节点。

**迁移目标**：所有NPC角色统一采用 VRM 格式。

| 能力 | 当前(GLB) | 目标(VRM) |
|------|-----------|-----------|
| 身体动作 | ✅ | ✅ |
| 表情系统 | ❌ | ✅ 52个BlendShape |
| 口型同步 | ❌ | ✅ A/I/U/E/O节点 |
| 头发物理 | ❌ | ✅ Spring Bone |
| 衣服摆动 | ❌ | ✅ Spring Bone |
| 眼神追踪 | ❌ | ✅ LookAt |
| 资源生态 | 有限 | ✅ VTuber生态，资源丰富 |

**前端依赖**：`@pixiv/three-vrm`（成熟库，直接用）

**动作重定向**：Mixamo骨骼名 → VRM骨骼名，写一次映射表永久复用。

### 6.3 动作资产管理平台

#### 资产入库流水线
```
维护人员上传视频
      │
      ├─► MediaPipe 提取骨骼动画 → 输出标准BVH
      │
      ├─► DeepSeek-V3 Vision 分析视频：
      │       自动生成 description + triggers(8-12条) + emotion标签
      │
      ├─► 人工审核界面（Studio编辑器扩展）：
      │       预览动作 / 修改标签 / 确认骨骼类型 / 一键通过
      │
      └─► 写入 action_catalog.json + 生成GLB → 入库
```

#### 标准骨骼类型体系
```json
骨骼类型库：
  humanoid   → 人形（Mixamo/VRM标准，当前已有）
  quadruped  → 四足（狗/猫/马）
  avian      → 鸟形（翅膀+双足）
  custom     → 用户自定义
```

**核心逻辑**：动作绑定标准骨骼类型，角色上传时注册骨骼类型，运行时先按骨骼类型过滤，再按语义标签检索。

#### 动作检索引擎（已实现基础版）
- `config/action_catalog.json` — 动作注册表，每条含 `triggers`（触发场景）
- `modules/action_retriever.py` — 双模式检索（向量语义 / 关键词TF-IDF降级）
- `tools/scan_action_catalog.py` — 扫描新GLB，自动生成草稿条目

**检索流程**：
```
NPC意图描述（自然语言）
      ↓
角色骨骼类型前置过滤
      ↓
向量相似度检索 top-K（或关键词TF-IDF降级）
      ↓
返回最匹配的动作文件路径
```

**规模化方案**：动作量 < 500 时关键词检索足够；超过500后安装 `sentence-transformers` 自动升级为向量检索，接口不变。

### 6.4 表情与口型系统

#### 表情系统
- 驱动方式：AI解析情绪 → `vrm.expressionManager.setValue('happy', 0.8)`
- 不依赖任何动作文件，实时参数驱动
- 与骨骼动画并行叠加，互不干扰

#### 口型同步
- 火山引擎TTS原生支持返回Viseme时间轴（近零成本实现）
- 前端按时间轴插值VRM口型BlendShape权重
- 备选：Rhubarb Lip Sync（离线音频分析）

#### 物理效果
- VRM Spring Bone自动运行（加载模型后无需额外代码）
- 头发/衣服/胸部物理随角色模型配置而定

### 6.5 实时动捕（远期）

```
主播开摄像头
      ↓
MediaPipe 实时提取骨骼（延迟<50ms，CPU可跑）
      ↓
WebSocket 推送骨骼数据到前端
      ↓
Three.js 实时驱动VRM角色
```

主播动作实时映射到NPC，彻底摆脱预录制动作库限制。

---

## 七、分阶段实施计划

### Phase 1 — 动作检索系统完善（已完成）

| 任务 | 状态 | 说明 |
|------|------|------|
| `action_catalog.json` 基础版 | ✅ 已完成 | 11个现有GLB已录入 |
| `action_retriever.py` 检索引擎 | ✅ 已完成 | 关键词TF-IDF，可升级向量 |
| `ai_action_planner.py` 对接检索 | ✅ 已完成 | 替换硬编码ACTION_FILES |
| `scan_action_catalog.py` 扫描工具 | ✅ 已完成 | 新增GLB自动生成草稿 |
| action_catalog 加 skeleton_type 字段 | ✅ 已完成 | 已添加humanoid类型 |
| ActionRetriever 加骨骼类型过滤 | ✅ 已完成 | skeleton_type前置过滤 |
| DeepSeek Vision 自动生成triggers | ✅ 已完成 | tools/autotag_actions.py |
| `character_skeletons.json` 角色注册表 | ✅ 已完成 | npc_01(VRM) + x_bot_mixamo(GLB) |
| `skeleton_types.json` 标准骨骼定义 | ✅ 已完成 | humanoid标准+Mixamo→VRM映射 |

### Phase 2 — VRM角色格式升级（已完成核心功能）

| 任务 | 状态 | 说明 |
|------|------|------|
| 引入 `@pixiv/three-vrm` 库 | ✅ 已完成 | CDN引入v2.1.3，兼容three.js r140 |
| 找1个VRM测试角色资源 | ✅ 已完成 | npc_01.vrm 已就位 |
| Mixamo→VRM 骨骼映射表 | ✅ 已完成 | config/skeleton_types.json mixamo_to_vrm |
| 动作重定向播放验证 | ✅ 已完成 | BoneRetargeter.js 实现 |
| 角色注册表 `character_skeletons.json` | ✅ 已完成 | 角色→骨骼类型映射 |
| 角色切换UI（场景编辑器+控制台） | ✅ 已完成 | 场景配置default_character + HUD选择器 |
| 控制台NPC加载VRM角色 | ✅ 已完成 | loadVRMCharacter + 自动识别格式 |

### Phase 3 — 表情与口型系统（已完成）

| 任务 | 状态 | 说明 |
|------|------|------|
| VRM表情接口封装 | ✅ 已完成 | ExpressionManager.js，AI情绪→表情映射 |
| 火山TTS Viseme时间轴接入 | ✅ 已完成 | LipSyncManager.parseVolcengineViseme() |
| 前端口型BlendShape插值 | ✅ 已完成 | aa/ih/ou/ee/oh 平滑过渡 |
| 表情+口型+骨骼三线并行 | ✅ 已完成 | 动画循环独立更新三个系统 |
| AI情绪标签解析 | ✅ 已完成 | [e:happy]标签 → setEmotion() |
| 自动眨眼 | ✅ 已完成 | ExpressionManager._updateBlink() |
| 口型测试序列 | ✅ 已完成 | playTest() A-I-U-E-O |

**待完善：**
- 后端TTS返回viseme时间轴（火山引擎extra参数需启用）
- 表情与口型的优先级管理（当前可叠加）

### Phase 4 — 动作资产管理平台（Studio编辑器扩展）（核心功能已完成）

| 任务 | 状态 | 说明 |
|------|------|------|
| 视频上传界面 | ✅ 已完成 | Studio编辑器新增"动作导入"Tab |
| MediaPipe后端处理接口 | ✅ 已完成 | `POST /api/motion/extract` |
| DeepSeek Vision打标签接口 | ✅ 已完成 | `POST /api/motion/autotag` |
| 待审核动作列表 | ✅ 已完成 | `GET /api/motion/drafts` |
| 人工审核界面（基础版） | ✅ 已完成 | 预览+编辑标签+确认入库 |
| 标准骨骼类型管理 | ✅ 已完成 | humanoid/quadruped/avian定义 |
| 完整MediaPipe提取实现 | ✅ 已完成 | tools/extract_motion.py 真正工作 |
| 骨骼预览可视化 | ✅ 已完成 | JSON格式动画数据可预览 |

**依赖已安装：**
```bash
✅ pip install mediapipe opencv-python numpy websockets
```

### Phase 5 — 实时动捕（核心功能已完成）

| 任务 | 状态 | 说明 |
|------|------|------|
| 前端MediaPipe集成 | ✅ 已完成 | WebcamMotionCapture.js |
| 骨骼数据WebSocket传输 | ✅ 已完成 | ws://localhost:8766 |
| VRM实时骨骼驱动 | ✅ 已完成 | applyMotionCaptureData() |
| 直播间动捕UI | ✅ 已完成 | HUD动捕开关+预览 |
| 主播端动捕发送 | ✅ 已完成 | MediaPipe→WebSocket发送端 |
| 消费端骨骼接收 | ✅ 已完成 | WebSocket消费端接收+应用 |

**依赖已安装：**
```bash
✅ pip install mediapipe opencv-python websockets
```

---

## 八、变更日志

| 日期 | 版本 | 主要变更 |
|------|------|---------|
| 2026-05-25 | v1.0 | 初始 8 阶段实施规划 |
| 2026-05-26 | v2.0 | 全面重写：反映多页面架构落地、编辑器v2全部已完成功能、明确未完成项及优先级 |
| 2026-05-28 | v3.0 | 新增NPC表演系统完整架构：VRM迁移方案、动作检索引擎、动作资产管理平台、表情口型系统、实时动捕规划 |
| 2026-05-28 | v3.1 | NPC表演系统核心功能全部完成：Phase 1-5 骨骼动画/口型/表情/资产管理/实时动捕 |
