/**
 * WebcamMotionCapture - 浏览器端实时动捕（MediaPipe）
 * 
 * 功能：
 * 1. 调用摄像头，MediaPipe实时提取人体骨骼关键点
 * 2. 关键点 → VRM骨骼旋转计算
 * 3. WebSocket实时传输到直播间，驱动NPC
 * 
 * 依赖：
 * - @mediapipe/camera_utils
 * - @mediapipe/control_utils
 * - @mediapipe/drawing_utils
 * - @mediapipe/pose
 * 
 * CDN方式引入（免npm安装）：
 * https://cdn.jsdelivr.net/npm/@mediapipe/pose/pose.js
 */

class WebcamMotionCapture {
  constructor() {
    // MediaPipe 实例
    this.pose = null;
    this.camera = null;
    
    // 状态
    this.isRunning = false;
    this.isInitialized = false;
    this.videoElement = null;
    this.canvasElement = null;
    
    // 骨骼数据
    this.landmarks = null;        // 当前帧的关键点
    this.skeletonData = null;     // 转换后的骨骼旋转数据
    
    // WebSocket传输
    this.ws = null;
    this.wsUrl = null;
    this.sendInterval = null;
    this.frameRate = 15;          // 发送频率（降低带宽）
    
    // VRM骨骼映射（简化版，MediaPipe 33个点 → VRM骨骼）
    this.boneMapping = {
      // MediaPipe landmark index → VRM bone name
      'hips': [23, 24],           // 左髋 + 右髋 中心
      'spine': [11, 12],          // 左右肩中心 → spine
      'neck': [0],                // 鼻子 → neck
      'head': [0, 1, 4],          // 鼻子 + 眼 + 耳 → head
      'leftShoulder': [11],
      'leftUpperArm': [11, 13],
      'leftLowerArm': [13, 15],
      'leftHand': [15],
      'rightShoulder': [12],
      'rightUpperArm': [12, 14],
      'rightLowerArm': [14, 16],
      'rightHand': [16],
      'leftUpperLeg': [23, 25],
      'leftLowerLeg': [25, 27],
      'leftFoot': [27],
      'rightUpperLeg': [24, 26],
      'rightLowerLeg': [26, 28],
      'rightFoot': [28],
    };
    
    // 回调
    this.onLandmarks = null;       // 关键点回调
    this.onSkeleton = null;        // 骨骼数据回调
    this.onError = null;           // 错误回调
  }

  /**
   * 初始化 MediaPipe（异步加载脚本）
   */
  async init() {
    if (this.isInitialized) return true;
    
    try {
      // 检测 MediaPipe 是否可用（CDN引入）
      if (typeof window.Pose === 'undefined') {
        console.log('[MotionCapture] MediaPipe 未加载，尝试从CDN加载...');
        await this._loadMediaPipeCDN();
      }
      
      // 创建 Pose 实例
      this.pose = new window.Pose({
        locateFile: (file) => {
          return `https://cdn.jsdelivr.net/npm/@mediapipe/pose/${file}`;
        }
      });
      
      this.pose.setOptions({
        modelComplexity: 1,         // 0=轻量, 1=完整, 2=超完整
        smoothLandmarks: true,      // 平滑关键点
        enableSegmentation: false,  // 不需要背景分割
        minDetectionConfidence: 0.5,
        minTrackingConfidence: 0.5
      });
      
      this.pose.onResults(this._onResults.bind(this));
      
      this.isInitialized = true;
      console.log('[MotionCapture] MediaPipe 初始化完成');
      return true;
      
    } catch (e) {
      console.error('[MotionCapture] 初始化失败:', e);
      if (this.onError) this.onError(e);
      return false;
    }
  }
  
