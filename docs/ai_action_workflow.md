# AI动作规划工作流程详解

## 📋 系统架构图

```
用户对话 → AI生成回复 → 意图识别 → 动作规划 → 执行序列 → 3D渲染
                ↑                                            ↓
                └──────────── 实时同步反馈 ←──────────────────┘
```

---

## 🎯 核心流程：从对话到动作表演

### 阶段1：对话生成（已有）
```
用户输入："给我看看那个高处的茶壶"
          ↓
    AI对话系统
          ↓
NPC回复："好的，我去给您取来，这个茶壶放在最上面的架子上呢"
          ↓
    情感标签：friendly
    音频时长：3.8秒（预估）
```

### 阶段2：意图识别（AI解析）
```
AI解析回复内容：
{
    "intent_type": "product_present",
    "target_products": ["茶壶"],
    "actions_implied": ["walk", "grab", "present"],
    "emotion": "friendly",
    "needs_fetch": true,        // 需要取货
    "needs_present": true,      // 需要展示
    "key_phrases": ["取来", "架子上"]
}
```

**意图类型对应表：**

| 意图类型 | 触发关键词 | 典型动作序列 |
|---------|-----------|------------|
| `product_present` | 介绍、看看、给你 | 行走→取物→展示 |
| `greeting` | 欢迎、来了、请进 | 挥手招呼→待机 |
| `thanks` | 谢谢、感谢 | 点头/鞠躬→待机 |
| `goodbye` | 再见、慢走 | 挥手告别 |
| `chat` | 其他对话 | 待机/讲解手势 |

### 阶段3：动作规划（核心决策）

#### 3.1 场景分析
```
当前NPC位置：{x: 0, y: 0, z: 0}
目标物体位置：{x: 3, y: 2.5, z: -2}  ← 高处货架
场景条件：
- 水平距离：3.6米
- 高度差：2.5米
- 是否有楼梯：是
- NPC能力：[walk, fly, climb, extend] ← 全能型NPC
```

#### 3.2 策略评分计算

**决策权重：**
```
time_weight: 0.4      // 时间效率40%
drama_weight: 0.3    // 戏剧性30%
energy_weight: 0.3   // 能量消耗30%
```

**各方案评分：**

| 方案 | 时间 | 能量 | 戏剧性 | 得分 | 原因 |
|-----|------|------|--------|------|------|
| 行走 | 2.4s | 10 | 0.2 | 0.42 | 只能到地面 |
| **飞行** | 2.5s | 30 | **0.8** | **0.71** | 高度差大 |
| 攀爬 | 3.6s | 15 | 0.4 | 0.38 | 较慢但真实 |
| **伸长** | 4.0s | 5 | **1.0** | **0.73** | ⭐ 戏剧性最高！|

**AI选择：伸长手臂（得分最高，直播效果最好）**

### 阶段4：动作序列生成

```
生成完整动作计划（共6.0秒）：

0.0s ── 待机准备 ── (idle, 0.5s)
        ↓
0.5s ── 手臂开始伸长 ── (arm_extend, 1.0s) 
        │  [视觉特效：手臂变长，发光]
        ↓
1.5s ── 伸长抓取茶壶 ── (arm_grab, 1.0s)
        │  [手部精准到达目标位置]
        ↓
2.5s ── 保持抓取 ── (hold, 1.0s)
        ↓
3.5s ── 手臂缩回 ── (arm_retract, 1.0s)
        │  [特效：手臂恢复]
        ↓
4.5s ── 展示茶壶给观众 ── (present, 1.5s)
        ↓
6.0s ── 回到待机 ── (idle, 循环)

同步点：
- 0.5s: 显示字幕"我去给您取来"
- 4.5s: 高亮展示手中的茶壶
```

### 阶段5：3D执行（前端渲染）

```javascript
// 前端接收到的动作计划
const actionPlan = {
    strategy: "extend",
    actions: [...],
    estimated_duration: 6.0
};

// 执行
await NPCActionSystem.extendArmTo(npc, targetPos, {
    maxLength: 8,
    grabTime: 1000
});
```

