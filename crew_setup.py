#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CrewAI 多 Agent 编排脚本 - 宝青坊项目

用途：自动分派开发任务给多个 AI Agent 协作完成

用法：
    python crew_setup.py --task "修复 motion_extractor 坐标系转换 bug"
    python crew_setup.py --task "添加新闻演播室场景支持" --verbose

模型优先级（按成本从低到高）：
    1. deepseek/deepseek-chat     - 简单任务、文档、中文理解
    2. gpt-4o                     - 前端代码、测试
    3. claude-3-5-sonnet          - 后端逻辑、复杂推理
    4. claude-4                   - 架构设计、跨文件重构

环境要求：
    pip install crewai litellm python-dotenv
    在 .env 中配置对应 API Key
"""

import os
import sys
import argparse
from pathlib import Path
from typing import List, Dict, Any

# 加载 .env（API Key 从这里读取）
from dotenv import load_dotenv

# 安全加载 .env：
# 1. 优先从 AGENT_ENV_PATH 环境变量指定的路径加载（推荐放在项目外）
# 2. 回退到项目目录的 .env（不建议用于生产环境）
# 3. 你也可以直接在系统环境变量中配置 API Key
env_path = os.environ.get("AGENT_ENV_PATH")
if env_path and Path(env_path).exists():
    load_dotenv(dotenv_path=env_path)
    print(f"[INFO] 已从 {env_path} 加载配置")
else:
    load_dotenv()
    if not any(os.environ.get(k) for k in ["DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"]):
        print("[WARN] 未找到 API Key。请执行以下操作之一：")
        print("  1. 设置系统环境变量 AGENT_ENV_PATH=C:\\path\\to\\your\\.env")
        print("  2. 在项目目录创建 .env 文件（仅开发环境）")
        print("  3. 直接在系统环境变量中配置 API Key")

# CrewAI 导入
try:
    from crewai import Agent, Task, Crew, Process
    from crewai.tools import tool
except ImportError:
    print("错误: crewai 未安装。运行: .venv\\Scripts\\pip install crewai[tools]")
    sys.exit(1)

# ──────────────────────────────────────────
# 模型选择器（根据任务复杂度自动分配合适模型）
# ──────────────────────────────────────────
MODEL_CONFIGS = {
    "architect": {
        "provider": "anthropic",
        "model": "claude-4-20250514",
        "temperature": 0.2,
        "cost": "high",
    },
    "senior": {
        "provider": "anthropic",
        "model": "claude-3-5-sonnet-20241022",
        "temperature": 0.3,
        "cost": "medium",
    },
    "frontend": {
        "provider": "openai",
        "model": "gpt-4o",
        "temperature": 0.4,
        "cost": "medium",
    },
    "implementer": {
        "provider": "deepseek",
        "model": "deepseek/deepseek-coder",
        "temperature": 0.5,
        "cost": "low",
    },
    "qa": {
        "provider": "deepseek",
        "model": "deepseek/deepseek-chat",
        "temperature": 0.3,
        "cost": "low",
    },
}


def get_model(model_key: str):
    """获取模型配置，检查 API Key 是否可用"""
    config = MODEL_CONFIGS.get(model_key)
    if not config:
        raise ValueError(f"未知模型配置: {model_key}")

    provider = config["provider"]
    env_map = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
    }

    env_key = env_map.get(provider)
    if env_key and not os.environ.get(env_key):
        print(f"警告: {env_key} 未设置，{model_key} 模型不可用")
        # 降级处理
        if model_key in ("architect", "senior"):
            print("降级到 deepseek/deepseek-coder")
            return "deepseek/deepseek-coder"
        return None

    return config["model"]


# ──────────────────────────────────────────
# 项目上下文（注入每个 Agent 的 system prompt）
# ──────────────────────────────────────────
PROJECT_CONTEXT = """
你正在参与 "宝青坊" 虚拟直播 NPC 项目的开发。

项目架构核心原则：
1. 每个 server.py 进程 = 一个 NPC = 一个直播间（多开=多进程）
2. NPC 的所有动作规划基于自己生成的回复文本来预规划
3. 工作流：用户弹幕 → AI生成NPC回复 → 解析回复提取意图/商品 → 规划动作序列 → 排入队列 → NPC执行

