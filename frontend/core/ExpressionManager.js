/**
 * ExpressionManager - VRM表情管理器
 * 
 * 功能：
 * 1. AI情绪标签 → VRM表情映射（happy → vrm.expressionManager.setValue('happy', 0.8)）
 * 2. 表情平滑过渡（淡入淡出）
 * 3. 表情优先级管理（情绪 vs 口型 vs 眨眼）
 * 
 * AI情绪标签来源：
 * - AI回复文本末尾 [e:happy] 标签
 * - 情绪关键词提取
 * 
 * VRM标准表情：
 * - happy, angry, sad, relaxed, surprised, neutral
 * - blink, blinkLeft, blinkRight
 * - aa, ih, ou, ee, oh (口型)
 */

class ExpressionManager {
  constructor(vrm) {
    this.vrm = vrm;
    this.expressionManager = vrm?.expressionManager;
    
    // 当前表情状态
    this.currentEmotion = 'neutral';
    this.currentWeight = 0;
    this.targetEmotion = 'neutral';
    this.targetWeight = 0;
    
    // 过渡参数
    this.transitionSpeed = 0.15;  // 表情切换速度
    this.fadeOutSpeed = 0.1;      // 表情消退速度
    
    // 自动眨眼
    this.blinkTimer = 0;
    this.blinkInterval = 3000;    // 眨眼间隔(ms)
    this.blinkDuration = 150;     // 眨眼持续时间(ms)
    this.isBlinking = false;
    
    // 情绪 → VRM表情 映射表
    this.emotionMap = {
      'happy': 'happy',
      'happiness': 'happy',
      '开心': 'happy',
      '高兴': 'happy',
      '喜悦': 'happy',
      '兴奋': 'happy',
      
      'sad': 'sad',
      'sadness': 'sad',
      '难过': 'sad',
      '悲伤': 'sad',
      '忧郁': 'sad',
      '沮丧': 'sad',
      '失望': 'sad',
      
      'angry': 'angry',
      'anger': 'angry',
      '生气': 'angry',
      '愤怒': 'angry',
      '恼火': 'angry',
      
      'surprised': 'surprised',
      'surprise': 'surprised',
      '惊讶': 'surprised',
      '惊喜': 'surprised',
      '震惊': 'surprised',
      
      'relaxed': 'relaxed',
      'relax': 'relaxed',
      '放松': 'relaxed',
      '平静': 'relaxed',
      '舒适': 'relaxed',
      
      'neutral': 'neutral',
      '自然': 'neutral',
      '正常': 'neutral',
      '无': 'neutral',
      'none': 'neutral',
      
      // 扩展表情（如果VRM支持）
      'embarrassed': 'embarrassed',
      '害羞': 'embarrassed',
      '尴尬': 'embarrassed',
      
      'confused': 'confused',
      '困惑': 'confused',
      '疑惑': 'confused',
      
      'scared': 'scared',
      '害怕': 'scared',
      '恐惧': 'scared',
      
      'disgusted': 'disgusted',
      '厌恶': 'disgusted',
      '恶心': 'disgusted',
      
      'love': 'love',
      'lovely': 'love',
      '喜爱': 'love',
      '爱': 'love',
      '心动': 'love',
    };
    
    // 情绪权重配置（不同情绪的表现强度）
    this.emotionWeights = {
      'happy': 0.8,
      'sad': 0.7,
      'angry': 0.75,
      'surprised': 0.85,
      'relaxed': 0.6,
      'neutral': 0,
      'embarrassed': 0.7,
      'confused': 0.6,
      'scared': 0.8,
      'disgusted': 0.7,
      'love': 0.75,
    };
  }

  /**
   * 从AI回复文本解析情绪标签
   * @param {string} text - AI回复文本，格式: "...内容...[e:happy]"
   * @returns {string} 情绪名称
   */
  parseEmotionFromText(text) {
    // 匹配 [e:emotion] 或 [emotion] 格式
    const match = text.match(/\[e:(\w+)\]|\[(happy|sad|angry|surprised|relaxed|neutral)\]/i);
    if (match) {
      const emotion = match[1] || match[2];
      return emotion.toLowerCase();
    }
    
    // 无标签时，根据关键词判断
    const lowerText = text.toLowerCase();
    for (const [keyword, emotion] of Object.entries(this.emotionMap)) {
      if (lowerText.includes(keyword)) {
        return emotion;
      }
    }
    
    return 'neutral';
  }

