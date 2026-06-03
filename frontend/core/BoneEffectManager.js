/**
 * BoneEffectManager.js
 * 骨骼节点特效管理器
 *
 * 功能：
 *  - 将粒子系统 / 3D光效 挂载到角色骨骼节点，自动跟随运动
 *  - 管理特效生命周期（attach / detach / auto_remove）
 *  - 支持 effect_catalog.json 里定义的所有特效类型
 *
 * 使用方式（ActionExecutor 自动调用，无需手动操作）：
 *   BoneEffectManager.attach('bao_qing_host', 'fx_palm_fire', 'rightHand')
 *   BoneEffectManager.detach('bao_qing_host', 'fx_palm_fire')
 */

class BoneEffectManager {
  constructor() {
    // characterId -> Map<effectInstanceId, {mesh, bone, config, timerId}>
    this.attached = new Map();

    // 已加载的特效定义缓存 effectId -> catalogEntry
    this.catalog = null;
    this._loadCatalog();
  }

  // ─────────────────────────────────────────────
  //  初始化：加载 effect_catalog.json
  // ─────────────────────────────────────────────
  async _loadCatalog() {
    try {
      const r = await fetch('/config/effect_catalog.json');
      const data = await r.json();
      // 展平 effects 数组为 id->entry 的 Map
      this.catalog = {};
      for (const entry of (data.effects || [])) {
        this.catalog[entry.id] = entry;
      }
      console.log(`[BoneEffectManager] 加载特效目录: ${Object.keys(this.catalog).length} 个`);
    } catch (e) {
      console.warn('[BoneEffectManager] 特效目录加载失败，使用内置默认配置');
      this.catalog = this._builtinCatalog();
    }
  }

  // ─────────────────────────────────────────────
  //  核心：挂载特效到骨骼节点
  // ─────────────────────────────────────────────
  /**
   * @param {string} characterId  - 角色ID，对应 CharacterLoader
   * @param {string} effectId     - 特效ID，对应 effect_catalog.json
   * @param {string} boneName     - 目标骨骼节点名称（如 "rightHand"）
   * @param {object} options      - 覆盖参数 {offset, duration_s, auto_remove}
   * @returns {string|null}       - instanceId（用于手动 detach）
   */
  attach(characterId, effectId, boneName, options = {}) {
    const skeleton = window.CharacterLoader.getSkeleton(characterId);
    if (!skeleton) {
      console.error(`[BoneEffectManager] 角色未加载: ${characterId}`);
      return null;
    }

    // 骨骼名称模糊匹配（兼容 Mixamo 前缀）
    const bone = this._findBone(skeleton, boneName);
    if (!bone) {
      console.error(`[BoneEffectManager] 未找到骨骼 "${boneName}" on ${characterId}`);
      return null;
    }

    const cfg = (this.catalog && this.catalog[effectId]) || this._builtinCatalog()[effectId];
    if (!cfg) {
      console.warn(`[BoneEffectManager] 未知特效: ${effectId}`);
      return null;
    }

    // 创建特效对象
    const effectMesh = this._createEffect(cfg, options);
    if (!effectMesh) return null;

    // 应用偏移
    const off = options.offset || cfg.offset || { x: 0, y: 0, z: 0 };
    effectMesh.position.set(off.x || 0, off.y || 0, off.z || 0);

    // 挂载到骨骼节点 → 跟随骨骼运动
    bone.add(effectMesh);

    const instanceId = `${effectId}_${Date.now()}`;
    if (!this.attached.has(characterId)) {
      this.attached.set(characterId, new Map());
    }

    const autoRemove = options.auto_remove !== undefined ? options.auto_remove : cfg.auto_remove;
    const duration   = options.duration_s || cfg.duration_s;

    let timerId = null;
    if (autoRemove && duration) {
      timerId = setTimeout(() => {
        this.detach(characterId, instanceId);
      }, duration * 1000);
    }

    this.attached.get(characterId).set(instanceId, {
      mesh: effectMesh,
      bone,
      config: cfg,
      timerId,
      effectId,
    });

    console.log(`[BoneEffectManager] 挂载 ${effectId} → ${boneName} (${characterId}) [instanceId=${instanceId}]`);
    return instanceId;
  }

  // ─────────────────────────────────────────────
  //  卸载特效
  // ─────────────────────────────────────────────
  /**
   * @param {string} characterId
   * @param {string} instanceIdOrEffectId - instanceId 或 effectId（移除同名所有实例）
   */
  detach(characterId, instanceIdOrEffectId) {
    const charEffects = this.attached.get(characterId);
    if (!charEffects) return;

    const toRemove = [];
    for (const [iid, entry] of charEffects.entries()) {
      if (iid === instanceIdOrEffectId || entry.effectId === instanceIdOrEffectId) {
        toRemove.push([iid, entry]);
      }
    }

    for (const [iid, entry] of toRemove) {
      if (entry.timerId) clearTimeout(entry.timerId);
      entry.bone.remove(entry.mesh);
      this._disposeEffect(entry.mesh);
      charEffects.delete(iid);
      console.log(`[BoneEffectManager] 卸载 ${entry.effectId} (${characterId})`);
    }
  }

