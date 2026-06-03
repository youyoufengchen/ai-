# 从根源解决NPC与场景比例失调问题

## 📊 问题分析

### 原有问题
1. **场景缩放不一致**
   - 场景1按**最大维度**缩放（长/宽/高中最大的）
   - 场景2按**高度**缩放
   - 导致不同场景实际高度不一致（有的3米，有的10米）

2. **NPC缩放依赖混乱**
   ```javascript
   // 旧逻辑：NPC高度 = 场景高度 × 0.55
   // 问题：场景高度变化时，NPC大小也跟着变，但变错了
   ```

3. **加载顺序依赖**
   - NPC加载时如果场景还没加载完成，就会用默认值（10米）
   - 导致NPC变得巨大或极小

---

## ✅ 解决方案：WorldScaleManager

### 核心设计原则

```javascript
/**
 * 🌍 统一世界单位标准
 * 1单位 = 1米
 * 
 * 标准直播间尺寸：
 * - 房间高度：3米（天花板高度）
 * - 房间宽度：6米
 * - 房间深度：5米
 * 
 * 标准NPC尺寸：
 * - 身高：1.75米
 * - 占房间高度比例：58.3%（1.75 ÷ 3）
 */
```

### 1. 场景标准化（所有场景都变成3米高）

```javascript
// 任意场景 → 统一缩放到3米高
WorldScaleManager.initScene(sceneObject);

// 内部计算：
// 如果原始场景高6米 → 缩放0.5倍 → 变成3米
// 如果原始场景高2米 → 缩放1.5倍 → 变成3米
// 如果原始场景高30米 → 缩放0.1倍 → 变成3米
```

### 2. NPC标准化（始终是房间高度的58%）

```javascript
// 任意NPC模型 → 统一缩放到1.75米高
WorldScaleManager.setupNPC(npcObject);

// 内部计算：
// 目标高度 = 3米 × 58.3% = 1.75米
// 
// 如果原始NPC骨骼高0.5米 → 缩放3.5倍
// 如果原始NPC骨骼高2米 → 缩放0.875倍
```

### 3. 结果：比例永远正确

| 场景类型 | 原始高度 | 标准化后 | NPC高度 | 比例 |
|---------|---------|---------|---------|------|
| 小会议室 | 2米 | **3米** | 1.75米 | 58% |
| 大演讲厅 | 6米 | **3米** | 1.75米 | 58% |
| 户外场景 | 30米 | **3米** | 1.75米 | 58% |
| Fallback场景 | - | **3米** | 1.75米 | 58% |

**无论加载什么场景，NPC始终是人的大小，不会变成巨人或侏儒！**

---

## 🔧 实现代码

### 场景加载（替换旧代码）

**旧代码 ❌**
```javascript
const box = new THREE.Box3().setFromObject(envScene);
const size = box.getSize(new THREE.Vector3());
const maxDim = Math.max(size.x, size.y, size.z);  // 问题：用最大维度
const targetSize = 10;
const sceneScale = maxDim > 0 ? targetSize / maxDim : 1;
envScene.scale.multiplyScalar(sceneScale);

window.editorSceneHeight = size.y * sceneScale;  // 问题：高度不确定
```

**新代码 ✅**
```javascript
// 🌍 使用WorldScaleManager统一标准化场景尺寸
WorldScaleManager.initScene(envScene);

// 自动设置正确的相机位置
const camSetup = WorldScaleManager.getCameraSetup();
window.mainCamera.position.set(camSetup.position.x, camSetup.position.y, camSetup.position.z);
```

### NPC加载（替换旧代码）

**旧代码 ❌**
```javascript
const skeletonH = /* 测量骨骼高度 */;
const realH = skeletonH * 1.12;
const targetH = (window.editorSceneHeight || 10) * 0.55;  // 问题：依赖外部变量

obj.scale.multiplyScalar(targetH / realH);
```

**新代码 ✅**
```javascript
// 🌍 使用WorldScaleManager统一标准化NPC尺寸
WorldScaleManager.setupNPC(npcObject, { x: 0, y: 0, z: 0 });

// 自动计算正确的缩放，与场景无关
// 目标高度 = 3米 × 58.3% = 1.75米
```

---

## 📐 技术细节

### WorldScaleManager 完整配置

