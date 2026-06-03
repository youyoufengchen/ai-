# AI Agent 开发工具使用指南（Aider + CrewAI）

## 快速开始

### 第 0 步：配置 API Key（一次）

```bash
# 1. 复制模板到外部安全目录
copy .env.example "C:\Users\71082\dangerous\.env"

# 2. 编辑 C:\Users\71082\dangerous\.env，填入你的 API Key（至少填一个）
# 推荐优先级：
#   DEEPSEEK_API_KEY    -> 最省钱（~2元/百万token）
#   ANTHROPIC_API_KEY   -> 最强推理（Claude 4）
#   OPENAI_API_KEY      -> 平衡之选（GPT-4o）
```

**安全提醒：**
- `.env` 存放在 `C:\Users\71082\dangerous\`**（项目目录外）**
- 项目目录中的 `.env.example` 只有占位值，**不含真实 Key**
- Aider 和 CrewAI 启动时会自动从 `C:\Users\71082\dangerous\.env` 读取 API Key
- 打包/部署/删除项目时，API Key 完全不受影响

---

## 方案一：Aider（单任务快速修复）

适合：修复单个 bug、重构单个文件、快速编码

### 启动方式

```bash
# 方式 1：双击脚本（推荐）
start-aider.bat

# 方式 2：命令行
.venv\Scripts\python.exe -m aider.main --config .aider.conf.yml
```

### 默认配置

| 角色 | 模型 | 用途 |
|------|------|------|
| **Architect** | Claude 4 | 分析问题、设计修复方案 |
| **Editor** | DeepSeek Coder | 实际修改代码文件 |
| **Weak** | DeepSeek Chat | 生成提交信息、简单任务 |

### 常用命令

```
/add modules/motion_extractor.py frontend/assets-manager.html    # 添加文件到上下文
/drop modules/platform_adapter.py                                 # 移除文件
/test                                                             # 运行 pytest
/commit "修复坐标系转换 bug"                                        # 提交 Git
/undo                                                             # 撤销上次修改
/quit                                                             # 退出
```

### 切换模型（按需）

```bash
# 用最强模型处理复杂问题
aider --model claude-4-20250514

# 用便宜模型处理简单任务
aider --model deepseek/deepseek-coder

# 用国内模型（如果海外模型不可用）
aider --model openrouter/alibaba/qwen-max
```

### 典型工作流

```bash
# 1. 启动
start-aider.bat

# 2. 添加相关文件
/add tools/extract_motion.py tools/motion/body_solver.py frontend/assets-manager.html

# 3. 描述问题
> 修复 motion_extractor 中 MediaPipe 左手系到 Three.js 右手系的坐标系转换问题。
> 当前生成的 3D 动画与原视频姿态差异很大。

# 4. Aider 自动：
#    - Claude 4 分析根因
#    - DeepSeek 修改代码
#    - 运行测试验证

# 5. 检查结果
/git diff    # 查看修改

# 6. 提交
/commit "fix: 修正 MediaPipe 到 Three.js 的坐标系转换"
```

---

## 方案二：CrewAI（多 Agent 协作）

适合：复杂功能开发、跨多文件重构、需要多角色协作的任务

### 启动方式

```bash
# 方式 1：双击脚本 + 交互输入
start-crewai.bat

# 方式 2：命令行直接指定任务
.venv\Scripts\python.exe crew_setup.py --task "修复 motion_extractor 坐标系转换 bug" --type bug -v

# 方式 3：新功能开发
.venv\Scripts\python.exe crew_setup.py --task "添加 NPC 支持展示多个商品的功能" --type feature -v
```

### Agent 分工

| Agent | 模型 | 职责 |
|-------|------|------|
| **技术负责人** | Claude 4 | 分析根因、设计跨文件方案 |
| **Python后端专家** | Claude 3.5 Sonnet | 实现后端逻辑、MediaPipe/NumPy |
| **Three.js前端专家** | GPT-4o | 实现前端、骨骼动画、截图验证 |
| **3D资产专家** | DeepSeek Coder | Blender 脚本、GLB 转换 |
| **QA测试员** | DeepSeek Chat | 运行测试、报告问题 |

### 任务类型

| 类型 | 用途 | 典型 Agent 流 |
|------|------|--------------|
| `bug` | 修复 bug | 架构师分析 → 后端实现 → QA 验证 |
| `feature` | 新功能 | 架构师设计 → 后端实现 → 前端实现 → QA 验证 |
| `refactor` | 重构 | 架构师规划 → 后端重构 → QA 回归 |
| `asset` | 资产处理 | 资产专家处理 → 自动验证 |

### 典型工作流

```bash
# 修复复杂 bug（涉及前后端联动）
python crew_setup.py \
    --task "修复 motion_extractor 生成的 3D 动画与原视频姿态不一致的问题。需要检查：1) MediaPipe 关键点提取 2) 坐标系转换逻辑 3) 前端骨骼重定向" \
    --type bug \
    --verbose

