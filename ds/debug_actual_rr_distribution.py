#!/usr/bin/env python3
"""
调试脚本：检查actual_risk_reward的实际分布
"""
import sys
sys.path.insert(0, '/root/10-23-bot/ds')

from calculate_actual_profit import simulate_trade_execution
import numpy as np

# 测试数据
test_cases = [
    {
        'name': '默认参数（tp=2.0, sl=1.5）',
        'opp': {
            'entry_price': 100.0,
            'direction': 'long',
            'atr': 2.0,
            'future_data': {
                'max_high': 105.0,
                'min_low': 98.0,
                'final_close': 103.0,
                'data_points': 96
            }
        },
        'tp_multiplier': 2.0,
        'sl_multiplier': 1.5
    },
    {
        'name': '高TP参数（tp=3.0, sl=1.0）',
        'opp': {
            'entry_price': 100.0,
            'direction': 'long',
            'atr': 2.0,
            'future_data': {
                'max_high': 105.0,
                'min_low': 98.0,
                'final_close': 103.0,
                'data_points': 96
            }
        },
        'tp_multiplier': 3.0,
        'sl_multiplier': 1.0
    },
    {
        'name': '低TP参数（tp=1.5, sl=1.0）',
        'opp': {
            'entry_price': 100.0,
            'direction': 'long',
            'atr': 2.0,
            'future_data': {
                'max_high': 105.0,
                'min_low': 98.0,
                'final_close': 103.0,
                'data_points': 96
            }
        },
        'tp_multiplier': 1.5,
        'sl_multiplier': 1.0
    }
]

print("=" * 80)
print("actual_risk_reward 分布测试")
print("=" * 80)

for test in test_cases:
    result = simulate_trade_execution(
        opp=test['opp'],
        future_data_summary=test['opp']['future_data'],
        tp_multiplier=test['tp_multiplier'],
        sl_multiplier=test['sl_multiplier']
    )
    
    print(f"\n{test['name']}:")
    print(f"  TP倍数: {test['tp_multiplier']}, SL倍数: {test['sl_multiplier']}")
    print(f"  理论R:R: {test['tp_multiplier'] / test['sl_multiplier']:.2f}")
    print(f"  actual_risk_reward: {result.get('actual_risk_reward', 'N/A'):.2f}")
    print(f"  actual_profit_pct: {result.get('actual_profit_pct', 'N/A'):.2f}%")
    print(f"  exit_reason: {result.get('exit_reason', 'N/A')}")
    print(f"  TP价格: {result.get('tp_price', 'N/A'):.2f}")
    print(f"  SL价格: {result.get('sl_price', 'N/A'):.2f}")

print("\n" + "=" * 80)
print("结论：")
print("  如果actual_risk_reward与理论R:R一致，说明计算正确")
print("  如果不一致，说明计算逻辑有问题")
print("=" * 80)

