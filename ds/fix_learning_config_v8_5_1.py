#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V8.5.1 修复 learning_config.json 参数

修复内容：
1. 确保 atr_tp_multiplier 和 atr_stop_multiplier 正确设置
2. 调整过滤参数（min_indicator_consensus, min_signal_score, min_risk_reward）
3. 提高动态ATR上限（在 calculate_actual_profit.py 中）
"""

import json
import os
from datetime import datetime

def fix_learning_config(model_name: str):
    """
    修复指定模型的 learning_config.json
    
    Args:
        model_name: 'qwen' 或 'deepseek'
    """
    config_path = f'/root/10-23-bot/ds/trading_data/{model_name}/learning_config.json'
    backup_path = f'/root/10-23-bot/ds/trading_data/{model_name}/learning_config_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
    
    print(f"\n{'='*60}")
    print(f"修复 {model_name.upper()} 的 learning_config.json")
    print(f"{'='*60}\n")
    
    # 检查文件是否存在
    if not os.path.exists(config_path):
        print(f"❌ 文件不存在: {config_path}")
        return False
    
    # 读取配置
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        print(f"✓ 成功读取配置文件")
    except Exception as e:
        print(f"❌ 读取配置失败: {e}")
        return False
    
    # 备份原配置
    try:
        with open(backup_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        print(f"✓ 已备份到: {backup_path}")
    except Exception as e:
        print(f"⚠️  备份失败: {e}")
    
    # 修复 scalping_params
    print(f"\n📊 修复 scalping_params...")
    
    if 'scalping_params' not in config:
        config['scalping_params'] = {}
    
    old_scalping = config['scalping_params'].copy()
    
    # 设置正确的参数
    config['scalping_params'].update({
        'atr_tp_multiplier': 2.5,          # V8.4.6优化后的值
        'atr_stop_multiplier': 1.5,        # 标准值
        'min_signal_score': 60,            # 降低门槛
        'min_indicator_consensus': 1,      # 降低门槛（从2改为1）
        'min_risk_reward': 1.5,            # 合理值
        'max_holding_hours': 12,           # 超短线最大持仓时间
        'min_consensus_score': 1,          # V8.4新增
    })
    
    print(f"   修改前: {old_scalping}")
    print(f"   修改后: {config['scalping_params']}")
    
    # 修复 swing_params
    print(f"\n📊 修复 swing_params...")
    
    if 'swing_params' not in config:
        config['swing_params'] = {}
    
    old_swing = config['swing_params'].copy()
    
    # 设置正确的参数
    config['swing_params'].update({
        'atr_tp_multiplier': 4.0,          # V8.4.6优化后的值
        'atr_stop_multiplier': 1.5,        # 标准值
        'min_signal_score': 60,            # 降低门槛（从70改为60）
        'min_indicator_consensus': 1,      # 降低门槛（从2改为1）
        'min_risk_reward': 2.0,            # 降低门槛（从3.0改为2.0）
        'max_holding_hours': 72,           # 波段最大持仓时间
        'min_consensus_score': 1,          # V8.4新增
    })
    
    print(f"   修改前: {old_swing}")
    print(f"   修改后: {config['swing_params']}")
    
    # 更新 last_update 时间
    config['last_update'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 保存配置
    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        print(f"\n✅ 配置已保存: {config_path}")
        return True
    except Exception as e:
        print(f"\n❌ 保存配置失败: {e}")
        return False


def main():
    """主函数"""
    print("\n" + "="*60)
    print("V8.5.1 修复 learning_config.json 参数")
    print("="*60)
    
    # 修复两个模型的配置
    models = ['qwen', 'deepseek']
    results = {}
    
    for model in models:
        results[model] = fix_learning_config(model)
    
    # 总结
    print("\n" + "="*60)
    print("修复总结")
    print("="*60)
    
    for model, success in results.items():
        status = "✅ 成功" if success else "❌ 失败"
        print(f"{model.upper()}: {status}")
    
    if all(results.values()):
        print("\n✅ 所有配置修复完成！")
        print("\n📝 修复内容：")
        print("   1. scalping_params:")
        print("      - atr_tp_multiplier: 2.5")
        print("      - atr_stop_multiplier: 1.5")
        print("      - min_signal_score: 60")
        print("      - min_indicator_consensus: 1")
        print("      - min_risk_reward: 1.5")
        print("      - max_holding_hours: 12")
        print("\n   2. swing_params:")
        print("      - atr_tp_multiplier: 4.0")
        print("      - atr_stop_multiplier: 1.5")
        print("      - min_signal_score: 60")
        print("      - min_indicator_consensus: 1")
        print("      - min_risk_reward: 2.0")
        print("      - max_holding_hours: 72")
        print("\n🚀 下一步：")
        print("   1. 重启服务: bash ~/快速重启_修复版.sh backtest")
        print("   2. 观察捕获率是否提升到80-100%")
        print("   3. 观察总利润是否保持在5-6%以上")
    else:
        print("\n⚠️  部分配置修复失败，请检查错误信息")
    
    print("\n" + "="*60)


if __name__ == '__main__':
    main()

