# 场景物体管理模块设计方案

## 📋 需求分析

### 当前问题
从截图可以看到，右侧虽然有物体管理，但左侧边栏缺少一个**快速访问当前场景所有物体**的模块。

### 功能目标
1. **快速查看**：所有场景物体的层级列表
2. **快速选择**：点击列表项选中3D物体
3. **快速操作**：显示/隐藏、删除、聚焦
4. **层级管理**：父子关系展示

---

## 🎨 界面设计

### 位置
放在左侧边栏，**"3D场景空间"下方**，"场景快照预设"上方

```
┌─────────────────────────────┐
│ 🌅 3D场景空间 ▶            │
├─────────────────────────────┤
│ 🎯 场景物体 ▼              │  ← 新增模块
│ ┌─────────────────────────┐ │
│ │ 🔍 搜索物体...         │ │
│ ├─────────────────────────┤ │
│ │ 类型筛选: [全部▼]      │ │
│ ├─────────────────────────┤ │
│ │ 📁 货架 (3)            │ │
│ │   ├── 🛒 主货架        │ │
│ │   ├── 🛒 左侧架    👁️ ✕ │ │
│ │   └── 🛒 右侧架    👁️ ✕ │ │
│ │                         │ │
│ │ 📦 道具 (2)            │ │
│ │   ├── 📦 展示台        │ │
│ │   └── 📦 装饰花瓶  👁️ ✕│ │
│ │                         │ │
│ │ 🎭 NPC固定点 (1)      │ │
│ │   └── 🎭 主播位置      │ │
│ │                         │ │
│ │ 💡 灯光 (2)            │ │
│ │   ├── 💡 主光源        │ │
│ │   └── 💡 补光          │ │
│ └─────────────────────────┘ │
├─────────────────────────────┤
│ 🎬 直播快照预设 ▶          │
└─────────────────────────────┘
```

---

## 🔧 功能规格

### 1. 数据结构
```javascript
// 场景物体数据结构
SceneObject = {
  id: "unique-id",           // 唯一标识
  name: "主货架",            // 显示名称
  type: "shelf",             // 类型: shelf/prop/npc/light/camera
  icon: "🛒",                // 类型图标
  visible: true,             // 是否可见
  selected: false,           // 是否选中
  parent: null,              // 父物体ID
  children: [],              // 子物体ID数组
  threeObject: Object3D,     // 引用Three.js对象
  metadata: {                // 扩展数据
    skuId: "xxx",
    productName: "xxx"
  }
}
```

### 2. 分类体系
```javascript
const ObjectCategories = {
  SHELF:     { id: 'shelf',   label: '货架',      icon: '🛒', color: '#4fc3f7' },
  PROP:      { id: 'prop',    label: '道具',      icon: '📦', color: '#81c784' },
  NPC:       { id: 'npc',     label: 'NPC固定点', icon: '🎭', color: '#ffb74d' },
  LIGHT:     { id: 'light',   label: '灯光',      icon: '💡', color: '#ffd54f' },
  CAMERA:    { id: 'camera',  label: '相机',      icon: '📷', color: '#e0e0e0' },
  ENV:       { id: 'env',     label: '环境',      icon: '🌍', color: '#9fa8da' },
  OTHER:     { id: 'other',   label: '其他',      icon: '🔹', color: '#b0bec5' }
};
```

### 3. 核心功能

| 功能 | 交互方式 | 说明 |
|------|---------|------|
| **展开/折叠** | 点击分类标题 | 折叠某类物体 |
| **选择物体** | 点击列表项 | 3D视口中选中并聚焦 |
| **显示/隐藏** | 点击👁️图标 | 切换visible属性 |
| **删除物体** | 点击✕图标 | 从场景移除 |
| **聚焦物体** | 双击列表项 | 相机聚焦到该物体 |
| **搜索过滤** | 输入关键词 | 按名称过滤 |
| **类型筛选** | 下拉选择 | 只显示某类物体 |
| **层级拖拽** | 拖拽物体 | 调整父子关系 |

