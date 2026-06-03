/**
 * CameraManager.js
 * 相机管理系统
 * 负责：多视角切换、跟随、第一人称
 */

class CameraManager {
  constructor() {
    this.camera = null;
    this.controls = null;
    this.currentMode = 'third_person'; // first_person, third_person, fixed
    this.modeConfig = {
      first_person: {
        fov: 75,
        near: 0.1,
        far: 1000,
        heightOffset: 0.1 // 眼睛在头部下方一点
      },
      third_person: {
        fov: 60,
        near: 0.1,
        far: 1000,
        offset: { x: 0, y: 1.7, z: -2.5 }, // 后方2.5米，高度1.7米
        smoothFollow: 0.1
      },
      fixed: {
        fov: 50,
        positions: {
          facing_screen: { pos: [0, 1.6, 3], lookAt: [0, 1, 0] },
          facing_counter: { pos: [0, 1.6, 2], lookAt: [0, 1, 0] },
          overview: { pos: [0, 5, 8], lookAt: [0, 0, 0] }
        }
      }
    };
    
    this.target = null; // 跟随目标
    this.currentOffset = { x: 0, y: 1.7, z: -2.5 };
    this.transitionDuration = 0.8;
    this.isTransitioning = false;
  }

  /**
   * 初始化相机。
   * @param {THREE.Renderer} renderer
   * @param {Element} domElement
   * @param {THREE.PerspectiveCamera} [existingCamera] - 传入已有相机（可选）
   * @param {THREE.OrbitControls} [existingControls] - 传入已有controls（可选）
   */
  init(renderer, domElement, existingCamera, existingControls) {
    if (existingCamera) {
      this.camera = existingCamera;
    } else {
      this.camera = new THREE.PerspectiveCamera(
        60, window.innerWidth / window.innerHeight, 0.1, 1000
      );
      this.camera.position.set(0, 2, 5);
    }

    if (existingControls) {
      this.controls = existingControls;
    } else if (domElement) {
      this.controls = new THREE.OrbitControls(this.camera, domElement);
      this.controls.enableDamping = true;
      this.controls.dampingFactor = 0.1;
    }
    
    console.log('[CameraManager] 相机初始化完成', existingCamera ? '(外部相机)' : '(新建相机)');
    return this;
  }

  /**
   * 切换到第一人称视角(NPC眼睛)
   */
  switchToFirstPerson(characterId) {
    const character = window.CharacterLoader.getModel(characterId);
    if (!character) {
      console.error(`[CameraManager] 未找到角色: ${characterId}`);
      return;
    }

    const headBone = window.CharacterLoader.getHeadBone(characterId);
    if (!headBone) {
      console.error(`[CameraManager] 角色没有头部骨骼: ${characterId}`);
      return;
    }

    this.currentMode = 'first_person';
    this.target = characterId;
    
    // 设置FOV
    this.camera.fov = this.modeConfig.first_person.fov;
    this.camera.updateProjectionMatrix();
    
    // 禁用OrbitControls（第一人称不需要）
    this.controls.enabled = false;
    
    console.log(`[CameraManager] 切换到第一人称: ${characterId}`);
  }

  /**
   * 切换到第三人称跟随
   */
  switchToThirdPerson(characterId, offset = 'default') {
    const character = window.CharacterLoader.getModel(characterId);
    if (!character) {
      console.error(`[CameraManager] 未找到角色: ${characterId}`);
      return;
    }

    this.currentMode = 'third_person';
    this.target = characterId;
    
    // 设置偏移
    const offsets = {
      default: { x: 0, y: 1.7, z: -2.5 },
      behind: { x: 0, y: 1.7, z: -3 },
      left: { x: -1.5, y: 1.7, z: -1.5 },
      right: { x: 1.5, y: 1.7, z: -1.5 },
      front: { x: 0, y: 1.5, z: 2 }
    };
    
    this.currentOffset = offsets[offset] || offsets.default;
    
    // 设置FOV
    this.camera.fov = this.modeConfig.third_person.fov;
    this.camera.updateProjectionMatrix();
    
    // 启用OrbitControls但限制范围
    this.controls.enabled = true;
    this.controls.minDistance = 2;
    this.controls.maxDistance = 10;
    
    console.log(`[CameraManager] 切换到第三人称: ${characterId}, 偏移: ${offset}`);
  }

