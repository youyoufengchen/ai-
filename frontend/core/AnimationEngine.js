/**
 * AnimationEngine.js
 * 核心骨骼动画引擎
 * 负责：Three.js AnimationMixer管理、动画融合、状态追踪
 */

class AnimationEngine {
  constructor() {
    this.mixers = new Map(); // characterId -> AnimationMixer
    this.clips = new Map();  // actionId -> AnimationClip
    this.currentActions = new Map(); // characterId -> {action, clip}
    this.isInitialized = false;
  }

  init() {
    console.log('[AnimationEngine] 初始化完成');
    this.isInitialized = true;
    return this;
  }

  /**
   * 为角色创建AnimationMixer
   */
  createMixer(characterId, model) {
    const mixer = new THREE.AnimationMixer(model);
    this.mixers.set(characterId, mixer);
    
    // 监听动画事件
    mixer.addEventListener('finished', (e) => {
      this.onAnimationFinished(characterId, e);
    });
    
    mixer.addEventListener('loop', (e) => {
      this.onAnimationLoop(characterId, e);
    });
    
    console.log(`[AnimationEngine] 为角色 ${characterId} 创建Mixer`);
    return mixer;
  }

  /**
   * 加载动画剪辑
   */
  loadClip(actionId, glbAnimationUrl) {
    return new Promise((resolve, reject) => {
      const loader = new THREE.GLTFLoader();
      loader.load(glbAnimationUrl, (gltf) => {
        const clip = gltf.animations[0];
        if (clip) {
          clip.name = actionId;
          this.clips.set(actionId, clip);
          console.log(`[AnimationEngine] 加载动画: ${actionId}`);
          resolve(clip);
        } else {
          reject(new Error(`GLB文件中没有动画: ${glbAnimationUrl}`));
        }
      }, undefined, reject);
    });
  }

  /**
   * 播放动画
   */
  play(characterId, actionId, options = {}) {
    const mixer = this.mixers.get(characterId);
    const clip = this.clips.get(actionId);
    
    if (!mixer) {
      console.error(`[AnimationEngine] 未找到角色Mixer: ${characterId}`);
      return null;
    }
    
    if (!clip) {
      console.error(`[AnimationEngine] 未找到动画剪辑: ${actionId}`);
      return null;
    }

    const action = mixer.clipAction(clip);
    
    // 设置选项
    action.loop = options.loop !== undefined ? options.loop : THREE.LoopOnce;
    action.clampWhenFinished = options.clampWhenFinished || true;
    
    // 淡入
    const fadeInDuration = options.fadeIn || 0.2;
    action.reset().fadeIn(fadeInDuration).play();
    
    this.currentActions.set(characterId, { action, clip, actionId });
    
    console.log(`[AnimationEngine] 播放: ${characterId} -> ${actionId}`);
    return action;
  }

  /**
   * 停止当前动画
   */
  stop(characterId, fadeOut = 0.2) {
    const current = this.currentActions.get(characterId);
    if (current && current.action) {
      current.action.fadeOut(fadeOut).stop();
      console.log(`[AnimationEngine] 停止: ${characterId}`);
    }
  }

  /**
   * 动画过渡
   */
  crossFade(characterId, fromActionId, toActionId, duration = 0.3) {
    const mixer = this.mixers.get(characterId);
    if (!mixer) return;

    const fromClip = this.clips.get(fromActionId);
    const toClip = this.clips.get(toActionId);
    
    if (!fromClip || !toClip) {
      console.error(`[AnimationEngine] 过渡失败: 找不到动画`);
      return;
    }

    const fromAction = mixer.clipAction(fromClip);
    const toAction = mixer.clipAction(toClip);
    
    fromAction.crossFadeTo(toAction, duration, false);
    toAction.play();
    
    this.currentActions.set(characterId, { action: toAction, clip: toClip, actionId: toActionId });
    
    console.log(`[AnimationEngine] 过渡: ${fromActionId} -> ${toActionId} (${duration}s)`);
  }

  /**
   * 更新所有Mixer（每帧调用）
   */
  update(deltaTime) {
    this.mixers.forEach((mixer) => {
      mixer.update(deltaTime);
    });
  }

  /**
   * 设置动画速度
   */
  setTimeScale(characterId, scale) {
    const mixer = this.mixers.get(characterId);
    if (mixer) {
      mixer.timeScale = scale;
    }
  }

  onAnimationFinished(characterId, event) {
    console.log(`[AnimationEngine] 动画完成: ${characterId}`);
    // TODO: 触发回调
  }

  onAnimationLoop(characterId, event) {
    // TODO: 处理循环
  }

  /**
   * 获取当前播放的动画信息
   */
  getCurrentAction(characterId) {
    return this.currentActions.get(characterId);
  }

  /**
   * 清理资源
   */
  dispose(characterId) {
    const mixer = this.mixers.get(characterId);
    if (mixer) {
      mixer.stopAllAction();
      mixer.uncacheRoot(mixer.getRoot());
      this.mixers.delete(characterId);
    }
    this.currentActions.delete(characterId);
    console.log(`[AnimationEngine] 清理资源: ${characterId}`);
  }
}

// 导出单例
window.AnimationEngine = new AnimationEngine();
