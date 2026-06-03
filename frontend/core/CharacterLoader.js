/**
 * CharacterLoader.js
 * 角色加载器
 * 负责：GLB角色加载、形态切换、骨骼解析
 */

class CharacterLoader {
  constructor() {
    this.characters = new Map(); // characterId -> {model, skeleton, morphs}
    this.currentForm = new Map(); // characterId -> formId
    this.loader = new THREE.GLTFLoader();
  }

  /**
   * 加载角色GLB文件
   */
  async loadCharacter(characterId, url, options = {}) {
    return new Promise((resolve, reject) => {
      this.loader.load(url, (gltf) => {
        const model = gltf.scene;
        
        // 启用阴影
        model.traverse((child) => {
          if (child.isMesh) {
            child.castShadow = true;
            child.receiveShadow = true;
          }
        });

        // 解析骨骼
        const skeleton = this.extractSkeleton(model);
        
        // 解析形态键
        const morphs = this.extractMorphs(model);
        
        // 保存角色数据
        const characterData = {
          id: characterId,
          model: model,
          skeleton: skeleton,
          morphs: morphs,
          gltf: gltf,
          defaultForm: options.defaultForm || 'human',
          forms: options.forms || {}
        };
        
        this.characters.set(characterId, characterData);
        this.currentForm.set(characterId, options.defaultForm || 'human');
        
        console.log(`[CharacterLoader] 加载角色: ${characterId}`);
        console.log(`  - 骨骼数: ${skeleton.bones.length}`);
        console.log(`  - 形态键: ${morphs.length}`);
        
        resolve(characterData);
      }, undefined, reject);
    });
  }

  /**
   * 提取骨骼结构
   */
  extractSkeleton(model) {
    const bones = [];
    let rootBone = null;
    
    model.traverse((child) => {
      if (child.isBone) {
        bones.push({
          name: child.name,
          bone: child,
          parent: child.parent?.name || null
        });
        if (!rootBone) rootBone = child;
      }
    });

    return {
      bones: bones,
      root: rootBone,
      getBoneByName: (name) => bones.find(b => b.name === name)?.bone
    };
  }

  /**
   * 提取形态键(BlendShapes)
   */
  extractMorphs(model) {
    const morphs = [];
    
    model.traverse((child) => {
      if (child.isMesh && child.morphTargetDictionary) {
        const targets = Object.keys(child.morphTargetDictionary);
        morphs.push(...targets);
      }
    });

    return [...new Set(morphs)]; // 去重
  }

  /**
   * 切换角色形态
   */
  switchForm(characterId, formId) {
    const character = this.characters.get(characterId);
    if (!character) {
      console.error(`[CharacterLoader] 未找到角色: ${characterId}`);
      return false;
    }

    const formConfig = character.forms[formId];
    if (!formConfig) {
      console.error(`[CharacterLoader] 未找到形态: ${formId}`);
      return false;
    }

    // 应用形态变换
    const { scale, heightOffset, morphWeights } = formConfig;
    
    if (scale) {
      character.model.scale.set(scale, scale, scale);
    }
    
    if (heightOffset) {
      character.model.position.y = heightOffset;
    }

    // 应用形态键权重
    if (morphWeights) {
      character.model.traverse((child) => {
        if (child.isMesh && child.morphTargetInfluences) {
          Object.entries(morphWeights).forEach(([morphName, weight]) => {
            const index = child.morphTargetDictionary[morphName];
            if (index !== undefined) {
              child.morphTargetInfluences[index] = weight;
            }
          });
        }
      });
    }

    this.currentForm.set(characterId, formId);
    console.log(`[CharacterLoader] 切换形态: ${characterId} -> ${formId}`);
    return true;
  }

  /**
   * 获取当前形态ID
   */
  getCurrentForm(characterId) {
    return this.currentForm.get(characterId);
  }

  /**
   * 获取角色模型
   */
  getModel(characterId) {
    return this.characters.get(characterId)?.model;
  }

  /**
   * 获取骨骼
   */
  getSkeleton(characterId) {
    return this.characters.get(characterId)?.skeleton;
  }

  /**
   * 获取身高（用于相机计算）
   */
  getHeight(characterId) {
    const character = this.characters.get(characterId);
    if (!character) return 1.7;

    const currentForm = this.currentForm.get(characterId);
    const formConfig = character.forms[currentForm];
    
    // 基础高度 * 形态缩放
    const baseHeight = 1.7;
    const scale = formConfig?.scale || 1.0;
    
    return baseHeight * scale;
  }

  /**
   * 获取头部骨骼（用于第一人称相机）
   */
  getHeadBone(characterId) {
    const skeleton = this.getSkeleton(characterId);
    if (!skeleton) return null;

    // 常见头部骨骼名称
    const headNames = ['Head', 'head', 'HEAD', 'mixamorigHead'];
    for (const name of headNames) {
      const bone = skeleton.getBoneByName(name);
      if (bone) return bone;
    }
    
    console.warn(`[CharacterLoader] 未找到头部骨骼: ${characterId}`);
    return null;
  }

  /**
   * 清理角色
   */
  dispose(characterId) {
    const character = this.characters.get(characterId);
    if (character) {
      character.model.traverse((child) => {
        if (child.isMesh) {
          child.geometry?.dispose();
          child.material?.dispose();
        }
      });
      this.characters.delete(characterId);
      this.currentForm.delete(characterId);
      console.log(`[CharacterLoader] 清理角色: ${characterId}`);
    }
  }

  /**
   * 列出所有已加载角色
   */
  listCharacters() {
    return Array.from(this.characters.keys()).map(id => ({
      id,
      form: this.currentForm.get(id),
      forms: Object.keys(this.characters.get(id)?.forms || {})
    }));
  }
}

// 导出单例
window.CharacterLoader = new CharacterLoader();