  /**
   * 切换到固定视角。
   * 先查内置 modeConfig.fixed.positions，再查 window.SCENE_CAMERA_PRESETS（场景配置注入）
   */
  switchToFixed(positionType = 'facing_screen', transition = true) {
    let config = this.modeConfig.fixed.positions[positionType];
    // 从场景camera_presets中查找
    if (!config && window.SCENE_CAMERA_PRESETS) {
      const preset = window.SCENE_CAMERA_PRESETS.find(p => p.id === positionType);
      if (preset) config = { pos: preset.pos, lookAt: preset.lookAt };
    }
    if (!config) {
      console.warn(`[CameraManager] 未找到固定视角配置: ${positionType}，使用默认`);
      config = this.modeConfig.fixed.positions.facing_screen;
    }

    this.currentMode = 'fixed';
    this.target = null;
    
    this.camera.fov = this.modeConfig.fixed.fov;
    this.camera.updateProjectionMatrix();
    
    if (this.controls) this.controls.enabled = false;
    
    if (transition) {
      this.animateCameraTo(config.pos, config.lookAt);
    } else {
      this.camera.position.set(...config.pos);
      this.camera.lookAt(...config.lookAt);
    }
    
    console.log(`[CameraManager] 切换到固定视角: ${positionType}`);
  }

  /**
   * 相机过渡动画
   */
  animateCameraTo(targetPos, targetLookAt, duration = 0.8) {
    if (this.isTransitioning) return;
    
    this.isTransitioning = true;
    
    const startPos = this.camera.position.clone();
    const startRot = this.camera.rotation.clone();
    
    const targetVector = new THREE.Vector3(...targetPos);
    const lookAtVector = new THREE.Vector3(...targetLookAt);
    
    // 临时相机计算目标旋转
    const tempCam = this.camera.clone();
    tempCam.position.copy(targetVector);
    tempCam.lookAt(lookAtVector);
    const targetRot = tempCam.rotation.clone();
    
    let elapsed = 0;
    const animate = (dt) => {
      elapsed += dt;
      const t = Math.min(elapsed / duration, 1);
      
      // 缓动函数
      const ease = this.easeInOutCubic(t);
      
      // 位置插值
      this.camera.position.lerpVectors(startPos, targetVector, ease);
      
      // 旋转插值
      this.camera.rotation.x = startRot.x + (targetRot.x - startRot.x) * ease;
      this.camera.rotation.y = startRot.y + (targetRot.y - startRot.y) * ease;
      this.camera.rotation.z = startRot.z + (targetRot.z - startRot.z) * ease;
      
      if (t < 1) {
        requestAnimationFrame(() => animate(0.016));
      } else {
        this.isTransitioning = false;
        this.camera.lookAt(lookAtVector);
      }
    };
    
    animate(0);
  }

  /**
   * 更新相机位置（每帧调用）
   */
  update(deltaTime) {
    if (this.currentMode === 'first_person' && this.target) {
      this.updateFirstPerson();
    } else if (this.currentMode === 'third_person' && this.target) {
      this.updateThirdPerson(deltaTime);
    }
    
    if (this.controls && this.controls.enabled) {
      this.controls.update();
    }
  }

  /**
   * 更新第一人称视角
   */
  updateFirstPerson() {
    const character = window.CharacterLoader.getModel(this.target);
    const headBone = window.CharacterLoader.getHeadBone(this.target);
    
    if (!character || !headBone) return;
    
    // 获取头部世界位置
    const headPos = new THREE.Vector3();
    headBone.getWorldPosition(headPos);
    
    // 获取头部朝向
    const headDir = new THREE.Vector3(0, 0, 1);
    headDir.applyQuaternion(headBone.getWorldQuaternion(new THREE.Quaternion()));
    
    // 设置相机位置（眼睛位置）
    const offset = headDir.clone().multiplyScalar(0.1); // 稍微向前
    offset.y = this.modeConfig.first_person.heightOffset;
    
    this.camera.position.copy(headPos).add(offset);
    
    // 视线方向
    const lookAt = headPos.clone().add(headDir.multiplyScalar(10));
    this.camera.lookAt(lookAt);
  }

  /**
   * 更新第三人称跟随
   */
  updateThirdPerson(deltaTime) {
    const character = window.CharacterLoader.getModel(this.target);
    if (!character) return;
    
    const targetPos = character.position.clone();
    targetPos.y += this.currentOffset.y; // 目标点抬高到角色胸部/头部高度
    
    // 计算相机目标位置（角色后方）
    const charRotation = character.rotation.y;
    const offset = new THREE.Vector3(
      this.currentOffset.x,
      0,
      this.currentOffset.z
    );
    offset.applyAxisAngle(new THREE.Vector3(0, 1, 0), charRotation);
    
    const cameraTargetPos = character.position.clone().add(offset);
    cameraTargetPos.y = this.currentOffset.y;
    
    // 平滑跟随
    const smooth = this.modeConfig.third_person.smoothFollow;
    this.camera.position.lerp(cameraTargetPos, smooth);
    
    // 相机朝向角色
    this.camera.lookAt(targetPos);
  }

  easeInOutCubic(t) {
    return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
  }

  /**
   * 获取当前相机模式
   */
  getCurrentMode() {
    return this.currentMode;
  }

  /**
   * 调整FOV
   */
  setFov(fov) {
    this.camera.fov = fov;
    this.camera.updateProjectionMatrix();
  }

  /**
   * 响应窗口大小变化
   */
  onWindowResize(width, height) {
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
  }
}

// 导出单例
window.CameraManager = new CameraManager();
