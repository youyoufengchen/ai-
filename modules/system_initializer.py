"""
system_initializer.py
系统初始化管理模块
负责：目录结构创建、文件恢复、系统健康检查
"""

import os
import json
import shutil
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import hashlib


class SystemInitializer:
    """系统初始化管理器"""
    
    # 必需的基础动作文件清单
    REQUIRED_ACTIONS = [
        "基础姿态/直立站立/版本01_标准.glb",
        "移动动作/走路/正常走路/版本01_标准.glb",
        "移动动作/走路/正常走路/版本02_活泼.glb",
        "移动动作/跑步/正常跑步/版本01_标准.glb",
        "交互动作/抓取动作/单手抓取/版本01_标准.glb",
        "交互动作/抓取动作/双手抓取/版本01_标准.glb",
        "交互动作/展示动作/平摊展示/版本01_标准.glb",
    ]
    
    # 中文目录结构定义
    DIRECTORY_STRUCTURE = {
        "基础姿态": ["直立站立", "蹲下", "坐姿", "躺下"],
        "移动动作": {
            "走路": ["慢走", "正常走路", "快走", "踮脚走"],
            "跑步": ["慢跑", "正常跑步", "快跑", "冲刺"],
            "特殊移动": ["飞行", "瞬移", "滑行", "跳跃"]
        },
        "交互动作": {
            "取物动作": ["取高处", "取中间", "取低处", "弯腰取"],
            "抓取动作": ["单手抓取", "双手抓取", "球形抓取", "捏取"],
            "展示动作": [],
            "递接动作": ["递给顾客", "接过物品", "放下物品"]
        },
        "讲解手势": {
            "指向动作": [],
            "计数手势": [],
            "比划大小": [],
            "强调手势": []
        },
        "情绪反应": {
            "正面情绪": [],
            "负面情绪": [],
            "中性反应": []
        },
        "视线控制": []
    }
    
    def __init__(self, base_path: str = None):
        self.base_path = Path(base_path) if base_path else Path(__file__).parent.parent
        self.action_root = self.base_path / "assets" / "动作库"
        self.backup_dir = self.base_path / "system_backup" / "动作库"
        self.manifest_path = self.action_root / "action_manifest.json"
        
        # 系统健康状态
        self.health_status = {
            "directories_ok": False,
            "required_files_ok": False,
            "manifest_ok": False,
            "total_actions": 0,
            "total_variants": 0,
            "missing_files": [],
            "invalid_files": []
        }
    
    def initialize(self, mode: str = "full") -> Dict:
        """
        执行系统初始化
        
        Args:
            mode: 初始化模式 ("full"完整, "quick"快速扫描, "repair"仅修复)
        
        Returns:
            初始化结果
        """
        print(f"🔧 开始系统初始化 [模式: {mode}]")
        
        results = {
            "status": "ok",
            "mode": mode,
            "steps": []
        }
        
        try:
            if mode in ["full", "repair"]:
                # 1. 创建目录结构
                step1 = self._create_directory_structure()
                results["steps"].append({"name": "创建目录结构", "result": step1})
                
                # 2. 恢复必需文件
                step2 = self._restore_required_files()
                results["steps"].append({"name": "恢复必需文件", "result": step2})
            
            if mode in ["full", "quick"]:
                # 3. 扫描动作文件
                step3 = self._scan_actions()
                results["steps"].append({"name": "扫描动作文件", "result": step3})
                
                # 4. 验证系统健康
                step4 = self._validate_system()
                results["steps"].append({"name": "验证系统健康", "result": step4})
            
            # 更新健康状态
            self._update_health_status()
            
            print(f"✅ 初始化完成")
            print(f"   - 动作总数: {self.health_status['total_actions']}")
            print(f"   - 变体总数: {self.health_status['total_variants']}")
            
        except Exception as e:
            results["status"] = "error"
            results["error"] = str(e)
            print(f"❌ 初始化失败: {e}")
        
        return results
    
    def _create_directory_structure(self) -> Dict:
        """创建中文目录结构"""
        created = []
        errors = []
        
        def create_recursive(structure, parent_path):
            for name, content in structure.items():
                current_path = parent_path / name
                
                try:
                    current_path.mkdir(parents=True, exist_ok=True)
                    created.append(str(current_path.relative_to(self.base_path)))
                    
                    # 创建说明文件
                    readme = current_path / "说明.txt"
                    if not readme.exists():
                        readme.write_text(f"# {name}\n\n请在此文件夹放置对应的动作文件\n命名格式: 版本XX_描述.glb\n", encoding="utf-8")
                    
                    # 递归创建子目录
                    if isinstance(content, dict):
                        create_recursive(content, current_path)
                    elif isinstance(content, list):
                        for subdir in content:
                            sub_path = current_path / subdir
                            sub_path.mkdir(parents=True, exist_ok=True)
                            created.append(str(sub_path.relative_to(self.base_path)))
                            
                            # 子目录说明文件
                            sub_readme = sub_path / "说明.txt"
                            if not sub_readme.exists():
                                sub_readme.write_text(f"# {subdir}\n\n放置{subdir}的动作文件\n", encoding="utf-8")
                
                except Exception as e:
                    errors.append(f"{current_path}: {e}")
        
        # 开始创建
        create_recursive(self.DIRECTORY_STRUCTURE, self.action_root)
        
        return {
            "created_count": len(created),
            "error_count": len(errors),
            "errors": errors[:5]  # 只返回前5个错误
        }
    
    def _restore_required_files(self) -> Dict:
        """从备份恢复必需文件"""
        restored = []
        missing = []
        
        for required_file in self.REQUIRED_ACTIONS:
            target_path = self.action_root / required_file
            
            if target_path.exists():
                continue  # 文件已存在，跳过
            
            # 从备份恢复
            backup_path = self.backup_dir / required_file
            if backup_path.exists():
                try:
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(backup_path, target_path)
                    restored.append(required_file)
                    print(f"  ♻️  恢复文件: {required_file}")
                except Exception as e:
                    missing.append(f"{required_file}: 复制失败 ({e})")
            else:
                missing.append(required_file)
        
        return {
            "restored_count": len(restored),
            "missing_count": len(missing),
            "restored_files": restored,
            "missing_files": missing[:10]
        }
    
    def _scan_actions(self) -> Dict:
        """扫描动作文件并生成清单（每次全量重建）"""
        manifest = {
            "version": "1.0",
            "last_scan": None,
            "actions": {},
            "stats": {}
        }
        
        scanned = 0
        errors = []
        
        # 扫描所有.glb文件
        glb_files = list(self.action_root.rglob("*.glb"))
        print(f"[Scan] Found {len(glb_files)} .glb files")
        
        for glb_file in glb_files:
            try:
                relative_path = glb_file.relative_to(self.action_root)
                path_parts = relative_path.parts
                
                # 解析路径
                # 格式: 动作分类/子分类/动作名/版本_描述.glb
                if len(path_parts) >= 3:
                    category = path_parts[0]
                    subcategory = path_parts[1] if len(path_parts) > 3 else ""
                    action_name = path_parts[-2] if len(path_parts) > 2 else path_parts[0]
                    filename = path_parts[-1]
                    
                    # 解析文件名：支持任意文件名
                    import re
                    stem = glb_file.stem  # 不含后缀的文件名
                    
                    # 尝试解析 "版本XX_描述" 格式
                    variant_match = re.match(r"版本(\d+)_(.+)", stem)
                    if variant_match:
                        variant_id = stem
                        description = variant_match.group(2)
                    else:
                        # 英文或其他文件名，直接使用
                        variant_id = stem
                        description = stem
                    
                    # 生成动作ID
                    action_id = self._generate_action_id(category, subcategory, action_name)
                    
                    if action_id not in manifest["actions"]:
                        manifest["actions"][action_id] = {
                            "display_name": action_name,
                            "category": "/".join(path_parts[:-1]),
                            "variants": []
                        }
                    
                    # 检查是否已存在（避免重复添加）
                    existing_paths = [v["file_path"] for v in manifest["actions"][action_id]["variants"]]
                    file_path_str = str(relative_path).replace("\\", "/")
                    
                    if file_path_str not in existing_paths:
                        manifest["actions"][action_id]["variants"].append({
                            "id": variant_id,
                            "file_path": file_path_str,
                            "description": description,
                            "path": file_path_str
                        })
                    
                    scanned += 1
            
            except Exception as e:
                errors.append(f"{glb_file}: {e}")
        
        # 保存清单（合并新旧数据）
        manifest["last_scan"] = self._get_timestamp()
        
        # 统计总数
        total_variants = sum(len(a.get("variants", [])) for a in manifest["actions"].values())
        manifest["stats"] = {
            "total_actions": len(manifest["actions"]),
            "total_variants": total_variants
        }
        
        try:
            with open(self.manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
            print(f"[Scan] Saved manifest: {len(manifest['actions'])} actions, {total_variants} variants")
        except Exception as e:
            errors.append(f"保存清单失败: {e}")
        
        return {
            "scanned_count": scanned,
            "actions_count": len(manifest["actions"]),
            "error_count": len(errors),
            "errors": errors[:5]
        }
    
    def _validate_system(self) -> Dict:
        """验证系统健康状态"""
        valid = 0
        invalid = []
        
        # 加载清单
        if not self.manifest_path.exists():
            return {"status": "error", "message": "清单文件不存在"}
        
        try:
            with open(self.manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception as e:
            return {"status": "error", "message": f"清单文件解析失败: {e}"}
        
        # 验证每个动作文件
        for action_id, action_data in manifest.get("actions", {}).items():
            for variant in action_data.get("variants", []):
                file_path = self.action_root / variant["file_path"]
                
                if not file_path.exists():
                    invalid.append(f"{variant['file_path']}: 文件不存在")
                    continue
                
                # 检查文件大小（至少1KB）
                if file_path.stat().st_size < 1024:
                    invalid.append(f"{variant['file_path']}: 文件过小")
                    continue
                
                valid += 1
        
        return {
            "status": "ok" if not invalid else "warning",
            "valid_count": valid,
            "invalid_count": len(invalid),
            "invalid_files": invalid[:10]
        }
    
    def _update_health_status(self):
        """更新系统健康状态"""
        # 检查目录
        self.health_status["directories_ok"] = self.action_root.exists()
        
        # 检查必需文件
        missing_required = []
        for req in self.REQUIRED_ACTIONS:
            if not (self.action_root / req).exists():
                missing_required.append(req)
        self.health_status["required_files_ok"] = len(missing_required) == 0
        self.health_status["missing_files"] = missing_required
        
        # 检查清单
        self.health_status["manifest_ok"] = self.manifest_path.exists()
        
        # 统计
        if self.manifest_path.exists():
            try:
                with open(self.manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                self.health_status["total_actions"] = len(manifest.get("actions", {}))
                self.health_status["total_variants"] = sum(
                    len(a.get("variants", [])) 
                    for a in manifest.get("actions", {}).values()
                )
            except:
                pass
    
    def _generate_action_id(self, category: str, subcategory: str, action_name: str) -> str:
        """生成动作ID"""
        # 将中文转换为拼音或英文标识
        # 简化版本：直接使用路径
        parts = [p for p in [category, subcategory, action_name] if p]
        
        # 映射表
        mapping = {
            "走路": "walk",
            "跑步": "run",
            "抓取": "grab",
            "展示": "present",
            "直立站立": "idle_stand",
            "正常走路": "walk_normal",
            "正常跑步": "run_normal",
        }
        
        # 尝试映射，否则使用原名
        id_parts = []
        for part in parts:
            if part in mapping:
                id_parts.append(mapping[part])
            else:
                # 保留中文（或未来转换为拼音）
                id_parts.append(part)
        
        return "_".join(id_parts)
    
    def _get_timestamp(self) -> str:
        """获取当前时间戳"""
        from datetime import datetime
        return datetime.now().isoformat()
    
    def get_health_status(self) -> Dict:
        """获取系统健康状态"""
        self._update_health_status()
        return self.health_status
    
    def quick_rescan(self) -> Dict:
        """快速重新扫描"""
        return self._scan_actions()
    
    def repair_missing_files(self) -> Dict:
        """修复缺失的必需文件"""
        return self._restore_required_files()


# 全局实例
initializer = SystemInitializer()

def initialize_system(mode: str = "full") -> Dict:
    """对外接口：执行系统初始化"""
    return initializer.initialize(mode)

def get_system_health() -> Dict:
    """对外接口：获取系统健康状态"""
    return initializer.get_health_status()

def quick_rescan() -> Dict:
    """对外接口：快速重新扫描"""
    return initializer.quick_rescan()
