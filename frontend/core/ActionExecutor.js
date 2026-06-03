/**
 * ActionExecutor.js
 * 动作执行器
 * 负责：动作序列执行、队列管理、过渡控制
 */

class ActionExecutor {
  constructor() {
    this.queue = []; // 动作队列
    this.isExecuting = false;
    this.currentIndex = 0;
    this.callbacks = {
      onStart: null,
      onComplete: null,
      onActionStart: null,
      onActionComplete: null
    };
    this.parallelActions = new Map(); // 并行执行的动作
  }

  /**
   * 执行动作序列
   */
  executeSequence(characterId, actions, options = {}) {
    if (this.isExecuting) {
      console.warn('[ActionExecutor] 已有动作序列在执行中');
      if (options.force) {
        this.stop();
      } else {
        return false;
      }
    }

    this.queue = actions.map((action, index) => ({
      ...action,
      id: `${action.type}_${index}`,
      status: 'pending'
    }));
    
    this.currentIndex = 0;
    this.isExecuting = true;
    this.characterId = characterId;
    
    // 设置回调
    this.callbacks = {
      onStart: options.onStart,
      onComplete: options.onComplete,
      onActionStart: options.onActionStart,
      onActionComplete: options.onActionComplete
    };

    console.log(`[ActionExecutor] 开始执行动作序列: ${actions.length}个动作`);
    
    if (this.callbacks.onStart) {
      this.callbacks.onStart(this.queue);
    }

    this.processNext();
    return true;
  }

  /**
   * 处理队列中的下一个动作
   */
  async processNext() {
    if (!this.isExecuting || this.currentIndex >= this.queue.length) {
      this.completeSequence();
      return;
    }

    const action = this.queue[this.currentIndex];
    action.status = 'executing';
    
    console.log(`[ActionExecutor] 执行动作 ${this.currentIndex + 1}/${this.queue.length}: ${action.type}`);
    
    if (this.callbacks.onActionStart) {
      this.callbacks.onActionStart(action, this.currentIndex);
    }

    try {
      await this.executeAction(action);
      action.status = 'completed';
      
      if (this.callbacks.onActionComplete) {
        this.callbacks.onActionComplete(action, this.currentIndex);
      }
    } catch (error) {
      console.error(`[ActionExecutor] 动作执行失败:`, error);
      action.status = 'failed';
      action.error = error.message;
    }

    this.currentIndex++;
    this.processNext();
  }

  /**
   * 执行单个动作
   */
  executeAction(action) {
    return new Promise((resolve, reject) => {
      const { type, ...params } = action;

      switch (type) {
        case 'animation':
          this.executeAnimation(params, resolve, reject);
          break;
        case 'locomotion':
          this.executeLocomotion(params, resolve, reject);
          break;
        case 'gaze':
          this.executeGaze(params, resolve, reject);
          break;
        case 'wait':
          this.executeWait(params, resolve, reject);
          break;
        case 'dialogue':
          this.executeDialogue(params, resolve, reject);
          break;
        case 'camera_switch':
          this.executeCameraSwitch(params, resolve, reject);
          break;
        case 'special_skill':
          this.executeSpecialSkill(params, resolve, reject);
          break;
        case 'expression':
          this.executeExpression(params, resolve, reject);
          break;
        case 'transformation':
          this.executeTransformation(params, resolve, reject);
          break;
        case 'sound':
          this.executeSound(params, resolve, reject);
          break;
        default:
          console.warn(`[ActionExecutor] 未知动作类型: ${type}`);
          resolve();
      }
    });
  }

