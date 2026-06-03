/**
 * LipSyncManager - VRM口型同步管理器
 * 
 * 功能：
 * 1. 解析火山引擎TTS返回的Viseme时间轴
 * 2. 驱动VRM的口型BlendShape权重
 * 3. 平滑插值，口型过渡自然
 * 
 * VRM标准口型节点（Viseme）：
 * - aa = A (张嘴)
 * - ih = I (咧嘴)
 * - ou = U (圆嘴)
 * - ee = E (展唇)
 * - oh = O (O型嘴)
 */

class LipSyncManager {
  constructor(vrm) {
    this.vrm = vrm;
    this.expressionManager = vrm?.expressionManager;
    
    // 口型状态
    this.currentViseme = null;    // 当前激活的口型
    this.targetWeight = 0;        // 目标权重
    this.currentWeight = 0;       // 当前权重
    this.transitionSpeed = 0.3;   // 过渡速度 (0-1)
    
    // Viseme时间轴
    this.visemeTimeline = [];     // [{time, viseme, weight}, ...]
    this.startTime = 0;
    this.isPlaying = false;
    this.audioDuration = 0;
    
    // 音素到VRM的映射
    this.visemeMap = {
      'A': 'aa',      // 啊
      'I': 'ih',      // 咿
      'U': 'ou',      // 呜
      'E': 'ee',      // 诶
      'O': 'oh',      // 哦
      'a': 'aa',
      'i': 'ih',
      'u': 'ou',
      'e': 'ee',
      'o': 'oh',
      // 常见音标变体
      'AA': 'aa',     // 英语 A
      'AE': 'aa',     // 英语 a
      'AH': 'aa',     // 英语 u
      'AO': 'oh',     // 英语 o
      'AW': 'aa',     // 英语 ow
      'AY': 'aa',     // 英语 ai
      'B': 'oh',      // 英语 b (闭嘴唇)
      'CH': 'ih',     // 英语 ch
      'D': 'ih',      // 英语 d
      'DH': 'ih',     // 英语 th
      'EH': 'ee',     // 英语 e
      'ER': 'oh',     // 英语 er
      'EY': 'ee',     // 英语 ei
      'F': 'ih',      // 英语 f (咬唇)
      'G': 'oh',      // 英语 g
      'HH': 'aa',     // 英语 h
      'IH': 'ih',     // 英语 i
      'IY': 'ee',     // 英语 ee
      'JH': 'ih',     // 英语 j
      'K': 'aa',      // 英语 k
      'L': 'aa',      // 英语 l
      'M': 'oh',      // 英语 m (闭嘴唇)
      'N': 'ih',      // 英语 n
      'NG': 'ou',     // 英语 ng
      'OW': 'oh',     // 英语 o
      'OY': 'oh',     // 英语 oy
      'P': 'oh',      // 英语 p (闭嘴唇)
      'R': 'aa',      // 英语 r
      'S': 'ee',      // 英语 s
      'SH': 'ee',     // 英语 sh
      'T': 'ih',      // 英语 t
      'TH': 'ih',     // 英语 th
      'UH': 'ou',     // 英语 u
      'UW': 'ou',     // 英语 oo
      'V': 'ih',      // 英语 v (咬唇)
      'W': 'ou',      // 英语 w
      'Y': 'ee',      // 英语 y
      'Z': 'ee',      // 英语 z
      'ZH': 'ee',     // 英语 zh
      'SIL': null,    // 静音
      'SP': null,     // 静音
    };
  }

  /**
   * 设置Viseme时间轴（从TTS返回数据解析）
   * @param {Array} timeline - [{time_ms, viseme, weight}, ...]
   * @param {number} duration_ms - 音频总时长
   */
  setVisemeTimeline(timeline, duration_ms) {
    this.visemeTimeline = timeline.map(item => ({
      time: item.time_ms / 1000,  // 转为秒
      viseme: this.visemeMap[item.viseme] || item.viseme.toLowerCase(),
      weight: item.weight || 1.0
    })).filter(item => item.viseme !== null);
    
    this.audioDuration = duration_ms / 1000;
    this.startTime = performance.now() / 1000;
    this.isPlaying = true;
    
    console.log('[LipSync] 设置口型时间轴:', this.visemeTimeline.length, '个点, 时长:', this.audioDuration.toFixed(2), 's');
  }