  /**
   * 卸载角色身上所有特效
   */
  detachAll(characterId) {
    const charEffects = this.attached.get(characterId);
    if (!charEffects) return;
    for (const [iid, entry] of charEffects.entries()) {
      if (entry.timerId) clearTimeout(entry.timerId);
      entry.bone.remove(entry.mesh);
      this._disposeEffect(entry.mesh);
    }
    charEffects.clear();
    console.log(`[BoneEffectManager] 清除所有特效: ${characterId}`);
  }

  // ─────────────────────────────────────────────
  //  从 bone_effects 数组批量处理（ActionExecutor 使用）
  // ─────────────────────────────────────────────
  /**
   * 处理 PlannedAction.params.bone_effects 数组
   * 在动画的第 start_frame 帧触发（通过 setTimeout 模拟）
   * @param {string} characterId
   * @param {Array}  boneEffects  - [{effect_id, attach_bone, offset, start_frame, duration_s, auto_remove}]
   * @param {number} fps          - 动画帧率，默认 30
   * @returns {Array<string>}     - instanceIds，供后续 detach
   */
  applyBoneEffects(characterId, boneEffects, fps = 30) {
    const instanceIds = [];
    for (const be of (boneEffects || [])) {
      const delayMs = be.start_frame ? (be.start_frame / fps) * 1000 : 0;
      setTimeout(() => {
        const iid = this.attach(
          characterId,
          be.effect_id,
          be.attach_bone,
          {
            offset:      be.offset,
            duration_s:  be.duration_s,
            auto_remove: be.auto_remove,
          }
        );
        if (iid) instanceIds.push(iid);
      }, delayMs);
    }
    return instanceIds;
  }

  // ─────────────────────────────────────────────
  //  骨骼名称模糊匹配
  // ─────────────────────────────────────────────
  _findBone(skeleton, boneName) {
    // 精确匹配
    let bone = skeleton.getBoneByName(boneName);
    if (bone) return bone;

    // Mixamo 前缀匹配（mixamorigRightHand → rightHand）
    const mixamoName = 'mixamorig' + boneName.charAt(0).toUpperCase() + boneName.slice(1);
    bone = skeleton.getBoneByName(mixamoName);
    if (bone) return bone;

    // 大小写不敏感遍历
    const lower = boneName.toLowerCase();
    for (const b of skeleton.bones) {
      if (b.name.toLowerCase().includes(lower)) return b.bone || b;
    }

    return null;
  }

  // ─────────────────────────────────────────────
  //  特效对象工厂
  // ─────────────────────────────────────────────
  _createEffect(cfg, options = {}) {
    const type = cfg.type || 'particle';

    switch (type) {
      case 'particle':
      case 'bone_attached':
        return this._createParticleEffect(cfg, options);

      case 'webm_overlay':
        // WebM 特效走 2D 层（不挂骨骼），由 OverlayManager 处理
        console.log(`[BoneEffectManager] WebM特效 "${cfg.id}" 走2D层，跳过骨骼挂载`);
        return null;

      case 'screen_flash':
        console.log(`[BoneEffectManager] 闪光特效 "${cfg.id}" 走屏幕层，跳过骨骼挂载`);
        return null;

      default:
        return this._createParticleEffect(cfg, options);
    }
  }

