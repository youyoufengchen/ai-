/**
 * 3D 虚拟演播室 - Three.js 实现
 * 
 * 功能：
 * - 3D 场景渲染（可旋转、缩放）
 * - NPC 视频作为纹理贴图（无需绿幕抠像）
 * - 动态场景切换
 * - 虚拟大屏展示商品
 */

class VirtualStudio3D {
  constructor(containerId) {
    this.container = document.getElementById(containerId);
    this.scene = null;
    this.camera = null;
    this.renderer = null;
    this.npcMesh = null;
    this.videoTexture = null;
    this.screenMesh = null;
    
    // 场景配置
    this.scenes = {
      tea_shop: {
        name: '古风茶室',
        background: 0xf5e6d3,
        fog: 0xf5e6d3,
        cameraPos: { x: 0, y: 1.6, z: 4 },
        npcPos: { x: 0, y: 0, z: 0 },
        screenPos: { x: -2, y: 1.5, z: -1 },
        ambientLight: 0.6,
        directionalLight: 0.8,
        useGLTF: false
      },
      news_studio: {
        name: '新闻演播室',
        background: 0x1a1a2e,
        fog: 0x1a1a2e,
        cameraPos: { x: 0, y: 1.6, z: 5 },
        npcPos: { x: 0, y: 0, z: 0 },
        screenPos: { x: -2.5, y: 1.2, z: -2 },
        ambientLight: 0.4,
        directionalLight: 0.9,
        useGLTF: false
      },
      modern_office: {
        name: '现代直播间',
        background: 0x2d3748,
        fog: 0x2d3748,
        cameraPos: { x: 0, y: 1.6, z: 4.5 },
        npcPos: { x: 0, y: 0, z: 0 },
        screenPos: { x: 2, y: 1.3, z: -1.5 },
        ambientLight: 0.5,
        directionalLight: 0.85,
        useGLTF: false
      },
      meeting_room_interior: {
        name: '会议室',
        background: 0x2c3e50,
        fog: 0x2c3e50,
        cameraPos: { x: 0, y: 1.6, z: 3 },
        npcPos: { x: 0, y: 0, z: 0 },
        screenPos: { x: -1.5, y: 1.2, z: -1 },
        ambientLight: 0.5,
        directionalLight: 0.8,
        useGLTF: true,
        gltfPath: '/assets/scenes/meeting_room_interior/scene.gltf'
      },
      virtual_studio: {
        name: '虚拟演播室',
        background: 0x1a1a2e,
        fog: 0x1a1a2e,
        cameraPos: { x: 0, y: 1.6, z: 4 },
        npcPos: { x: 0, y: 0, z: 0 },
        screenPos: { x: 2, y: 1.3, z: -1.5 },
        ambientLight: 0.6,
        directionalLight: 0.9,
        useGLTF: true,
        gltfPath: '/assets/scenes/virtual_studio/scene.gltf'
      }
    };
    
    this.currentScene = 'tea_shop';
    this.isAutoRotate = false;
    
    this.init();
  }
  
  init() {
    // 1. 创建场景
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(this.scenes.tea_shop.background);
    this.scene.fog = new THREE.Fog(this.scenes.tea_shop.fog, 5, 20);
    
    // 2. 创建相机
    this.camera = new THREE.PerspectiveCamera(
      60,
      this.container.clientWidth / this.container.clientHeight,
      0.1,
      100
    );
    this.camera.position.set(0, 1.6, 4);
    this.camera.lookAt(0, 1, 0);
    
    // 3. 创建渲染器
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setSize(this.container.clientWidth, this.container.clientHeight);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.container.appendChild(this.renderer.domElement);
    
    // 4. 添加灯光
    this.setupLights();
    
    // 5. 创建环境
    this.createEnvironment();
    
    // 6. 创建NPC占位（等待视频加载）
    this.createNPCPlaceholder();
    
    // 7. 创建虚拟大屏
    this.createVirtualScreen();
    
    // 8. 添加控制
    this.setupControls();
    
    // 9. 启动渲染循环
    this.animate();
    
    // 10. 响应窗口变化
    window.addEventListener('resize', () => this.onResize());
  }
  
