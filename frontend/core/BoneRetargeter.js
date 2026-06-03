/**
 * BoneRetargeter - Mixamo动画 → VRM骨骼重定向器
 * 
 * 核心功能：
 * 1. 骨骼名称映射（mixamorigHips → hips）
 * 2. Hips坐标系转换（Mixamo hips在腰部，VRM hips在地面）
 * 3. 动画Clip实时重定向
 */

class BoneRetargeter {
  constructor() {
    this.boneMap = null;        // Mixamo → VRM 骨骼名映射
    this.inverseMap = null;     // VRM → Mixamo 反向映射
    this.loaded = false;
  }

  /**
   * 加载骨骼映射配置
   */
  async loadConfig() {
    if (this.loaded) return;
    
    try {
      // 从后端获取骨骼映射表
      const res = await fetch('/api/skeleton-types');
      const data = await res.json();
      
      if (data.retarget_maps?.mixamo_to_vrm) {
        this.boneMap = data.retarget_maps.mixamo_to_vrm;
        // 构建反向映射
        this.inverseMap = {};
        for (const [mixamo, vrm] of Object.entries(this.boneMap)) {
          this.inverseMap[vrm] = mixamo;
        }
        this.loaded = true;
        console.log('[BoneRetargeter] 骨骼映射表加载完成:', Object.keys(this.boneMap).length, '个骨骼');
      }
    } catch (e) {
      console.error('[BoneRetargeter] 加载配置失败:', e);
      // 使用默认映射作为fallback
      this.boneMap = this._getDefaultBoneMap();
      this.inverseMap = {};
      for (const [mixamo, vrm] of Object.entries(this.boneMap)) {
        this.inverseMap[vrm] = mixamo;
      }
      this.loaded = true;
    }
  }

  /**
   * 重定向动画Clip（Mixamo → VRM）
   * @param {THREE.AnimationClip} clip - 原始Mixamo动画
   * @param {THREE.Object3D} vrmScene - VRM模型的scene
   * @returns {THREE.AnimationClip} 重定向后的动画
   */
  retargetClip(clip, vrmScene) {
    if (!this.loaded) {
      console.warn('[BoneRetargeter] 配置未加载，使用原始动画');
      return clip;
    }

    // 克隆clip以免修改原始数据
    const newClip = clip.clone();
    
    // 重定向每个track
    newClip.tracks = clip.tracks.map(track => {
      return this._retargetTrack(track, vrmScene);
    }).filter(Boolean); // 过滤掉null

    return newClip;
  }

  /**
   * 重定向单个动画轨道
   */
  _retargetTrack(track, vrmScene) {
    // 支持两种track名格式：
    //   格式A: ".bones[mixamorigHips].quaternion"  (带bones[])
    //   格式B: "mixamorigHips.quaternion"           (直接骨骼名)
    let mixamoName, property, useBonesFormat;

    const bonesMatch = track.name.match(/\.bones\[(.+?)\]\.?(.*)/);
    if (bonesMatch) {
      mixamoName = bonesMatch[1];
      property = bonesMatch[2] || 'quaternion';
      useBonesFormat = true;
    } else {
      const dotIdx = track.name.lastIndexOf('.');
      if (dotIdx < 0) return null;
      mixamoName = track.name.substring(0, dotIdx);
      property = track.name.substring(dotIdx + 1);
      useBonesFormat = false;
    }

    // 跳过scale轨道（Mixamo缩放值不适用于VRM）
    if (property === 'scale') return null;

    // 查找VRM对应骨骼名
    const vrmName = this.boneMap[mixamoName];
    if (!vrmName || mixamoName === '_comment') {
      return null; // 跳过未知骨骼或注释键
    }

    // 非hips骨骼的position track也跳过：Mixamo存的是绝对坐标，直接用会拉飞VRM局部骨骼
    if (property === 'position' && vrmName !== 'Normalized_J_Bip_C_Hips') return null;

    // 在VRM场景中查找对应骨骼节点（VRM骨骼可能是Object3D而非Bone）
    let targetBone = null;
    vrmScene.traverse(node => {
      if ((node.isBone || node.isObject3D) && node.name === vrmName) {
        targetBone = node;
      }
    });

    if (!targetBone) {
      console.warn(`[BoneRetargeter] VRM中未找到骨骼: ${vrmName}`);
      return null;
    }

    // 构建新的track名称（保持与原格式一致）
    const newTrackName = useBonesFormat
      ? track.name.replace(`.bones[${mixamoName}]`, `.bones[${targetBone.name}]`)
      : `${targetBone.name}.${property}`;

    // 克隆track并修改名称
    const newTrack = track.clone();
    newTrack.name = newTrackName;

    // 特殊处理 hips 骨骼的位置（Mixamo hips在腰部，VRM hips在地面，需要坐标转换）
    if ((vrmName === 'Normalized_J_Bip_C_Hips') && property.includes('position')) {
      return this._convertHipsPosition(newTrack, vrmScene);
    }

    // 特殊处理旋转方向（Mixamo和VRM可能有不同的坐标系朝向）
    if (property.includes('quaternion')) {
      return this._convertQuaternion(newTrack, mixamoName, vrmName);
    }

    return newTrack;
  }