  /**
   * 执行骨骼动画
   */
  executeAnimation(params, resolve, reject) {
    const { action, variant, duration, loop = false } = params;
    
    // 获取动作ID（支持变体选择）
    const actionId = variant ? `${action}_${variant}` : action;
    
    // 播放动画
    const animAction = window.AnimationEngine.play(this.characterId, actionId, {
      loop: loop ? THREE.LoopRepeat : THREE.LoopOnce,
      fadeIn: 0.2
    });

    if (!animAction) {
      reject(new Error(`动画加载失败: ${actionId}`));
      return;
    }

    if (loop) {
      // 循环动画等待指定时长后停止
      if (duration) {
        setTimeout(() => {
          window.AnimationEngine.stop(this.characterId, 0.3);
          resolve();
        }, duration * 1000);
      } else {
        // 无限循环，需要外部停止
        resolve();
      }
    } else {
      // 单次播放，监听完成
      const checkFinished = () => {
        const current = window.AnimationEngine.getCurrentAction(this.characterId);
        if (!current || current.action.paused || !current.action.isRunning()) {
          resolve();
        } else {
          setTimeout(checkFinished, 100);
        }
      };
      setTimeout(checkFinished, 100);
    }
  }

  /**
   * 执行移动
   */
  executeLocomotion(params, resolve, reject) {
    const { action, to, speed = 1.0, path } = params;
    
    const character = window.CharacterLoader.getModel(this.characterId);
    if (!character) {
      reject(new Error('角色未加载'));
      return;
    }

    // 播放走路动画
    window.AnimationEngine.play(this.characterId, action, {
      loop: true,
      fadeIn: 0.2
    });

    // 目标位置
    const targetPos = new THREE.Vector3(to.x, to.y, to.z);
    const startPos = character.position.clone();
    const distance = startPos.distanceTo(targetPos);
    const duration = distance / speed;

    let elapsed = 0;
    const animate = (dt) => {
      elapsed += dt;
      const t = Math.min(elapsed / duration, 1);
      
      // 位置插值
      character.position.lerpVectors(startPos, targetPos, t);
      
      // 面向目标
      character.lookAt(targetPos.x, character.position.y, targetPos.z);
      
      if (t < 1) {
        requestAnimationFrame(() => animate(0.016));
      } else {
        // 停止走路动画
        window.AnimationEngine.stop(this.characterId, 0.3);
        resolve();
      }
    };

    animate(0);
  }

  /**
   * 执行视线控制
   */
  executeGaze(params, resolve, reject) {
    const { target, duration = 0.5 } = params;
    
    // TODO: 实现视线控制（需要GazeController模块）
    console.log(`[ActionExecutor] 视线转向: ${target}`);
    
    setTimeout(resolve, duration * 1000);
  }

  /**
   * 执行等待
   */
  executeWait(params, resolve, reject) {
    const { duration } = params;
    setTimeout(resolve, (duration || 1) * 1000);
  }

  /**
   * 执行对话
   */
  executeDialogue(params, resolve, reject) {
    const { text, duration } = params;
    
    // 触发对话显示（通过事件总线）
    if (window.EventBus) {
      window.EventBus.emit('dialogue', { text, characterId: this.characterId });
    }
    
    console.log(`[ActionExecutor] 对话: ${text}`);
    
    // 根据文字长度估算时长，或等待TTS完成
    const estimatedDuration = duration || Math.max(2, text.length / 5);
    setTimeout(resolve, estimatedDuration * 1000);
  }

  /**
   * 执行相机切换
   */
  executeCameraSwitch(params, resolve, reject) {
    const { mode, offset, transition = true } = params;
    
    switch (mode) {
      case 'first_person':
        window.CameraManager.switchToFirstPerson(this.characterId);
        break;
      case 'third_person':
        window.CameraManager.switchToThirdPerson(this.characterId, offset);
        break;
      case 'fixed':
        window.CameraManager.switchToFixed(offset, transition);
        break;
    }
    
    setTimeout(resolve, (transition ? 0.8 : 0) * 1000);
  }

  /**
   * 并行执行动作（用于上下半身分离）
   */
  executeParallel(actions) {
    const promises = actions.map(action => this.executeAction(action));
    return Promise.all(promises);
  }