  /**
   * 从CDN加载MediaPipe脚本
   */
  _loadMediaPipeCDN() {
    return new Promise((resolve, reject) => {
      const scripts = [
        'https://cdn.jsdelivr.net/npm/@mediapipe/pose/pose.js',
        'https://cdn.jsdelivr.net/npm/@mediapipe/camera_utils/camera_utils.js',
        'https://cdn.jsdelivr.net/npm/@mediapipe/drawing_utils/drawing_utils.js',
      ];
      
      let loaded = 0;
      scripts.forEach(src => {
        const script = document.createElement('script');
        script.src = src;
        script.onload = () => {
          loaded++;
          if (loaded === scripts.length) resolve();
        };
        script.onerror = () => reject(new Error(`加载失败: ${src}`));
        document.head.appendChild(script);
      });
      
      // 5秒超时
      setTimeout(() => reject(new Error('MediaPipe加载超时')), 5000);
    });
  }

  /**
   * 启动摄像头动捕
   * @param {HTMLVideoElement} videoElement - 视频元素（可选，自动创建）
   * @param {HTMLCanvasElement} canvasElement - 画布元素（用于预览，可选）
   */
  async start(videoElement = null, canvasElement = null) {
    if (!this.isInitialized) {
      const ok = await this.init();
      if (!ok) return false;
    }
    
    if (this.isRunning) return true;
    
    try {
      // 创建或复用视频元素
      this.videoElement = videoElement || this._createHiddenVideo();
      this.canvasElement = canvasElement;
      
      // 请求摄像头权限
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { 
          width: { ideal: 640 },
          height: { ideal: 480 },
          frameRate: { ideal: 30 }
        },
        audio: false
      });
      
      this.videoElement.srcObject = stream;
      await this.videoElement.play();
      
      // 启动MediaPipe处理
      this._startProcessing();
      
