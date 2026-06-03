# 使用 Conda 安装向量检索依赖（解决 Windows DLL 阻止问题）

## 步骤 1：安装 Miniconda（如果还没有）
下载地址：https://docs.conda.io/en/latest/miniconda.html

## 步骤 2：创建新环境
```powershell
conda create -n npc-live python=3.11
conda activate npc-live
```

## 步骤 3：安装所有依赖
```powershell
pip install sentence-transformers transformers torch scikit-learn
```

## 步骤 4：使用 conda 环境运行服务器
```powershell
conda activate npc-live
cd "D:\新建文件夹 (2)"
python server.py
```

## 优点
- Conda 包经过预编译，Windows 兼容性好
- 避免 Windows Defender 阻止 DLL
- 环境隔离，不影响其他项目