  /**
   * 停止当前序列
   */
  stop() {
    this.isExecuting = false;
    this.queue = [];
    this.currentIndex = 0;
    
    // 停止动画
    if (this.characterId) {
      window.AnimationEngine.stop(this.characterId, 0.3);
    }
    
    console.log('[ActionExecutor] 动作序列已停止');
  }

  /**
   * 执行特殊技能（骨骼动画 + 骨骼节点粒子挂载）
   * params.bone_effects = [{effect_id, attach_bone, offset, start_frame, duration_s, auto_remove}]
   * params.sounds       = {on_start, on_keyframe_N, on_complete}
   */
  executeSpecialSkill(params, resolve, reject) {
    const { file_path, action_id, loop = false, duration, bone_effects = [], sounds } = params;

    // 1. 播放骨骼动画
    const animAction = window.AnimationEngine.play(this.characterId, action_id, {
      loop: loop ? THREE.LoopRepeat : THREE.LoopOnce,
      clampWhenFinished: true,
      fadeIn: 0.1,
    });

    if (!animAction) {
      console.warn(`[ActionExecutor] 特殊技能动画未找到: ${action_id}，仅执行特效`);
    }

    // 2. 按 start_frame 定时挂载骨骼粒子
    if (window.BoneEffectManager) {
      window.BoneEffectManager.applyBoneEffects(this.characterId, bone_effects);
    }

    // 3. 音效触发
    if (sounds) this._playSounds(sounds, duration);

    // 4. 等待动画完成
    const totalDur = (duration || 1.5) * 1000;
    setTimeout(resolve, totalDur);
  }

  /**
   * 执行表情（Morph Target 混合）
   * params.morph_weights = {mouthSmile: 0.8, eyeSquint: 0.3, ...}
   * params.transition_duration_s = 0.3
   */
  executeExpression(params, resolve, reject) {
    const { morph_weights = {}, transition_duration_s = 0.3, sounds } = params;

    const model = window.CharacterLoader.getModel(this.characterId);
    if (!model) { resolve(); return; }

    // 逐帧插值应用 morph 权重
    const targetWeights = morph_weights;
    const startWeights  = {};
    const startTime     = performance.now();
    const durMs         = transition_duration_s * 1000;

    // 收集当前权重作为起始值
    model.traverse(child => {
      if (child.isMesh && child.morphTargetDictionary) {
        Object.keys(targetWeights).forEach(morphName => {
          const idx = child.morphTargetDictionary[morphName];
          if (idx !== undefined) {
            startWeights[morphName] = startWeights[morphName] ?? child.morphTargetInfluences[idx];
          }
        });
      }
    });

    const animate = () => {
      const elapsed = performance.now() - startTime;
      const t = Math.min(elapsed / durMs, 1);

      model.traverse(child => {
        if (child.isMesh && child.morphTargetDictionary && child.morphTargetInfluences) {
          Object.entries(targetWeights).forEach(([morphName, target]) => {
            const idx = child.morphTargetDictionary[morphName];
            if (idx !== undefined) {
              const start = startWeights[morphName] ?? 0;
              child.morphTargetInfluences[idx] = start + (target - start) * t;
            }
          });
        }
      });

      if (t < 1) requestAnimationFrame(animate);
      else resolve();
    };

    requestAnimationFrame(animate);
    if (sounds?.on_enter) this._playOneSfx(sounds.on_enter);
  }

