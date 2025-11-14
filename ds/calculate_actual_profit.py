#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实际利润计算模块 V8.3.21.9

功能：为每个交易机会计算actual_profit_pct（实际执行后的利润）
内存优化：确保在1GB限制内运行
"""

import numpy as np
from typing import Dict, List, Tuple, Optional


def simulate_trade_execution(
    opp: Dict,
    future_data_summary: Dict,
    tp_multiplier: float = 2.0,
    sl_multiplier: float = 1.5,
    slippage_pct: float = 0.05,
    fee_pct: float = 0.1
) -> Dict:
    """
    模拟单笔交易的完整执行过程（内存优化版）
    
    Args:
        opp: 机会数据（包含entry_price, direction, atr等）
        future_data_summary: 未来数据摘要（max_high, min_low等）
        tp_multiplier: 止盈ATR倍数
        sl_multiplier: 止损ATR倍数
        slippage_pct: 滑点百分比
        fee_pct: 手续费百分比
    
    Returns:
        {
            'actual_profit_pct': float,  # 实际利润百分比
            'exit_reason': str,          # 退出原因：'tp', 'sl', 'time_exit'
            'exit_price': float          # 退出价格
        }
    
    内存占用：~1KB/次调用（不保存K线数据）
    """
    entry_price = opp['entry_price']
    direction = opp['direction']
    atr = opp.get('atr', entry_price * 0.02)  # 默认2%
    
    # 计算止盈止损价格
    if direction == 'long':
        tp_price = entry_price + (atr * tp_multiplier)
        sl_price = entry_price - (atr * sl_multiplier)
        max_price = future_data_summary['max_high']
        min_price = future_data_summary['min_low']
        
        # 判断退出原因
        if max_price >= tp_price:
            # 止盈
            exit_price = tp_price * (1 - slippage_pct / 100)  # 考虑滑点
            exit_reason = 'tp'
        elif min_price <= sl_price:
            # 止损
            exit_price = sl_price * (1 - slippage_pct / 100)  # 考虑滑点
            exit_reason = 'sl'
        else:
            # 时间退出
            exit_price = future_data_summary['final_close']
            exit_reason = 'time_exit'
        
        # 计算利润（考虑手续费）
        profit_pct = (exit_price - entry_price) / entry_price * 100
        profit_pct -= fee_pct * 2  # 开仓+平仓手续费
        
    else:  # short
        tp_price = entry_price - (atr * tp_multiplier)
        sl_price = entry_price + (atr * sl_multiplier)
        max_price = future_data_summary['max_high']
        min_price = future_data_summary['min_low']
        
        # 判断退出原因
        if min_price <= tp_price:
            # 止盈
            exit_price = tp_price * (1 + slippage_pct / 100)  # 考虑滑点
            exit_reason = 'tp'
        elif max_price >= sl_price:
            # 止损
            exit_price = sl_price * (1 + slippage_pct / 100)  # 考虑滑点
            exit_reason = 'sl'
        else:
            # 时间退出
            exit_price = future_data_summary['final_close']
            exit_reason = 'time_exit'
        
        # 计算利润（考虑手续费）
        profit_pct = (entry_price - exit_price) / entry_price * 100
        profit_pct -= fee_pct * 2  # 开仓+平仓手续费
    
    return {
        'actual_profit_pct': profit_pct,
        'exit_reason': exit_reason,
        'exit_price': exit_price,
        'tp_price': tp_price,
        'sl_price': sl_price
    }


def calculate_actual_profit_batch(
    opportunities: List[Dict],
    strategy_params: Dict,
    batch_size: int = 100
) -> List[Dict]:
    """
    批量计算actual_profit_pct（内存优化版）
    
    Args:
        opportunities: 机会列表
        strategy_params: 策略参数（包含atr_tp_multiplier等）
        batch_size: 批次大小（控制内存使用）
    
    Returns:
        更新后的机会列表（添加了actual_profit_pct字段）
    
    内存优化：
    - 每次处理batch_size个机会
    - 处理完立即释放内存
    - 总内存占用：~batch_size * 1KB = 100KB
    """
    import gc
    
    # 获取策略参数
    tp_multiplier = strategy_params.get('atr_tp_multiplier', 2.0)
    sl_multiplier = strategy_params.get('atr_stop_multiplier', 1.5)
    
    total = len(opportunities)
    updated_opps = []
    
    # 分批处理
    for i in range(0, total, batch_size):
        batch = opportunities[i:i+batch_size]
        batch_results = []
        
        for opp in batch:
            # 检查是否有future_data
            if 'future_data' not in opp:
                # 没有未来数据，跳过
                opp['actual_profit_pct'] = opp.get('objective_profit', 0)
                opp['exit_reason'] = 'no_future_data'
                batch_results.append(opp)
                continue
            
            # 模拟交易执行
            result = simulate_trade_execution(
                opp=opp,
                future_data_summary=opp['future_data'],
                tp_multiplier=tp_multiplier,
                sl_multiplier=sl_multiplier
            )
            
            # 更新机会数据
            opp.update(result)
            batch_results.append(opp)
        
        updated_opps.extend(batch_results)
        
        # 显示进度
        progress = min(100, (i + batch_size) * 100 // total)
        print(f"\r  💰 计算实际利润: {progress}% ({i+batch_size}/{total})", end='', flush=True)
        
        # 释放内存
        del batch, batch_results
        gc.collect()
    
    print(f"\r  ✅ 实际利润计算完成: {total}个机会")
    
    return updated_opps


def add_actual_profit_to_opportunities(
    scalping_opps: List[Dict],
    swing_opps: List[Dict],
    scalping_params: Dict,
    swing_params: Dict
) -> Tuple[List[Dict], List[Dict]]:
    """
    为超短线和波段机会添加actual_profit_pct
    
    Args:
        scalping_opps: 超短线机会列表
        swing_opps: 波段机会列表
        scalping_params: 超短线策略参数
        swing_params: 波段策略参数
    
    Returns:
        (updated_scalping_opps, updated_swing_opps)
    
    内存占用：
    - 超短线：~1300个 * 1KB = 1.3MB
    - 波段：~2000个 * 1KB = 2MB
    - 总计：~3.3MB（远低于1GB限制）
    """
    print(f"\n  📊 【V8.3.21.9】计算实际利润（内存优化版）")
    print(f"     超短线机会: {len(scalping_opps)}个")
    print(f"     波段机会: {len(swing_opps)}个")
    print(f"     预计内存: <5MB")
    
    # 计算超短线实际利润
    if scalping_opps:
        print(f"\n  ⚡ 处理超短线机会...")
        scalping_opps = calculate_actual_profit_batch(
            scalping_opps,
            scalping_params,
            batch_size=100
        )
    
    # 计算波段实际利润
    if swing_opps:
        print(f"\n  🌊 处理波段机会...")
        swing_opps = calculate_actual_profit_batch(
            swing_opps,
            swing_params,
            batch_size=100
        )
    
    # 统计对比
    if scalping_opps:
        scalping_objective = np.mean([o['objective_profit'] for o in scalping_opps])
        scalping_actual = np.mean([o.get('actual_profit_pct', 0) for o in scalping_opps])
        print(f"\n  📊 超短线对比:")
        print(f"     理论利润: {scalping_objective:.2f}%")
        print(f"     实际利润: {scalping_actual:.2f}%")
        print(f"     差距: {scalping_objective - scalping_actual:.2f}%")
    
    if swing_opps:
        swing_objective = np.mean([o['objective_profit'] for o in swing_opps])
        swing_actual = np.mean([o.get('actual_profit_pct', 0) for o in swing_opps])
        print(f"\n  📊 波段对比:")
        print(f"     理论利润: {swing_objective:.2f}%")
        print(f"     实际利润: {swing_actual:.2f}%")
        print(f"     差距: {swing_objective - swing_actual:.2f}%")
    
    return scalping_opps, swing_opps


# 使用示例
if __name__ == "__main__":
    # 测试单个机会
    test_opp = {
        'entry_price': 100.0,
        'direction': 'long',
        'atr': 2.0,
        'future_data': {
            'max_high': 105.0,
            'min_low': 98.0,
            'final_close': 103.0,
            'data_points': 96
        }
    }
    
    result = simulate_trade_execution(
        test_opp,
        test_opp['future_data'],
        tp_multiplier=2.0,
        sl_multiplier=1.5
    )
    
    print("测试结果:")
    print(f"  实际利润: {result['actual_profit_pct']:.2f}%")
    print(f"  退出原因: {result['exit_reason']}")
    print(f"  退出价格: {result['exit_price']:.2f}")
    print(f"  止盈价格: {result['tp_price']:.2f}")
    print(f"  止损价格: {result['sl_price']:.2f}")