      this.isRunning = true;
      console.log('[MotionCapture] 动捕已启动');
      return true;
      
    } catch (e) {
      console.error('[MotionCapture] 启动失败:', e);
      if (this.onError) this.onError(e);
      return false;
    }
  }

  /**
   * 停止动捕
   */
  stop() {
    if (!this.isRunning) return;
    
    // 停止发送
    if (this.sendInterval) {
      clearInterval(this.sendInterval);
      this.sendInterval = null;
    }
    
    // 关闭WebSocket
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    
    // 停止摄像头
    if (this.videoElement && this.videoElement.srcObject) {
      this.videoElement.srcObject.getTracks().forEach(t => t.stop());
      this.videoElement.srcObject = null;
    }
    
    this.isRunning = false;
    console.log('[MotionCapture] 动捕已停止');
  }

  /**
   * 连接到WebSocket服务器（传输骨骼数据到直播间）
   * @param {string} wsUrl - WebSocket地址，如 ws://localhost:8766
   */
  connectWebSocket(wsUrl) {
    this.wsUrl = wsUrl;
    
    try {
      this.ws = new WebSocket(wsUrl);
      
      this.ws.onopen = () => {
        console.log('[MotionCapture] WebSocket 已连接:', wsUrl);
        // 开始定时发送骨骼数据
        this._startSending();
      };
      
      this.ws.onclose = () => {
        console.log('[MotionCapture] WebSocket 已断开');
        // 3秒后自动重连
        setTimeout(() => this.connectWebSocket(wsUrl), 3000);
      };
      
      this.ws.onerror = (e) => {
        console.error('[MotionCapture] WebSocket 错误:', e);
      };
      
    } catch (e) {
      console.error('[MotionCapture] WebSocket 连接失败:', e);
    }
  }

  /**
   * MediaPipe 结果回调
   */
  _onResults(results) {
    if (!results.poseLandmarks) return;
    
    this.landmarks = results.poseLandmarks;
    
    // 转换为骨骼旋转数据
    this.skeletonData = this._convertToSkeleton(results.poseLandmarks);
    
    // 绘制预览（如果有canvas）
    if (this.canvasElement) {
      this._drawPreview(results);
    }
    
    // 回调
    if (this.onLandmarks) this.onLandmarks(this.landmarks);
    if (this.onSkeleton) this.onSkeleton(this.skeletonData);
  }

  /**
   * 将MediaPipe关键点转换为VRM骨骼旋转数据
   */
  _convertToSkeleton(landmarks) {
    const skeleton = {};
    
    // 计算hips位置（左右髋部中心）
    const leftHip = landmarks[23];
    const rightHip = landmarks[24];
    skeleton.hips = {
      position: {
        x: (leftHip.x + rightHip.x) / 2,
        y: (leftHip.y + rightHip.y) / 2,
        z: (leftHip.z + rightHip.z) / 2
      },
      rotation: { x: 0, y: 0, z: 0, w: 1 }  // 简化，实际需要计算
    };
    
    // 计算脊柱方向（肩到髋）
    const leftShoulder = landmarks[11];
    const rightShoulder = landmarks[12];
    const shoulderCenter = {
      x: (leftShoulder.x + rightShoulder.x) / 2,
      y: (leftShoulder.y + rightShoulder.y) / 2,
      z: (leftShoulder.z + rightShoulder.z) / 2
    };
    
    const hipCenter = skeleton.hips.position;
    skeleton.spine = this._calculateRotation(hipCenter, shoulderCenter);
    
    // 计算四肢（简化版）
    skeleton.leftUpperArm = this._calculateRotation(landmarks[11], landmarks[13]);
    skeleton.leftLowerArm = this._calculateRotation(landmarks[13], landmarks[15]);
    skeleton.rightUpperArm = this._calculateRotation(landmarks[12], landmarks[14]);
    skeleton.rightLowerArm = this._calculateRotation(landmarks[14], landmarks[16]);
    
    skeleton.leftUpperLeg = this._calculateRotation(landmarks[23], landmarks[25]);
    skeleton.leftLowerLeg = this._calculateRotation(landmarks[25], landmarks[27]);
    skeleton.rightUpperLeg = this._calculateRotation(landmarks[24], landmarks[26]);
    skeleton.rightLowerLeg = this._calculateRotation(landmarks[26], landmarks[28]);
    
    // 时间戳
    skeleton.timestamp = Date.now();
    
    return skeleton;
  }

  /**
   * 计算两点间的旋转（简化欧拉角）
   */
  _calculateRotation(from, to) {
    const dx = to.x - from.x;
    const dy = to.y - from.y;
    const dz = to.z - from.z;
    
    // 简化为四元数（实际需要完整的IK解算）
    return {
      x: dy,  // pitch
      y: dx,  // yaw
      z: 0,
      w: 1
    };
  }

  /**
   * 开始定时发送骨骼数据
   */
  _startSending() {
    if (this.sendInterval) return;
    
    const intervalMs = 1000 / this.frameRate;
    
    this.sendInterval = setInterval(() => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN && this.skeletonData) {
        this.ws.send(JSON.stringify({
          type: 'motion_capture',
          skeleton: this.skeletonData,
          timestamp: Date.now()
        }));
      }
    }, intervalMs);
    
    console.log(`[MotionCapture] 开始发送骨骼数据 (${this.frameRate}fps)`);
  }

  /**
   * 创建隐藏的视频元素
   */
  _createHiddenVideo() {
    const video = document.createElement('video');
    video.style.position = 'fixed';
    video.style.left = '-9999px';
    video.style.width = '1px';
    video.style.height = '1px';
    video.playsInline = true;
    document.body.appendChild(video);
    return video;
  }

  /**
   * 绘制预览画面
   */
  _drawPreview(results) {
    const canvas = this.canvasElement;
    const ctx = canvas.getContext('2d');
    
    // 清空
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    
    // 绘制关键点（使用MediaPipe的drawing_utils）
    if (window.drawConnectors && window.drawLandmarks) {
      window.drawConnectors(ctx, results.poseLandmarks, window.POSE_CONNECTIONS, {
        color: '#00FF00',
        lineWidth: 2
      });
      window.drawLandmarks(ctx, results.poseLandmarks, {
        color: '#FF0000',
        lineWidth: 1,
        radius: 3
      });
    }
  }

  /**
   * 设置帧率
   */
  setFrameRate(fps) {
    this.frameRate = fps;
    if (this.isRunning && this.sendInterval) {
      clearInterval(this.sendInterval);
      this._startSending();
    }
  }
}

// 导出
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { WebcamMotionCapture };
} else {
  window.WebcamMotionCapture = WebcamMotionCapture;
}