  setupLights() {
    const config = this.scenes[this.currentScene];
    
    // 环境光
    this.ambientLight = new THREE.AmbientLight(0xffffff, config.ambientLight);
    this.scene.add(this.ambientLight);
    
    // 主光源（模拟演播室灯光）
    this.mainLight = new THREE.DirectionalLight(0xffffff, config.directionalLight);
    this.mainLight.position.set(3, 5, 4);
    this.mainLight.castShadow = true;
    this.mainLight.shadow.mapSize.width = 2048;
    this.mainLight.shadow.mapSize.height = 2048;
    this.scene.add(this.mainLight);
    
    // 补光（让NPC面部更亮）
    this.fillLight = new THREE.PointLight(0xffeebb, 0.4);
    this.fillLight.position.set(-2, 2, 3);
    this.scene.add(this.fillLight);
    
    // 轮廓光（让NPC从背景分离）
    this.rimLight = new THREE.SpotLight(0x88ccff, 0.6);
    this.rimLight.position.set(0, 3, -2);
    this.rimLight.lookAt(0, 1, 0);
    this.scene.add(this.rimLight);
  }
  
  createEnvironment() {
    const config = this.scenes[this.currentScene];
    
    // 如果是GLTF场景，加载3D模型
    if (config.useGLTF) {
      this.loadGLTFScene(config.gltfPath);
      return;
    }
    
    // 地板
    const floorGeometry = new THREE.PlaneGeometry(20, 20);
    const floorMaterial = new THREE.MeshStandardMaterial({
      color: 0x8b7355,
      roughness: 0.8,
      metalness: 0.1
    });
    const floor = new THREE.Mesh(floorGeometry, floorMaterial);
    floor.rotation.x = -Math.PI / 2;
    floor.receiveShadow = true;
    this.scene.add(floor);
    
    // 创建不同风格的演播室装饰
    if (this.currentScene === 'tea_shop') {
      this.createTeaShopDecor();
    } else if (this.currentScene === 'news_studio') {
      this.createNewsStudioDecor();
    } else {
      this.createModernDecor();
    }
  }
  
  createTeaShopDecor() {
    // 茶桌
    const tableGeometry = new THREE.CylinderGeometry(0.8, 0.9, 0.1, 32);
    const tableMaterial = new THREE.MeshStandardMaterial({ color: 0x5c3a21 });
    const table = new THREE.Mesh(tableGeometry, tableMaterial);
    table.position.set(0, 0.05, 1.2);
    table.castShadow = true;
    table.receiveShadow = true;
    this.scene.add(table);
    
    // 茶桌腿
    const legGeometry = new THREE.CylinderGeometry(0.08, 0.08, 0.8);
    const legMaterial = new THREE.MeshStandardMaterial({ color: 0x4a2f1b });
    const positions = [[0.5, 0.7], [-0.5, 0.7], [0.5, 1.7], [-0.5, 1.7]];
    positions.forEach(pos => {
      const leg = new THREE.Mesh(legGeometry, legMaterial);
      leg.position.set(pos[0], 0.4, pos[1]);
      leg.castShadow = true;
      this.scene.add(leg);
    });
    
    // 背景墙装饰
    const screenGeometry = new THREE.BoxGeometry(3, 2, 0.1);
    const screenMaterial = new THREE.MeshStandardMaterial({ color: 0x2d3748 });
    const screen = new THREE.Mesh(screenGeometry, screenMaterial);
    screen.position.set(0, 2, -3);
    screen.castShadow = true;
    this.scene.add(screen);
    
    // 装饰屏风（简化版）
    const panelGeometry = new THREE.BoxGeometry(0.1, 2.5, 0.8);
    const panelMaterial = new THREE.MeshStandardMaterial({ color: 0x8b4513 });
    for (let i = -2; i <= 2; i++) {
      const panel = new THREE.Mesh(panelGeometry, panelMaterial);
      panel.position.set(i * 0.9, 1.25, -2.5);
      panel.rotation.y = i * 0.1;
      panel.castShadow = true;
      this.scene.add(panel);
    }
  }
  
