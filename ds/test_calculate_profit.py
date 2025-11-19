#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试calculate_actual_profit的计算逻辑
模拟回测中的场景
"""

# 模拟一个opportunity
opportunity = {
    'coin': 'BTC',
    'entry_price': 100.0,
    'direction': 'long',
    'atr': 1.2,  # 1.2%
    'objective_profit': 36.0,  # 最大利润36%
    'future_data': {
        'max_high': 136.0,  # 最高涨到136（+36%）
        'min_low': 95.0,     # 最低跌到95（-5%）
        'final_close': 110.0,  # 最终110（+10%）
        'data_points': 96
    },
    'signal_score': 85
}

# 模拟strategy_params（使用最优TP/SL）
strategy_params = {
    'atr_tp_multiplier': 30.0,  # TP = 30倍ATR
    'atr_stop_multiplier': 1.5,  # SL = 1.5倍ATR
    'max_holding_hours': 24
}

print("="*60)
print("测试场景：")
print(f"  Entry: {opportunity['entry_price']}")
print(f"  Direction: {opportunity['direction']}")
print(f"  ATR: {opportunity['atr']}%")
print(f"  Max High: {opportunity['future_data']['max_high']} (+{(opportunity['future_data']['max_high'] - opportunity['entry_price'])/opportunity['entry_price']*100:.2f}%)")
print(f"  Min Low: {opportunity['future_data']['min_low']} ({(opportunity['future_data']['min_low'] - opportunity['entry_price'])/opportunity['entry_price']*100:.2f}%)")
print(f"  TP Multiplier: {strategy_params['atr_tp_multiplier']}")
print(f"  SL Multiplier: {strategy_params['atr_stop_multiplier']}")
print("="*60)

# 引入calculate_single_actual_profit
import sys
sys.path.append('/Users/mac-bauyu/Downloads/10-23-bot/ds')
from calculate_actual_profit import calculate_single_actual_profit

# 测试1：use_dynamic_atr=False（和参数组合测试一样）
print("\n【测试1】use_dynamic_atr=False")
profit1 = calculate_single_actual_profit(
    opportunity,
    strategy_params=strategy_params,
    use_dynamic_atr=False,
    include_trading_costs=True
)
print(f"结果: {profit1:.2f}%")

# 测试2：use_dynamic_atr=True
print("\n【测试2】use_dynamic_atr=True")
profit2 = calculate_single_actual_profit(
    opportunity,
    strategy_params=strategy_params,
    use_dynamic_atr=True,
    include_trading_costs=True
)
print(f"结果: {profit2:.2f}%")

# 测试3：无future_data（模拟数据缺失）
print("\n【测试3】无future_data（数据缺失）")
opp_no_data = opportunity.copy()
opp_no_data['future_data'] = {}
profit3 = calculate_single_actual_profit(
    opp_no_data,
    strategy_params=strategy_params,
    use_dynamic_atr=False,
    include_trading_costs=True
)
print(f"结果: {profit3:.2f}%")

print("\n" + "="*60)
print("结论：")
if profit1 > 0:
    print("✅ calculate_actual_profit工作正常")
else:
    print("❌ calculate_actual_profit返回0，需要调试")