  /**
   * 转换 hips 位置（关键：Mixamo hips高度 vs VRM hips高度）
   * Mixamo: hips在腰部，动画记录的是相对位移
   * VRM: hips通常在地面(0,0,0)，需要把动画位移映射到正确的高度
   */
  _convertHipsPosition(track, vrmScene) {
    // 获取VRM hips节点的 local rest position（骨骼层级里的局部坐标）
    let vrmHipsRestLocal = new THREE.Vector3();
    vrmScene.traverse(node => {
      if ((node.isBone || node.isObject3D) && (node.name === 'Normalized_J_Bip_C_Hips' || node.name === 'J_Bip_C_Hips')) {
        vrmHipsRestLocal.copy(node.position);
      }
    });

    const newTrack = track.clone();
    const values = newTrack.values;
    const frameCount = values.length / 3;

    // 计算Mixamo hips动画的平均（基准）位置，用于去除绝对偏置
    let baseX = 0, baseY = 0, baseZ = 0;
    for (let i = 0; i < values.length; i += 3) {
      baseX += values[i]; baseY += values[i+1]; baseZ += values[i+2];
    }
    baseX /= frameCount; baseY /= frameCount; baseZ /= frameCount;

    // 只保留相对于基准的位移变化，叠加VRM的rest local position
    for (let i = 0; i < values.length; i += 3) {
      values[i]   = vrmHipsRestLocal.x + (values[i]   - baseX);
      values[i+1] = vrmHipsRestLocal.y + (values[i+1] - baseY);
      values[i+2] = vrmHipsRestLocal.z + (values[i+2] - baseZ);
    }

    return newTrack;
  }

  /**
   * 转换四元数（处理左右手坐标系差异）
   */
  _convertQuaternion(track, mixamoName, vrmName) {
    // scene.rotation.y = PI 只影响视觉渲染，不影响 Normalized 层骨骼坐标系
    // Mixamo 和 VRM Normalized 层都是 Y-up 右手系，四元数可直接使用
    return track.clone();
  }

  /**
   * 匹配VRM骨骼节点（处理命名差异）
   */
  _matchVrmBone(node, vrmName) {
    const name = node.name.toLowerCase();
    const target = vrmName.toLowerCase();
    
    // 直接匹配
    if (name === target) return true;
    
    // 常见变体匹配
    const variants = {
      'hips': ['hips', 'hip', 'mixamorighips'],
      'spine': ['spine', 'mixamorigspine'],
      'chest': ['chest', 'mixamorigspine1'],
      'upperchest': ['upperchest', 'upper_chest', 'mixamorigspine2'],
      'neck': ['neck', 'mixamorigneck'],
      'head': ['head', 'mixamorighead'],
      'leftshoulder': ['leftshoulder', 'left_shoulder', 'mixamorigleftshoulder'],
      'leftupperarm': ['leftupperarm', 'left_upper_arm', 'mixamorigleftarm'],
      'leftlowerarm': ['leftlowerarm', 'left_lower_arm', 'mixamorigleftforearm'],
      'lefthand': ['lefthand', 'left_hand', 'mixamoriglefthand'],
      'rightshoulder': ['rightshoulder', 'right_shoulder', 'mixamorigrightshoulder'],
      'rightupperarm': ['rightupperarm', 'right_upper_arm', 'mixamorigrightarm'],
      'rightlowerarm': ['rightlowerarm', 'right_lower_arm', 'mixamorigrightforearm'],
      'righthand': ['righthand', 'right_hand', 'mixamorigrighthand'],
      'leftupperleg': ['leftupperleg', 'left_upper_leg', 'mixamorigleftupleg'],
      'leftlowerleg': ['leftlowerleg', 'left_lower_leg', 'mixamorigleftleg'],
      'leftfoot': ['leftfoot', 'left_foot', 'mixamorigleftfoot'],
      'lefttoes': ['lefttoes', 'left_toes', 'mixamoriglefttoebase'],
      'rightupperleg': ['rightupperleg', 'right_upper_leg', 'mixamorigrightupleg'],
      'rightlowerleg': ['rightlowerleg', 'right_lower_leg', 'mixamorigrightleg'],
      'rightfoot': ['rightfoot', 'right_foot', 'mixamorigrightfoot'],
      'righttoes': ['righttoes', 'right_toes', 'mixamorigrighttoebase']
    };
    
    if (variants[target]) {
      return variants[target].includes(name);
    }
    
    return false;
  }