# CrewAI 自动执行：
#   1. 技术负责人读取所有相关文件，分析根因
#   2. Python后端专家修改 extract_motion.py, body_solver.py
#   3. Three.js前端专家修改 assets-manager.html 的 previewAction
#   4. QA测试员运行测试、验证修复
#   5. 生成 crew_report.md 报告
```

---

## API Key 获取方式

### DeepSeek（最便宜，推荐）

1. 访问 https://platform.deepseek.com/
2. 注册账号
3. 创建 API Key
4. 写入 `.env`：`DEEPSEEK_API_KEY=sk-...`
5. 费用：~2元/百万输入token

### Anthropic Claude（最强）

1. 访问 https://console.anthropic.com/
2. 注册（需海外手机号）
3. 创建 API Key
4. 写入 `.env`：`ANTHROPIC_API_KEY=sk-ant-...`
5. 费用：Claude 4 ~$15/百万token

### OpenAI（平衡）

1. 访问 https://platform.openai.com/
2. 注册（需海外手机号）
3. 创建 API Key
4. 写入 `.env`：`OPENAI_API_KEY=sk-...`
5. 费用：GPT-4o ~$2.5/百万token

### 国内替代方案

| 平台 | 获取地址 | 配置项 |
|------|---------|--------|
| 阿里云百炼 | https://bailian.console.aliyun.com/ | `DASHSCOPE_API_KEY` |
| 火山引擎 | https://console.volcengine.com/ | `ARK_API_KEY` |

---

## 成本对比（参考）

修复一个中等复杂度的 bug（约 10K token 输入 + 5K token 输出）：

| 方案 | 费用（人民币） | 效果 |
|------|--------------|------|
| DeepSeek 全流程 | ~0.06元 | 够用，复杂逻辑可能需多轮 |
| Claude 4 分析 + DeepSeek 执行 | ~0.5元 | 最佳性价比 |
| Claude 4 全流程 | ~1.5元 | 最稳，一次搞定 |
| GPT-4o 全流程 | ~0.2元 | 平衡之选 |

---

## 故障排除

### "API Key 未设置"

```bash
# 检查外部 .env 是否存在
dir "C:\Users\71082\dangerous\.env"

# 检查 Key 是否可读
.venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv(dotenv_path=r'C:\Users\71082\dangerous\.env'); import os; print('DEEPSEEK:', bool(os.getenv('DEEPSEEK_API_KEY')))"
```

### "模型不可用"

```bash
# 检查 litellm 是否安装
.venv\Scripts\pip.exe install litellm

# 检查模型名称是否正确
.venv\Scripts\python.exe -c "import litellm; print(litellm.model_list)"
```

### "aider/crewai 命令找不到"

```bash
# 确保在虚拟环境中
.venv\Scripts\pip.exe install aider-chat crewai[tools]
```

---

## 与现有工作流集成

```
日常开发（Windsurf IDE）
        │
        ▼ 遇到复杂 bug
   start-aider.bat
        │
        ▼ 单文件修复完成
   git diff / git commit
        │
        ▼ 涉及多文件/跨模块
   start-crewai.bat --type bug
        │
        ▼ 自动生成报告
   回到 Windsurf 查看 crew_report.md
        │
        ▼ 新功能开发
   start-crewai.bat --type feature
        │
        ▼ 前后端 + 测试全部完成
   git diff 检查 → 合并提交
```

---

## 下一步

1. **现在就做**：复制 `.env.example` → `C:\Users\71082\dangerous\.env`，填入至少一个 API Key
2. **测试 Aider**：双击 `start-aider.bat`，输入 `/add tools/extract_motion.py`，描述一个 bug
3. **测试 CrewAI**：双击 `start-crewai.bat`，输入任务描述
4. **熟悉后**：修改 `.aider.conf.yml` 和 `crew_setup.py` 定制你自己的工作流
