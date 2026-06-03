# AI驱动的Action Flow架构设计

## 1. 核心设计原则

### 1.1 基于NPC回复预规划
- **关键原则**: NPC的所有动作规划基于NPC自己生成的回复文本，**而不是用户原始输入**
- **原因**:
  1. 用户输入不确定、格式随意，无法可靠地映射到动作
  2. NPC的回复是提前生成（AI预生成），内容确定
  3. 基于确定的回复文本可以提前规划动作流，让表演流畅无卡顿
  4. NPC用自己的语言复述用户需求（如用户说"有篮球吗" → NPC回复"好的，我来给您介绍篮球" → 基于这句话规划：走到篮球货架→取货→展示）

### 1.2 完整工作流
```
用户弹幕 → AI生成NPC回复 → 解析回复内容 → 规划动作序列 → 排入动作队列 → NPC执行（语音+动作同步）
```

---

## 2. 数据结构设计

### 2.1 ActionPlan - AI生成的动作计划
```python
@dataclass
class ActionPlan:
    id: str                           # 唯一标识
    dialogue_id: str                  # 关联对话ID
    trigger_type: str                 # product_query/gift/order/chat
    trigger_sku_id: Optional[str]     # 关联商品
    trigger_emotion: str              # happy/sad/surprised/neutral
    actions: List[PlannedAction]        # 动作序列（核心）
    estimated_duration: float         # 预估总时长
    audio_duration: Optional[float]   # 实际语音时长
    sync_points: List[SyncPoint]      # 语音与动作同步时间点
    status: str                       # pending/executing/completed
    priority: int

@dataclass
class PlannedAction:
    id: str
    type: str                         # animation/locomotion/gaze/effect
    action_id: str                    # walk/grab/present/turn等
    params: Dict[str, Any]            # 位置、目标、速度等
    start_time: float                 # 相对于音频开始的时间点
    duration: float
    wait_for_complete: bool           # 是否等待完成
    can_interrupt: bool

@dataclass
class SyncPoint:
    time_offset: float                # 相对于音频开始的时间
    action_id: str
    subtitle_text: Optional[str]
    effect: Optional[str]
```

### 2.2 ActionFlowItem - 增强对话项
```python
@dataclass
class ActionFlowItem(DialogueItem):
    action_plan: Optional[ActionPlan] = None
    parsed_intent: Dict[str, Any] = field(default_factory=dict)
    mentioned_skus: List[str] = field(default_factory=list)
    audio_url: Optional[str] = None
    audio_duration: float = 0.0
    execution_state: ExecutionState = field(default_factory=lambda: ExecutionState())
```

---

## 3. 后端模块设计

### 3.1 AIActionPlanner（新模块）
```python
class AIActionPlanner:
    """AI驱动的动作规划器"""
    
    async def plan_for_dialogue(self, item: ActionFlowItem) -> ActionPlan:
        # 1. AI解析回复内容
        parsed = await self._parse_reply_with_ai(item.reply)
        
        # 2. 提取商品信息
        skus = self._extract_mentioned_skus(item.reply)
        
        # 3. 根据意图规划动作序列
        if parsed["intent"] == "product_present":
            actions = self._plan_product_presentation(skus[0])
        elif parsed["intent"] == "greeting":
            actions = self._plan_greeting_sequence()
        else:
            actions = self._plan_default_chat()
            
        # 4. 计算同步点
        sync_points = self._calculate_sync_points(actions, item.audio_duration)
        
        return ActionPlan(
            actions=actions,
            sync_points=sync_points,
            ...
        )
```