  /**
   * 执行变身序列
   * params 由后端 _plan_transformation 填充，包含：
   *   target_form / model_override / morph_weights / prop_attachments / scale
   *   transition_effect / transition_duration_s
   *   revert_to_form / revert_after_seconds / revert_effect
   *   origin_model / origin_morph_weights / origin_prop_attachments
   */
  executeTransformation(params, resolve, reject) {
    const {
      target_form,
      model_override       = null,
      morph_weights        = {},
      prop_attachments     = [],
      scale                = 1.0,
      transition_effect,
      transition_duration_s = 1.2,
      revert_to_form       = 'human',
      revert_after_seconds = 180,
      revert_effect,
      origin_model         = null,
      origin_morph_weights = {},
      origin_prop_attachments = [],
    } = params;

    const charId = this.characterId;

    // ── Step1: 触发入场音效 ──────────────────────────────────────
    if (params.sounds?.on_enter) this._playOneSfx(params.sounds.on_enter);

    // ── Step2: 触发过渡特效（粒子/WebM），遮盖切换瞬间 ─────────────
    if (transition_effect && window.BoneEffectManager) {
      window.BoneEffectManager.attach(charId, transition_effect, 'hips', {
        auto_remove: true,
        duration_s: transition_duration_s,
      });
    }

    // ── Step3: 特效中途切换外观（被特效遮住，不穿帮）───────────────
    const switchMs = (transition_duration_s * 0.5) * 1000;
    setTimeout(() => {
      // 3a. 若有 model_override → 换整个模型
      if (model_override) {
        this._swapModel(charId, model_override, scale);
      } else {
        // 3b. 无换模型 → 用 morph 渐变 + 缩放
        const model = window.CharacterLoader?.getModel(charId);
        if (model && scale !== 1.0) model.scale.setScalar(scale);
        if (Object.keys(morph_weights).length > 0) {
          this.executeExpression(
            { morph_weights, transition_duration_s: transition_duration_s * 0.5 },
            () => {}, () => {}
          );
        }
      }

      // 3c. 挂载道具到骨骼（如狐耳、九尾）
      if (window.BoneEffectManager && prop_attachments.length > 0) {
        // 先清理原有道具
        window.BoneEffectManager.detachAll(charId);
        prop_attachments.forEach(pa => {
          window.BoneEffectManager.attach(charId, pa.prop_id, pa.attach_bone, {
            offset: pa.offset,
            auto_remove: false,
          });
        });
      }

      // 3d. 通知 CharacterLoader 更新 form 状态（影响动作兼容过滤）
      if (window.CharacterLoader?.switchForm) {
        window.CharacterLoader.switchForm(charId, target_form);
      }

      if (params.sounds?.on_complete) this._playOneSfx(params.sounds.on_complete);

    }, switchMs);

    // ── Step4: 变身完成，启动倒计时 HUD + 自动还原 ─────────────────
    const totalMs = transition_duration_s * 1000;
    setTimeout(() => {
      this._startRevertCountdown(charId, {
        revert_to_form,
        revert_after_seconds,
        revert_effect,
        origin_model,
        origin_morph_weights,
        origin_prop_attachments,
        target_form,
      });
      resolve();
    }, totalMs);
  }

  /**
   * 启动变身倒计时，到时自动还原
   */
  _startRevertCountdown(charId, revertParams) {
    const { revert_after_seconds, revert_to_form, target_form } = revertParams;

    // 清除旧倒计时（防止叠加）
    if (this._revertTimer) {
      clearInterval(this._revertTimer);
      clearTimeout(this._revertTimeout);
    }
    this._revertRemaining = revert_after_seconds;

    // 显示倒计时 HUD
    this._showTransformHUD(target_form, revert_after_seconds);

    // 每秒更新 HUD
    this._revertTimer = setInterval(() => {
      this._revertRemaining--;
      this._updateTransformHUD(this._revertRemaining);
      if (this._revertRemaining <= 0) {
        clearInterval(this._revertTimer);
      }
    }, 1000);

    // 时限到达 → 执行还原
    this._revertTimeout = setTimeout(() => {
      clearInterval(this._revertTimer);
      this._hideTransformHUD();
      this._revertTransformation(charId, revertParams);
    }, revert_after_seconds * 1000);

    console.log(`[ActionExecutor] 变身倒计时启动: ${revert_after_seconds}s 后自动还原为 ${revert_to_form}`);
  }

