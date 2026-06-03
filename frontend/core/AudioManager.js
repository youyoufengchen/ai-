/**
 * AudioManager.js
 * 音效/音乐统一管理器
 *
 * 职责：
 * 1. 从 sound_catalog.json 加载音效注册表
 * 2. 按 id 播放/停止/循环音效（Web Audio API + HTMLAudio 双通道）
 * 3. 并发控制（同类型不叠加，不同类型可并行）
 * 4. 音量分层（ambient / emotion / action / transform / event / music）
 * 5. 语义检索：按自然语言查询匹配最佳音效（triggers + tags TF-IDF）
 */

class AudioManager {
  constructor() {
    /** @type {Map<string, Object>} id → catalog entry */
    this._catalog = new Map();

    /** @type {Map<string, AudioBuffer>} id → decoded buffer（Web Audio） */
    this._bufferCache = new Map();

    /** @type {Map<string, {source, gainNode, startTime}>} id → 当前播放实例 */
    this._playing = new Map();

    /** @type {Map<string, string>} category → 当前正在播的 id（同类互斥） */
    this._categoryActive = new Map();

    /** @type {AudioContext|null} */
    this._ctx = null;

    /** @type {GainNode|null} 主音量节点 */
    this._masterGain = null;

    // 分类音量（与 sound_catalog.json._playback_rules 对齐）
    this._volumeMap = {
      ambient:   0.25,
      emotion:   0.6,
      action:    0.8,
      transform: 1.0,
      event:     0.9,
      effect:    0.8,
      music:     0.5,
      singing:   0.7,
    };

    // 最大同时播放数
    this._maxSimultaneous = 4;

    // TF-IDF 索引
    this._idf = {};
    this._entries = []; // [{id, searchText, ...}]

    this._loaded = false;
  }

  // ═══════════════════════════════════════════════════════
  //  初始化
  // ═══════════════════════════════════════════════════════

  /**
   * 加载 sound_catalog.json 并构建索引
   * @param {string} catalogUrl - 音效目录的URL（默认 /config/sound_catalog.json）
   */
  async init(catalogUrl = '/config/sound_catalog.json') {
    try {
      const resp = await fetch(catalogUrl);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();

      // 解析 playback rules
      const rules = data._playback_rules || {};
      this._maxSimultaneous = rules.max_simultaneous || 4;
      Object.keys(this._volumeMap).forEach(cat => {
        if (rules[`${cat}_volume`] !== undefined) {
          this._volumeMap[cat] = rules[`${cat}_volume`];
        }
      });

      // 注册所有音效
      for (const entry of (data.sounds || [])) {
        this._catalog.set(entry.id, entry);
      }

      // 构建语义检索索引
      this._buildSearchIndex();

      this._loaded = true;
      console.log(`[AudioManager] 加载 ${this._catalog.size} 个音效`);
    } catch (e) {
      console.warn('[AudioManager] 加载音效目录失败:', e);
    }
  }

  /** 确保 AudioContext 已创建（需用户交互后调用） */
  _ensureContext() {
    if (!this._ctx) {
      this._ctx = new (window.AudioContext || window.webkitAudioContext)();
      this._masterGain = this._ctx.createGain();
      this._masterGain.connect(this._ctx.destination);
    }
    if (this._ctx.state === 'suspended') {
      this._ctx.resume();
    }
    return this._ctx;
  }

  // ═══════════════════════════════════════════════════════
  //  播放 / 停止
  // ═══════════════════════════════════════════════════════

  /**
   * 播放音效
   * @param {string} soundId - sound_catalog 中的 id
   * @param {Object} opts
   * @param {number} opts.volume - 覆盖音量 (0~1)
   * @param {boolean} opts.loop - 覆盖循环
   * @param {boolean} opts.allowOverlap - 允许同类叠加（默认 false）
   * @returns {string|null} 播放实例 key（用于 stop）
   */
  play(soundId, opts = {}) {
    const entry = this._catalog.get(soundId);
    if (!entry) {
      console.warn(`[AudioManager] 未注册的音效: ${soundId}`);
      return null;
    }

    const category = entry.category || 'action';
    const loop = opts.loop !== undefined ? opts.loop : (entry.loop || false);
    const volume = (opts.volume !== undefined ? opts.volume : (entry.volume_multiplier || 1.0))
                   * (this._volumeMap[category] || 0.8);

    // 同类互斥：停掉同类别当前播放的
    if (!opts.allowOverlap) {
      const activeId = this._categoryActive.get(category);
      if (activeId && this._playing.has(activeId)) {
        this.stop(activeId);
      }
    }

    // 并发上限
    if (this._playing.size >= this._maxSimultaneous) {
      // 按优先级淘汰最低的
      const priorities = ['ambient', 'action', 'emotion', 'effect', 'event', 'transform'];
      for (const lowCat of priorities) {
        const lowId = this._categoryActive.get(lowCat);
        if (lowId && this._playing.has(lowId)) {
          this.stop(lowId);
          break;
        }
      }
    }

    const playKey = `${soundId}_${Date.now()}`;
    this._categoryActive.set(category, playKey);

    // 优先尝试 Web Audio API（低延迟），失败降级到 HTMLAudio
    this._playWebAudio(playKey, entry, volume, loop).catch(() => {
      this._playHTMLAudio(playKey, entry, volume, loop);
    });

    return playKey;
  }