### 3.2 ActionPlanner关键方法
```python
    def _plan_product_presentation(self, sku_id: str) -> List[PlannedAction]:
        """商品展示完整流程规划"""
        actions = []
        t = 0.0
        
        # 1. 转身面向货架 (0.5s)
        actions.append(PlannedAction(
            id="turn_to_shelf", type="animation", action_id="turn_toward",
            start_time=t, duration=0.5, wait_for_complete=True
        ))
        t += 0.5
        
        # 2. 走向货架
        walk_duration = self._calculate_walk_duration(to_pos=shelf_pos)
        actions.append(PlannedAction(
            id="walk_to_shelf", type="locomotion", action_id="walk",
            params={"to": shelf_pos, "speed": 1.0},
            start_time=t, duration=walk_duration, wait_for_complete=True
        ))
        t += walk_duration
        
        # 3. 取货动作
        actions.append(PlannedAction(
            id="reach_item", type="animation", action_id="reach_mid",
            start_time=t, duration=1.0, wait_for_complete=True
        ))
        t += 1.0
        
        # 4. 抓取 + 显示手持物品
        actions.append(PlannedAction(
            id="grab_item", type="animation", action_id="grab_onehand",
            start_time=t, duration=0.5, wait_for_complete=True
        ))
        actions.append(PlannedAction(
            id="show_hand_item", type="effect", action_id="show_hand",
            params={"sku_id": sku_id}, start_time=t+0.3, duration=0.1
        ))
        t += 0.5
        
        # 5. 转身返回
        actions.append(PlannedAction(
            id="turn_back", type="animation", action_id="turn_back",
            start_time=t, duration=0.5, wait_for_complete=True
        ))
        t += 0.5
        
        # 6. 走回中央
        actions.append(PlannedAction(
            id="walk_back", type="locomotion", action_id="walk",
            params={"to": center_pos, "speed": 0.8},
            start_time=t, duration=walk_duration*1.2, wait_for_complete=True
        ))
        t += walk_duration * 1.2
        
        # 7. 展示动作（循环直到语音结束）
        actions.append(PlannedAction(
            id="present_loop", type="animation", action_id="present_show",
            params={"loop": True}, start_time=t, duration=999,
            can_interrupt=True
        ))
        
        return actions
```

---

## 4. DialogueQueue集成

```python
class ActionFlowQueueManager(DialogueQueueManager):
    def __init__(self, ai_service, tts_service, action_planner, cfg=None):
        super().__init__(ai_service, tts_service, cfg)
        self.action_planner = action_planner
        
    async def _generate_reply(self, item_id: str):
        # 1. 生成AI回复
        reply, emotion = await self._call_ai_chat(item)
        item.reply = reply
        item.emotion = emotion
        
        # 2. TTS合成获取音频时长
        audio_url, duration = await self._synthesize_tts(item)
        item.audio_url = audio_url
        item.audio_duration = duration
        
        # 3. 【关键】AI规划动作流
        if self.action_planner:
            action_plan = await self.action_planner.plan_for_dialogue(item)
            item.action_plan = action_plan
            
            # 广播动作计划就绪
            await self.hub.broadcast({
                "action": "action_plan_ready",
                "dialogue_id": item.id,
                "plan": action_plan.to_dict()
            })
        
        # 移动到queued队列
        item.status = DialogueStatus.QUEUED
        
    async def mark_playing(self, item_id: str):
        """开始播放时同步触发3D执行"""
        item = self.queued.get(item_id)
        if item and item.action_plan:
            # 发送执行指令给前端
            await self.hub.broadcast({
                "action": "execute_action_flow",
                "dialogue_id": item.id,
                "plan": item.action_plan.to_dict(),
                "audio_url": item.audio_url
            })
```

---

## 5. 前端执行架构