  /**
   * 执行还原变身（与变身逻辑对称）
   */
  _revertTransformation(charId, revertParams) {
    const {
      revert_to_form, revert_effect,
      origin_model, origin_morph_weights, origin_prop_attachments,
    } = revertParams;

    console.log(`[ActionExecutor] 还原变身 → ${revert_to_form}`);

    // 还原特效
    if (revert_effect && window.BoneEffectManager) {
      window.BoneEffectManager.attach(charId, revert_effect, 'hips', {
        auto_remove: true, duration_s: 1.2,
      });
    }

    setTimeout(() => {
      // 换回原模型
      if (origin_model) {
        this._swapModel(charId, origin_model, 1.0);
      } else {
        // morph 还原为原始权重
        const model = window.CharacterLoader?.getModel(charId);
        if (model) model.scale.setScalar(1.0);
        if (Object.keys(origin_morph_weights).length > 0) {
          this.executeExpression(
            { morph_weights: origin_morph_weights, transition_duration_s: 0.6 },
            () => {}, () => {}
          );
        } else {
          // 清零所有 morph
          this._clearAllMorphs(charId);
        }
      }

      // 卸载所有道具，恢复原始道具挂载
      if (window.BoneEffectManager) {
        window.BoneEffectManager.detachAll(charId);
        origin_prop_attachments.forEach(pa => {
          window.BoneEffectManager.attach(charId, pa.prop_id, pa.attach_bone, {
            offset: pa.offset, auto_remove: false,
          });
        });
      }

      // 还原 form 状态
      if (window.CharacterLoader?.switchForm) {
        window.CharacterLoader.switchForm(charId, revert_to_form);
      }
    }, 600);
  }

  /**
   * 换整个角色模型（model_override 方案）
   */
  _swapModel(charId, modelUrl, scale = 1.0) {
    const scene = window._threeScene; // live-scene.html 挂载的 THREE.Scene
    if (!scene) {
      console.warn('[ActionExecutor] _swapModel: window._threeScene 未找到');
      return;
    }
    const oldModel = window.CharacterLoader?.getModel(charId);
    if (oldModel) oldModel.visible = false;

    // 加载新模型（如已缓存则直接显示）
    const loader = new THREE.GLTFLoader();
    loader.load(modelUrl, (gltf) => {
      const newModel = gltf.scene;
      newModel.scale.setScalar(scale);
      // 继承原始位置
      if (oldModel) {
        newModel.position.copy(oldModel.position);
        newModel.rotation.copy(oldModel.rotation);
      }
      scene.add(newModel);
      // 临时存储，还原时用
      if (!window._swappedModels) window._swappedModels = {};
      window._swappedModels[charId] = { newModel, oldModel };
      console.log(`[ActionExecutor] 模型已切换: ${charId} → ${modelUrl}`);
    });
  }

  /**
   * 清零角色所有 morph 权重（还原用）
   */
  _clearAllMorphs(charId) {
    const model = window.CharacterLoader?.getModel(charId);
    if (!model) return;
    model.traverse(child => {
      if (child.isMesh && child.morphTargetInfluences) {
        child.morphTargetInfluences.fill(0);
      }
    });
  }

  /**
   * 变身状态 HUD（右下角倒计时条）
   */
  _showTransformHUD(formName, seconds) {
    let hud = document.getElementById('transform-hud');
    if (!hud) {
      hud = document.createElement('div');
      hud.id = 'transform-hud';
      hud.style.cssText = `
        position:fixed; bottom:90px; right:20px; z-index:200;
        background:rgba(10,8,4,.88); border:1px solid #c9a55c;
        border-radius:12px; padding:10px 16px; color:#e8dcc8;
        font-size:13px; backdrop-filter:blur(8px);
        display:flex; flex-direction:column; gap:6px; min-width:160px;
      `;
      document.body.appendChild(hud);
    }
    const names = { fox_partial:'半狐形态', fox_full:'全狐形态', human:'人形态' };
    hud.innerHTML = `
      <div style="color:#c9a55c;font-weight:bold;">🦊 ${names[formName] || formName}</div>
      <div id="transform-hud-time" style="font-size:20px;text-align:center;letter-spacing:2px;">
        ${this._formatCountdown(seconds)}
      </div>
      <div style="height:4px;background:#333;border-radius:2px;overflow:hidden;">
        <div id="transform-hud-bar" style="height:100%;background:#c9a55c;width:100%;
          transition:width 1s linear;border-radius:2px;"></div>
      </div>
      <div style="font-size:11px;color:#888;text-align:center;">变身时限</div>
    `;
    hud.style.display = 'flex';
    this._revertTotal = seconds;
  }