  /**
   * 设置目标情绪
   * @param {string} emotion - 情绪名称
   * @param {number} weight - 权重 (0-1)
   */
  setEmotion(emotion, weight = null) {
    // 映射情绪名称
    const mappedEmotion = this.emotionMap[emotion.toLowerCase()] || emotion.toLowerCase();
    
    // 检查VRM是否支持该表情
    if (!this._isExpressionSupported(mappedEmotion)) {
      console.warn(`[Expression] VRM不支持表情: ${mappedEmotion}`);
      return;
    }
    
    // 如果情绪变化，重置当前权重（实现淡入效果）
    if (this.targetEmotion !== mappedEmotion && this.currentEmotion !== 'neutral') {
      this.currentWeight = 0;
    }
    
    this.targetEmotion = mappedEmotion;
    this.targetWeight = weight !== null ? weight : (this.emotionWeights[mappedEmotion] || 0.7);
    
    console.log(`[Expression] 设置情绪: ${emotion} → ${mappedEmotion} (权重: ${this.targetWeight})`);
  }

  /**
   * 从AI回复设置情绪（自动解析）
   * @param {string} aiResponse - AI完整回复
   */
  setEmotionFromAIResponse(aiResponse) {
    const emotion = this.parseEmotionFromText(aiResponse);
    this.setEmotion(emotion);
    
    // 移除文本中的情绪标签（返回干净的文本）
    return aiResponse.replace(/\[e:\w+\]/g, '').trim();
  }

  /**
   * 短暂显示一个表情（用于事件响应）
   * @param {string} emotion - 情绪名称
   * @param {number} duration - 持续时间(ms)
   * @param {number} weight - 权重
   */
  flashEmotion(emotion, duration = 2000, weight = 0.8) {
    this.setEmotion(emotion, weight);
    
    // duration后恢复neutral
    setTimeout(() => {
      this.setEmotion('neutral');
    }, duration);
  }

  /**
   * 更新表情（每帧调用）
   * @param {number} dt - 时间增量（秒）
   */
  update(dt) {
    if (!this.expressionManager) return;
    
    // 处理表情过渡
    if (this.targetEmotion !== this.currentEmotion) {
      // 旧表情淡出
      if (this.currentEmotion !== 'neutral' && this.currentWeight > 0) {
        this.currentWeight = Math.max(0, this.currentWeight - this.fadeOutSpeed);
        this.expressionManager.setValue(this.currentEmotion, this.currentWeight);
        
        if (this.currentWeight <= 0) {
          this.currentEmotion = this.targetEmotion;
          this.currentWeight = 0;
        }
      } else {
        // 旧表情已淡出，切换到新表情
        this.currentEmotion = this.targetEmotion;
        this.currentWeight = 0;
      }
    } else {
      // 同表情，调整权重到目标
      if (Math.abs(this.currentWeight - this.targetWeight) > 0.01) {
        const diff = this.targetWeight - this.currentWeight;
        this.currentWeight += diff * this.transitionSpeed;
        this.expressionManager.setValue(this.currentEmotion, this.currentWeight);
      }
    }
    
    // 自动眨眼
    this._updateBlink(dt);
  }

  /**
   * 自动眨眼更新
   */
  _updateBlink(dt) {
    const now = performance.now();
    
    if (!this.isBlinking) {
      // 检查是否该眨眼了
      if (now - this.blinkTimer > this.blinkInterval) {
        this.isBlinking = true;
        this.blinkTimer = now;
        this.blinkInterval = 2000 + Math.random() * 2000; // 2-4秒随机间隔
      }
    } else {
      // 眨眼进行中
      const elapsed = now - this.blinkTimer;
      
      if (elapsed < this.blinkDuration / 2) {
        // 闭眼阶段
        const weight = elapsed / (this.blinkDuration / 2);
        this.expressionManager.setValue('blink', weight);
      } else if (elapsed < this.blinkDuration) {
        // 睁眼阶段
        const weight = 1 - (elapsed - this.blinkDuration / 2) / (this.blinkDuration / 2);
        this.expressionManager.setValue('blink', weight);
      } else {
        // 眨眼结束
        this.isBlinking = false;
        this.blinkTimer = now;
        this.expressionManager.setValue('blink', 0);
      }
    }
  }

  /**
   * 强制眨眼一次
   */
  blink() {
    this.isBlinking = true;
    this.blinkTimer = performance.now() - this.blinkDuration / 2;
  }

  /**
   * 检查表情是否被支持
   */
  _isExpressionSupported(name) {
    if (!this.expressionManager) return false;
    const expressions = Object.keys(this.expressionManager.expressionMap || {});
    return expressions.includes(name);
  }

  /**
   * 获取当前支持的表情列表
   */
  getSupportedExpressions() {
    if (!this.expressionManager) return [];
    return Object.keys(this.expressionManager.expressionMap || {});
  }

  /**
   * 重置所有表情
   */
  reset() {
    if (!this.expressionManager) return;
    
    const expressions = this.getSupportedExpressions();
    for (const exp of expressions) {
      this.expressionManager.setValue(exp, 0);
    }
    
    this.currentEmotion = 'neutral';
    this.currentWeight = 0;
    this.targetEmotion = 'neutral';
    this.targetWeight = 0;
    
    console.log('[Expression] 所有表情已重置');
  }
}

// 导出
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { ExpressionManager };
} else {
  window.ExpressionManager = ExpressionManager;
}
