/**
 * TransformControls - 轻量版 (兼容旧版全局THREE)
 * 支持 translate / rotate 模式，挂载到 THREE.Object3D
 * 依赖：THREE.Raycaster, THREE.Plane, THREE.Vector3, THREE.EventDispatcher
 */
(function () {
  if (!window.THREE) return;

  const _raycaster = new THREE.Raycaster();
  const _mouse     = new THREE.Vector2();
  const _offset    = new THREE.Vector3();
  const _planeNormal = new THREE.Vector3();
  const _plane     = new THREE.Plane();
  const _worldPos  = new THREE.Vector3();
  const _startPos  = new THREE.Vector3();

  function TransformControls(camera, domElement) {
    THREE.EventDispatcher.call(this);

    this.camera      = camera;
    this.domElement  = domElement;
    this.object      = null;
    this.mode        = 'translate'; // 'translate' | 'rotate'
    this.space       = 'world';
    this.enabled     = true;
    this.axis        = null;

    // 显示用辅助体
    this._gizmo = null;
    this._dragging = false;
    this._changed  = false;

    const self = this;

    // ── 辅助体 ──────────────────────────────────────────────
    this._buildGizmo = function () {
      if (self._gizmo && self._gizmo.parent) {
        self._gizmo.parent.remove(self._gizmo);
      }
      const group = new THREE.Group();
      group.name = '__TransformGizmo__';

      const axisColors = { x: 0xff4444, y: 0x44ff44, z: 0x4488ff };
      const dirs = {
        x: new THREE.Vector3(1, 0, 0),
        y: new THREE.Vector3(0, 1, 0),
        z: new THREE.Vector3(0, 0, 1),
      };
      Object.entries(dirs).forEach(([ax, dir]) => {
        const geo  = new THREE.CylinderGeometry(0.025, 0.025, 1.2, 8);
        const mat  = new THREE.MeshBasicMaterial({ color: axisColors[ax], depthTest: false, transparent: true, opacity: 0.85 });
        const mesh = new THREE.Mesh(geo, mat);
        mesh.userData.axis = ax;

        // 旋转让柱体沿对应轴
        if (ax === 'x') mesh.rotation.z = -Math.PI / 2;
        if (ax === 'z') mesh.rotation.x =  Math.PI / 2;
        mesh.position.copy(dir.clone().multiplyScalar(0.6));
        group.add(mesh);

        // 箭头头
        const coneGeo  = new THREE.ConeGeometry(0.07, 0.22, 8);
        const coneMesh = new THREE.Mesh(coneGeo, mat.clone());
        coneMesh.userData.axis = ax;
        if (ax === 'x') { coneMesh.rotation.z = -Math.PI / 2; coneMesh.position.set(1.28, 0, 0); }
        else if (ax === 'y') { coneMesh.position.set(0, 1.28, 0); }
        else { coneMesh.rotation.x = Math.PI / 2; coneMesh.position.set(0, 0, 1.28); }
        group.add(coneMesh);
      });

      self._gizmo = group;
      return group;
    };

    // ── 绑定到物体 ───────────────────────────────────────────
    this.attach = function (object) {
      self.object = object;
      const g = self._buildGizmo();
      if (object.parent) object.parent.add(g);
      else if (window.mainScene) window.mainScene.add(g);
      self._syncGizmo();
      return self;
    };

    this.detach = function () {
      if (self._gizmo && self._gizmo.parent) self._gizmo.parent.remove(self._gizmo);
      self.object = null;
      return self;
    };

    this._syncGizmo = function () {
      if (!self._gizmo || !self.object) return;
      self.object.getWorldPosition(_worldPos);
      self._gizmo.position.copy(_worldPos);
      // 按相机距离缩放保持屏幕大小一致
      const dist = self.camera.position.distanceTo(_worldPos);
      self._gizmo.scale.setScalar(dist * 0.12);
    };

    // ── 鼠标事件 ─────────────────────────────────────────────
    function toNDC(event) {
      const rect = domElement.getBoundingClientRect();
      _mouse.x = ((event.clientX - rect.left) / rect.width)  * 2 - 1;
      _mouse.y = -((event.clientY - rect.top)  / rect.height) * 2 + 1;
    }

    function getIntersectedAxis(event) {
      if (!self._gizmo) return null;
      toNDC(event);
      _raycaster.setFromCamera(_mouse, self.camera);
      const hits = _raycaster.intersectObjects(self._gizmo.children, false);
      return hits.length ? hits[0].object.userData.axis : null;
    }

    this._onPointerDown = function (event) {
      if (!self.enabled || !self.object || event.button !== 0) return;
      const ax = getIntersectedAxis(event);
      if (!ax) return;

      self.axis = ax;
      self._dragging = true;
      self._changed  = false;

      // 拖拽平面：法线朝向相机
      self.object.getWorldPosition(_worldPos);
      _planeNormal.copy(self.camera.position).sub(_worldPos).normalize();
      _plane.setFromNormalAndCoplanarPoint(_planeNormal, _worldPos);

      toNDC(event);
      _raycaster.setFromCamera(_mouse, self.camera);
      const hit = new THREE.Vector3();
      _raycaster.ray.intersectPlane(_plane, hit);
      _offset.copy(hit).sub(_worldPos);
      _startPos.copy(self.object.position);

      // 阻止 OrbitControls
      event.stopPropagation();
      domElement.setPointerCapture?.(event.pointerId);
      self.dispatchEvent({ type: 'mouseDown' });
    };

    this._onPointerMove = function (event) {
      if (!self._dragging || !self.object) return;
      toNDC(event);
      _raycaster.setFromCamera(_mouse, self.camera);
      const hit = new THREE.Vector3();
      if (!_raycaster.ray.intersectPlane(_plane, hit)) return;
      const newPos = hit.clone().sub(_offset);

      // 约束到轴
      const ax = self.axis;
      if (ax === 'x') { self.object.position.x = newPos.x; }
      else if (ax === 'y') { self.object.position.y = newPos.y; }
      else if (ax === 'z') { self.object.position.z = newPos.z; }

      self._changed = true;
      self._syncGizmo();
      self.dispatchEvent({ type: 'change' });
      self.dispatchEvent({ type: 'objectChange' });
      event.stopPropagation();
    };

    this._onPointerUp = function (event) {
      if (!self._dragging) return;
      self._dragging = false;
      domElement.releasePointerCapture?.(event.pointerId);
      if (self._changed) {
        self.dispatchEvent({ type: 'mouseUp', object: self.object });
      }
    };

    domElement.addEventListener('pointerdown', this._onPointerDown, false);
    domElement.addEventListener('pointermove', this._onPointerMove, false);
    window.addEventListener('pointerup',   this._onPointerUp,   false);

    this.dispose = function () {
      self.detach();
      domElement.removeEventListener('pointerdown', self._onPointerDown);
      domElement.removeEventListener('pointermove', self._onPointerMove);
      window.removeEventListener('pointerup', self._onPointerUp);
    };
  }

  TransformControls.prototype = Object.create(THREE.EventDispatcher.prototype);
  TransformControls.prototype.constructor = TransformControls;

  THREE.TransformControls = TransformControls;
})();