技术栈：
- 后端：Python 3.12 + aiohttp + asyncio
- 前端：Three.js + 原生 JS
- 3D：Mixamo X Bot (GLB) + MediaPipe 动作提取
- 坐标系：MediaPipe 左手系 → 需转换为 Three.js 右手系 (Y-up)

目录结构：
- modules/        后端逻辑
- frontend/       前端页面
- assets/         3D 资产
- tools/          脚本工具
- config/         配置文件
- cache/          运行时缓存
- docs/           文档

修改规则：
- 保持现有代码风格
- 不要删除注释
- 修改后验证测试
- 3D 相关注意坐标系
"""


# ──────────────────────────────────────────
# Agent 定义
# ──────────────────────────────────────────
def create_agents() -> Dict[str, Agent]:
    """创建项目所需的 Agent 角色"""

    agents = {}

    # 1. 技术负责人（架构师）- 最难的任务
    model = get_model("architect") or get_model("senior")
    if model:
        agents["architect"] = Agent(
            role="技术负责人",
            goal="分析复杂问题根因，设计可靠的修复方案，确保跨文件改动的一致性",
            backstory=f"""你是资深全栈架构师，擅长：
- 跨文件代码分析（Python 后端 + Three.js 前端联动）
- 坐标系和数学问题（MediaPipe 左手系 vs Three.js 右手系）
- 动画系统（骨骼重定向、IK/FK）
- 异步架构（asyncio + aiohttp）

你在做任何修改前，会先完整阅读所有相关文件，理解数据流和依赖关系。
你输出的方案总是包含：1) 根因分析 2) 修改文件列表 3) 详细步骤 4) 测试验证方法。""",
            llm=model,
            verbose=True,
            allow_delegation=True,
            max_iter=5,
        )

    # 2. Python 后端开发 - 中等难度
    model = get_model("senior") or get_model("implementer")
    if model:
        agents["backend"] = Agent(
            role="Python后端专家",
            goal="高质量实现后端逻辑修改，保证 asyncio 和 MediaPipe 处理正确",
            backstory=f"""你专注于 Python 后端开发，擅长：
- asyncio 异步编程和并发控制
- MediaPipe 姿态估计和数据处理
- NumPy 矩阵运算和坐标系转换
- pytest 单元测试编写

你总是先写测试用例再改实现，确保修改不会破坏现有功能。""",
            llm=model,
            verbose=False,
            allow_delegation=False,
        )

    # 3. Three.js 前端开发
    model = get_model("frontend") or get_model("implementer")
    if model:
        agents["frontend"] = Agent(
            role="Three.js前端专家",
            goal="实现前端 3D 预览和交互功能，确保动画与视频姿态一致",
            backstory=f"""你专注于 Three.js 和 Web 3D 开发，擅长：
- Three.js AnimationMixer 和骨骼动画
- GLTF/GLB 加载和骨骼重定向
- Canvas 2D 绘制（MediaPipe 关键点叠加）
- 浏览器调试和性能优化

你会用 Playwright 或浏览器工具截图验证 3D 效果。""",
            llm=model,
            verbose=False,
            allow_delegation=False,
        )

    # 4. 3D 资产专家
    model = get_model("implementer")
    if model:
        agents["asset"] = Agent(
            role="3D资产专家",
            goal="处理 Blender 批量转换、GLB 生成、骨骼标准化",
            backstory=f"""你专注于 3D 资产管线，擅长：
- Blender Python (bpy) 脚本自动化
- Mixamo 骨骼重定向到自定义模型
- GLB 格式规范和 Three.js 兼容性
- 批量处理和错误恢复

你熟悉 MixamorigHips 骨骼命名和 Canonical Skeleton 映射。""",
            llm=model,
            verbose=False,
            allow_delegation=False,
        )

    # 5. QA/验证
    model = get_model("qa")
    if model:
        agents["qa"] = Agent(
            role="QA测试员",
            goal="验证修改后的功能正确性，运行测试和截图对比",
            backstory=f"""你专注于软件质量保障，擅长：
- pytest 测试编写和执行
- 浏览器自动化（Playwright）
- 截图对比和视觉回归测试
- 编写清晰的 bug 报告