---

## 💻 实现代码规划

### HTML结构
```html
<!-- 🎯 场景物体管理（可折叠） -->
<div class="sidebar-section collapsible" data-section="objects" style="padding:0;border-bottom:1px solid rgba(255,255,255,0.06);flex-shrink:0;max-height:350px;">
  <div class="section-header" onclick="toggleSection('objects')" style="padding:10px 12px;display:flex;justify-content:space-between;align-items:center;cursor:pointer;user-select:none;">
    <span style="font-size:12px;color:#c9a55c;display:flex;align-items:center;gap:6px;">🎯 场景物体</span>
    <div style="display:flex;align-items:center;gap:8px;" onclick="event.stopPropagation()">
      <span id="object-count-badge" style="font-size:10px;padding:2px 6px;background:rgba(201,165,92,0.2);color:#c9a55c;border-radius:10px;">0</span>
      <span class="section-toggle" style="font-size:10px;color:var(--text-3);margin-left:4px;">▶</span>
    </div>
  </div>
  <div class="section-content" id="section-objects" style="padding:8px 12px 12px;display:none;">
    <!-- 搜索框 -->
    <div style="display:flex;gap:6px;margin-bottom:8px;">
      <input type="text" id="object-search" placeholder="🔍 搜索物体..." 
             style="flex:1;background:#15151c;border:1px solid rgba(255,255,255,0.08);color:var(--text);padding:4px 8px;border-radius:4px;font-size:11px;"
             oninput="filterSceneObjects(this.value)">
    </div>
    
    <!-- 类型筛选 -->
    <div style="display:flex;gap:6px;margin-bottom:8px;align-items:center;">
      <span style="font-size:10px;color:var(--text-3);">筛选:</span>
      <select id="object-type-filter" onchange="filterByType(this.value)"
              style="flex:1;background:#15151c;border:1px solid rgba(255,255,255,0.08);color:var(--text);padding:3px 6px;border-radius:4px;font-size:11px;">
        <option value="all">全部类型</option>
        <option value="shelf">🛒 货架</option>
        <option value="prop">📦 道具</option>
        <option value="npc">🎭 NPC点</option>
        <option value="light">💡 灯光</option>
      </select>
    </div>
    
    <!-- 物体列表容器 -->
    <div id="scene-objects-container" 
         style="display:flex;flex-direction:column;gap:2px;min-height:40px;max-height:250px;overflow-y:auto;font-size:11px;">
      <div style="text-align:center;color:var(--text-3);padding:15px;font-size:11px;">
        暂无物体，从右侧添加
      </div>
    </div>
  </div>
</div>
```