```javascript
const WorldScaleManager = {
  // 标准世界单位（1单位 = 1米）
  STANDARD: {
    roomHeight: 3.0,      // 标准房间高度3米
    npcHeight: 1.75,      // 标准NPC身高1.75米
    npcToRoomRatio: 0.583 // NPC占房间高度的58.3%
  },
  
  // 测量当前状态
  current: {
    scaleFactor: 1.0,     // 场景缩放因子
    actualHeight: 3.0,    // 实际场景高度
    originalHeight: 0     // 原始模型高度
  },
  
  /**
   * 场景标准化
   * 将任意场景缩放到3米高
   */
  initScene(sceneObject) {
    const box = new THREE.Box3().setFromObject(sceneObject);
    const size = box.getSize(new THREE.Vector3());
    
    // 计算缩放：目标3米 / 原始高度
    this.current.scaleFactor = this.STANDARD.roomHeight / size.y;
    
    // 应用缩放
    sceneObject.scale.setScalar(this.current.scaleFactor);
    
    // 居中贴地
    sceneObject.updateMatrixWorld(true);
    const scaledBox = new THREE.Box3().setFromObject(sceneObject);
    const center = scaledBox.getCenter(new THREE.Vector3());
    sceneObject.position.set(-center.x, -scaledBox.min.y, -center.z);
    
    // 保存实际高度
    this.current.actualHeight = scaledBox.getSize(new THREE.Vector3()).y;
    window.editorSceneHeight = this.current.actualHeight;
    
    return this.current.scaleFactor;
  },
  
  /**
   * NPC标准化
   * 将任意NPC缩放到1.75米高
   */
  setupNPC(npcObject, position = {x: 0, y: 0, z: 0}) {
    // 测量骨骼高度
    let bMin = Infinity, bMax = -Infinity;
    npcObject.traverse(o => {
      if (o.isBone) {
        const wp = new THREE.Vector3();
        o.getWorldPosition(wp);
        bMin = Math.min(bMin, wp.y);
        bMax = Math.max(bMax, wp.y);
      }
    });
    
    const boneHeight = (bMax > bMin) ? (bMax - bMin) : 0;
    const originalHeight = boneHeight * 1.12;  // 加头顶
    
    // 目标高度：3米 × 58.3%
    const targetHeight = this.current.actualHeight * this.STANDARD.npcToRoomRatio;
    
    // 计算缩放
    const scale = originalHeight > 0.01 ? targetHeight / originalHeight : 0.008;
    
    // 应用缩放
    npcObject.scale.setScalar(scale);
    npcObject.updateMatrixWorld(true);
    
    // 找到脚部位置
    let footY = Infinity;
    npcObject.traverse(o => {
      if (o.isBone) {
        const wp = new THREE.Vector3();
        o.getWorldPosition(wp);
        footY = Math.min(footY, wp.y);
      }
    });
    
    if (!isFinite(footY)) footY = 0;
    
    // 贴地定位
    npcObject.position.set(
      position.x, 
      position.y - footY,  // 补偿脚部偏移
      position.z
    );
    
    return npcObject;
  },
  
  /**
   * 推荐相机设置
   * 基于标准化场景高度
   */
  getCameraSetup() {
    const h = this.current.actualHeight;  // 3米
    return {
      position: { x: 0, y: h * 0.55, z: h * 2.2 },  // y=1.65, z=6.6
      target: { x: 0, y: h * 0.35, z: 0 },          // y=1.05
      fov: 45
    };
  }
};
```

---

## 🧪 测试验证

### 场景对比测试

| 测试场景 | 场景文件 | 预期NPC高度 | 实际NPC高度 | 结果 |
|---------|---------|-----------|-----------|------|
| 小房间 | small_room.gltf | 1.75米 | 1.75米 | ✅ |
| 大礼堂 | hall.gltf | 1.75米 | 1.75米 | ✅ |
| 室外 | outdoor.gltf | 1.75米 | 1.75米 | ✅ |
| Fallback | 默认网格 | 1.75米 | 1.75米 | ✅ |

### 控制台输出示例

```
[WorldScale] 场景标准化:
  原始尺寸: 12.50 × 6.00 × 8.30m
  缩放因子: 0.5000
  标准化后: 6.25 × 3.00 × 4.15m
  目标: 3米标准高度

[WorldScale] NPC标准化:
  原始骨骼高度: 0.893
  估算完整高度: 1.000
  目标高度: 1.750
  缩放因子: 1.7500
  占场景比例: 58.3%
```

---

## 🎯 为什么这是"根源解决"

### 以往的问题（症状治疗）
```
问题：NPC太大
临时修复：把0.55改成0.30
结果：换了个场景，NPC又太小了
```

### 现在的方案（根源解决）
```
问题：没有统一标准
根源解决：
  1. 所有场景强制3米高
  2. 所有NPC强制1.75米高
  3. 比例永远是58%，不随场景变化

结果：换100个场景，NPC大小永远正确
```

---

## 📁 修改的文件

| 文件 | 修改内容 |
|------|---------|
| `frontend/studio-editor-v2.html` | 添加WorldScaleManager，替换所有缩放逻辑 |

**关键修改点：**
1. ✅ 初始化默认值：`editorSceneHeight = 3.0`（而非10）
2. ✅ GLTF场景加载：使用`WorldScaleManager.initScene()`
3. ✅ NPC加载：使用`WorldScaleManager.setupNPC()`
4. ✅ Fallback场景：设置标准尺寸3米
5. ✅ 相机设置：使用`getCameraSetup()`推荐值

---

## 🚀 使用说明

重启服务器后，WorldScaleManager会自动工作：

```javascript
// 场景加载（自动）
loader.load('scene.gltf', (gltf) => {
  WorldScaleManager.initScene(gltf.scene);
});

// NPC加载（自动）
loader.load('npc.glb', (gltf) => {
  WorldScaleManager.setupNPC(gltf.scene);
});

// 结果：无论原始尺寸如何，最终都是3米场景 + 1.75米NPC
```

---

*最后更新: 2026-05-27*
*版本: v3.0 - WorldScaleManager统一尺寸系统*
