/**
 * Action Flow Executor - 3D动作流执行器
 */

class ActionFlowExecutor {
  constructor(scene3d, wsConnection) {
    this.scene3d = scene3d;
    this.ws = wsConnection;
    this.currentPlan = null;
    this.isExecuting = false;
    this.audioStartTime = 0;
    this.currentAudio = null;
    this.mixer = null;
    this.character = null;
    this.actors = new Map(); // actor_id → { character, mixer }
    this.loadedAnimations = new Map();
    this.actionStates = new Map();
    this.completedActions = new Set();
    this.handItemMesh = null;
    
    this._bindEvents();
    this._startExecutionLoop();
  }
  
  /**
   * 注册角色。actorId 默认为主播 ID。
   * @param {THREE.Object3D} character
   * @param {THREE.AnimationMixer} mixer
   * @param {string} actorId
   */
  setCharacter(character, mixer, actorId = 'bao_qing_host') {
    this.character = character;
    this.mixer = mixer;
    this.mixer.addEventListener('finished', (e) => this._onAnimationFinished(e));
    this.actors.set(actorId, { character, mixer });
  }

  /**
   * 注册辅助角色（机器人、助手等）
   * @param {string} actorId
   * @param {THREE.Object3D} character
   * @param {THREE.AnimationMixer} mixer
   */
  registerActor(actorId, character, mixer) {
    this.actors.set(actorId, { character, mixer });
    console.log(`[ActionFlow] Actor registered: ${actorId}`);
  }

  /** 获取指定actor的 {character, mixer}，fallback到主播 */
  _getActorContext(actorId) {
    if (actorId && this.actors.has(actorId)) return this.actors.get(actorId);
    return { character: this.character, mixer: this.mixer };
  }
  
  _bindEvents() {
    if (!this.ws) return;
    this.ws.on('execute_action_flow', (data) => {
      this.executePlan(data.plan, data.audio_url);
    });
    this.ws.on('action_flow_interrupted', (data) => {
      this.interruptCurrent(data.reason);
    });
  }
  
  async executePlan(plan, audioUrl) {
    if (this.isExecuting) await this.interruptCurrent('new_plan');
    
    this.currentPlan = plan;
    this.isExecuting = true;
    this.completedActions.clear();
    
    if (audioUrl) await this._startAudio(audioUrl);
    else this.audioStartTime = performance.now();
    
    plan.actions.forEach(a => this.actionStates.set(a.id, 'pending'));
    
    this._notifyBackend('action_flow_execution_started', {
      dialogue_id: plan.dialogue_id,
      plan_id: plan.id
    });
  }
  