  /**
   * 创建粒子系统（Three.js Points）
   * 支持 cfg.particle 子配置：color / size / count / spread
   */
  _createParticleEffect(cfg, options) {
    const p = cfg.particle || {};
    const count  = p.count  || 80;
    const size   = p.size   || 0.04;
    const color  = p.color  || '#ff8800';
    const spread = p.spread || 0.15;

    const geometry = new THREE.BufferGeometry();
    const positions = new Float32Array(count * 3);
    const velocities = new Float32Array(count * 3); // 存在 userData 里驱动动画

    for (let i = 0; i < count; i++) {
      positions[i * 3]     = (Math.random() - 0.5) * spread;
      positions[i * 3 + 1] = (Math.random() - 0.5) * spread;
      positions[i * 3 + 2] = (Math.random() - 0.5) * spread;
      velocities[i * 3]     = (Math.random() - 0.5) * 0.01;
      velocities[i * 3 + 1] = Math.random() * 0.02 + 0.005; // 向上漂
      velocities[i * 3 + 2] = (Math.random() - 0.5) * 0.01;
    }

    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));

    const material = new THREE.PointsMaterial({
      color:       new THREE.Color(color),
      size,
      transparent: true,
      opacity:     0.85,
      depthWrite:  false,
      blending:    THREE.AdditiveBlending, // 叠加混合让火焰更亮
      sizeAttenuation: true,
    });

    const points = new THREE.Points(geometry, material);
    points.userData.velocities   = velocities;
    points.userData.isParticle   = true;
    points.userData.effectId     = cfg.id;
    points.userData.lifeTime     = 0;
    points.userData.maxLifeTime  = (p.lifetime_s || 999) * 60; // 帧数

    // 注册到全局 render loop
    this._registerUpdateHook(points, geometry, velocities, count, p);

    return points;
  }

  // ─────────────────────────────────────────────
  //  每帧更新粒子位置（注册到 AnimationEngine.update 钩子）
  // ─────────────────────────────────────────────
  _registerUpdateHook(points, geometry, velocities, count, p) {
    const spread = p.spread || 0.15;
    const hook = () => {
      if (!points.parent) {
        // 已从场景移除，取消钩子
        window._boneEffectHooks = (window._boneEffectHooks || []).filter(h => h !== hook);
        return;
      }

      const pos = geometry.attributes.position.array;
      points.userData.lifeTime++;

      for (let i = 0; i < count; i++) {
        pos[i * 3]     += velocities[i * 3];
        pos[i * 3 + 1] += velocities[i * 3 + 1];
        pos[i * 3 + 2] += velocities[i * 3 + 2];

        // 超出范围重置（循环效果）
        if (pos[i * 3 + 1] > spread * 3) {
          pos[i * 3]     = (Math.random() - 0.5) * spread * 0.3;
          pos[i * 3 + 1] = 0;
          pos[i * 3 + 2] = (Math.random() - 0.5) * spread * 0.3;
        }
      }
      geometry.attributes.position.needsUpdate = true;
    };

    window._boneEffectHooks = window._boneEffectHooks || [];
    window._boneEffectHooks.push(hook);
  }

  // ─────────────────────────────────────────────
  //  释放资源
  // ─────────────────────────────────────────────
  _disposeEffect(mesh) {
    if (!mesh) return;
    mesh.geometry?.dispose();
    mesh.material?.dispose();
  }

  // ─────────────────────────────────────────────
  //  内置默认特效目录（API不通时的 fallback）
  // ─────────────────────────────────────────────
  _builtinCatalog() {
    return {
      fx_palm_fire: {
        id: 'fx_palm_fire', type: 'bone_attached',
        particle: { color: '#ff6600', size: 0.03, count: 60, spread: 0.08, lifetime_s: 999 },
        offset: { x: 0, y: 0.05, z: 0 },
        duration_s: null, auto_remove: false,
      },
      fx_fox_fire_burst: {
        id: 'fx_fox_fire_burst', type: 'particle',
        particle: { color: '#00aaff', size: 0.05, count: 120, spread: 0.3, lifetime_s: 2.0 },
        offset: { x: 0, y: 0.1, z: 0 },
        duration_s: 2.0, auto_remove: true,
      },
      fx_fox_fire_aura: {
        id: 'fx_fox_fire_aura', type: 'bone_attached',
        particle: { color: '#0066ff', size: 0.025, count: 80, spread: 0.2, lifetime_s: 999 },
        offset: { x: 0, y: 0, z: 0 },
        duration_s: null, auto_remove: false,
      },
      fx_robot_materialize: {
        id: 'fx_robot_materialize', type: 'particle',
        particle: { color: '#00ffcc', size: 0.04, count: 100, spread: 0.5, lifetime_s: 2.0 },
        offset: { x: 0, y: 0.5, z: 0 },
        duration_s: 2.0, auto_remove: true,
      },
    };
  }
}

window.BoneEffectManager = new BoneEffectManager();

// ─────────────────────────────────────────────
//  接入 AnimationEngine 的每帧更新（打一个全局钩子）
// ─────────────────────────────────────────────
// 在 AnimationEngine.update() 调用后执行所有粒子钩子
const _origAnimEngineUpdate = window.AnimationEngine?.update?.bind(window.AnimationEngine);
if (_origAnimEngineUpdate) {
  window.AnimationEngine.update = function(dt) {
    _origAnimEngineUpdate(dt);
    if (window._boneEffectHooks) {
      for (const hook of window._boneEffectHooks) hook();
    }
  };
} else {
  // AnimationEngine 还未初始化时，延迟注入
  window.addEventListener('DOMContentLoaded', () => {
    setTimeout(() => {
      const orig = window.AnimationEngine?.update?.bind(window.AnimationEngine);
      if (orig) {
        window.AnimationEngine.update = function(dt) {
          orig(dt);
          if (window._boneEffectHooks) {
            for (const hook of window._boneEffectHooks) hook();
          }
        };
      }
    }, 500);
  });
}
