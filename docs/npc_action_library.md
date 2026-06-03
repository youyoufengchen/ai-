# NPC动作库配置清单

## 概述
本系统支持4种移动模式，需要配套的动作库支持。

## 移动模式

| 模式 | ID | 说明 |
|------|-----|------|
| 行走 | `walk` | 地面行走，使用NavMesh避障 |
| 飞行 | `fly` | 3D空间移动，有起飞/降落阶段 |
| 攀爬 | `climb` | 爬楼梯/梯子，路径点移动 |
| 伸长 | `extend` | 手臂伸长特效，主体不动 |

---

## 基础动作库（必需）

### 1. 行走动作组
| 动作ID | 名称 | 时长 | 循环 | 说明 |
|--------|------|------|------|------|
| `idle` | 待机 | 2-5s | ✅ | 站立呼吸/小动作 |
| `walk_loop` | 行走循环 | 1-2s | ✅ | 基础行走动画 |
| `run_loop` | 奔跑循环 | 0.8s | ✅ | 快速移动 |
| `walk_stop` | 停止行走 | 0.5s | ❌ | 从行走到站立 |

### 2. 飞行动作组
| 动作ID | 名称 | 时长 | 循环 | 说明 |
|--------|------|------|------|------|
| `takeoff` | 起飞 | 1-2s | ❌ | 从地面到空中 |
| `fly_loop` | 飞行动作循环 | 1-3s | ✅ | 空中悬浮/飞行姿态 |
| `land` | 降落 | 1-2s | ❌ | 从空中到地面 |
| `fly_turn` | 飞行转向 | 0.5s | ❌ | 空中转向 |

### 3. 攀爬动作组
| 动作ID | 名称 | 时长 | 循环 | 说明 |
|--------|------|------|------|------|
| `climb_start` | 攀爬开始 | 1s | ❌ | 准备攀爬姿态 |
| `climb_loop` | 攀爬循环 | 1-2s | ✅ | 持续攀爬动作 |
| `climb_end` | 攀爬结束 | 0.8s | ❌ | 到达顶部站立 |
| `climb_down` | 向下攀爬 | 1s | ✅ | 向下爬的特殊动画 |

### 4. 手臂伸长特效动作组（独特能力）
| 动作ID | 名称 | 时长 | 循环 | 说明 |
|--------|------|------|------|------|
| `arm_idle` | 手臂待机 | 2s | ✅ | 正常手臂姿态 |
| `arm_extend` | 手臂伸长 | 1-2s | ❌ | 手臂开始变长 |
| `arm_reach` | 手臂前伸 | 可变 | ✅ | 手臂在空中延伸 |
| `arm_grab` | 抓取动作 | 1s | ❌ | 手掌抓取物体 |
| `arm_hold` | 保持抓取 | 可变 | ✅ | 手臂伸长状态保持 |
| `arm_retract` | 手臂缩回 | 1-2s | ❌ | 手臂恢复原长 |
| `arm_reset` | 手臂复位 | 0.5s | ❌ | 回到正常姿态 |

---

## 交互动作库（推荐）

### 高处物体获取
| 动作ID | 名称 | 时长 | 说明 |
|--------|------|------|------|
| `reach_up` | 向上伸手 | 0.8s | 尝试触碰高处 |
| `jump_reach` | 跳跃抓取 | 1s | 跳起抓取 |
| `grab_high` | 高处抓取 | 1s | 成功抓取高处物体 |
| `pull_down` | 拉下物体 | 1.5s | 将高处物体拉下来 |

### 特殊效果动作
| 动作ID | 名称 | 时长 | 说明 |
|--------|------|------|------|
| `arm_glow` | 手臂发光 | 可变 | 伸长时的能量特效 |
| `body_float` | 身体漂浮 | 可变 | 飞行时的悬浮效果 |
| `stretch_bones` | 骨骼伸展 | 2s | 手臂伸长的夸张变形 |

---

## AI决策参数

### 动作选择权重配置
```javascript
const ActionWeights = {
  // 效率权重
  time_efficiency: 0.4,      // 时间效率 40%
  energy_cost: 0.3,          // 能量消耗 30%
  
  // 戏剧性权重
  visual_drama: 0.3,         // 视觉效果 30%
  
  // 各动作戏剧性评分（0-1）
  drama_scores: {
    walk: 0.2,               // 普通行走，低戏剧性
    fly: 0.8,                // 飞行，高戏剧性
    climb: 0.4,              // 攀爬，中等戏剧性
    extend: 1.0              // 手臂伸长，最高戏剧性！
  }
};
```