  createNewsStudioDecor() {
    // 主播台
    const deskGeometry = new THREE.BoxGeometry(2.5, 0.1, 1);
    const deskMaterial = new THREE.MeshStandardMaterial({ 
      color: 0x1e3a8a,
      metalness: 0.3,
      roughness: 0.4
    });
    const desk = new THREE.Mesh(deskGeometry, deskMaterial);
    desk.position.set(0, 0.9, 0.8);
    desk.castShadow = true;
    this.scene.add(desk);
    
    // 主播台支柱
    const pillarGeometry = new THREE.CylinderGeometry(0.15, 0.15, 0.9);
    const pillar = new THREE.Mesh(pillarGeometry, deskMaterial);
    pillar.position.set(0, 0.45, 0.8);
    pillar.castShadow = true;
    this.scene.add(pillar);
    
    // 环形灯带效果（简化）
    const ringGeometry = new THREE.TorusGeometry(3, 0.05, 16, 100);
    const ringMaterial = new THREE.MeshBasicMaterial({ color: 0x00ffff });
    const ring = new THREE.Mesh(ringGeometry, ringMaterial);
    ring.position.set(0, 3.5, -1);
    ring.rotation.x = Math.PI / 2;
    this.scene.add(ring);
    
    // 背景LED墙
    const ledGeometry = new THREE.PlaneGeometry(8, 4);
    const ledMaterial = new THREE.MeshBasicMaterial({ color: 0x0f172a });
    const led = new THREE.Mesh(ledGeometry, ledMaterial);
    led.position.set(0, 2, -4);
    this.scene.add(led);
  }
  
  createModernDecor() {
    // 简约装饰
    const shelfGeometry = new THREE.BoxGeometry(4, 0.1, 0.5);
    const shelfMaterial = new THREE.MeshStandardMaterial({ color: 0xffffff });
    const shelf = new THREE.Mesh(shelfGeometry, shelfMaterial);
    shelf.position.set(0, 1.5, -2);
    shelf.castShadow = true;
    this.scene.add(shelf);
    
    // 装饰方块
    const boxGeometry = new THREE.BoxGeometry(0.3, 0.3, 0.3);
    const colors = [0xff6b6b, 0x4ecdc4, 0xffd93d, 0x95e1d3];
    for (let i = 0; i < 4; i++) {
      const box = new THREE.Mesh(
        boxGeometry,
        new THREE.MeshStandardMaterial({ color: colors[i] })
      );
      box.position.set(-1.5 + i * 1, 1.8 + Math.random() * 0.3, -2);
      box.rotation.y = Math.random() * Math.PI;
      box.castShadow = true;
      this.scene.add(box);
    }
  }
  
  loadGLTFScene(gltfPath) {
    if (!this.gltfLoader) {
      this.gltfLoader = new GLTFLoader();
    }
    
    this.gltfLoader.load(
      gltfPath,
      (gltf) => {
        // 清除之前的GLTF模型
        if (this.currentGLTFScene) {
          this.scene.remove(this.currentGLTFScene);
        }
        
        // 添加新模型
        this.currentGLTFScene = gltf.scene;
        this.scene.add(gltf.scene);
        
        // 启用阴影
        gltf.scene.traverse((child) => {
          if (child.isMesh) {
            child.castShadow = true;
            child.receiveShadow = true;
          }
        });
        
        // 调整模型大小和位置（根据需要调整）
        const box = new THREE.Box3().setFromObject(gltf.scene);
        const center = box.getCenter(new THREE.Vector3());
        const size = box.getSize(new THREE.Vector3());
        
        // 居中模型
        gltf.scene.position.x = -center.x;
        gltf.scene.position.y = -center.y;
        gltf.scene.position.z = -center.z;
        
        // 缩放模型以适应场景
        const maxDim = Math.max(size.x, size.y, size.z);
        const scale = 2 / maxDim; // 调整这个值来控制模型大小
        gltf.scene.scale.multiplyScalar(scale);
        
        console.log(`Loaded GLTF scene: ${gltfPath}`);
      },
      (progress) => {
        console.log('Loading progress:', (progress.loaded / progress.total * 100) + '%');
      },
      (error) => {
        console.error('Error loading GLTF scene:', error);
        // 如果GLTF加载失败，回退到基础场景
        this.createFallbackScene();
      }
    );
  }
  
  createFallbackScene() {
    // 创建一个简单的 fallback 场景
    const floorGeometry = new THREE.PlaneGeometry(20, 20);
    const floorMaterial = new THREE.MeshStandardMaterial({
      color: 0x888888,
      roughness: 0.8,
      metalness: 0.1
    });
    const floor = new THREE.Mesh(floorGeometry, floorMaterial);
    floor.rotation.x = -Math.PI / 2;
    floor.receiveShadow = true;
    this.scene.add(floor);
    
    console.log('Created fallback scene due to GLTF loading failure');
  }
  