### 5.1 ActionFlowExecutor
```javascript
class ActionFlowExecutor {
  constructor(scene3d, wsConnection) {
    this.scene3d = scene3d;
    this.ws = wsConnection;
    this.currentPlan = null;
    this.isExecuting = false;
    this.mixer = new THREE.AnimationMixer(character);
    this.loadedAnimations = new Map();
  }
  
  _bindEvents() {
    this.ws.on('execute_action_flow', (data) => {
      this.executePlan(data.plan, data.audio_url);
    });
    
    this.ws.on('action_interrupt', () => {
      this.interruptCurrent();
    });
  }
  
  async executePlan(plan, audioUrl) {
    this.currentPlan = plan;
    this.isExecuting = true;
    
    // 1. 预加载所有需要的动画
    const actionIds = plan.actions.map(a => a.action_id);
    await this._preloadAnimations(actionIds);
    
    // 2. 开始播放音频
    const audio = new Audio(audioUrl);
    audio.play();
    this.audioStartTime = performance.now();
    
    // 3. 启动动作执行循环
    this._startActionLoop(plan.actions);
    
    // 4. 监听音频结束
    audio.addEventListener('ended', () => {
      this._onAudioComplete();
    });
  }
  
  _startActionLoop(actions) {
    const checkAndExecute = () => {
      if (!this.isExecuting) return;
      
      const elapsed = (performance.now() - this.audioStartTime) / 1000;
      
      // 检查每个动作是否应该开始
      for (const action of actions) {
        if (!action.started && elapsed >= action.start_time) {
          this._executeAction(action);
          action.started = true;
        }
      }
      
      // 更新动画混合器
      this.mixer.update(0.016); // ~60fps
      
      requestAnimationFrame(checkAndExecute);
    };
    
    requestAnimationFrame(checkAndExecute);
  }
  
  _executeAction(action) {
    switch (action.type) {
      case 'animation':
        this._playAnimation(action);
        break;
      case 'locomotion':
        this._executeLocomotion(action);
        break;
      case 'effect':
        this._executeEffect(action);
        break;
    }
    
    // 通知后端动作已开始
    this.ws.send({
      type: 'action_started',
      action_id: action.id,
      dialogue_id: this.currentPlan.dialogue_id
    });
  }
  
  _playAnimation(action) {
    const clip = this.loadedAnimations.get(action.action_id);
    if (!clip) {
      console.warn(`Animation ${action.action_id} not loaded`);
      return;
    }
    
    const action = this.mixer.clipAction(clip);
    
    if (action.params?.loop) {
      action.setLoop(THREE.LoopRepeat);
    } else {
      action.setLoop(THREE.LoopOnce);
    }
    
    action.reset().play();
    
    // 如果不是循环动作，设置完成回调
    if (!action.params?.loop) {
      action.clampWhenFinished = true;
    }
  }
  
  _executeLocomotion(action) {
    const { to, speed } = action.params;
    const character = this.scene3d.character;
    const startPos = character.position.clone();
    const targetPos = new THREE.Vector3(to.x, to.y, to.z);
    
    // 计算移动时间
    const distance = startPos.distanceTo(targetPos);
    const duration = distance / speed;
    
    // 同时播放走路动画
    const walkAnim = this.mixer.clipAction(
      this.loadedAnimations.get('walk')
    );
    walkAnim.setLoop(THREE.LoopRepeat);
    walkAnim.play();
    
    // 使用Tween或手动插值移动角色
    const startTime = performance.now();
    const move = () => {
      const elapsed = (performance.now() - startTime) / 1000;
      const t = Math.min(elapsed / duration, 1);
      
      character.position.lerpVectors(startPos, targetPos, t);
      character.lookAt(targetPos);
      
      if (t < 1) {
        requestAnimationFrame(move);
      } else {
        // 移动完成，停止走路动画
        walkAnim.stop();
      }
    };
    
    move();
  }
  
  _executeEffect(action) {
    switch (action.action_id) {
      case 'show_hand':
        this.scene3d.showHandItem(action.params.sku_id);
        break;
      case 'hide_hand':
        this.scene3d.hideHandItem();
        break;
      case 'highlight_shelf':
        this.scene3d.highlightShelf(action.params.slot_id);
        break;
    }
  }
  
  interruptCurrent() {
    this.isExecuting = false;
    
    // 停止所有动画
    this.mixer.stopAllAction();
    
    // 停止音频
    if (this.currentAudio) {
      this.currentAudio.pause();
    }
    
    // 隐藏手持物品等清理
    this.scene3d.hideHandItem();
    
    // 通知后端
    this.ws.send({
      type: 'action_interrupted',
      dialogue_id: this.currentPlan?.dialogue_id
    });
  }
}
```

---

## 6. WebSocket通信协议

### 6.1 后端→前端消息
```javascript
// 动作流开始
{
  "action": "action_flow_start",
  "dialogue_id": "abc123",
  "plan_id": "plan456",
  "audio_url": "/cache/tts/xxx.mp3",
  "audio_duration": 3.5,
  "actions_count": 7
}

// 执行动作流
{
  "action": "execute_action_flow",
  "dialogue_id": "abc123",
  "plan": {
    "id": "plan456",
    "actions": [
      {
        "id": "turn_to_shelf",
        "type": "animation",
        "action_id": "turn_toward",
        "start_time": 0,
        "duration": 0.5,
        "params": {"target": "A1"}
      },
      {
        "id": "walk_to_shelf",
        "type": "locomotion", 
        "action_id": "walk",
        "start_time": 0.5,
        "duration": 2.0,
        "params": {"to": {"x": 180, "y": 0, "z": -2}, "speed": 1.0}
      }
    ],
    "sync_points": [
      {"time_offset": 1.0, "action_id": "show_subtitle", "subtitle_text": "这茶..."}
    ]
  }
}

// 打断执行
{
  "action": "action_interrupt",
  "reason": "emergency",
  "dialogue_id": "abc123"
}
```

### 6.2 前端→后端消息
```javascript
// 动作开始
{
  "type": "action_started",
  "dialogue_id": "abc123",
  "action_id": "turn_to_shelf",
  "timestamp": 1699123456
}

// 动作完成
{
  "type": "action_completed",
  "dialogue_id": "abc123",
  "action_id": "turn_to_shelf"
}

// 动作流完成
{
  "type": "action_flow_completed",
  "dialogue_id": "abc123",
  "plan_id": "plan456",
  "completed_at": 1699123460
}

// 执行错误
{
  "type": "action_error",
  "dialogue_id": "abc123",
  "action_id": "walk_to_shelf",
  "error": "animation_not_found"
}
```

