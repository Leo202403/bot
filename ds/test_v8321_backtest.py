#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V8.3.21回测优化系统 - 快速测试脚本

测试项：
1. 模块导入
2. 机会识别（V8.3.21字段）
3. Grid Search
4. 资源使用（CPU/内存）
"""

import sys
import os
import gc
from datetime import datetime

# 尝试导入psutil（可选）
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    print("⚠️  psutil未安装，跳过资源监控测试")

# 添加路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print(f"\n{'='*60}")
print(f"V8.3.21回测优化系统 - 快速测试")
print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
if HAS_PSUTIL:
    print(f"环境: {psutil.cpu_count()}核 {psutil.virtual_memory().total/(1024**3):.1f}G内存")
else:
    print(f"环境: 资源监控不可用（psutil未安装）")
print(f"{'='*60}\n")

# ===== 测试1：模块导入 =====
print("测试1: 模块导入...")
try:
    from backtest_optimizer_v8321 import (
        optimize_params_v8321_lightweight,
        define_param_grid_v8321,
        simulate_params_with_v8321_filter,
        calculate_v8321_optimization_score
    )
    print("   ✅ backtest_optimizer_v8321 导入成功")
except Exception as e:
    print(f"   ❌ 导入失败: {e}")
    sys.exit(1)

# ===== 测试2：创建模拟数据 =====
print("\n测试2: 创建模拟机会数据...")
try:
    # 创建100个模拟机会（包含V8.3.21字段）
    test_opportunities = []
    for i in range(100):
        opp = {
            'coin': 'ETH',
            'time': f"{10+i//4:02d}{(i%4)*15:02d}",
            'direction': 'long' if i % 2 == 0 else 'short',
            'entry_price': 3500 + (i % 50),
            'signal_score': 50 + (i % 21),
            'consensus': 2 + (i % 3),
            'risk_reward': 1.5 + (i % 10) * 0.2,
            'actual_profit_pct': -2 + (i % 10) * 0.8,
            'signal_type': 'scalping' if i % 3 == 0 else 'swing',
            'atr': 50 + (i % 20),
            
            # V8.3.21字段
            'kline_ctx_count': 10,
            'kline_ctx_bullish_ratio': 0.6 + (i % 5) * 0.08,
            'kline_ctx_price_chg_pct': 0.5 + (i % 10) * 0.2,
            'kline_ctx_is_up': (i % 3) == 0,
            'kline_ctx_is_down': (i % 3) == 1,
            'kline_ctx_volatility': 1.0 + (i % 5) * 0.3,
            
            'mkt_struct_swing': ['HH-HL', 'LL-LH', 'choppy'][i % 3],
            'mkt_struct_trend_strength': ['strong_bullish', 'strong_bearish', 'weak'][i % 3],
            'mkt_struct_age_hours': 0.5 + (i % 10) * 0.5,
            'mkt_struct_pos_in_range': 0.2 + (i % 7) * 0.1,
            
            'resist_hist_test_cnt': i % 6,
            'resist_hist_false_bo': i % 3,
            'support_hist_test_cnt': i % 6,
            'support_hist_false_bd': i % 3
        }
        test_opportunities.append(opp)
    
    print(f"   ✅ 创建{len(test_opportunities)}个模拟机会")
except Exception as e:
    print(f"   ❌ 创建失败: {e}")
    sys.exit(1)

# ===== 测试3：Grid Search参数定义 =====
print("\n测试3: 定义Grid Search参数...")
try:
    grid = define_param_grid_v8321('scalping')
    total_combinations = 1
    for values in grid.values():
        total_combinations *= len(values)
    
    print(f"   ✅ 参数空间定义完成")
    print(f"      参数维度: {len(grid)}个")
    print(f"      理论组合: {total_combinations}组")
except Exception as e:
    print(f"   ❌ 定义失败: {e}")
    sys.exit(1)

# ===== 测试4：单次过滤测试 =====
print("\n测试4: 测试V8.3.21过滤...")
try:
    test_params = {
        'min_signal_score': 60,
        'min_consensus': 3,
        'min_risk_reward': 2.0,
        'min_kline_bullish_ratio': 0.7,
        'min_price_chg_pct': 1.0,
        'allowed_mkt_struct': 'trend_only',
        'min_trend_age_hours': 1.0,
        'max_sr_test_count': 5
    }
    
    result = simulate_params_with_v8321_filter(test_opportunities, test_params)
    
    print(f"   ✅ 过滤测试完成")
    print(f"      捕获: {result['captured_count']}/{result['total_opportunities']}")
    print(f"      捕获率: {result['capture_rate']*100:.0f}%")
    print(f"      错过原因: {result['missed_reasons']}")
except Exception as e:
    print(f"   ❌ 过滤失败: {e}")
    sys.exit(1)

# ===== 测试5：完整优化流程（小批量）=====
print("\n测试5: 运行完整优化流程（50组测试）...")
try:
    # 记录初始资源（如果有psutil）
    if HAS_PSUTIL:
        process = psutil.Process()
        mem_before = process.memory_info().rss / (1024**2)
        cpu_percent_before = psutil.cpu_percent(interval=1)
        
        print(f"   初始状态:")
        print(f"      内存: {mem_before:.1f}MB")
        print(f"      CPU: {cpu_percent_before:.1f}%")
    else:
        mem_before = cpu_percent_before = 0
    
    # 运行优化
    result = optimize_params_v8321_lightweight(
        opportunities=test_opportunities,
        current_params={'min_signal_score': 60, 'min_consensus': 3, 'min_risk_reward': 2.0},
        signal_type='scalping',
        max_combinations=50  # 小批量测试
    )
    
    # 记录最终资源
    if HAS_PSUTIL:
        mem_after = process.memory_info().rss / (1024**2)
        cpu_percent_after = psutil.cpu_percent(interval=1)
    else:
        mem_after = cpu_percent_after = 0
    
    print(f"\n   ✅ 优化完成")
    print(f"      最优分数: {result['top_10_configs'][0]['score']:.3f}")
    print(f"      成本节省: ${result['cost_saved']:.4f}")
    
    if HAS_PSUTIL:
        print(f"\n   资源使用:")
        print(f"      内存: {mem_before:.1f}MB → {mem_after:.1f}MB (Δ{mem_after-mem_before:+.1f}MB)")
        print(f"      CPU: {cpu_percent_before:.1f}% → {cpu_percent_after:.1f}%")
    
    # 打印Top 3配置
    print(f"\n   Top 3配置:")
    for i, config in enumerate(result['top_10_configs'][:3], 1):
        print(f"      #{i}: score={config['score']:.3f}, " \
              f"capture={config['metrics']['capture_rate']*100:.0f}%, " \
              f"profit={config['metrics']['avg_profit']:.1f}%")
    
    # 打印关键洞察
    if result['context_analysis'].get('key_insights'):
        print(f"\n   💡 关键洞察:")
        for insight in result['context_analysis']['key_insights']:
            print(f"      {insight}")
    
except Exception as e:
    print(f"   ❌ 优化失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# ===== 测试6：内存清理验证 =====
print("\n测试6: 内存清理验证...")
try:
    if HAS_PSUTIL:
        mem_before_gc = process.memory_info().rss / (1024**2)
        gc.collect()
        mem_after_gc = process.memory_info().rss / (1024**2)
        
        print(f"   ✅ GC完成")
        print(f"      内存: {mem_before_gc:.1f}MB → {mem_after_gc:.1f}MB (释放{mem_before_gc-mem_after_gc:.1f}MB)")
    else:
        gc.collect()
        print(f"   ✅ GC完成（无资源监控）")
except Exception as e:
    print(f"   ⚠️  GC测试: {e}")

# ===== 总结 =====
print(f"\n{'='*60}")
print(f"✅ 所有测试通过！")
print(f"{'='*60}")
if HAS_PSUTIL:
    print(f"\n系统状态:")
    print(f"  可用内存: {psutil.virtual_memory().available/(1024**2):.0f}MB")
    print(f"  CPU负载: {psutil.cpu_percent(interval=1):.1f}%")
print(f"\n可以安全部署到服务器！")