  createNPCPlaceholder() {
    // 创建NPC显示平面（等待视频纹理）
    const geometry = new THREE.PlaneGeometry(1, 1.6);
    const material = new THREE.MeshBasicMaterial({ 
      color: 0x333333,
      transparent: true,
      opacity: 0.9
    });
    this.npcMesh = new THREE.Mesh(geometry, material);
    this.npcMesh.position.set(0, 0.8, 0);
    this.npcMesh.castShadow = true;
    this.scene.add(this.npcMesh);
    
    // NPC底座（阴影接收器）
    const baseGeometry = new THREE.CircleGeometry(0.6, 32);
    const baseMaterial = new THREE.MeshBasicMaterial({ 
      color: 0x000000,
      transparent: true,
      opacity: 0.3
    });
    const base = new THREE.Mesh(baseGeometry, baseMaterial);
    base.rotation.x = -Math.PI / 2;
    base.position.set(0, 0.01, 0);
    this.scene.add(base);
  }
  
  createVirtualScreen() {
    // 虚拟大屏（展示商品视频/图片）
    const geometry = new THREE.PlaneGeometry(1.6, 0.9);
    const material = new THREE.MeshBasicMaterial({ color: 0x111111 });
    this.screenMesh = new THREE.Mesh(geometry, material);
    
    const config = this.scenes[this.currentScene];
    this.screenMesh.position.set(
      config.screenPos.x,
      config.screenPos.y,
      config.screenPos.z
    );
    this.screenMesh.lookAt(0, 1.6, 4);
    this.scene.add(this.screenMesh);
    
    // 屏幕边框
    const frameGeometry = new THREE.BoxGeometry(1.7, 1, 0.05);
    const frameMaterial = new THREE.MeshStandardMaterial({ 
      color: 0x222222,
      metalness: 0.8,
      roughness: 0.2
    });
    const frame = new THREE.Mesh(frameGeometry, frameMaterial);
    frame.position.copy(this.screenMesh.position);
    frame.position.z -= 0.03;
    frame.lookAt(0, 1.6, 4);
    this.scene.add(frame);
    
    // 屏幕发光效果
    const light = new THREE.PointLight(0x88ccff, 0.3, 3);
    light.position.copy(this.screenMesh.position);
    light.position.z += 0.5;
    this.scene.add(light);
  }
  
  setupControls() {
    // 鼠标控制
    let isDragging = false;
    let previousMousePosition = { x: 0, y: 0 };
    let cameraAngle = 0;
    let cameraHeight = 1.6;
    
    this.container.addEventListener('mousedown', (e) => {
      isDragging = true;
      previousMousePosition = { x: e.clientX, y: e.clientY };
    });
    
    document.addEventListener('mousemove', (e) => {
      if (!isDragging) return;
      
      const deltaX = e.clientX - previousMousePosition.x;
      const deltaY = e.clientY - previousMousePosition.y;
      
      cameraAngle -= deltaX * 0.005;
      cameraHeight = Math.max(0.5, Math.min(3, cameraHeight - deltaY * 0.01));
      
      const radius = 4;
      this.camera.position.x = Math.sin(cameraAngle) * radius;
      this.camera.position.z = Math.cos(cameraAngle) * radius;
      this.camera.position.y = cameraHeight;
      this.camera.lookAt(0, 1, 0);
      
      previousMousePosition = { x: e.clientX, y: e.clientY };
    });
    
    document.addEventListener('mouseup', () => {
      isDragging = false;
    });
    
    // 滚轮缩放
    this.container.addEventListener('wheel', (e) => {
      e.preventDefault();
      const fov = this.camera.fov + e.deltaY * 0.05;
      this.camera.fov = Math.max(30, Math.min(90, fov));
      this.camera.updateProjectionMatrix();
    });
  }
  
  // 设置NPC视频（对接你现有的视频系统）
  setNPCVideo(videoUrl) {
    const video = document.createElement('video');
    video.src = videoUrl;
    video.crossOrigin = 'anonymous';
    video.loop = true;
    video.muted = true;
    video.playsInline = true;
    
    video.addEventListener('canplay', () => {
      video.play().catch(() => {});
      
      // 创建视频纹理
      if (this.videoTexture) {
        this.videoTexture.dispose();
      }
      
      this.videoTexture = new THREE.VideoTexture(video);
      this.videoTexture.minFilter = THREE.LinearFilter;
      this.videoTexture.magFilter = THREE.LinearFilter;
      
      // 更新NPC材质
      this.npcMesh.material = new THREE.MeshBasicMaterial({
        map: this.videoTexture,
        transparent: true,
        side: THREE.DoubleSide
      });
      
      // 根据视频比例调整NPC大小
      const videoAspect = video.videoWidth / video.videoHeight;
      if (videoAspect > 0) {
        const height = 1.6;
        const width = height * videoAspect;
        this.npcMesh.geometry.dispose();
        this.npcMesh.geometry = new THREE.PlaneGeometry(width, height);
      }
    });
    
    video.load();
    this.npcVideo = video;
  }
  