---

## 7. 动画资源管理

### 7.1 动画文件命名规范
```
assets/动作库/
├── 基础姿态/
│   ├── Standing Idle.glb          # idle默认站立
│   ├── Standing Greeting.glb      # 打招呼
│   └── Sitting Idle.glb           # 坐着
├── 移动动作/
│   ├── Walking.glb                # 走路
│   ├── Walking Backwards.glb      # 后退
│   ├── Running.glb                # 跑步
│   └── Turn Left 90.glb           # 转身
├── 交互动作/
│   ├── Pick Fruit.glb             # 低处取物
│   ├── Pick Fruit (2).glb         # 高处取物
│   ├── Shaking Hands 1.glb        # 递接物品
│   └── Standing Greeting.glb      # 欢迎手势
└── 情绪反应/
    ├── Happy Idle.glb             # 开心
    ├── Angry.glb                  # 生气
    └── Surprised.glb              # 惊讶
```

### 7.2 动作映射配置
```json
{
  "event_action_map": {
    "idle": "基础姿态/Standing Idle.glb",
    "greeting": "交互动作/Standing Greeting.glb",
    "walk": "移动动作/Walking.glb",
    "grab_high": "交互动作/Pick Fruit (2).glb",
    "grab_mid": "交互动作/Pick Fruit.glb",
    "present": "交互动作/Shaking Hands 1.glb",
    "happy": "情绪反应/Happy Idle.glb"
  }
}
```

---

## 8. 实施路线图

### Phase 1: 基础架构 (1-2周)
- [ ] 创建 `AIActionPlanner` 模块
- [ ] 扩展 `DialogueItem` 支持 `ActionPlan`
- [ ] 实现基础动作规划方法
- [ ] 添加动作计划生成到对话队列流程

### Phase 2: 前端执行器 (2周)
- [ ] 创建 `ActionFlowExecutor` 类
- [ ] 实现动画加载和管理
- [ ] 实现时间同步执行循环
- [ ] 处理打断和清理逻辑

### Phase 3: 同步优化 (1-2周)
- [ ] 精确音频时长获取
- [ ] 同步点计算优化
- [ ] 语音-动作对齐微调
- [ ] 缓冲和容错机制

### Phase 4: 场景集成 (1周)
- [ ] 货架位置自动映射
- [ ] 场景切换时的动作适配
- [ ] 多SKU连续展示支持

---

## 9. 关键技术点

### 9.1 时间同步策略
```
时间基准：音频播放时间（最可靠）

策略：
1. 记录音频开始时间 audioStartTime
2. 计算 elapsed = now - audioStartTime
3. 当 elapsed >= action.start_time 时触发动作
4. 使用 requestAnimationFrame 保证60fps更新
```

### 9.2 打断处理
```python
# 高优先级事件（订单、大礼物）可以打断
async def on_gift_big(...):
    # 发送打断指令
    await self.hub.broadcast({
        "action": "action_interrupt",
        "reason": "gift_big",
        "new_priority": 2
    })
```

### 9.3 错误处理
```javascript
// 动作执行失败时的回退
_executeWithFallback(action) {
  try {
    this._executeAction(action);
  } catch (error) {
    console.error(`Action ${action.id} failed:`, error);
    // 发送错误报告
    this.ws.send({type: 'action_error', ...});
    // 继续执行下一个（如果不需要等待完成）
    if (!action.wait_for_complete) {
      this._advanceToNext();
    }
  }
}
```

---

## 10. 性能考虑

1. **动画预加载**: 在收到action_plan时就开始加载所需动画资源
2. **对象池**: 复用Audio对象和动画Action实例
3. **节流**: 低优先级弹幕的动作简化（只播放基础动画）
4. **WebWorker**: 考虑将动画更新放入worker避免阻塞主线程
5. **GPU加速**: 确保动画在GPU上执行（transform3d, will-change）

---

## 11. 扩展设计

### 11.1 多角色支持
```python
class MultiCharacterActionPlanner:
    def plan_for_character(self, character_id, dialogue):
        character = self.cfg.get_character(character_id)
        # 根据角色特性规划不同动作风格
```

### 11.2 自定义动作序列
```python
# 允许运营配置特定话术的动作序列
CUSTOM_ACTION_SEQUENCES = {
    "开场白": ["wave", "bow", "gesture_welcome"],
    "感谢下单": ["clap", "bow_deep", "thumbs_up"]
}
```

---

**文档版本**: 1.0  
**创建日期**: 2024-05-26  
**状态**: 架构设计完成，待实施
