# 宝青坊 - 虚拟主播直播带货系统

> 基于事件驱动的智能素材调度系统，支持多平台直播间矩阵运营

## 项目结构

```
project/
├── server.py                # Python 主服务（WebSocket + REST API）
├── requirements.txt         # Python 依赖
├── README.md                # 本文档
│
├── config/                  # 配置文件
│   ├── main.json            # 主配置
│   ├── skus.json            # 商品库
│   └── characters.json      # 角色与风格定义
│
├── frontend/                # 前端展示层
│   ├── index.html           # 主直播间页面
│   ├── control.html         # 运营控制面板
│   ├── app.js               # 核心逻辑
│   └── style.css            # UI样式（古风美化版）
│
├── modules/                 # Python 业务模块
│   ├── __init__.py
│   ├── ai_service.py        # DeepSeek AI对话服务 ✓
│   ├── tts_service.py       # 火山引擎TTS服务 ✓
│   └── douyin_danmaku.py    # 抖音弹幕抓取模块 ✓
│
└── assets/                  # 素材库
    ├── scenes/              # 场景背景
    ├── host/                # 角色视频（多风格）
    ├── products/            # 商品素材（按 SKU 分目录）
    └── cache/tts/           # TTS音频缓存
```

## 快速启动

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 API Key

复制环境变量模板并填入你的密钥：

```bash
# Windows
copy .env.example .env

# Mac/Linux
cp .env.example .env
```

然后编辑 `.env` 文件：

```bash
# 必填：DeepSeek API Key（从 https://platform.deepseek.com/ 获取）
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# 可选：火山引擎TTS（不填则使用浏览器TTS降级）
VOLC_TTS_APPID=your-app-id
VOLC_TTS_TOKEN=your-token
```

> ⚠️ `.env` 文件已加入 `.gitignore`，不会上传到Git，安全存储你的密钥。

### 3. 准备最小素材（用于测试）

在 `assets/` 下放入以下占位素材（任何 mp4/png 都行，先跑通流程）：

```
assets/scenes/bg_tea_shop.jpg              # 任意一张背景图
assets/host/classical_01_idle.mp4          # 一段角色待机视频（5-10秒循环）
assets/host/classical_03_fetch_turn.mp4    # 转身拿货视频
assets/host/classical_04_fetch_return.mp4  # 拿回展示视频
assets/host/classical_05_present.mp4       # 介绍商品视频
assets/products/tea_001/shelf.png          # 任意商品图
assets/products/tea_001/hand.png
assets/products/tea_001/table.png
assets/products/tea_001/intro.mp4          # 任意一段视频当作产品介绍
```

> 测试期可以让所有视频指向同一个文件，先验证切换逻辑。

### 3. 启动服务

```bash
python server.py
```

服务启动后会输出：
```
[Server] HTTP server: http://localhost:8080
[Server] WebSocket: ws://localhost:8765
[Server] Config loaded: 3 SKUs
```

### 4. 打开前端

浏览器访问：`http://localhost:8080`

应该看到：背景图 + 角色播放 idle 视频。

### 5. 测试触发动作

打开另一个终端，发送测试指令：

```bash
# 触发"商品询问"流程（角色去拿茶并介绍）
curl -X POST http://localhost:8080/api/test/trigger -H "Content-Type: application/json" -d "{\"intent\":\"product_query\",\"sku_id\":\"tea_001\"}"

# 触发欢迎
curl -X POST http://localhost:8080/api/test/trigger -H "Content-Type: application/json" -d "{\"intent\":\"user_enter\",\"username\":\"测试客官\"}"

# 触发下单感谢
curl -X POST http://localhost:8080/api/test/trigger -H "Content-Type: application/json" -d "{\"intent\":\"order_placed\",\"username\":\"测试客官\",\"sku_id\":\"tea_001\"}"
```

观察浏览器画面切换。

## 访问地址

| 页面 | 地址 | 说明 |
|------|------|------|
| 直播间 | http://localhost:8080/ | OBS采集源 |
| 控制面板 | http://localhost:8080/control | 运营控制台 |

## 开发进度

- [x] **Phase 1**：项目骨架 + 前端展示 + WebSocket通信
- [x] **Phase 1.5**：状态机 + 事件队列 + 弹窗系统 ✓
- [x] **Phase 2**：DeepSeek AI对话 + TTS（浏览器降级）✓
- [x] **Phase 2.5**：UI美化 + 风格切换 + 控制面板 ✓
- [x] **Phase 3**：弹幕抓取模块（模拟模式）✓
- [ ] **Phase 3.5**：聚水潭API（待开放平台审核）
- [ ] **Phase 4**：真实抖音弹幕抓取
- [ ] **Phase 5**：多平台扩展

## UI美化特性

- ✨ 玻璃拟态（Glassmorphism）弹窗效果
- 🎨 CSS变量统一管理古风配色
- 💫 入场/切换动画（淡入、滑动、缩放）
- 🏮 货架呼吸灯高亮效果
- 🌊 背景微动效（呼吸明暗）
- 📦 手持物品悬浮动画

## 运行环境

- Python 3.10+
- Chrome 浏览器（推荐用 OBS 采集）
- Windows / Mac / Linux 均可
- 无需火山TTS（浏览器TTS已降级支持）

## 详细架构

参考 `项目总体架构文档.md`