### JavaScript核心逻辑
```javascript
// ═══════════════════════════════════════════════════════════
//  🎯 场景物体管理模块
// ═══════════════════════════════════════════════════════════
const SceneObjectsManager = {
  // 物体数据存储
  objects: new Map(),  // id -> SceneObject
  
  // 初始化
  init() {
    this.bindToThreeScene();
    this.renderList();
    console.log('[SceneObjects] 管理器已初始化');
  },
  
  // 从Three.js场景同步物体
  bindToThreeScene() {
    if (!window.mainScene) return;
    
    // 遍历场景中的所有物体
    window.mainScene.traverse((obj) => {
      // 跳过系统对象
      if (obj.name.startsWith('__') || !obj.userData.editable) return;
      
      // 识别物体类型
      const type = this.detectObjectType(obj);
      if (type) {
        this.addObject({
          id: obj.uuid,
          name: obj.name || `${type.label}_${this.objects.size + 1}`,
          type: type.id,
          icon: type.icon,
          visible: obj.visible,
          threeObject: obj
        });
      }
    });
  },
  
  // 识别物体类型
  detectObjectType(obj) {
    // 根据userData或名称模式识别
    if (obj.userData.type === 'shelf' || obj.name.includes('shelf')) 
      return ObjectCategories.SHELF;
    if (obj.userData.type === 'prop' || obj.name.includes('prop')) 
      return ObjectCategories.PROP;
    if (obj.userData.type === 'npc' || obj.name.includes('npc')) 
      return ObjectCategories.NPC;
    if (obj.isLight) return ObjectCategories.LIGHT;
    if (obj.isCamera) return ObjectCategories.CAMERA;
    
    // 默认：如果是Mesh且有可编辑标记
    if (obj.isMesh && obj.userData.editable) 
      return ObjectCategories.OTHER;
    
    return null;
  },
  
  // 添加物体
  addObject(data) {
    this.objects.set(data.id, {
      ...data,
      children: [],
      parent: null
    });
    this.renderList();
  },
  
  // 移除物体
  removeObject(id) {
    const obj = this.objects.get(id);
    if (obj && obj.threeObject) {
      // 从Three.js场景中移除
      obj.threeObject.parent.remove(obj.threeObject);
    }
    this.objects.delete(id);
    this.renderList();
  },
  
  // 切换可见性
  toggleVisibility(id) {
    const obj = this.objects.get(id);
    if (obj && obj.threeObject) {
      obj.visible = !obj.visible;
      obj.threeObject.visible = obj.visible;
      this.renderList();
    }
  },
  
  // 选中物体
  selectObject(id) {
    // 清除其他选中状态
    this.objects.forEach(obj => obj.selected = false);
    
    const obj = this.objects.get(id);
    if (obj) {
      obj.selected = true;
      
      // 在3D视口中选中
      if (obj.threeObject && window.selectObject3D) {
        window.selectObject3D(obj.threeObject);
      }
      
      // 聚焦相机
      this.focusOnObject(id);
    }
    
    this.renderList();
  },
  
  // 相机聚焦
  focusOnObject(id) {
    const obj = this.objects.get(id);
    if (!obj || !obj.threeObject || !window.mainCamera) return;
    
    // 获取物体位置
    const target = new THREE.Vector3();
    obj.threeObject.getWorldPosition(target);
    
    // 计算相机位置（物体前方2米，稍高）
    const offset = new THREE.Vector3(0, 1, 3);
    const cameraPos = target.clone().add(offset);
    
    // 平滑移动相机
    this.animateCamera(cameraPos, target);
  },
  
  // 相机动画
  animateCamera(position, target) {
    const startPos = window.mainCamera.position.clone();
    const startTarget = window.mainControls.target.clone();
    let progress = 0;
    
    const animate = () => {
      progress += 0.05;
      if (progress >= 1) progress = 1;
      
      // 插值
      window.mainCamera.position.lerpVectors(startPos, position, progress);
      window.mainControls.target.lerpVectors(startTarget, target, progress);
      window.mainControls.update();
      
      if (progress < 1) requestAnimationFrame(animate);
    };
    
    animate();
  },
  
  // 渲染列表
  renderList() {
    const container = document.getElementById('scene-objects-container');
    if (!container) return;
    
    // 获取搜索和筛选条件
    const searchTerm = document.getElementById('object-search')?.value?.toLowerCase() || '';
    const typeFilter = document.getElementById('object-type-filter')?.value || 'all';
    
    // 过滤物体
    let filtered = Array.from(this.objects.values()).filter(obj => {
      const matchSearch = obj.name.toLowerCase().includes(searchTerm);
      const matchType = typeFilter === 'all' || obj.type === typeFilter;
      return matchSearch && matchType;
    });
    
    // 按类型分组
    const grouped = this.groupByType(filtered);
    
    // 更新计数
    const countBadge = document.getElementById('object-count-badge');
    if (countBadge) countBadge.textContent = this.objects.size;
    
    // 生成HTML
    if (filtered.length === 0) {
      container.innerHTML = '<div style="text-align:center;color:var(--text-3);padding:20px;font-size:11px;">没有匹配的物体</div>';
      return;
    }
    
    container.innerHTML = Object.entries(grouped).map(([typeId, items]) => {
      const type = ObjectCategories[typeId.toUpperCase()] || ObjectCategories.OTHER;
      const isExpanded = items.some(i => i.selected) || items.length <= 3;
      
      return `
        <div class="object-group" data-type="${typeId}" style="margin-bottom:4px;">
          <!-- 分类标题 -->
          <div onclick="SceneObjectsManager.toggleGroup('${typeId}')" 
               style="display:flex;align-items:center;gap:4px;padding:4px 6px;background:rgba(255,255,255,0.02);border-radius:3px;cursor:pointer;font-size:10px;color:${type.color};font-weight:500;">
            <span class="group-toggle" style="transition:transform 0.2s;${isExpanded ? 'transform:rotate(90deg)' : ''}">▶</span>
            <span>${type.icon} ${type.label}</span>
            <span style="margin-left:auto;color:var(--text-3);font-size:9px;">${items.length}</span>
          </div>
          
          <!-- 物体列表 -->
          <div class="group-items" data-type="${typeId}" 
               style="display:${isExpanded ? 'flex' : 'none'};flex-direction:column;gap:1px;padding-left:12px;margin-top:2px;">
            ${items.map(item => `
              <div onclick="SceneObjectsManager.selectObject('${item.id}')"
                   style="display:flex;align-items:center;gap:6px;padding:4px 6px;border-radius:3px;cursor:pointer;font-size:11px;color:var(--text);${item.selected ? 'background:rgba(201,165,92,0.15);border:1px solid rgba(201,165,92,0.3);' : 'border:1px solid transparent;'}"
                   onmouseenter="this.style.background='rgba(255,255,255,0.05)'" 
                   onmouseleave="this.style.background='${item.selected ? 'rgba(201,165,92,0.15)' : 'transparent'}'">
                <span style="font-size:10px;">${item.icon}</span>
                <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${item.name}</span>
                
                <!-- 操作按钮 -->
                <div style="display:flex;gap:4px;opacity:0;transition:opacity 0.2s;" class="object-actions">
                  <span onclick="event.stopPropagation();SceneObjectsManager.toggleVisibility('${item.id}')" 
                        style="cursor:pointer;font-size:11px;${item.visible ? '' : 'opacity:0.3;'}">👁️</span>
                  <span onclick="event.stopPropagation();SceneObjectsManager.focusOnObject('${item.id}')" 
                        style="cursor:pointer;font-size:11px;">🎯</span>
                  <span onclick="event.stopPropagation();SceneObjectsManager.removeObject('${item.id}')" 
                        style="cursor:pointer;font-size:11px;color:#e57373;">✕</span>
                </div>
              </div>
            `).join('')}
          </div>
        </div>
      `;
    }).join('');
    
    // 添加悬停效果（显示操作按钮）
    container.querySelectorAll('.object-group > .group-items > div').forEach(el => {
      el.addEventListener('mouseenter', () => {
        const actions = el.querySelector('.object-actions');
        if (actions) actions.style.opacity = '1';
      });
      el.addEventListener('mouseleave', () => {
        const actions = el.querySelector('.object-actions');
        if (actions) actions.style.opacity = '0';
      });
    });
  },
  
  // 按类型分组
  groupByType(items) {
    return items.reduce((acc, item) => {
      if (!acc[item.type]) acc[item.type] = [];
      acc[item.type].push(item);
      return acc;
    }, {});
  },
  
  // 切换分组展开
  toggleGroup(typeId) {
    const group = document.querySelector(`.group-items[data-type="${typeId}"]`);
    const toggle = document.querySelector(`.object-group[data-type="${typeId}"] .group-toggle`);
    if (group) {
      const isHidden = group.style.display === 'none';
      group.style.display = isHidden ? 'flex' : 'none';
      if (toggle) toggle.style.transform = isHidden ? 'rotate(90deg)' : '';
    }
  }
};

// 暴露到全局
window.SceneObjectsManager = SceneObjectsManager;

// 辅助函数：过滤和搜索
function filterSceneObjects(keyword) {
  SceneObjectsManager.renderList();
}

function filterByType(type) {
  SceneObjectsManager.renderList();
}
```