你的任务是确保：1) 单元测试通过 2) 端到端流程正常 3) 3D 预览与原视频一致。""",
            llm=model,
            verbose=False,
            allow_delegation=False,
        )

    return agents


# ──────────────────────────────────────────
# 工具定义（Agent 可调用的外部能力）
# ──────────────────────────────────────────

@tool("run_tests")
def run_tests(test_path: str = "tests/") -> str:
    """运行 pytest 测试套件，返回测试报告"""
    import subprocess
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", test_path, "-v", "--tb=short"],
            capture_output=True, text=True, timeout=120, cwd=str(Path(__file__).parent)
        )
        return f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"
    except Exception as e:
        return f"测试运行失败: {e}"


@tool("read_project_file")
def read_project_file(filepath: str) -> str:
    """读取项目文件内容，支持相对路径"""
    root = Path(__file__).parent
    full = root / filepath
    if not full.exists():
        return f"文件不存在: {full}"
    try:
        return full.read_text(encoding="utf-8")
    except Exception as e:
        return f"读取失败: {e}"


@tool("list_directory")
def list_directory(dirpath: str = ".") -> str:
    """列出目录内容"""
    root = Path(__file__).parent
    target = root / dirpath
    if not target.exists():
        return f"目录不存在: {target}"
    items = []
    for item in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name)):
        prefix = "[DIR]" if item.is_dir() else "[FILE]"
        items.append(f"{prefix} {item.name}")
    return "\n".join(items)


@tool("write_file")
def write_file(filepath: str, content: str) -> str:
    """写入文件（覆盖）"""
    root = Path(__file__).parent
    full = root / filepath
    try:
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
        return f"已写入: {full}"
    except Exception as e:
        return f"写入失败: {e}"


# ──────────────────────────────────────────
# 任务模板
# ──────────────────────────────────────────

def create_bug_fix_task(task_description: str, agents: Dict[str, Agent]) -> List[Task]:
    """创建 Bug 修复任务流"""

    if "architect" not in agents:
        print("警告: Architect Agent 不可用，跳过分析阶段")
        return []

    task1 = Task(
        description=f"""
        分析以下 bug 的根因，给出详细的修复方案：

        【问题描述】
        {task_description}

        【要求】
        1. 先阅读所有相关文件（通过 read_project_file 工具）
        2. 找出根因（具体到代码行）
        3. 给出修改方案（包含修改的文件列表和每处改动的详细说明）
        4. 说明测试验证方法

        使用以下工具：read_project_file, list_directory
        """,
        expected_output="详细的根因分析报告 + 修复方案（含修改文件列表和具体改动）",
        agent=agents["architect"],
    )

    task2 = Task(
        description=f"""
        根据 Architect 的分析报告，实现修复代码修改：

        【原始问题】
        {task_description}

        【要求】
        1. 按照 Architect 的方案修改代码
        2. 保持代码风格一致
        3. 修改完成后运行测试（通过 run_tests 工具）
        4. 如果测试失败，分析原因并修复

        使用工具：read_project_file, write_file, run_tests
        """,
        expected_output="修改后的代码 + 测试通过报告",
        agent=agents.get("backend", agents.get("architect")),
        context=[task1],
    )

    task3 = Task(
        description=f"""
        验证修复是否完整，检查是否有遗漏：

        【原始问题】
        {task_description}

        【要求】
        1. 检查修改是否覆盖了所有相关文件
        2. 运行完整测试套件
        3. 检查是否引入了新的问题
        4. 输出验证报告

        使用工具：run_tests
        """,
        expected_output="验证报告（通过/失败 + 详细说明）",
        agent=agents.get("qa", agents.get("architect")),
        context=[task2],
    )

    tasks = [task1, task2, task3]

    return tasks


def create_feature_task(feature_description: str, agents: Dict[str, Agent]) -> List[Task]:
    """创建新功能开发任务流"""

    tasks = []

    if "architect" in agents:
        tasks.append(Task(
            description=f"""
            设计新功能的技术方案：

            【需求】
            {feature_description}

            【要求】
            1. 阅读相关现有代码（read_project_file）
            2. 设计实现方案
            3. 确定涉及的文件和模块
            4. 考虑与现有架构的兼容性
            """,
            expected_output="技术方案文档（含文件列表、接口设计、数据流）",
            agent=agents["architect"],
        ))

    # 后端实现
    if "backend" in agents and tasks:
        tasks.append(Task(
            description=f"""
            实现后端代码：

            【需求】
            {feature_description}

            【要求】
            1. 按照 Architect 的方案实现
            2. 添加适当的错误处理
            3. 编写单元测试
            4. 运行测试验证
            """,
            expected_output="后端代码 + 测试",
            agent=agents["backend"],
            context=[tasks[0]],
        ))

    # 前端实现
    if "frontend" in agents and len(tasks) > 0:
        tasks.append(Task(
            description=f"""
            实现前端代码：

            【需求】
            {feature_description}

            【要求】
            1. 实现前端界面和交互
            2. 确保与后端 API 对接
            3. 验证 3D 效果（如有）
            """,
            expected_output="前端代码 + 截图验证",
            agent=agents["frontend"],
            context=[tasks[1]] if len(tasks) > 1 else None,
        ))

    # QA
    if "qa" in agents:
        tasks.append(Task(
            description=f"""
            端到端验证新功能：

            【需求】
            {feature_description}

            【要求】
            1. 运行完整测试
            2. 验证端到端流程
            3. 输出测试报告
            """,
            expected_output="测试报告",
            agent=agents["qa"],
            context=[tasks[-2]] if len(tasks) > 2 else None,
        ))

    return tasks


# ──────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="CrewAI 多 Agent 任务编排")
    parser.add_argument("--task", "-t", required=True, help="任务描述")
    parser.add_argument("--type", choices=["bug", "feature", "refactor", "asset"], default="bug",
                        help="任务类型: bug(修复)|feature(新功能)|refactor(重构)|asset(资产处理)")
    parser.add_argument("--process", choices=["sequential", "parallel", "hierarchical"], default="sequential",
                        help="执行方式")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    parser.add_argument("--output", "-o", default="crew_report.md", help="报告输出文件")
    args = parser.parse_args()

    print("=" * 60)
    print(f"CrewAI 任务启动: {args.type}")
    print(f"描述: {args.task}")
    print("=" * 60)

    # 检查 API Key
    required_keys = ["DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"]
    available = [k for k in required_keys if os.environ.get(k)]
    if not available:
        print("\n错误: 没有可用的 API Key!")
        print("请在 .env 文件中配置至少一个：")
        print("  DEEPSEEK_API_KEY, ANTHROPIC_API_KEY, 或 OPENAI_API_KEY")
        print("\n步骤:")
        print("  1. 复制 .env.example → .env")
        print("  2. 填入你的 API Key")
        print("  3. 重新运行此脚本")
        sys.exit(1)

    print(f"\n可用模型: {', '.join(available)}")

    # 创建 Agent
    agents = create_agents()
    if not agents:
        print("错误: 没有可用的 Agent（请检查 API Key 配置）")
        sys.exit(1)

    print(f"\n已创建 Agent: {', '.join(agents.keys())}")

    # 创建任务
    if args.type == "bug":
        tasks = create_bug_fix_task(args.task, agents)
    elif args.type == "feature":
        tasks = create_feature_task(args.task, agents)
    elif args.type == "refactor":
        tasks = create_bug_fix_task(f"重构: {args.task}", agents)
    elif args.type == "asset":
        # 资产处理任务（简化版）
        if "asset" in agents:
            tasks = [Task(
                description=f"处理 3D 资产: {args.task}",
                expected_output="处理完成的资产文件",
                agent=agents["asset"],
            )]
        else:
            tasks = []
    else:
        tasks = []

    if not tasks:
        print("错误: 无法创建任务")
        sys.exit(1)

    print(f"任务数: {len(tasks)}")
    for i, t in enumerate(tasks, 1):
        print(f"  [{i}] {t.agent.role}: {t.description[:50]}...")

    # 执行 Crew
    crew = Crew(
        agents=list(agents.values()),
        tasks=tasks,
        process=getattr(Process, args.process),
        verbose=args.verbose,
        memory=True,  # 启用记忆，Agent 间共享上下文
    )

    print("\n开始执行...\n")
    result = crew.kickoff()

    # 保存报告
    output_path = Path(__file__).parent / args.output
    output_path.write_text(str(result), encoding="utf-8")
    print(f"\n报告已保存: {output_path}")

    return result


if __name__ == "__main__":
    main()