**实时反馈：**
- 手臂伸长时播放发光特效
- 抓取成功后显示物品在手中
- 同时播放NPC语音（与动作同步）

---

## 🧠 AI决策系统详解

### 移动策略配置
```python
MOVEMENT_STRATEGIES = {
    "walk": {
        "speed": 1.5,           # 米/秒
        "energy_cost": 10,      # 能量消耗
        "drama_score": 0.2,     # 戏剧性评分
        "max_height_diff": 0.5  # 最大高度差
    },
    "fly": {
        "speed": 3.0,
        "energy_cost": 30,
        "drama_score": 0.8,     # 高戏剧性！
        "max_height_diff": 100
    },
    "climb": {
        "speed": 1.0,
        "energy_cost": 15,
        "drama_score": 0.4
    },
    "extend": {
        "speed": 0,             # 主体不动
        "energy_cost": 5,       # 最省力
        "drama_score": 1.0      # 最高戏剧性！
    }
}
```

### NPC能力系统
```python
# 不同NPC类型拥有不同能力
NPC_TYPES = {
    "human_host":    ["walk", "run", "climb"],
    "fairy_guide":   ["walk", "fly", "idle"],
    "robot_butler":  ["walk", "fly", "extend", "climb"],
    "giant_guard":   ["walk", "extend"]  # 巨人主要靠伸长
}
```

### 动态决策示例

**场景1：普通取货（地面）**
```
用户："给我那瓶水"（地面货架）
AI决策：
- 行走：得分0.62（最快）
- 飞行：不适合（高度差小）
- 伸长：得分0.45（距离近但没必要）
→ 选择：行走
```

**场景2：高处取货（直播场景）**
```
用户："看看顶层那个"（3米高）
AI决策：
- 行走：无法到达
- 飞行：得分0.71（快但戏剧性一般）
- 伸长：得分0.73（戏剧性最高！）
→ 选择：伸长手臂 ⭐
理由：直播效果好，观众惊叹
```

**场景3：远距离高处**
```
用户："取那个远处的"（10米远，5米高）
AI决策：
- 行走：无法到达
- 飞行：得分0.68（必须飞过去）
- 伸长：超出范围（max 8米）
→ 选择：飞行
```

---

## 🎬 动作映射表

### 基础动作 → 实际GLB文件

| 动作Key | 文件路径 | 用途 |
|---------|----------|------|
| `idle` | 基础姿态/直立站立/Standing Arguing.glb | 待机 |
| `walk` | 移动动作/走路/正常走路/Walking.glb | 行走循环 |
| `takeoff` | 移动动作/飞行/起飞/Takeoff.glb | 起飞 |
| `fly_loop` | 移动动作/飞行/飞行循环/Fly Loop.glb | 飞行姿态 |
| `land` | 移动动作/飞行/降落/Land.glb | 降落 |
| `climb_start` | 移动动作/攀爬/攀爬开始/Climb Start.glb | 开始攀爬 |
| `climb_loop` | 移动动作/攀爬/攀爬循环/Climb Loop.glb | 攀爬循环 |
| `climb_end` | 移动动作/攀爬/攀爬结束/Climb End.glb | 攀爬结束 |
| `arm_extend` | 特殊能力/手臂伸长/伸长/Arm Extend.glb | 手臂伸长 |
| `arm_grab` | 特殊能力/手臂伸长/抓取/Arm Grab.glb | 伸长抓取 |
| `arm_retract` | 特殊能力/手臂伸长/缩回/Arm Retract.glb | 手臂缩回 |
| `reach_high` | 交互动作/取物动作/取高处/Pick Fruit (1).glb | 高处取物 |
| `present` | 交互动作/递接动作/放下物品/Standing Greeting.glb | 展示物品 |
| `greeting` | 情绪反应/打招呼/Standing Greeting (1).glb | 打招呼 |

---

## 🔧 实际调用示例