  /**
   * 停止指定音效
   * @param {string} playKey - play() 返回的 key，或 soundId 字符串
   */
  stop(playKey) {
    // 如果传入的是 soundId，查找对应的 playKey
    if (!this._playing.has(playKey)) {
      for (const [key, info] of this._playing) {
        if (info.soundId === playKey || key.startsWith(playKey + '_')) {
          playKey = key;
          break;
        }
      }
    }

    const info = this._playing.get(playKey);
    if (!info) return;

    try {
      if (info.source) {
        if (info.source.stop) info.source.stop();
        if (info.gainNode) info.gainNode.disconnect();
      }
      if (info.audioEl) {
        info.audioEl.pause();
        info.audioEl.src = '';
      }
    } catch (e) { /* ignore */ }

    this._playing.delete(playKey);

    // 清除 category active
    for (const [cat, activeKey] of this._categoryActive) {
      if (activeKey === playKey) {
        this._categoryActive.delete(cat);
        break;
      }
    }
  }

  /** 停止所有 */
  stopAll() {
    for (const key of [...this._playing.keys()]) {
      this.stop(key);
    }
    this._categoryActive.clear();
  }

  /** 停止指定类别的所有音效 */
  stopCategory(category) {
    for (const [key, info] of this._playing) {
      if (info.category === category) {
        this.stop(key);
      }
    }
  }

  /** 设置主音量 */
  setMasterVolume(v) {
    if (this._masterGain) {
      this._masterGain.gain.setValueAtTime(
        Math.max(0, Math.min(1, v)),
        this._ctx.currentTime
      );
    }
  }

  /** 设置分类音量 */
  setCategoryVolume(category, v) {
    this._volumeMap[category] = Math.max(0, Math.min(1, v));
  }

  /** 获取当前正在播放的音效列表 */
  getPlaying() {
    return [...this._playing.entries()].map(([key, info]) => ({
      key,
      soundId: info.soundId,
      category: info.category,
    }));
  }

  // ═══════════════════════════════════════════════════════
  //  语义检索（TF-IDF，与 ActionRetriever 同架构）
  // ═══════════════════════════════════════════════════════

  /**
   * 按自然语言查询最佳匹配的音效
   * @param {string} query - 如 "生气低吼" "开心笑声" "变身狐狸"
   * @param {Object} opts
   * @param {string} opts.category - 限定类别
   * @param {string} opts.emotion - 限定情绪
   * @param {string} opts.form - 限定形态
   * @param {number} opts.topK - 返回数量
   * @returns {Array<{id, score, entry}>}
   */
  search(query, opts = {}) {
    const { category, emotion, form, topK = 3 } = opts;
    const queryTokens = this._tokenize(query);

    let results = [];
    for (const item of this._entries) {
      // 前置过滤
      if (category && item.category !== category) continue;
      if (emotion && item.emotion_tag && item.emotion_tag !== emotion) continue;
      if (form && item.form_restriction && item.form_restriction !== form) continue;

      const score = this._tfidfScore(queryTokens, item.tokens);
      if (score > 0) {
        results.push({ id: item.id, score, entry: this._catalog.get(item.id) });
      }
    }

    results.sort((a, b) => b.score - a.score);
    return results.slice(0, topK);
  }

  /**
   * 按自然语言查询并直接播放最佳匹配
   * @param {string} query
   * @param {Object} searchOpts - search() 的选项
   * @param {Object} playOpts - play() 的选项
   * @returns {string|null} playKey
   */
  searchAndPlay(query, searchOpts = {}, playOpts = {}) {
    const results = this.search(query, { ...searchOpts, topK: 1 });
    if (results.length > 0) {
      console.log(`[AudioManager] 语义匹配: "${query}" → ${results[0].id} (${results[0].score.toFixed(3)})`);
      return this.play(results[0].id, playOpts);
    }
    console.warn(`[AudioManager] 无匹配: "${query}"`);
    return null;
  }