### CSS样式补充
```css
/* 物体列表样式 */
#scene-objects-container {
  scrollbar-width: thin;
  scrollbar-color: rgba(255,255,255,0.1) transparent;
}

#scene-objects-container::-webkit-scrollbar {
  width: 4px;
}

#scene-objects-container::-webkit-scrollbar-thumb {
  background: rgba(255,255,255,0.1);
  border-radius: 2px;
}

/* 选中物体高亮 */
.object-selected {
  background: rgba(201, 165, 92, 0.15) !important;
  border: 1px solid rgba(201, 165, 92, 0.3) !important;
}

/* 隐藏物体淡化 */
.object-hidden {
  opacity: 0.4;
  text-decoration: line-through;
}
```

---

## 🔗 与其他模块的集成

### 1. 与右侧物体管理面板同步
```javascript
// 当选中左侧列表中的物体时，自动展开右侧属性面板
SceneObjectsManager.selectObject = function(id) {
  // ...原有代码...
  
  // 同步到右侧属性面板
  if (window.ShelfEditor && window.ShelfEditor.loadFromObject) {
    window.ShelfEditor.loadFromObject(obj.threeObject);
  }
};
```

### 2. 与3D视口交互
```javascript
// 在3D视口中点击物体时，同步选中左侧列表
window.selectObject3D = function(threeObject) {
  // 查找对应的列表项
  const entry = Array.from(SceneObjectsManager.objects.values())
    .find(o => o.threeObject === threeObject);
  
  if (entry) {
    SceneObjectsManager.selectObject(entry.id);
  }
};
```

