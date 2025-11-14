#!/usr/bin/env python3
"""
🔧 优化器修复脚本

修复内容：
1. 降低共振阈值（从2改为1）
2. 添加平均利润验证（拒绝负利润参数）
3. 修改评分函数权重（更重视实际盈利）

使用方法：
python3 apply_optimizer_fixes.py
"""

import json
import os
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
DS_DIR = PROJECT_ROOT / "ds"

def fix_learning_config(model_name: str):
    """修复learning_config.json中的共振阈值"""
    config_path = DS_DIR / "trading_data" / model_name / "learning_config.json"
    
    if not config_path.exists():
        print(f"⚠️ {model_name}: learning_config.json 不存在，跳过")
        return
    
    # 读取配置
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    # 备份
    backup_path = config_path.with_suffix('.json.backup')
    with open(backup_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    print(f"✓ {model_name}: 已备份到 {backup_path.name}")
    
    # 修改参数
    modified = False
    
    # 修改scalping参数
    if 'scalping' in config:
        old_consensus = config['scalping'].get('min_consensus', 2)
        if old_consensus >= 2:
            config['scalping']['min_consensus'] = 1
            config['scalping']['min_signal_score'] = max(70, config['scalping'].get('min_signal_score', 60))
            print(f"✓ {model_name}: scalping min_consensus {old_consensus} → 1")
            modified = True
    
    # 修改swing参数
    if 'swing' in config:
        old_consensus = config['swing'].get('min_consensus', 2)
        if old_consensus >= 2:
            config['swing']['min_consensus'] = 1
            config['swing']['min_signal_score'] = max(70, config['swing'].get('min_signal_score', 60))
            print(f"✓ {model_name}: swing min_consensus {old_consensus} → 1")
            modified = True
    
    # 保存修改
    if modified:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        print(f"✅ {model_name}: learning_config.json 已更新")
    else:
        print(f"ℹ️ {model_name}: 无需修改")

def add_profit_validation_to_optimizer():
    """在backtest_optimizer_v8321.py中添加利润验证"""
    optimizer_path = DS_DIR / "backtest_optimizer_v8321.py"
    
    if not optimizer_path.exists():
        print("⚠️ backtest_optimizer_v8321.py 不存在")
        return
    
    # 读取文件
    with open(optimizer_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 检查是否已经添加过验证
    if "# 【修复】硬性约束：平均利润必须为正" in content:
        print("ℹ️ backtest_optimizer_v8321.py 已包含利润验证，跳过")
        return
    
    # 备份
    backup_path = optimizer_path.with_suffix('.py.backup')
    with open(backup_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"✓ 已备份到 {backup_path.name}")
    
    # 在calculate_v8321_optimization_score函数开头添加验证
    old_code = """def calculate_v8321_optimization_score(result: Dict) -> float:
    \"\"\"
    【V8.3.21利润最大化+风控】评分函数
    
    核心目标：利润最大 + 亏损最小
    
    关键指标：
    1. 期望收益 = (胜率 × 平均盈利) + (败率 × 平均亏损)
       - 综合考虑盈利和亏损
    2. 盈亏比 = 平均盈利 / |平均亏损|
       - 赚的时候赚多少 vs 亏的时候亏多少
    3. 最大回撤
       - 连续亏损的最大幅度（风险指标）
    4. 捕获率
       - 确保不过度保守
    
    权重设计（对齐"利润最大+亏损最小"）：
    - 期望收益: 40%（核心，已包含盈亏）
    - 盈亏比: 30%（赚多亏少）
    - 捕获率: 20%（不过度保守）
    - 回撤惩罚: -10%（控制风险）
    
    示例：
    - 配置A: 3%期望 + 2.0盈亏比 + 50%捕获 - 5%回撤 = 高分
    - 配置B: 3%期望 + 1.2盈亏比 + 50%捕获 - 8%回撤 = 低分（亏损大）
    \"\"\"
    if result['captured_count'] == 0:
        return 0.0"""
    
    new_code = """def calculate_v8321_optimization_score(result: Dict) -> float:
    \"\"\"
    【V8.3.21利润最大化+风控】评分函数
    
    核心目标：利润最大 + 亏损最小
    
    关键指标：
    1. 期望收益 = (胜率 × 平均盈利) + (败率 × 平均亏损)
       - 综合考虑盈利和亏损
    2. 盈亏比 = 平均盈利 / |平均亏损|
       - 赚的时候赚多少 vs 亏的时候亏多少
    3. 最大回撤
       - 连续亏损的最大幅度（风险指标）
    4. 捕获率
       - 确保不过度保守
    
    权重设计（对齐"利润最大+亏损最小"）：
    - 期望收益: 50%（核心，已包含盈亏）【从40%提升到50%】
    - 盈亏比: 25%（赚多亏少）【从30%降到25%】
    - 捕获率: 15%（不过度保守）【从20%降到15%】
    - 回撤惩罚: -10%（控制风险）
    
    示例：
    - 配置A: 3%期望 + 2.0盈亏比 + 50%捕获 - 5%回撤 = 高分
    - 配置B: 3%期望 + 1.2盈亏比 + 50%捕获 - 8%回撤 = 低分（亏损大）
    \"\"\"
    if result['captured_count'] == 0:
        return 0.0
    
    # 【修复】硬性约束：平均利润必须为正
    avg_profit = result.get('avg_profit', 0)
    if avg_profit <= 0:
        return 0.0  # 直接淘汰负利润配置
    
    # 【修复】硬性约束：期望收益必须为正
    expectancy = result.get('expectancy', 0)
    if expectancy <= 0:
        return 0.0  # 直接淘汰负期望配置"""
    
    # 替换
    if old_code in content:
        content = content.replace(old_code, new_code)
        
        # 修改权重
        content = content.replace(
            "expectancy_score * 0.40 +      # 期望收益 40%\n        plr_score * 0.30 +              # 盈亏比 30%\n        capture_score * 0.20 +          # 捕获率 20%",
            "expectancy_score * 0.50 +      # 期望收益 50%（提升）\n        plr_score * 0.25 +              # 盈亏比 25%\n        capture_score * 0.15 +          # 捕获率 15%（降低）"
        )
        
        # 保存
        with open(optimizer_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print("✅ backtest_optimizer_v8321.py 已添加利润验证")
    else:
        print("⚠️ 未找到目标代码，可能文件已被修改")

def main():
    print("=" * 60)
    print("🔧 开始修复优化器")
    print("=" * 60)
    print()
    
    # 1. 修复learning_config.json
    print("【步骤1】修复learning_config.json中的共振阈值")
    print("-" * 60)
    fix_learning_config("qwen")
    fix_learning_config("deepseek")
    print()
    
    # 2. 修改优化器代码
    print("【步骤2】添加利润验证到优化器")
    print("-" * 60)
    add_profit_validation_to_optimizer()
    print()
    
    print("=" * 60)
    print("✅ 修复完成！")
    print("=" * 60)
    print()
    print("📝 下一步：")
    print("1. 提交代码：git add -A && git commit -m '🔧 修复优化器'")
    print("2. 推送到服务器：git push")
    print("3. 在服务器上：cd ~/10-23-bot && git pull")
    print("4. 重新运行回测：bash ~/快速重启_修复版.sh backtest")
    print()

if __name__ == "__main__":
    main()