  // ═══════════════════════════════════════════════════════
  //  内部：Web Audio API 播放
  // ═══════════════════════════════════════════════════════

  async _playWebAudio(playKey, entry, volume, loop) {
    const ctx = this._ensureContext();
    const filePath = '/' + entry.file;

    // 尝试从缓存获取 buffer
    let buffer = this._bufferCache.get(entry.id);
    if (!buffer) {
      const resp = await fetch(filePath);
      if (!resp.ok) throw new Error(`Failed to fetch ${filePath}`);
      const arrayBuf = await resp.arrayBuffer();
      buffer = await ctx.decodeAudioData(arrayBuf);
      this._bufferCache.set(entry.id, buffer);
    }

    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.loop = loop;

    const gainNode = ctx.createGain();
    gainNode.gain.setValueAtTime(volume, ctx.currentTime);
    source.connect(gainNode);
    gainNode.connect(this._masterGain);

    source.start(0);

    this._playing.set(playKey, {
      soundId: entry.id,
      category: entry.category,
      source,
      gainNode,
      startTime: ctx.currentTime,
    });

    // 非循环：播完自动清理
    if (!loop) {
      source.onended = () => {
        this._playing.delete(playKey);
        for (const [cat, activeKey] of this._categoryActive) {
          if (activeKey === playKey) {
            this._categoryActive.delete(cat);
            break;
          }
        }
      };
    }
  }

  /** 降级：HTMLAudio 播放 */
  _playHTMLAudio(playKey, entry, volume, loop) {
    const audio = new Audio('/' + entry.file);
    audio.volume = Math.min(1, volume);
    audio.loop = loop;
    audio.play().catch(() => {});

    this._playing.set(playKey, {
      soundId: entry.id,
      category: entry.category,
      audioEl: audio,
    });

    if (!loop) {
      audio.onended = () => {
        this._playing.delete(playKey);
        for (const [cat, activeKey] of this._categoryActive) {
          if (activeKey === playKey) {
            this._categoryActive.delete(cat);
            break;
          }
        }
      };
    }
  }

  // ═══════════════════════════════════════════════════════
  //  内部：TF-IDF 语义检索
  // ═══════════════════════════════════════════════════════

  _buildSearchIndex() {
    this._entries = [];
    for (const [id, entry] of this._catalog) {
      const searchText = [
        entry.display_name || '',
        ...(entry.triggers || []),
        ...(entry.tags || []),
        entry.category || '',
        entry.emotion_tag || '',
        entry.description || '',
      ].join(' ');

      const tokens = this._tokenize(searchText);
      this._entries.push({
        id,
        category: entry.category,
        emotion_tag: entry.emotion_tag,
        form_restriction: entry.form_restriction,
        tokens,
        searchText,
      });
    }

    // 构建 IDF
    const N = this._entries.length;
    const df = {};
    for (const item of this._entries) {
      const unique = new Set(item.tokens);
      for (const t of unique) {
        df[t] = (df[t] || 0) + 1;
      }
    }
    this._idf = {};
    for (const [t, cnt] of Object.entries(df)) {
      this._idf[t] = Math.log((N + 1) / (cnt + 1)) + 1;
    }
  }

  _tokenize(text) {
    text = (text || '').toLowerCase().trim();
    const words = text.match(/[\u4e00-\u9fff]{1,4}|[a-z_]+/g) || [];
    const bigrams = [];
    for (let i = 0; i < text.length - 1; i++) {
      if (text[i] >= '\u4e00' && text[i] <= '\u9fff') {
        bigrams.push(text.substring(i, i + 2));
      }
    }
    return [...new Set([...words, ...bigrams])];
  }

  _tfidfScore(queryTokens, docTokens) {
    const docFreq = {};
    for (const t of docTokens) {
      docFreq[t] = (docFreq[t] || 0) + 1;
    }
    let score = 0;
    for (const t of queryTokens) {
      if (docFreq[t]) {
        const tf = docFreq[t] / Math.max(docTokens.length, 1);
        const idf = this._idf[t] || 1.0;
        score += tf * idf;
      }
    }
    const norm = Math.sqrt(
      queryTokens.reduce((s, t) => s + (this._idf[t] || 1.0) ** 2, 0)
    );
    return score / Math.max(norm, 1e-9);
  }
}

// 导出全局单例
window.AudioManager = new AudioManager();