### 3. 场景变化自动刷新
```javascript
// 当添加/删除物体时，自动刷新列表
window.addEventListener('scene-changed', () => {
  SceneObjectsManager.bindToThreeScene();
});
```

---

## 📊 数据结构关系

```
SceneObjectsManager
├── objects: Map<id, SceneObject>
│   └── SceneObject
│       ├── id, name, type, icon
│       ├── visible, selected
│       ├── parent, children
│       └── threeObject (引用)
│
├── Three.js Scene
│   ├── Object3D (userData.editable = true)
│   ├── Object3D
│   └── Object3D
│
└── UI Components
    ├── 搜索框 (filterSceneObjects)
    ├── 类型筛选 (filterByType)
    ├── 分组列表 (renderList)
    └── 操作按钮 (toggle/select/focus/remove)
```

---

## 🎯 实现步骤

1. **添加HTML结构**到左侧边栏（在"3D场景空间"和"场景快照预设"之间）
2. **添加CSS样式**到style标签
3. **添加JavaScript逻辑**到script标签
4. **在场景加载完成后初始化**：`SceneObjectsManager.init()`
5. **绑定事件监听**：场景变化时自动刷新列表

---

## ✅ 验收标准

- [ ] 左侧边栏显示"🎯 场景物体"模块
- [ ] 自动列出场景中所有可编辑物体
- [ ] 按类型（货架/道具/NPC/灯光）分组显示
- [ ] 显示物体数量统计
- [ ] 点击列表项选中3D物体
- [ ] 双击聚焦相机到物体
- [ ] 👁️按钮控制显示/隐藏
- [ ] ✕按钮删除物体
- [ ] 搜索框实时过滤
- [ ] 类型筛选下拉菜单
- [ ] 与右侧属性面板同步

---

*规划完成时间: 2026-05-27*
*版本: v1.0*