  _updateTransformHUD(remaining) {
    const timeEl = document.getElementById('transform-hud-time');
    const barEl  = document.getElementById('transform-hud-bar');
    if (timeEl) timeEl.textContent = this._formatCountdown(remaining);
    if (barEl && this._revertTotal) {
      barEl.style.width = `${(remaining / this._revertTotal) * 100}%`;
    }
    // 最后30秒变红警示
    if (remaining <= 30) {
      if (barEl) barEl.style.background = '#e55';
      if (timeEl) timeEl.style.color = '#ff6666';
    }
  }

  _hideTransformHUD() {
    const hud = document.getElementById('transform-hud');
    if (hud) hud.style.display = 'none';
  }

  _formatCountdown(seconds) {
    const m = String(Math.floor(seconds / 60)).padStart(2, '0');
    const s = String(seconds % 60).padStart(2, '0');
    return `${m}:${s}`;
  }

  /**
   * 执行音效播放（独立音效动作，不阻塞动作队列）
   */
  executeSound(params, resolve, reject) {
    const { sound_id, volume = 1.0, loop = false } = params;
    this._playOneSfx(sound_id, volume, loop);
    resolve(); // 立即 resolve，不阻塞队列
  }

  /**
   * 内部：播放单个音效
   */
  _playOneSfx(soundId, volume = 1.0, loop = false) {
    if (!soundId) return;
    // 优先用已有的 AudioManager，没有则走 fetch API
    if (window.AudioManager?.play) {
      window.AudioManager.play(soundId, { volume, loop });
    } else {
      fetch('/api/sound/play', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sound_id: soundId, volume, loop }),
      }).catch(() => {});
    }
  }

  /**
   * 内部：按 sounds 字典的 timing 键批量触发音效
   * sounds = {on_start, on_keyframe_8, on_complete, loop_during}
   */
  _playSounds(sounds, totalDuration) {
    if (!sounds) return;
    if (sounds.on_start)    this._playOneSfx(sounds.on_start);
    if (sounds.loop_during) this._playOneSfx(sounds.loop_during, 1.0, true);

    // on_keyframe_N → 按帧号换算成秒触发
    Object.entries(sounds).forEach(([key, sfxId]) => {
      const m = key.match(/^on_keyframe_(\d+)$/);
      if (m) {
        const delayS = parseInt(m[1]) / 30; // 假设 30fps
        setTimeout(() => this._playOneSfx(sfxId), delayS * 1000);
      }
    });

    if (sounds.on_complete && totalDuration) {
      setTimeout(() => this._playOneSfx(sounds.on_complete), totalDuration * 1000);
    }
  }

  /**
   * 序列完成
   */
  completeSequence() {
    this.isExecuting = false;
    console.log('[ActionExecutor] 动作序列完成');
    
    if (this.callbacks.onComplete) {
      this.callbacks.onComplete(this.queue);
    }
  }

  /**
   * 获取当前执行状态
   */
  getStatus() {
    return {
      isExecuting: this.isExecuting,
      currentIndex: this.currentIndex,
      totalActions: this.queue.length,
      currentAction: this.queue[this.currentIndex],
      queue: this.queue
    };
  }

  /**
   * 跳转到指定动作
   */
  jumpTo(index) {
    if (index >= 0 && index < this.queue.length) {
      this.currentIndex = index;
      console.log(`[ActionExecutor] 跳转到动作: ${index}`);
    }
  }
}

// 导出单例
window.ActionExecutor = new ActionExecutor();