  _startExecutionLoop() {
    const loop = () => {
      if (this.isExecuting && this.currentPlan) {
        this._checkAndExecuteActions();
        if (this.mixer) this.mixer.update(0.016);
      }
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  }
  
  _getElapsedTime() {
    return this.audioStartTime ? (performance.now() - this.audioStartTime) / 1000 : 0;
  }
  
  _checkAndExecuteActions() {
    const elapsed = this._getElapsedTime();
    
    for (const action of this.currentPlan.actions) {
      const state = this.actionStates.get(action.id);
      if (state === 'pending' && elapsed >= action.start_time) {
        if (action.depends_on && !this.completedActions.has(action.depends_on)) continue;
        this._executeAction(action);
        this.actionStates.set(action.id, 'running');
      }
      
      if (state === 'running' && !action.params?.loop) {
        if (elapsed >= action.start_time + action.duration) {
          this.actionStates.set(action.id, 'completed');
          this.completedActions.add(action.id);
        }
      }
    }
    
    const audioEnded = this.currentAudio?.ended || 
                       elapsed >= (this.currentPlan.audio_duration || 999);
    if (audioEnded && this._allActionsComplete()) this._onPlanCompleted();
  }
  
  _allActionsComplete() {
    return this.currentPlan.actions.every(a => {
      const state = this.actionStates.get(a.id);
      return state === 'completed' || a.params?.loop;
    });
  }
  
  _executeAction(action) {
    switch (action.type) {
      case 'animation':       this._playAnimation(action); break;
      case 'locomotion':      this._executeLocomotion(action); break;
      case 'effect':          this._executeEffect(action); break;
      case 'expression':      this._executeExpression(action); break;
      case 'sound':           this._executeSound(action); break;
      case 'transformation':  this._executeTransformation(action); break;
      case 'special_skill':   this._executeSpecialSkill(action); break;
      case 'prop_attach':     this._executePropAttach(action); break;
      case 'actor_spawn':     this._executeActorSpawn(action); break;
      default:
        console.warn('[ActionFlow] Unknown action type:', action.type, action.id);
    }
    // on_start 音效由各子方法负责（_executeSound/_executeSpecialSkill 除外，避免重复）
    if (!['sound', 'special_skill'].includes(action.type) && action.sounds?.on_start) {
      this._playSound(action.sounds.on_start);
    }
  }

  _executePropAttach(action) {
    const { prop_id, attach_bone, offset, detach, model_file } = action.params || {};
    const isDetach = detach === true || action.action_id?.startsWith('detach_');
    console.log(`[ActionFlow] PropAttach: ${isDetach ? 'detach' : 'attach'} prop=${prop_id} bone=${attach_bone}`);

    // 通知外部（live-scene.html 处理实际的3D挂载逻辑）
    window.dispatchEvent(new CustomEvent('npc_prop_attach', {
      detail: {
        actor_id: action.actor_id,
        prop_id,
        attach_bone,
        offset: offset || { x: 0, y: 0, z: 0 },
        model_file,
        detach: isDetach,
      }
    }));

    if (isDetach && action.sounds?.on_detach) this._playSound(action.sounds.on_detach);
    else if (!isDetach && action.sounds?.on_attach) this._playSound(action.sounds.on_attach);
  }

  _executeActorSpawn(action) {
    const { actor_id, model_file, spawn_position, spawn_animation } = action.params || {};
    const targetActorId = actor_id || action.actor_id;
    console.log(`[ActionFlow] ActorSpawn: actor=${targetActorId} model=${model_file}`);

    // 通知外部加载/显示辅助角色（机器人助手等）
    window.dispatchEvent(new CustomEvent('npc_actor_spawn', {
      detail: {
        actor_id: targetActorId,
        model_file,
        position: spawn_position || { x: 1.0, y: 0, z: 0 },
        animation: spawn_animation,
      }
    }));
  }
  
  async _playAnimation(action) {
    const { character, mixer } = this._getActorContext(action.actor_id);
    if (!mixer) return;

    const filePath = action.params?.file_path;
    if (!filePath) {
      console.warn('[ActionFlow] No file_path in action:', action.id);
      return;
    }

    const clip = await this._loadAnimClip(filePath);
    if (!clip) {
      console.warn('[ActionFlow] Failed to load clip:', filePath);
      return;
    }

    const loop = action.params?.loop;
    const newAction = mixer.clipAction(clip);
    newAction.setLoop(loop ? THREE.LoopRepeat : THREE.LoopOnce, loop ? Infinity : 1);
    newAction.clampWhenFinished = !loop;
    newAction.timeScale = 1.0;

    // 智能 Crossfade：根据动作类型决定过渡时间
    const actionType = action.action_id || 'default';
    const fadeConfig = this._getCrossfadeConfig(actionType, action.params);
    
    // CrossFade: 找正在播放的动作平滑过渡
    const runningActions = [];
    mixer._actions?.forEach(a => { 
      if (a.isRunning() && a !== newAction) runningActions.push(a); 
    });
    
    if (runningActions.length > 0) {
      newAction.reset().play();
      const fadeTime = fadeConfig.fadeIn;
      runningActions.forEach(prev => {
        // 如果当前是循环动作，先停止循环，然后在过渡完成后停止
        if (prev.loop === THREE.LoopRepeat) {
          prev.loop = THREE.LoopOnce;
          prev.clampWhenFinished = true;
        }
        prev.crossFadeTo(newAction, fadeTime, fadeConfig.warp);
      });
    } else {
      newAction.fadeIn(fadeConfig.fadeIn).reset().play();
    }

    console.log(`[ActionFlow] Playing [${action.actor_id||'main'}]: ${action.id} → ${filePath}${loop ? ' (loop)' : ''}`);
  }

  async _loadAnimClip(filePath) {
    if (this.loadedAnimations.has(filePath)) {
      return this.loadedAnimations.get(filePath);
    }
    return new Promise((resolve) => {
      const url = '/assets/动作库/' + filePath;
      const loader = new THREE.GLTFLoader();
      loader.load(url, (gltf) => {
        const clip = gltf.animations?.[0] || null;
        this.loadedAnimations.set(filePath, clip);
        resolve(clip);
      }, undefined, (err) => {
        console.error('[ActionFlow] GLB load error:', filePath, err.message);
        resolve(null);
      });
    });
  }
  
  _executeLocomotion(action) {
    const { to, speed } = action.params;
    const { character, mixer } = this._getActorContext(action.actor_id);
    if (!character) return;

    const startPos = character.position.clone();
    const targetPos = new THREE.Vector3(to.x, to.y || 0, to.z);
    const duration = Math.max(startPos.distanceTo(targetPos) / (speed || 1.0), 0.5);

    // 同步播放走路动画
    const walkPath = action.params?.file_path;
    if (walkPath && mixer) {
      this._loadAnimClip(walkPath).then(clip => {
        if (!clip || !mixer) return;
        const walkAction = mixer.clipAction(clip);
        walkAction.setLoop(THREE.LoopRepeat, Infinity);
        const running = [];
        mixer._actions?.forEach(a => { if (a.isRunning()) running.push(a); });
        // 走路动画使用更长的过渡避免滑步感
        const walkFadeTime = 0.35;
        walkAction.reset().play();
        running.forEach(prev => prev.crossFadeTo(walkAction, walkFadeTime, true));
      });
    }

    const startTime = performance.now();
    const move = () => {
      if (!this.isExecuting) return;
      const elapsed = (performance.now() - startTime) / 1000;
      const t = Math.min(elapsed / duration, 1);
      const smoothT = t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t;

      character.position.lerpVectors(startPos, targetPos, smoothT);
      character.lookAt(targetPos.x, character.position.y, targetPos.z);

      if (t < 1) requestAnimationFrame(move);
      else {
        this.actionStates.set(action.id, 'completed');
        this.completedActions.add(action.id);
      }
    };
    move();
  }
  
  _executeEffect(action) {
    switch (action.action_id) {
      case 'show_hand_item': this._showHandItem(action.params.sku_id); break;
      case 'hide_hand_item': this._hideHandItem(); break;
      case 'highlight_shelf':
        const shelfId = action.params.shelf_id || action.params.slot_id;
        if (this.scene3d?.highlightShelf) this.scene3d.highlightShelf(shelfId);
        break;
    }
  }
  
  _showHandItem(skuId) {
    if (!this.character) return;
    if (!this.handItemMesh) {
      const geo = new THREE.BoxGeometry(0.15, 0.15, 0.15);
      const mat = new THREE.MeshBasicMaterial({ color: 0x8B4513 });
      this.handItemMesh = new THREE.Mesh(geo, mat);
    }
    this.handItemMesh.position.set(0.3, 1.0, 0.2);
    this.character.add(this.handItemMesh);
  }
  
  _hideHandItem() {
    if (this.handItemMesh && this.character) {
      this.character.remove(this.handItemMesh);
    }
  }

  _executeExpression(action) {
    const { morph_weights, transition_duration_s, animation_file } = action.params || {};
    // 优先：骨骼动画文件（如果有）
    if (animation_file && this.mixer) {
      this._loadAnimClip(animation_file).then(clip => {
        if (!clip || !this.mixer) return;
        const animAction = this.mixer.clipAction(clip);
        animAction.setLoop(THREE.LoopOnce, 1);
        animAction.clampWhenFinished = true;
        animAction.fadeIn(transition_duration_s || 0.3);
        animAction.reset().play();
      });
      return;
    }
    // Morph target 权重（VRM / 支持morph的模型）
    if (morph_weights && this.character) {
      try {
        const vrm = this.character.userData?.vrm;
        if (vrm?.expressionManager) {
          for (const [name, weight] of Object.entries(morph_weights)) {
            vrm.expressionManager.setValue(name, weight);
          }
          console.log(`[ActionFlow] Expression: ${action.action_id}`, morph_weights);
        }
      } catch (e) {
        console.warn('[ActionFlow] Expression morph failed:', e.message);
      }
    }
  }

  _executeSound(action) {
    const file = action.params?.file;
    if (!file) return;
    this._playSound(file, action.params?.volume || 0.8);
  }

  _playSound(url, volume = 0.8) {
    if (!url) return;
    try {
      const audio = new Audio(url);
      audio.volume = Math.min(Math.max(volume, 0), 1);
      audio.play().catch(e => console.warn('[ActionFlow] Sound play failed:', url, e.message));
    } catch (e) {
      console.warn('[ActionFlow] Sound error:', e.message);
    }
  }

  _executeTransformation(action) {
    const params = action.params || {};
    const { target_form, transition_effect, revert_after_seconds, revert_to_form } = params;
    const actorId = action.actor_id || 'bao_qing_host';

    console.log(`[ActionFlow] Transformation → ${target_form}, effect=${transition_effect}`);

    // 记录变换前的状态
    this._transformationStates = this._transformationStates || new Map();
    this._transformationStates.set(actorId, {
      targetForm: target_form,
      startTime: performance.now(),
      revertAfter: revert_after_seconds,
      revertToForm: revert_to_form,
    });

    // 1. 播放过渡特效（如果配置了）
    if (transition_effect) {
      this._playTransitionEffect(transition_effect, params.transition_duration_s || 1.2);
    }

    // 2. 通知外部切换角色形态（live-scene.html 监听此事件）
    window.dispatchEvent(new CustomEvent('npc_transform', {
      detail: {
        actor_id: actorId,
        target_form,
        params: params,
        duration: action.duration,
      }
    }));

    // 3. 播放变身音效
    if (action.sounds?.on_start) {
      this._playSound(action.sounds.on_start);
    }

    // 4. 设置自动还原定时器
    if (revert_after_seconds && revert_to_form) {
      this._scheduleRevert(actorId, revert_after_seconds, revert_to_form, params.revert_effect);
    }

    // 5. 完成后音效
    if (action.sounds?.on_complete) {
      setTimeout(() => this._playSound(action.sounds.on_complete), action.duration * 1000);
    }

    // 标记完成
    this.actionStates.set(action.id, 'completed');
    this.completedActions.add(action.id);
  }

  _playTransitionEffect(effectName, duration) {
    // 触发特效播放事件，由外部特效管理器处理
    window.dispatchEvent(new CustomEvent('play_transition_effect', {
      detail: { effect: effectName, duration }
    }));
  }

  _scheduleRevert(actorId, delaySeconds, revertToForm, revertEffect) {
    // 清除之前的定时器
    if (this._revertTimers?.has(actorId)) {
      clearTimeout(this._revertTimers.get(actorId));
    }
    this._revertTimers = this._revertTimers || new Map();

    const timerId = setTimeout(() => {
      console.log(`[ActionFlow] Auto-revert → ${revertToForm}`);

      // 播放还原特效
      if (revertEffect) {
        this._playTransitionEffect(revertEffect, 1.0);
      }

      // 触发还原事件
      window.dispatchEvent(new CustomEvent('npc_transform', {
        detail: {
          actor_id: actorId,
          target_form: revertToForm,
          is_revert: true,
          params: {},
        }
      }));

      this._revertTimers.delete(actorId);
      this._transformationStates?.delete(actorId);
    }, delaySeconds * 1000);

    this._revertTimers.set(actorId, timerId);
  }

  _executeSpecialSkill(action) {
    const { file_path, bone_effects } = action.params || {};
    console.log(`[ActionFlow] Special skill: ${action.action_id}`);
    // 播放技能动画
    if (file_path && this.mixer) {
      this._loadAnimClip(file_path).then(clip => {
        if (!clip || !this.mixer) return;
        this.mixer.stopAllAction();
        const animAction = this.mixer.clipAction(clip);
        animAction.setLoop(THREE.LoopOnce, 1);
        animAction.clampWhenFinished = true;
        animAction.fadeIn(0.1);
        animAction.reset().play();
      });
    }
    // 通知外部播放骨骼特效
    if (bone_effects?.length) {
      window.dispatchEvent(new CustomEvent('npc_bone_effect', {
        detail: { actor_id: action.actor_id, bone_effects }
      }));
    }
  }
  
  async _startAudio(url) {
    try {
      this.currentAudio = new Audio(url);
      await this.currentAudio.play();
      this.audioStartTime = performance.now();
      this.currentAudio.addEventListener('ended', () => this._onPlanCompleted(), { once: true });
    } catch (e) {
      this.audioStartTime = performance.now();
    }
  }
  
  _onPlanCompleted() {
    this._notifyBackend('action_flow_completed', {
      plan_id: this.currentPlan?.id,
      dialogue_id: this.currentPlan?.dialogue_id
    });
    this._cleanup();
  }
  
  async interruptCurrent(reason = 'unknown') {
    if (!this.isExecuting) return;
    if (this.currentAudio) { this.currentAudio.pause(); this.currentAudio = null; }
    if (this.mixer) this.mixer.stopAllAction();
    this._hideHandItem();
    
    this._notifyBackend('action_flow_interrupted', { reason });
    this._cleanup();
  }
  
  /**
   * 获取动画 Crossfade 配置
   * 根据动作类型返回最佳的过渡时间和参数
   */
  _getCrossfadeConfig(actionType, params = {}) {
    // 用户自定义参数优先
    if (params.fade_in !== undefined || params.fadeIn !== undefined) {
      return {
        fadeIn: params.fade_in ?? params.fadeIn ?? 0.2,
        fadeOut: params.fade_out ?? params.fadeOut ?? 0.2,
        warp: params.warp ?? true,
      };
    }

    // 根据动作类型预设
    const PRESETS = {
      // 走路类：需要更长过渡避免滑步
      walk: { fadeIn: 0.35, fadeOut: 0.3, warp: true },
      walk_normal: { fadeIn: 0.35, fadeOut: 0.3, warp: true },
      // 待机和闲聊：平滑过渡
      idle: { fadeIn: 0.4, fadeOut: 0.4, warp: true },
      chat: { fadeIn: 0.3, fadeOut: 0.3, warp: true },
      // 手势/表达类：快速响应
      greeting: { fadeIn: 0.15, fadeOut: 0.15, warp: false },
      present: { fadeIn: 0.2, fadeOut: 0.2, warp: true },
      handover: { fadeIn: 0.15, fadeOut: 0.15, warp: false },
      // 取物类：中等过渡
      reach_high: { fadeIn: 0.2, fadeOut: 0.15, warp: false },
      reach_mid: { fadeIn: 0.2, fadeOut: 0.15, warp: false },
      reach_low: { fadeIn: 0.2, fadeOut: 0.15, warp: false },
      // 特殊技能：戏剧性过渡
      special_skill: { fadeIn: 0.1, fadeOut: 0.3, warp: false },
      summon: { fadeIn: 0.1, fadeOut: 0.2, warp: false },
      // 默认
      default: { fadeIn: 0.25, fadeOut: 0.2, warp: true },
    };

    return PRESETS[actionType] || PRESETS.default;
  }

  _cleanup() {
    this.currentPlan = null;
    this.isExecuting = false;
    this.audioStartTime = 0;
    this.actionStates.clear();
    this.completedActions.clear();
    
    // 回到 idle 待机（crossfade平滑过渡）
    if (this.mixer) {
      const IDLE_PATH = '基础姿态/直立站立/Standing Arguing.glb';
      this._loadAnimClip(IDLE_PATH).then(clip => {
        if (!clip || !this.mixer) return;
        const idleAction = this.mixer.clipAction(clip);
        idleAction.setLoop(THREE.LoopRepeat, Infinity);
        const running = [];
        this.mixer._actions?.forEach(a => { if (a.isRunning()) running.push(a); });
        idleAction.reset().play();
        running.forEach(prev => prev.crossFadeTo(idleAction, 0.4, true));
      });
    }
  }
  
  _notifyBackend(type, data) {
    if (this.ws) this.ws.send(JSON.stringify({ type, ...data }));
  }
  
  async _preloadAnimations(ids) {
    // Animation loading logic would go here
  }
  
  _onAnimationFinished(e) {
    // Handle animation completion
  }
}

// Export
window.ActionFlowExecutor = ActionFlowExecutor;
