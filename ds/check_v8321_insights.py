#!/usr/bin/env python3
"""
检查v8321_insights是否成功保存到learning_config.json
"""

import json
import os
from datetime import datetime

def check_v8321_insights(model_name: str):
    """检查指定模型的v8321_insights"""
    config_path = f'/root/10-23-bot/ds/trading_data/{model_name}/learning_config.json'
    
    print(f"\n{'='*60}")
    print(f"检查 {model_name.upper()} 的 v8321_insights")
    print(f"{'='*60}")
    
    if not os.path.exists(config_path):
        print(f"❌ 配置文件不存在: {config_path}")
        return False
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # 检查compressed_insights
        if 'compressed_insights' not in config:
            print(f"❌ compressed_insights 不存在")
            return False
        
        print(f"✅ compressed_insights 存在")
        
        # 检查v8321_insights
        v8321_insights = config['compressed_insights'].get('v8321_insights', {})
        
        if not v8321_insights:
            print(f"❌ v8321_insights 不存在或为空")
            return False
        
        print(f"✅ v8321_insights 存在")
        
        # 检查scalping数据
        if 'scalping' in v8321_insights:
            print(f"\n📊 超短线数据:")
            scalping = v8321_insights['scalping']
            
            # 检查performance
            if 'performance' in scalping:
                perf = scalping['performance']
                print(f"  ✅ performance 存在")
                print(f"     - score: {perf.get('score', 'N/A')}")
                print(f"     - capture_rate: {perf.get('capture_rate', 0)*100:.1f}%")
                print(f"     - avg_profit: {perf.get('avg_profit', 0)*100:.2f}%")
                print(f"     - win_rate: {perf.get('win_rate', 0)*100:.1f}%")
            else:
                print(f"  ❌ performance 不存在")
            
            # 检查updated_at
            if 'updated_at' in scalping:
                print(f"  ✅ updated_at: {scalping['updated_at']}")
            else:
                print(f"  ⚠️  updated_at 不存在")
        else:
            print(f"\n❌ scalping 数据不存在")
        
        # 检查swing数据
        if 'swing' in v8321_insights:
            print(f"\n📊 波段数据:")
            swing = v8321_insights['swing']
            
            # 检查performance
            if 'performance' in swing:
                perf = swing['performance']
                print(f"  ✅ performance 存在")
                print(f"     - score: {perf.get('score', 'N/A')}")
                print(f"     - capture_rate: {perf.get('capture_rate', 0)*100:.1f}%")
                print(f"     - avg_profit: {perf.get('avg_profit', 0)*100:.2f}%")
                print(f"     - win_rate: {perf.get('win_rate', 0)*100:.1f}%")
            else:
                print(f"  ❌ performance 不存在")
            
            # 检查updated_at
            if 'updated_at' in swing:
                print(f"  ✅ updated_at: {swing['updated_at']}")
            else:
                print(f"  ⚠️  updated_at 不存在")
        else:
            print(f"\n❌ swing 数据不存在")
        
        return True
        
    except json.JSONDecodeError as e:
        print(f"❌ JSON解析失败: {e}")
        return False
    except Exception as e:
        print(f"❌ 检查失败: {e}")
        return False

def check_atr_in_params(model_name: str):
    """检查learning_config中的atr_tp_multiplier参数"""
    config_path = f'/root/10-23-bot/ds/trading_data/{model_name}/learning_config.json'
    
    print(f"\n{'='*60}")
    print(f"检查 {model_name.upper()} 的 atr_tp_multiplier 参数")
    print(f"{'='*60}")
    
    if not os.path.exists(config_path):
        print(f"❌ 配置文件不存在: {config_path}")
        return False
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # 检查scalping_params
        if 'scalping_params' in config:
            scalping = config['scalping_params']
            print(f"\n⚡ 超短线参数:")
            print(f"  atr_tp_multiplier: {scalping.get('atr_tp_multiplier', 'N/A')}")
            print(f"  atr_stop_multiplier: {scalping.get('atr_stop_multiplier', 'N/A')}")
            print(f"  min_risk_reward: {scalping.get('min_risk_reward', 'N/A')}")
            print(f"  min_signal_score: {scalping.get('min_signal_score', 'N/A')}")
            print(f"  min_indicator_consensus: {scalping.get('min_indicator_consensus', 'N/A')}")
        else:
            print(f"\n❌ scalping_params 不存在")
        
        # 检查swing_params
        if 'swing_params' in config:
            swing = config['swing_params']
            print(f"\n🌊 波段参数:")
            print(f"  atr_tp_multiplier: {swing.get('atr_tp_multiplier', 'N/A')}")
            print(f"  atr_stop_multiplier: {swing.get('atr_stop_multiplier', 'N/A')}")
            print(f"  min_risk_reward: {swing.get('min_risk_reward', 'N/A')}")
            print(f"  min_signal_score: {swing.get('min_signal_score', 'N/A')}")
            print(f"  min_indicator_consensus: {swing.get('min_indicator_consensus', 'N/A')}")
        else:
            print(f"\n❌ swing_params 不存在")
        
        return True
        
    except Exception as e:
        print(f"❌ 检查失败: {e}")
        return False

if __name__ == "__main__":
    print(f"\n🔍 V8.3.21 洞察检查工具")
    print(f"运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 检查Qwen
    qwen_v8321 = check_v8321_insights('qwen')
    qwen_atr = check_atr_in_params('qwen')
    
    # 检查DeepSeek
    deepseek_v8321 = check_v8321_insights('deepseek')
    deepseek_atr = check_atr_in_params('deepseek')
    
    # 总结
    print(f"\n{'='*60}")
    print(f"检查总结")
    print(f"{'='*60}")
    print(f"Qwen:")
    print(f"  v8321_insights: {'✅ 正常' if qwen_v8321 else '❌ 异常'}")
    print(f"  atr参数: {'✅ 正常' if qwen_atr else '❌ 异常'}")
    print(f"\nDeepSeek:")
    print(f"  v8321_insights: {'✅ 正常' if deepseek_v8321 else '❌ 异常'}")
    print(f"  atr参数: {'✅ 正常' if deepseek_atr else '❌ 异常'}")
    
    print(f"\n{'='*60}")
    print(f"📝 说明:")
    print(f"{'='*60}")
    print(f"1. v8321_insights: 优化器保存的性能数据，用于Bark推送")
    print(f"2. atr参数: learning_config中的实际参数配置")
    print(f"3. 如果v8321_insights不存在，Bark推送会使用历史统计数据")
    print(f"4. V8.5.1修复后，即使v8321_insights不存在，也会使用优化函数返回值")

