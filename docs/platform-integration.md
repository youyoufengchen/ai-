# 多直播平台接入指南

## 已支持平台

| 平台 | 状态 | Webhook地址 | 支持事件 |
|------|------|------------|---------|
| 抖音直播 | ✅ | `/webhook/douyin` | 弹幕/礼物/进入/点赞/关注/下单 |
| 微信视频号 | ⏳ | `/webhook/wechat` | 弹幕/礼物/进入/点赞/关注 |
| 小红书直播 | ⏳ | `/webhook/xiaohongshu` | 弹幕/礼物/进入/点赞/关注 |
| 淘宝直播 | ⏳ | `/webhook/taobao` | 弹幕/礼物/进入/点赞/关注/下单 |
| 快手直播 | ⏳ | `/webhook/kuaishou` | 弹幕/礼物/进入/点赞/关注/下单 |
| 火山引擎 | ⏳ | `/webhook/huoshan` | 弹幕/礼物/进入/点赞/关注/下单 |

> ⏳ 表示需要配置平台认证信息后才能启用

---

## 快速配置

### 1. 修改配置文件

编辑 `config/platforms.json`，启用需要的平台：

```json
{
  "douyin": {
    "enabled": true,
    "webhook_secret": "your_douyin_secret"
  },
  "wechat": {
    "enabled": true,
    "token": "your_wechat_token",
    "app_id": "your_app_id"
  }
}
```

### 2. 配置平台Webhook推送

在各直播平台后台，将Webhook推送地址配置为：

```
http://your-server-ip:8080/webhook/{platform}
```

例如：
- 抖音：`http://192.168.1.100:8080/webhook/douyin`
- 视频号：`http://192.168.1.100:8080/webhook/wechat`

### 3. 重启服务

```bash
python server.py
```

---

## 各平台详细接入

### 抖音直播

**接入方式：** 抖音开放平台 webhook

**配置步骤：**
1. 登录 [抖音开放平台](https://developer.open-douyin.com/)
2. 创建应用，获取 AppID 和 AppSecret
3. 申请直播相关权限
4. 配置服务器域名和 webhook 地址
5. 设置 webhook 签名密钥
6. 将密钥填入 `platforms.json`

**本地测试：** 使用内网穿透工具（如 ngrok）

```bash
ngrok http 8080
# 获得公网地址如 https://abc123.ngrok.io
# 配置为 webhook 地址：https://abc123.ngrok.io/webhook/douyin
```

---

### 微信视频号

**接入方式：** 视频号直播消息推送

**配置步骤：**
1. 登录 [视频号助手](https://channels.weixin.qq.com/)
2. 进入「直播管理」→「开发者设置」
3. 开启消息推送，配置服务器URL
4. 设置 Token 和 EncodingAESKey
5. 填入 `platforms.json`

**注意：** 视频号需要企业认证，个人账号无API权限

---

### 小红书直播

**接入方式：** 小红书专业号 API

**配置步骤：**
1. 登录 [小红书专业号后台](https://pro.xiaohongshu.com/)
2. 申请直播中心 API 权限
3. 获取 API Key 和 Secret
4. 配置消息推送地址（需HTTPS）
5. 填入 `platforms.json`

---

### 淘宝直播

**接入方式：** 千牛开放平台 / TOP API

**配置步骤：**
1. 登录 [淘宝开放平台](https://open.taobao.com/)
2. 创建应用，获取 AppKey 和 AppSecret
3. 申请「直播消息订阅」权限
4. 配置消息推送地址
5. 填入 `platforms.json`

---

### 快手直播

**接入方式：** 快手开放平台直播SDK

**配置步骤：**
1. 登录 [快手开放平台](https://open.kuaishou.com/)
2. 创建应用，获取 AppID
3. 申请直播相关权限
4. 配置推送地址和签名密钥
5. 填入 `platforms.json`

---

## 统一事件格式

所有平台的事件都会转换为统一的 `LiveEvent` 格式：

```python
{
    "platform": "douyin",      # 平台标识
    "event_type": "chat",      # chat/gift/enter/like/follow/order
    "user_id": "12345",
    "username": "用户昵称",
    "content": "弹幕内容",
    "amount": 1,               # 数量（点赞数/礼物数）
    "price": 0.0,              # 金额（礼物价值/订单金额）
    "sku_id": "",              # 商品ID（下单时）
    "timestamp": "2024-01-01T00:00:00"
}
```

---

## 常见问题

### Q: Webhook 推送不通怎么办？

1. **检查防火墙**：确保 8080 端口对外开放
2. **使用内网穿透**：开发环境推荐使用 ngrok
3. **查看日志**：检查 server.py 日志中的 webhook 接收记录

### Q: 多个平台同时开播如何处理？

当前系统支持同时接入多个平台，所有事件都会进入同一个事件队列，按优先级处理。

如需区分平台做不同响应，可在 action.json 中添加平台判断条件。

### Q: 平台推送延迟高怎么办？

1. 确保服务器网络稳定
2. 使用离用户近的服务器部署
3. 考虑使用平台官方提供的 SDK 直接接入

---

## 开发计划

- [x] 抖音 webhook 接入
- [x] 多平台统一适配器框架
- [ ] 微信视频号完整接入
- [ ] 小红书直播接入
- [ ] 淘宝直播接入
- [ ] 快手直播接入
- [ ] 本地弹幕抓取（无需官方API）