### 能力解锁配置
```javascript
const CharacterAbilities = {
  basic: ['walk', 'run', 'idle'],
  level_5: ['fly'],          // 5级解锁飞行
  level_10: ['climb'],       // 10级解锁攀爬
  special: ['extend'],       // 特殊任务解锁手臂伸长
  
  // NPC类型预设
  types: {
    human: ['walk', 'run', 'climb'],
    fairy: ['walk', 'fly', 'idle'],
    robot: ['walk', 'fly', 'extend', 'climb'],
    giant: ['walk', 'extend'] // 巨人主要靠伸长
  }
};
```

---

## 使用示例

### 基础移动
```javascript
// 普通行走（使用NavMesh避障）
await NPCMovement.moveTo(npc, targetPos, { speed: 1.5 });
```

### 飞行模式
```javascript
// 飞行到目标位置
await NPCActionSystem.flyTo(npc, targetPos, { 
  speed: 3.0, 
  height: 5,
  ascentRate: 2.0 
});
```

### 攀爬模式
```javascript
// 沿楼梯攀爬
const stairsPath = [
  { x: 0, y: 0, z: 0 },
  { x: 2, y: 1, z: 0 },
  { x: 4, y: 2, z: 0 }
];
await NPCActionSystem.climbTo(npc, stairsPath, { speed: 1.0 });
```

### 手臂伸长特效
```javascript
// 伸长手臂抓取高处物体
await NPCActionSystem.extendArmTo(npc, targetPos, {
  extendSpeed: 2.0,
  maxLength: 8.0,
  grabTime: 2000  // 抓取停留2秒
});
```

### AI智能选择
```javascript
// 让AI自动选择最佳方案
const result = await NPCActionSystem.smartApproach(npc, targetObject, {
  canFly: true,        // 能飞
  canClimb: true,      // 能爬
  canExtend: true,     // 能伸长手臂
  energy: 80,          // 当前能量
  drama: 0.8           // 需要高戏剧性（直播效果好）
});

console.log(`AI选择: ${result.strategy}`);
// 可能输出: "extend" （因为戏剧性最高）
```

---

## 动画技术规格

### 骨骼绑定要求
```
必需骨骼:
├── root (根节点)
├── hips (臀部)
│   ├── spine (脊柱)
│   │   ├── chest (胸部)
│   │   │   ├── neck (颈部)
│   │   │   │   └── head (头部)
│   │   │   ├── shoulder_L (左肩)
│   │   │   │   ├── upper_arm_L (左上臂)
│   │   │   │   │   ├── lower_arm_L (左前臂) ⭐ 伸长关键
│   │   │   │   │   │   └── hand_L (左手)
│   │   │   │   └── ... (右臂镜像)
│   └── ... (腿部)
```

### 特殊效果骨骼
- `arm_stretch_bone`: 手臂伸长专用骨骼（缩放控制）
- `wing_L/R`: 飞行翅膀骨骼（如有）
- `effect_point`: 特效挂载点

### 材质要求
| 部位 | 材质类型 | 特殊要求 |
|------|----------|----------|
| 身体 | PBR材质 | 支持透明、自发光 |
| 手臂伸长段 | 自发光材质 | 伸长时发光特效 |
| 手掌 | 可变形材质 | 抓取时形状变化 |

---

## 扩展建议

### 1. 添加新动作
```javascript
// 在 NPCActionSystem 中添加新方法
async dashTo(npc, targetPos, options) {
  // 冲刺移动
  await this.playAnimation(npc, 'dash_start');
  // ... 实现代码
  await this.playAnimation(npc, 'dash_end');
}
```

### 2. 自定义决策算法
```javascript
// 修改 smartApproach 中的策略评分
strategies.push({
  method: 'dash',
  score: (1 / dashTime) * 0.6 + (dashDrama * dramaLevel) * 0.4,
  action: () => this.dashTo(npc, targetPos, options)
});
```

### 3. 组合动作序列
```javascript
// 复杂动作：起飞 → 飞行 → 抓取 → 降落
async flyAndGrab(npc, targetPos) {
  await this.flyTo(npc, targetPos, { height: targetPos.y + 2 });
  await this.playAnimation(npc, 'grab');
  await this.flyTo(npc, returnPos, { height: 5 });
  await this.land(npc);
}
```

---

## 注意事项

1. **动画过渡**: 确保动作之间有平滑的过渡动画
2. **物理碰撞**: 飞行模式需要关闭角色与地面的碰撞
3. **视角跟随**: 飞行时相机应该平滑跟随高度变化
4. **网络同步**: 如果是多人场景，动作需要同步给其他玩家
5. **性能优化**: 手臂伸长特效的网格应该使用LOD优化

---

## 文件位置

- 系统代码: `frontend/studio-editor-v2.html`
  - `NPCMovement` - 基础行走系统
  - `NPCActionSystem` - 多模态动作系统
  - `MovementMode` - 移动模式常量
  - `NavMesh` - 导航网格系统

---

*最后更新: 2026-05-27*
*版本: v2.0*