  // 切换NPC视频（动作切换）
  switchNPCVideo(videoUrl) {
    if (this.npcVideo) {
      this.npcVideo.src = videoUrl;
      this.npcVideo.load();
      this.npcVideo.play().catch(() => {});
    } else {
      this.setNPCVideo(videoUrl);
    }
  }
  
  // 在虚拟大屏上显示内容
  setScreenContent(type, url) {
    if (type === 'video') {
      const video = document.createElement('video');
      video.src = url;
      video.crossOrigin = 'anonymous';
      video.loop = true;
      video.muted = true;
      
      video.addEventListener('canplay', () => {
        video.play().catch(() => {});
        const texture = new THREE.VideoTexture(video);
        this.screenMesh.material = new THREE.MeshBasicMaterial({
          map: texture
        });
      });
      
      video.load();
    } else if (type === 'image') {
      const loader = new THREE.TextureLoader();
      loader.load(url, (texture) => {
        this.screenMesh.material = new THREE.MeshBasicMaterial({
          map: texture
        });
      });
    }
  }
  
  // 切换场景
  switchScene(sceneId) {
    if (!this.scenes[sceneId]) {
      console.warn('Unknown scene:', sceneId);
      return;
    }
    
    this.currentScene = sceneId;
    const config = this.scenes[sceneId];
    
    // 更新背景
    this.scene.background = new THREE.Color(config.background);
    this.scene.fog = new THREE.Fog(config.fog, 5, 20);
    
    // 更新灯光
    this.ambientLight.intensity = config.ambientLight;
    this.mainLight.intensity = config.directionalLight;
    
    // 更新相机位置
    this.camera.position.set(
      config.cameraPos.x,
      config.cameraPos.y,
      config.cameraPos.z
    );
    this.camera.lookAt(0, 1, 0);
    
    // 更新NPC位置
    this.npcMesh.position.set(
      config.npcPos.x,
      config.npcPos.y + 0.8,
      config.npcPos.z
    );
    
    // 更新屏幕位置
    this.screenMesh.position.set(
      config.screenPos.x,
      config.screenPos.y,
      config.screenPos.z
    );
    this.screenMesh.lookAt(0, 1.6, 4);
    
    // 重新创建环境装饰
    this.clearEnvironment();
    this.createEnvironment();
    
    console.log('Switched to scene:', config.name);
  }
  
  clearEnvironment() {
    // 移除所有非核心对象（保留灯光、NPC、屏幕）
    const toRemove = [];
    this.scene.traverse((child) => {
      if (child !== this.npcMesh && 
          child !== this.screenMesh &&
          child !== this.ambientLight &&
          child !== this.mainLight &&
          child !== this.fillLight &&
          child !== this.rimLight) {
        toRemove.push(child);
      }
    });
    toRemove.forEach(obj => this.scene.remove(obj));
    
    // 清除GLTF场景引用
    this.currentGLTFScene = null;
  }
  
  // 启用/禁用自动旋转
  toggleAutoRotate(enabled) {
    this.isAutoRotate = enabled;
  }
  
  animate() {
    requestAnimationFrame(() => this.animate());
    
    // 更新视频纹理
    if (this.videoTexture) {
      this.videoTexture.needsUpdate = true;
    }
    
    // 自动旋转相机
    if (this.isAutoRotate) {
      const time = Date.now() * 0.0002;
      const radius = 4;
      this.camera.position.x = Math.sin(time) * radius;
      this.camera.position.z = Math.cos(time) * radius;
      this.camera.lookAt(0, 1, 0);
    }
    
    this.renderer.render(this.scene, this.camera);
  }
  
  onResize() {
    const width = this.container.clientWidth;
    const height = this.container.clientHeight;
    
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height);
  }
  
  destroy() {
    if (this.npcVideo) {
      this.npcVideo.pause();
      this.npcVideo = null;
    }
    if (this.videoTexture) {
      this.videoTexture.dispose();
    }
    this.renderer.dispose();
    this.container.removeChild(this.renderer.domElement);
  }
}

// 导出供其他模块使用
window.VirtualStudio3D = VirtualStudio3D;