### 示例1：简单打招呼
```python
planner = AIActionPlanner(ai_service, config)

plan = await planner.plan_for_dialogue(
    dialogue_id="dlg_001",
    reply_text="欢迎光临！请进来看看吧",
    emotion="happy",
    audio_duration=2.5
)

# 生成的动作序列：
# 0.0s: greeting (挥手，2.0s)
# 2.0s: idle (待机，0.5s)
```

### 示例2：智能取货（使用新系统）
```python
# 获取目标位置
slot = planner.scene_context.find_sku_slot("tea_pot_001")

# NPC能力配置
npc_abilities = ["walk", "fly", "extend"]

# AI选择最优策略
strategy = planner._select_movement_strategy(
    from_pos={"x": 0, "y": 0, "z": 0},
    to_pos={"x": 3, "y": 2.5, "z": -2},
    npc_abilities=npc_abilities,
    context={
        "drama_weight": 0.5,  # 重视直播效果
        "time_weight": 0.3
    }
)

print(f"选择策略: {strategy['strategy']}")
print(f"原因: {strategy['reason']}")
print(f"备选方案: {strategy['all_options']}")

# 输出:
# 选择策略: extend
# 原因: 距离近，伸长手臂最具戏剧性！
# 备选方案: [
#   {"strategy": "extend", "score": 0.73},
#   {"strategy": "fly", "score": 0.71},
#   {"strategy": "walk", "score": 0.42}
# ]
```

---

## 🎨 前端执行系统

### NPCActionSystem 调用方式
```javascript
// 1. 基础行走（NavMesh避障）
await NPCMovement.moveTo(npc, targetPos, {
    speed: 1.5,
    stopDistance: 0.3
});

// 2. 飞行模式
await NPCActionSystem.flyTo(npc, targetPos, {
    speed: 3.0,
    height: 5,
    ascentRate: 2.0
});

// 3. 攀爬模式
await NPCActionSystem.climbTo(npc, stairsPath, {
    speed: 1.0
});

// 4. 手臂伸长特效
await NPCActionSystem.extendArmTo(npc, targetPos, {
    extendSpeed: 2.0,
    maxLength: 8.0,
    grabTime: 2000
});

// 5. AI智能选择（自动决策）
const result = await NPCActionSystem.smartApproach(npc, targetObject, {
    canFly: true,
    canClimb: true,
    canExtend: true,
    drama: 0.8,       // 重视戏剧性
    energy: 80       // 当前能量
});

console.log(`AI选择: ${result.strategy}`);
```

---

## 📊 性能指标

| 指标 | 目标值 | 实现方式 |
|------|--------|---------|
| 动作规划延迟 | < 50ms | 预计算 + 缓存 |
| 动作切换平滑 | < 200ms | 过渡动画混合 |
| 语音同步精度 | ±100ms | 时间轴对齐 |
| 路径计算 | 实时 | NavMesh射线检测 |

---

## 🔄 未来扩展方向

### 1. 更多动作类型
- **游泳**（水下场景）
- **瞬移**（科幻角色）
- **变身**（形态切换）

### 2. 更复杂的AI决策
```python
# 考虑观众情绪的动态调整
if audience_engagement < 0.3:
    drama_weight *= 1.5  # 观众无聊时增加戏剧性
    
# 考虑连续动作的连贯性
if last_action == "fly":
    fly_score *= 1.2  # 已经在飞行中，继续飞更自然
```

### 3. 多NPC协作
```python
# 一个NPC伸长手臂，另一个配合递物
combined_action = [
    npc1.extendArmTo(middle_point),
    npc2.handoverTo(middle_point),
    npc1.retractArm()
]
```

---

## 📁 文件位置

- **动作库清单**: `assets/动作库/action_manifest.json`
- **AI规划器**: `modules/ai_action_planner.py`
- **前端执行**: `frontend/studio-editor-v2.html`
  - `NPCMovement` - 基础行走
  - `NPCActionSystem` - 多模态动作
  - `NavMesh` - 导航网格

---

*最后更新: 2026-05-27*
*版本: v2.0 - 多模态移动*
