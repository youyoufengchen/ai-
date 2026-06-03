# 3D 虚拟演播室搭建指南

## 概述

这个3D虚拟演播室系统可以将你原有的2D直播场景升级为3D沉浸式环境，类似新闻演播室的效果：

- **真3D场景**：可旋转、缩放、自动环绕展示
- **NPC视频纹理**：无需绿幕抠像，直接作为3D物体显示
- **虚拟大屏**：展示商品图片/视频
- **多场景切换**：古风茶室 / 新闻演播室 / 现代直播间

---

## 快速开始

### 1. 启动服务

```bash
cd "d:\新建文件夹 (2)"
.venv\Scripts\activate
python server.py
```

### 2. 访问3D版本

打开浏览器访问：
```
http://localhost:8000/frontend/index-3d.html
```

（原有2D版本仍在 `http://localhost:8000/frontend/index.html`）

### 3. 交互操作

| 操作 | 效果 |
|------|------|
| **鼠标拖拽** | 旋转视角，环绕NPC观看 |
| **滚轮** | 缩放（FOV调整） |
| **底部按钮** | 切换场景风格 |
| **自动旋转** | 开启/关闭场景自动环绕 |

---

## 技术架构

### 与原有系统的兼容

```
┌─────────────────────────────────────────────────────────────┐
│                      后端（Python）                          │
│  server.py → WebSocket → 原有指令协议（完全兼容）            │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    前端（浏览器）                              │
│  ┌─────────────────────────────────────────────────────────┐│
│  │ 3D渲染层（Three.js）                                     ││
│  │ - 场景渲染                                               ││
│  │ - NPC视频纹理                                            ││
│  │ - 虚拟大屏                                               ││
│  └─────────────────────────────────────────────────────────┘│
│  ┌─────────────────────────────────────────────────────────┐│
│  │ UI层（HTML/CSS）                                         ││
│  │ - 弹窗卡片                                               ││
│  │ - 字幕显示                                               ││
│  │ - 特效层                                                 ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

### 核心文件

| 文件 | 作用 |
|------|------|
| `frontend/scene3d.js` | 3D演播室核心类，Three.js渲染 |
| `frontend/app-3d.js` | 对接WebSocket，兼容原有指令 |
| `frontend/index-3d.html` | 3D版本入口页面 |

---

## 3D 场景配置

### 内置场景

1. **古风茶室** (`tea_shop`)
   - 茶桌、屏风、传统装饰
   - 暖色调灯光
   - 适合茶叶、文创类产品

2. **新闻演播室** (`news_studio`)
   - 主播台、环形灯带、LED背景墙
   - 冷色调专业灯光
   - 适合高端产品介绍

3. **现代直播间** (`modern_office`)
   - 简约装饰、几何元素
   - 中性色调
   - 通用型场景

### 场景切换

```javascript
// 在浏览器控制台测试
window.switchScene3D('tea_shop');
window.switchScene3D('news_studio');
window.switchScene3D('modern_office');
```

---

## NPC视频集成

### 现有视频素材直接使用

你现有的绿幕视频可以直接作为3D纹理使用：

```javascript
// 设置待机动作
studio.setNPCVideo('/assets/host/classical_01_idle.mp4');

// 切换打招呼动作
studio.switchNPCVideo('/assets/host/classical_02_greet.mp4');
```

**注意**：3D模式下不需要绿幕抠像，视频直接贴在3D平面上，但建议使用带透明通道的视频（WebM格式）效果更佳。

### 推荐视频格式

| 格式 | 优点 | 缺点 |
|------|------|------|
| MP4 (绿幕) | 兼容性好，可直接用现有素材 | 边缘可能有绿色溢出 |
| WebM (Alpha) | 真透明，效果最好 | 需要重新导出 |

---

## 虚拟大屏

### 显示商品图片

```javascript
studio.setScreenContent('image', '/assets/products/tea_001/table.png');
```

### 播放产品介绍视频

```javascript
studio.setScreenContent('video', '/assets/products/tea_001/intro.mp4');
```

---

## OBS 推流配置

### 采集设置

1. **窗口采集**：采集浏览器窗口
2. **无需色度键**：3D模式下NPC已经是合成的，不需要抠像
3. **音频**：桌面音频采集浏览器的TTS输出

### 分辨率建议

```
画布分辨率: 1920x1080
输出分辨率: 1920x1080
帧率: 30fps
```

---

## 性能优化

### 浏览器要求

- **推荐**：Chrome / Edge 最新版（WebGL 2.0支持）
- **最低**：支持WebGL的浏览器

### 硬件要求

| 配置 | 效果 |
|------|------|
| 独立显卡 | 流畅60fps，可开抗锯齿 |
| 集成显卡 | 30fps，建议降低分辨率 |

### 优化选项

在 `scene3d.js` 中可以调整：

```javascript
// 降低渲染分辨率（提升性能）
this.renderer.setPixelRatio(1);  // 默认是Math.min(window.devicePixelRatio, 2)

// 关闭阴影
this.renderer.shadowMap.enabled = false;

// 降低场景复杂度
// 修改 createEnvironment() 减少物体数量
```

---

## 扩展开发

### 添加新场景

在 `scene3d.js` 的 `scenes` 配置中添加：

```javascript
my_custom_scene: {
  name: '我的场景',
  background: 0xffffff,
  fog: 0xffffff,
  cameraPos: { x: 0, y: 1.6, z: 4 },
  npcPos: { x: 0, y: 0, z: 0 },
  screenPos: { x: -2, y: 1.5, z: -1 },
  ambientLight: 0.6,
  directionalLight: 0.8
}
```

然后添加对应的装饰函数 `createMyDecor()`。

### 自定义NPC模型

替换 `createNPCPlaceholder()` 中的平面几何体：

```javascript
// 使用3D模型代替平面
const loader = new THREE.GLTFLoader();
loader.load('/assets/models/npc.glb', (gltf) => {
  this.npcMesh = gltf.scene;
  this.scene.add(this.npcMesh);
});
```

---

## 常见问题

### Q: 3D场景不显示？

检查：
1. 浏览器是否支持WebGL（访问 https://get.webgl.org/ 测试）
2. 控制台是否有错误信息
3. Three.js CDN是否加载成功

### Q: NPC视频不显示？

检查：
1. 视频路径是否正确
2. 视频是否跨域（需要CORS配置）
3. 视频格式是否支持（H.264编码的MP4兼容性最好）

### Q: 性能卡顿？

优化方案：
1. 关闭浏览器其他标签页
2. 在 `scene3d.js` 中降低 `setPixelRatio`
3. 简化场景装饰（减少几何体数量）

### Q: 如何回退到2D模式？

直接访问原有地址：
```
http://localhost:8000/frontend/index.html
```

---

## 下一步建议

1. **测试现有视频在3D场景中的效果**
2. **尝试不同场景切换**
3. **调整NPC位置和虚拟大屏位置**
4. **考虑制作WebM透明通道视频提升效果**
5. **OBS推流测试**

---

## 参考资源

- [Three.js 文档](https://threejs.org/docs/)
- [WebGL 基础](https://webglfundamentals.org/)
- [抖音直播伴侣](https://streamingtool.douyin.com/)