  /**
   * 从火山引擎TTS响应解析Viseme时间轴
   * @param {Object} ttsResponse - TTS API响应
   * @returns {Array} timeline
   */
  parseVolcengineViseme(ttsResponse) {
    // 火山引擎TTS返回格式：
    // {
    //   "audio": "base64...",
    //   "viseme": [
    //     {"t": 0, "v": "SIL"},
    //     {"t": 80, "v": "A"},
    //     {"t": 160, "v": "I"},
    //     ...
    //   ],
    //   "duration": 3250
    // }
    
    if (!ttsResponse?.viseme) {
      return [];
    }
    
    const timeline = ttsResponse.viseme.map(item => ({
      time_ms: item.t || item.time || 0,
      viseme: item.v || item.viseme || 'SIL',
      weight: 1.0
    }));
    
    const duration = ttsResponse.duration || 
                    (timeline.length > 0 ? timeline[timeline.length - 1].time_ms + 200 : 0);
    
    return { timeline, duration };
  }

  /**
   * 从简单音素序列生成时间轴（无TTS viseme时使用）
   * @param {string} phonemes - 音素序列，如 "a-i-u-e-o"
   * @param {number} duration_ms - 总时长
   */
  generateFromPhonemes(phonemes, duration_ms) {
    const phonemeList = phonemes.split(/[-\s]+/);
    const interval = duration_ms / phonemeList.length;
    
    const timeline = phonemeList.map((p, i) => ({
      time_ms: i * interval,
      viseme: p.toUpperCase(),
      weight: 1.0
    }));
    
    this.setVisemeTimeline(timeline, duration_ms);
  }

  /**
   * 更新口型（每帧调用）
   * @param {number} dt - 时间增量（秒）
   */
  update(dt) {
    if (!this.isPlaying || !this.expressionManager) return;
    
    const now = performance.now() / 1000;
    const elapsed = now - this.startTime;
    
    // 检查是否结束
    if (elapsed > this.audioDuration + 0.5) {
      this.stop();
      return;
    }
    
    // 找到当前时间点对应的口型
    let targetViseme = null;
    let targetWeight = 0;
    
    for (let i = 0; i < this.visemeTimeline.length; i++) {
      const item = this.visemeTimeline[i];
      if (item.time <= elapsed) {
        targetViseme = item.viseme;
        targetWeight = item.weight;
      } else {
        break;
      }
    }
    
    // 平滑过渡
    if (targetViseme !== this.currentViseme) {
      // 切换到新口型，先归零旧的
      if (this.currentViseme) {
        this.currentWeight = Math.max(0, this.currentWeight - this.transitionSpeed);
        if (this.currentWeight < 0.01) {
          this.expressionManager.setValue(this.currentViseme, 0);
          this.currentViseme = null;
          this.currentWeight = 0;
        } else {
          this.expressionManager.setValue(this.currentViseme, this.currentWeight);
        }
      } else {
        this.currentViseme = targetViseme;
        this.targetWeight = targetWeight;
      }
    } else {
      // 保持当前口型，平滑接近目标权重
      if (this.currentViseme) {
        const diff = this.targetWeight - this.currentWeight;
        if (Math.abs(diff) > 0.01) {
          this.currentWeight += diff * this.transitionSpeed;
        } else {
          this.currentWeight = this.targetWeight;
        }
        this.expressionManager.setValue(this.currentViseme, this.currentWeight);
      }
    }
  }

  /**
   * 立即停止口型
   */
  stop() {
    this.isPlaying = false;
    
    // 归零所有口型
    if (this.expressionManager) {
      ['aa', 'ih', 'ou', 'ee', 'oh'].forEach(v => {
        this.expressionManager.setValue(v, 0);
      });
    }
    
    this.currentViseme = null;
    this.currentWeight = 0;
    this.visemeTimeline = [];
    
    console.log('[LipSync] 停止');
  }

  /**
   * 播放测试序列（用于调试）
   */
  playTest() {
    const testTimeline = [
      { time_ms: 0, viseme: 'SIL', weight: 0 },
      { time_ms: 100, viseme: 'A', weight: 1.0 },
      { time_ms: 300, viseme: 'I', weight: 1.0 },
      { time_ms: 500, viseme: 'U', weight: 1.0 },
      { time_ms: 700, viseme: 'E', weight: 1.0 },
      { time_ms: 900, viseme: 'O', weight: 1.0 },
      { time_ms: 1100, viseme: 'SIL', weight: 0 },
    ];
    
    this.setVisemeTimeline(testTimeline, 1200);
    console.log('[LipSync] 播放测试序列: A-I-U-E-O');
  }
}

// 导出
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { LipSyncManager };
} else {
  window.LipSyncManager = LipSyncManager;
}
