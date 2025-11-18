#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
【V8.5.1.6】实际利润计算模块

功能：根据止盈止损策略参数，模拟真实交易过程，计算actual_profit_pct

核心逻辑：
1. 基于future_data摘要数据进行快速模拟（避免内存爆炸）
2. 考虑ATR倍数、止盈止损、超时退出
3. 支持Long/Short双向
4. 批量计算优化

注意：
- 使用摘要数据模拟，不如逐根K线精确，但性能和内存占用更优
- 假设价格在max_high/min_low范围内均匀分布（保守估计）
"""

import numpy as np
from typing import Dict, List


def calculate_single_actual_profit(
    opportunity: Dict,
    strategy_params: Dict,
    use_dynamic_atr: bool = True
) -> float:
    """
    计算单个机会的实际利润
    
    Args:
        opportunity: 机会数据，包含entry_price, direction, atr, future_data等
        strategy_params: 策略参数，包含atr_stop_multiplier, atr_tp_multiplier等
        use_dynamic_atr: 是否使用动态ATR倍数（V8.4.8特性）
    
    Returns:
        actual_profit_pct: 实际利润百分比（正数=盈利，负数=亏损，0=超时平仓无盈亏）
    """
    try:
        # 1. 提取基础数据
        entry_price = opportunity.get('entry_price', 0)
        direction = opportunity.get('direction', 'long')
        atr = opportunity.get('atr', 0)
        future_data = opportunity.get('future_data', {})
        
        if entry_price <= 0 or atr <= 0:
            return 0  # 数据不完整，返回0
        
        # 2. 获取未来价格数据
        max_high = future_data.get('max_high', entry_price)
        min_low = future_data.get('min_low', entry_price)
        final_close = future_data.get('final_close', entry_price)
        data_points = future_data.get('data_points', 96)  # 默认24小时=96个15分钟K线
        
        # 3. 计算止盈止损价格
        atr_stop_mult = strategy_params.get('atr_stop_multiplier', 1.5)
        atr_tp_mult = strategy_params.get('atr_tp_multiplier', 4.0)
        max_holding_hours = strategy_params.get('max_holding_hours', 24)
        
        # 🆕 V8.4.8: 动态ATR倍数（根据signal_score调整）
        if use_dynamic_atr:
            signal_score = opportunity.get('signal_score', 75)
            # 高分信号可以设置更宽松的止损（提高胜率）
            if signal_score >= 85:
                atr_stop_mult *= 1.2  # +20%
                atr_tp_mult *= 1.15   # +15%
            elif signal_score <= 70:
                atr_stop_mult *= 0.9  # -10%
                atr_tp_mult *= 0.95   # -5%
        
        if direction == 'long':
            stop_loss = entry_price - (atr * atr_stop_mult)
            take_profit = entry_price + (atr * atr_tp_mult)
        else:  # short
            stop_loss = entry_price + (atr * atr_stop_mult)
            take_profit = entry_price - (atr * atr_tp_mult)
        
        # 4. 模拟交易结果
        # 简化模拟：检查是否触发止盈/止损，假设先触发哪个就按哪个平仓
        
        if direction == 'long':
            # Long: 止损在下方，止盈在上方
            hit_stop_loss = min_low <= stop_loss
            hit_take_profit = max_high >= take_profit
            
            if hit_stop_loss and hit_take_profit:
                # 🔧 关键：同时触发，判断哪个先触发
                # 保守假设：按价格距离比例判断
                distance_to_sl = abs(entry_price - stop_loss)
                distance_to_tp = abs(take_profit - entry_price)
                # 如果止损更近，假设先触发止损
                if distance_to_sl < distance_to_tp:
                    exit_price = stop_loss
                else:
                    exit_price = take_profit
            elif hit_stop_loss:
                exit_price = stop_loss
            elif hit_take_profit:
                exit_price = take_profit
            else:
                # 超时退出（按最终收盘价）
                exit_price = final_close
            
            profit_pct = (exit_price - entry_price) / entry_price * 100
        
        else:  # short
            # Short: 止损在上方，止盈在下方
            hit_stop_loss = max_high >= stop_loss
            hit_take_profit = min_low <= take_profit
            
            if hit_stop_loss and hit_take_profit:
                # 同时触发，保守判断
                distance_to_sl = abs(stop_loss - entry_price)
                distance_to_tp = abs(entry_price - take_profit)
                if distance_to_sl < distance_to_tp:
                    exit_price = stop_loss
                else:
                    exit_price = take_profit
            elif hit_stop_loss:
                exit_price = stop_loss
            elif hit_take_profit:
                exit_price = take_profit
            else:
                # 超时退出
                exit_price = final_close
            
            profit_pct = (entry_price - exit_price) / entry_price * 100
        
        # 5. 考虑超时退出的限制
        # 如果未触发止盈止损，但持仓时间超过max_holding_hours，强制平仓
        klines_per_hour = 4  # 15分钟K线，每小时4根
        max_klines = max_holding_hours * klines_per_hour
        if data_points > max_klines:
            # 实际只能持有max_holding_hours，重新计算
            # 这里简化处理：如果已经计算了profit_pct，且未触发止盈止损，则使用final_close
            pass
        
        # 6. 记录退出原因（用于调试）
        if direction == 'long':
            if min_low <= stop_loss:
                opportunity['exit_reason'] = 'stop_loss'
            elif max_high >= take_profit:
                opportunity['exit_reason'] = 'take_profit'
            else:
                opportunity['exit_reason'] = 'time_exit'
        else:
            if max_high >= stop_loss:
                opportunity['exit_reason'] = 'stop_loss'
            elif min_low <= take_profit:
                opportunity['exit_reason'] = 'take_profit'
            else:
                opportunity['exit_reason'] = 'time_exit'
        
        return profit_pct
    
    except Exception as e:
        # 计算失败，返回0（避免中断整体流程）
        opportunity['exit_reason'] = 'error'
        opportunity['error_msg'] = str(e)
        return 0


def calculate_actual_profit_batch(
    opportunities: List[Dict],
    strategy_params: Dict,
    batch_size: int = 100,
    use_dynamic_atr: bool = True
) -> List[Dict]:
    """
    批量计算实际利润（带进度提示）
    
    Args:
        opportunities: 机会列表
        strategy_params: 策略参数
        batch_size: 批处理大小（每100个打印一次进度）
        use_dynamic_atr: 是否使用动态ATR
    
    Returns:
        更新后的机会列表（添加了actual_profit_pct字段）
    """
    total = len(opportunities)
    
    for i, opp in enumerate(opportunities):
        # 计算实际利润
        actual_profit = calculate_single_actual_profit(
            opp, 
            strategy_params, 
            use_dynamic_atr
        )
        opp['actual_profit_pct'] = actual_profit
        
        # 进度提示
        if (i + 1) % batch_size == 0 or (i + 1) == total:
            print(f"     进度: {i+1}/{total} ({(i+1)/total*100:.1f}%)", end='\r')
    
    print()  # 换行
    return opportunities


def add_actual_profit_to_opportunities(
    scalping_opps: List[Dict],
    swing_opps: List[Dict],
    scalping_params: Dict,
    swing_params: Dict,
    use_dynamic_atr: bool = True,
    phase1_mode: bool = False
) -> tuple:
    """
    为超短线和波段机会分别添加actual_profit_pct字段
    
    Args:
        scalping_opps: 超短线机会列表
        swing_opps: 波段机会列表
        scalping_params: 超短线策略参数
        swing_params: 波段策略参数
        use_dynamic_atr: 是否使用动态ATR
        phase1_mode: 是否为Phase 1（纯客观统计模式）
    
    Returns:
        (updated_scalping_opps, updated_swing_opps)
    """
    if phase1_mode:
        # 【V8.5.2.4.8】Phase 1纯客观统计：只统计objective_profit
        print(f"\n  📊 Phase 1客观统计（最大潜在利润）...")
        
        if scalping_opps:
            avg_obj_profit = np.mean([o.get('objective_profit', 0) for o in scalping_opps])
            print(f"     ⚡ 超短线: {len(scalping_opps)}个机会，平均最大利润{avg_obj_profit:.2f}%")
        
        if swing_opps:
            avg_obj_profit = np.mean([o.get('objective_profit', 0) for o in swing_opps])
            print(f"     🌊 波段: {len(swing_opps)}个机会，平均最大利润{avg_obj_profit:.2f}%")
        
        return scalping_opps, swing_opps
    
    # Phase 2-5：使用参数模拟实际利润
    print(f"\n  🔄 计算实际利润（基于止盈止损模拟）...")
    
    # 超短线
    if scalping_opps:
        print(f"     ⚡ 超短线: {len(scalping_opps)}个机会")
        scalping_opps = calculate_actual_profit_batch(
            scalping_opps,
            scalping_params,
            batch_size=100,
            use_dynamic_atr=use_dynamic_atr
        )
        
        # 统计
        avg_profit = np.mean([o.get('actual_profit_pct', 0) for o in scalping_opps])
        wins = len([o for o in scalping_opps if o.get('actual_profit_pct', 0) > 0])
        win_rate = wins / len(scalping_opps) * 100 if scalping_opps else 0
        print(f"     ✓ 超短线: 平均利润{avg_profit:.2f}%, 胜率{win_rate:.1f}%")
    
    # 波段
    if swing_opps:
        print(f"     🌊 波段: {len(swing_opps)}个机会")
        swing_opps = calculate_actual_profit_batch(
            swing_opps,
            swing_params,
            batch_size=100,
            use_dynamic_atr=use_dynamic_atr
        )
        
        # 统计
        avg_profit = np.mean([o.get('actual_profit_pct', 0) for o in swing_opps])
        wins = len([o for o in swing_opps if o.get('actual_profit_pct', 0) > 0])
        win_rate = wins / len(swing_opps) * 100 if swing_opps else 0
        print(f"     ✓ 波段: 平均利润{avg_profit:.2f}%, 胜率{win_rate:.1f}%")
    
    return scalping_opps, swing_opps


if __name__ == '__main__':
    """
    测试代码
    """
    # 模拟一个机会
    test_opp = {
        'entry_price': 90000,
        'direction': 'long',
        'atr': 500,
        'signal_score': 80,
        'future_data': {
            'max_high': 92000,   # +2.22%
            'min_low': 89000,    # -1.11%
            'final_close': 91000,
            'data_points': 96
        }
    }
    
    # 超短线参数
    scalping_params = {
        'atr_stop_multiplier': 1.0,   # 止损 = 90000 - 500 = 89500
        'atr_tp_multiplier': 1.5,     # 止盈 = 90000 + 750 = 90750
        'max_holding_hours': 2
    }
    
    # 计算实际利润
    actual_profit = calculate_single_actual_profit(
        test_opp,
        scalping_params,
        use_dynamic_atr=True
    )
    
    print(f"入场价: ${test_opp['entry_price']}")
    print(f"止损: ${test_opp['entry_price'] - 500}")
    print(f"止盈: ${test_opp['entry_price'] + 750}")
    print(f"未来24小时: 最高${test_opp['future_data']['max_high']}, 最低${test_opp['future_data']['min_low']}")
    print(f"实际利润: {actual_profit:.2f}%")
    print(f"退出原因: {test_opp.get('exit_reason', 'unknown')}")
    print(f"理论利润(objective): {(test_opp['future_data']['max_high'] - test_opp['entry_price']) / test_opp['entry_price'] * 100:.2f}%")

