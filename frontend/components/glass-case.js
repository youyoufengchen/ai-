/**
 * 玻璃展柜组件 (GlassCase / Shelf)
 *
 * 用法：
 *   const shelf = new GlassCase(THREE, shelfConfig);
 *   scene.add(shelf.root);
 *   // 渲染循环里：
 *   shelf.update(deltaSeconds);
 *
 * shelfConfig 见 docs/shelf-system-design.md
 *
 * 依赖：全局 THREE（已含 GLTFLoader）。组件运行时构造一个 Group：
 *   root (Group)
 *   ├── base (底座 Mesh)
 *   ├── caseMesh (玻璃罩 Mesh)
 *   ├── productPivot (Object3D, 内部自转)
 *   │   └── productMesh (商品)
 *   └── label (Sprite, 显示编号)
 */
(function (global) {
  'use strict';

  const DEG2RAD = Math.PI / 180;

  class GlassCase {
    constructor(THREE, config) {
      this.THREE = THREE;
      this.config = Object.assign({}, GlassCase.defaultConfig(), config || {});
      this._attached = false;
      this._opacity = 1;
      this._fadeTarget = 1;
      this._fadeSpeed = 0;
      this._defaultParent = null;
      this._defaultLocalPos = null;
      this._defaultLocalQuat = null;

      this.root = new THREE.Group();
      this.root.name = `Shelf:${this.config.id}`;
      this.root.userData.shelfId = this.config.id;

      this._buildBase();
      this._buildGlassCase();
      this._buildProductPivot();
      this._buildLabel();

      this._applyTransform();
      if (this.config.product) {
        this.setProduct(this.config.product);
      }
    }

    static defaultConfig() {
      return {
        id: 'shelf_default',
        label: '货架',
        position: [0, 0, 0],
        rotation_y: 0,
        case_size: { width: 0.8, height: 1.2, depth: 0.8 },
        spin: { enabled: true, speed_deg_per_sec: 30, axis: [0, 1, 0] },
        product: null,
        npc_stop_point: null,
      };
    }

    _buildBase() {
      const THREE = this.THREE;
      const { width, depth } = this.config.case_size;
      const baseGeo = new THREE.CylinderGeometry(
        Math.max(width, depth) * 0.55, // top radius
        Math.max(width, depth) * 0.6,  // bottom radius (略宽一点更稳)
        0.1,                            // height
        24
      );
      const baseMat = new THREE.MeshStandardMaterial({
        color: 0x8a7a5a,
        roughness: 0.35,
        metalness: 0.7,
      });
      this.base = new THREE.Mesh(baseGeo, baseMat);
      this.base.position.y = 0.05;
      this.base.castShadow = true;
      this.base.receiveShadow = true;
      this.root.add(this.base);
    }

    _buildGlassCase() {
      const THREE = this.THREE;
      const { width, height, depth } = this.config.case_size;
      // 玻璃罩：略小于 base 的圆柱形罩（更通用），用半透明物理材质
      const caseGeo = new THREE.CylinderGeometry(
        Math.max(width, depth) * 0.5,
        Math.max(width, depth) * 0.5,
        height,
        32,
        1,
        true // openEnded
      );
      // 物理材质可能不支持，降级到普通材质
      let caseMat;
      if (THREE.MeshPhysicalMaterial) {
        caseMat = new THREE.MeshPhysicalMaterial({
          color: 0xffffff,
          metalness: 0,
          roughness: 0.05,
          transmission: 0.92,    // 玻璃感
          transparent: true,
          opacity: 0.25,
          ior: 1.5,
          thickness: 0.05,
          side: THREE.DoubleSide,
        });
      } else {
        caseMat = new THREE.MeshStandardMaterial({
          color: 0xaaccee,
          metalness: 0.1,
          roughness: 0.1,
          transparent: true,
          opacity: 0.25,
          side: THREE.DoubleSide,
        });
      }
      this.caseMesh = new THREE.Mesh(caseGeo, caseMat);
      this.caseMesh.position.y = 0.1 + height / 2; // base 上方
      this.root.add(this.caseMesh);

      // 顶盖
      const capGeo = new THREE.CylinderGeometry(
        Math.max(width, depth) * 0.5,
        Math.max(width, depth) * 0.5,
        0.03,
        32
      );
      const capMat = new THREE.MeshStandardMaterial({
        color: 0x8a7a5a, roughness: 0.4, metalness: 0.7,
      });
      this.cap = new THREE.Mesh(capGeo, capMat);
      this.cap.position.y = 0.1 + height + 0.015;
      this.root.add(this.cap);
    }

    _buildProductPivot() {
      const THREE = this.THREE;
      this.productPivot = new THREE.Object3D();
      this.productPivot.position.y = 0.1 + this.config.case_size.height / 2;
      this.root.add(this.productPivot);
      this.productMesh = null;
    }

    _buildLabel() {
      const THREE = this.THREE;
      // 用 Canvas 贴图做 Sprite 标签，避免依赖 CSS2DRenderer
      const canvas = document.createElement('canvas');
      canvas.width = 256; canvas.height = 64;
      const ctx = canvas.getContext('2d');
      ctx.fillStyle = 'rgba(0,0,0,0.65)';
      this._roundRect(ctx, 0, 0, 256, 64, 12); ctx.fill();
      ctx.fillStyle = '#ffd56a';
      ctx.font = 'bold 36px sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(this.config.label || this.config.id, 128, 34);
      const tex = new THREE.CanvasTexture(canvas);
      tex.needsUpdate = true;
      const mat = new THREE.SpriteMaterial({ map: tex, transparent: true });
      this.label = new THREE.Sprite(mat);
      this.label.scale.set(0.6, 0.15, 1);
      this.label.position.y = 0.1 + this.config.case_size.height + 0.18;
      this.root.add(this.label);
    }

    _roundRect(ctx, x, y, w, h, r) {
      ctx.beginPath();
      ctx.moveTo(x + r, y);
      ctx.arcTo(x + w, y, x + w, y + h, r);
      ctx.arcTo(x + w, y + h, x, y + h, r);
      ctx.arcTo(x, y + h, x, y, r);
      ctx.arcTo(x, y, x + w, y, r);
      ctx.closePath();
    }

    _applyTransform() {
      const [x, y, z] = this.config.position || [0, 0, 0];
      this.root.position.set(x, y, z);
      this.root.rotation.y = (this.config.rotation_y || 0) * DEG2RAD;
    }

    /** 设置/切换展示的商品 */
    setProduct(productConfig) {
      const THREE = this.THREE;
      this.config.product = productConfig;
      // 清除旧的
      if (this.productMesh) {
        this.productPivot.remove(this.productMesh);
        this.productMesh.traverse?.((o) => {
          if (o.geometry) o.geometry.dispose();
          if (o.material) {
            const mats = Array.isArray(o.material) ? o.material : [o.material];
            mats.forEach((m) => m.dispose());
          }
        });
        this.productMesh = null;
      }
      if (!productConfig) return;

      const dispType = productConfig.display_type || '3d_model';
      const scale = productConfig.scale || 1;
      const offsetY = productConfig.offset_y || 0;

      if (dispType === '3d_model' && productConfig.asset_path) {
        if (!THREE.GLTFLoader) {
          console.warn('[GlassCase] THREE.GLTFLoader 未加载，无法显示3D商品');
          this._fallbackProductBox();
          return;
        }
        const loader = new THREE.GLTFLoader();
        loader.load(productConfig.asset_path, (gltf) => {
          const m = gltf.scene;
          m.scale.setScalar(scale);
          m.position.y = offsetY;
          this.productMesh = m;
          this.productPivot.add(m);
        }, undefined, (err) => {
          console.warn('[GlassCase] 商品3D模型加载失败:', err?.message);
          this._fallbackProductBox();
        });
      } else if (dispType === 'image_2d' && productConfig.asset_path) {
        const tex = new THREE.TextureLoader().load(productConfig.asset_path);
        const ar = 1;
        const w = 0.45 * scale, h = 0.45 * scale / ar;
        const geo = new THREE.PlaneGeometry(w, h);
        const mat = new THREE.MeshBasicMaterial({ map: tex, transparent: true, side: THREE.DoubleSide });
        this.productMesh = new THREE.Mesh(geo, mat);
        this.productMesh.position.y = offsetY;
        this.productPivot.add(this.productMesh);
      } else {
        this._fallbackProductBox();
      }
    }

    _fallbackProductBox() {
      const THREE = this.THREE;
      const geo = new THREE.BoxGeometry(0.3, 0.3, 0.3);
      const mat = new THREE.MeshStandardMaterial({ color: 0xff9966 });
      this.productMesh = new THREE.Mesh(geo, mat);
      this.productPivot.add(this.productMesh);
    }

    /** 渲染循环调用 */
    update(deltaSec) {
      // 商品自转
      const spin = this.config.spin || {};
      if (spin.enabled && this.productPivot) {
        const speed = (spin.speed_deg_per_sec || 0) * DEG2RAD;
        const axis = spin.axis || [0, 1, 0];
        if (axis[0]) this.productPivot.rotation.x += axis[0] * speed * deltaSec;
        if (axis[1]) this.productPivot.rotation.y += axis[1] * speed * deltaSec;
        if (axis[2]) this.productPivot.rotation.z += axis[2] * speed * deltaSec;
      }
      // 渐隐渐显
      if (this._fadeSpeed !== 0) {
        const next = this._opacity + this._fadeSpeed * deltaSec;
        const reached = (this._fadeSpeed > 0 && next >= this._fadeTarget) ||
                        (this._fadeSpeed < 0 && next <= this._fadeTarget);
        this._opacity = reached ? this._fadeTarget : next;
        this._applyOpacity(this._opacity);
        if (reached) {
          this._fadeSpeed = 0;
          if (this._opacity <= 0) this.root.visible = false;
        }
      }
    }

    _applyOpacity(o) {
      this.root.traverse((c) => {
        if (c.material) {
          const mats = Array.isArray(c.material) ? c.material : [c.material];
          mats.forEach((m) => {
            if (m.userData._origOpacity == null) {
              m.userData._origOpacity = m.opacity != null ? m.opacity : 1;
            }
            m.transparent = true;
            m.opacity = (m.userData._origOpacity ?? 1) * o;
          });
        }
      });
    }

    fadeOut(durationMs = 600) {
      this._fadeTarget = 0;
      this._fadeSpeed = -1 / (durationMs / 1000);
      this.root.visible = true;
    }

    fadeIn(durationMs = 400) {
      this.root.visible = true;
      this._fadeTarget = 1;
      this._fadeSpeed = 1 / (durationMs / 1000);
    }

    /** 把货架附着到 NPC 的骨骼上 */
    attachToBone(bone) {
      if (!bone) return;
      // 记录原状态
      if (!this._attached) {
        this._defaultParent = this.root.parent;
        this._defaultLocalPos = this.root.position.clone();
        this._defaultLocalQuat = this.root.quaternion.clone();
      }
      bone.add(this.root);
      this.root.position.set(0, 0, 0);
      this.root.quaternion.identity();
      this._attached = true;
    }

    /** 还原到场景原位置 */
    detach() {
      if (!this._attached) return;
      if (this._defaultParent) {
        this._defaultParent.add(this.root);
        this.root.position.copy(this._defaultLocalPos);
        this.root.quaternion.copy(this._defaultLocalQuat);
      }
      this._attached = false;
    }

    /** 应用新配置（编辑器实时调整用） */
    applyConfig(config) {
      Object.assign(this.config, config);
      this._applyTransform();
      // 可见性
      if (config.visible !== undefined) {
        this.root.visible = !!config.visible;
      }
      // case_size 改变时需要重建几何（简化处理：保留下次实现）
    }

    dispose() {
      this.root.traverse((o) => {
        if (o.geometry) o.geometry.dispose();
        if (o.material) {
          const mats = Array.isArray(o.material) ? o.material : [o.material];
          mats.forEach((m) => m.dispose());
        }
      });
      if (this.root.parent) this.root.parent.remove(this.root);
    }
  }

  global.GlassCase = GlassCase;
})(typeof window !== 'undefined' ? window : globalThis);