  /**
   * 默认骨骼映射（fallback）
   */
  _getDefaultBoneMap() {
    return {
      'mixamorigHips':          'Normalized_J_Bip_C_Hips',
      'mixamorigSpine':         'Normalized_J_Bip_C_Spine',
      'mixamorigSpine1':        'Normalized_J_Bip_C_Chest',
      'mixamorigSpine2':        'Normalized_J_Bip_C_UpperChest',
      'mixamorigNeck':          'Normalized_J_Bip_C_Neck',
      'mixamorigHead':          'Normalized_J_Bip_C_Head',
      'mixamorigLeftShoulder':  'Normalized_J_Bip_L_Shoulder',
      'mixamorigLeftArm':       'Normalized_J_Bip_L_UpperArm',
      'mixamorigLeftForeArm':   'Normalized_J_Bip_L_LowerArm',
      'mixamorigLeftHand':      'Normalized_J_Bip_L_Hand',
      'mixamorigRightShoulder': 'Normalized_J_Bip_R_Shoulder',
      'mixamorigRightArm':      'Normalized_J_Bip_R_UpperArm',
      'mixamorigRightForeArm':  'Normalized_J_Bip_R_LowerArm',
      'mixamorigRightHand':     'Normalized_J_Bip_R_Hand',
      'mixamorigLeftUpLeg':     'Normalized_J_Bip_L_UpperLeg',
      'mixamorigLeftLeg':       'Normalized_J_Bip_L_LowerLeg',
      'mixamorigLeftFoot':      'Normalized_J_Bip_L_Foot',
      'mixamorigLeftToeBase':   'Normalized_J_Bip_L_ToeBase',
      'mixamorigRightUpLeg':    'Normalized_J_Bip_R_UpperLeg',
      'mixamorigRightLeg':      'Normalized_J_Bip_R_LowerLeg',
      'mixamorigRightFoot':     'Normalized_J_Bip_R_Foot',
      'mixamorigRightToeBase':  'Normalized_J_Bip_R_ToeBase'
    };
  }

  /**
   * 创建适用于VRM的动画Mixer
   * @param {THREE.Object3D} vrmRoot - VRM模型的根对象
   * @returns {THREE.AnimationMixer} 配置好的mixer
   */
  createVRMMixer(vrmRoot) {
    const mixer = new THREE.AnimationMixer(vrmRoot);
    
    // 重写 mixer 的 clipAction 方法，自动进行重定向
    const originalClipAction = mixer.clipAction.bind(mixer);
    mixer.clipAction = (clip, root) => {
      // 如果clip的来源是Mixamo（通过track名称判断）
      const isMixamoClip = clip.tracks.some(t => t.name.includes('mixamorig'));
      
      if (isMixamoClip && this.loaded) {
        const retargetedClip = this.retargetClip(clip, vrmRoot);
        return originalClipAction(retargetedClip, root);
      }
      
      return originalClipAction(clip, root);
    };
    
    return mixer;
  }
}

// 导出
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { BoneRetargeter };
} else {
  window.BoneRetargeter = BoneRetargeter;
}
