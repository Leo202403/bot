#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实际利润计算模块 V8.4.8

功能：为每个交易机会计算actual_profit_pct（实际执行后的利润）
内存优化：确保在1GB限制内运行
V8.4.8新增：动态ATR倍数计算
"""

import numpy as np
from typing import Dict, List, Tuple, Optional


def calculate_dynamic_atr_multiplier(
    objective_profit_pct: float,
    atr: float,
    entry_price: float,
    signal_type: str = 'scalping'
) -> Tuple[float, float]:
    """
    【V8.4.8】根据理论利润动态计算ATR倍数
    
    核心思路：
    1. 计算达到理论利润需要的ATR倍数
    2. 取理论倍数的60%作为实际目标（让actual_profit达到objective_profit的50-70%）
    3. 限制在合理范围内（防止极端值）
    
    Args:
        objective_profit_pct: 理论利润百分比（例如15.5）
        atr: ATR值
        entry_price: 入场价格
        signal_type: 'scalping' 或 'swing'
    
    Returns:
        (atr_tp_multiplier, atr_sl_multiplier)
    
    示例：
        objective_profit=10%, atr=2%, entry_price=100
        → theoretical_multiplier = 10/2 = 5.0
        → atr_tp = 5.0 * 0.6 = 3.0
        → 限制在[2.0, 4.0]范围内 → 3.0 ✅
    """
    # 计算ATR占入场价的百分比
    atr_pct = (atr / entry_price) * 100
    
    # 计算理论倍数
    if atr_pct > 0:
        theoretical_multiplier = objective_profit_pct / atr_pct
    else:
        theoretical_multiplier = 3.0  # 默认值
    
    # 【V8.4.9.3】取70%作为实际目标（从60%提高，更接近50-70%目标）
    target_multiplier = theoretical_multiplier * 0.7
    
    # 根据策略类型设置范围
    if signal_type == 'scalping':
        # 【V8.5.1】超短线：2.0-10.0倍ATR（上限从6.0提高到10.0，允许捕获更高利润）
        min_tp, max_tp = 2.0, 10.0
        sl_multiplier = 1.5  # 固定止损
    else:  # swing
        # 【V8.5.1】波段：3.0-20.0倍ATR（上限从10.0提高到20.0，允许捕获更高利润）
        min_tp, max_tp = 3.0, 20.0
        sl_multiplier = 1.5  # 固定止损
    
    # 限制在合理范围内
    atr_tp_multiplier = max(min_tp, min(max_tp, target_multiplier))
    
    return atr_tp_multiplier, sl_multiplier


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
    
    # 计算实际R:R（基于实际执行的止盈止损价格）
    if direction == 'long':
        tp_distance_pct = abs(tp_price - entry_price) / entry_price * 100
        sl_distance_pct = abs(entry_price - sl_price) / entry_price * 100
    else:  # short
        tp_distance_pct = abs(entry_price - tp_price) / entry_price * 100
        sl_distance_pct = abs(sl_price - entry_price) / entry_price * 100
    
    actual_rr = tp_distance_pct / sl_distance_pct if sl_distance_pct > 0 else 999
    
    return {
        'actual_profit_pct': profit_pct,
        'actual_risk_reward': actual_rr,
        'exit_reason': exit_reason,
        'exit_price': exit_price,
        'tp_price': tp_price,
        'sl_price': sl_price
    }


def calculate_actual_profit_batch(
    opportunities: List[Dict],
    strategy_params: Dict,
    batch_size: int = 100,
    use_dynamic_atr: bool = False
) -> List[Dict]:
    """
    批量计算actual_profit_pct和actual_risk_reward（内存优化版）
    
    Args:
        opportunities: 机会列表
        strategy_params: 策略参数（包含atr_tp_multiplier等）
        batch_size: 批次大小（控制内存使用）
        use_dynamic_atr: 【V8.4.8】是否使用动态ATR倍数
    
    Returns:
        更新后的机会列表（添加了actual_profit_pct和actual_risk_reward字段）
    
    内存优化：
    - 每次处理batch_size个机会
    - 处理完立即释放内存
    - 总内存占用：~batch_size * 1KB = 100KB
    """
    import gc
    
    # 获取策略参数
    default_tp_multiplier = strategy_params.get('atr_tp_multiplier', 2.0)
    default_sl_multiplier = strategy_params.get('atr_stop_multiplier', 1.5)
    signal_type = strategy_params.get('signal_type', 'scalping')  # 【V8.4.8】获取策略类型
    
    total = len(opportunities)
    updated_opps = []
    
    # 分批处理
    for i in range(0, total, batch_size):
        batch = opportunities[i:i+batch_size]
        batch_results = []
        
        for opp in batch:
            # 检查是否有future_data
            if 'future_data' not in opp:
                # 没有未来数据，使用理论值
                opp['actual_profit_pct'] = opp.get('objective_profit', 0)
                opp['actual_risk_reward'] = opp.get('risk_reward', default_tp_multiplier / default_sl_multiplier)
                opp['exit_reason'] = 'no_future_data'
                batch_results.append(opp)
                continue
            
            # 【V8.4.8】决定使用固定还是动态ATR倍数
            if use_dynamic_atr:
                # 动态计算ATR倍数
                objective_profit = opp.get('objective_profit', 0)
                atr = opp.get('atr', opp['entry_price'] * 0.02)
                entry_price = opp['entry_price']
                
                tp_multiplier, sl_multiplier = calculate_dynamic_atr_multiplier(
                    objective_profit_pct=objective_profit,
                    atr=atr,
                    entry_price=entry_price,
                    signal_type=signal_type
                )
                
                # 【V8.4.9.2调试】每100个机会打印一次样本
                if i == 0 and len(batch_results) == 0:
                    atr_pct = (atr / entry_price) * 100
                    theoretical = objective_profit / atr_pct if atr_pct > 0 else 0
                    print(f"\n  🔍 【V8.4.9.3动态ATR调试】样本:")
                    print(f"     理论利润: {objective_profit:.2f}%")
                    print(f"     ATR: {atr:.4f} ({atr_pct:.2f}%)")
                    print(f"     理论倍数: {theoretical:.2f}")
                    print(f"     实际倍数: {tp_multiplier:.2f} (70%={theoretical*0.7:.2f})")
            else:
                # 使用固定ATR倍数
                tp_multiplier = default_tp_multiplier
                sl_multiplier = default_sl_multiplier
            
            # 模拟交易执行（会自动计算actual_risk_reward）
            result = simulate_trade_execution(
                opp=opp,
                future_data_summary=opp['future_data'],
                tp_multiplier=tp_multiplier,
                sl_multiplier=sl_multiplier
            )
            
            # 更新机会数据（result已包含actual_risk_reward）
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
    swing_params: Dict,
    use_dynamic_atr: bool = False
) -> Tuple[List[Dict], List[Dict]]:
    """
    为超短线和波段机会添加actual_profit_pct
    
    Args:
        scalping_opps: 超短线机会列表
        swing_opps: 波段机会列表
        scalping_params: 超短线策略参数
        swing_params: 波段策略参数
        use_dynamic_atr: 【V8.4.8】是否使用动态ATR倍数
    
    Returns:
        (updated_scalping_opps, updated_swing_opps)
    
    内存占用：
    - 超短线：~1300个 * 1KB = 1.3MB
    - 波段：~2000个 * 1KB = 2MB
    - 总计：~3.3MB（远低于1GB限制）
    """
    version_tag = "V8.4.9.3动态ATR" if use_dynamic_atr else "V8.4.6固定ATR"
    print(f"\n  📊 【{version_tag}】计算实际利润（内存优化版）")
    print(f"     超短线机会: {len(scalping_opps)}个")
    print(f"     波段机会: {len(swing_opps)}个")
    print(f"     预计内存: <5MB")
    
    # 【V8.4.8】添加signal_type到参数中
    scalping_params_with_type = {**scalping_params, 'signal_type': 'scalping'}
    swing_params_with_type = {**swing_params, 'signal_type': 'swing'}
    
    # 计算超短线实际利润
    if scalping_opps:
        print(f"\n  ⚡ 处理超短线机会...")
        scalping_opps = calculate_actual_profit_batch(
            scalping_opps,
            scalping_params_with_type,
            batch_size=100,
            use_dynamic_atr=use_dynamic_atr
        )
    
    # 计算波段实际利润
    if swing_opps:
        print(f"\n  🌊 处理波段机会...")
        swing_opps = calculate_actual_profit_batch(
            swing_opps,
            swing_params_with_type,
            batch_size=100,
            use_dynamic_atr=use_dynamic_atr
        )
    
    # 统计对比
    if scalping_opps:
        scalping_objective = np.mean([o['objective_profit'] for o in scalping_opps])
        scalping_actual = np.mean([o.get('actual_profit_pct', 0) for o in scalping_opps])
        print(f"\n  📊 超短线对比:")
        print(f"     理论利润: {scalping_objective:.2f}%")
        print(f"     实际利润: {scalping_actual:.2f}%")
        print(f"     差距: {scalping_objective - scalping_actual:.2f}%")
        if use_dynamic_atr:
            ratio = (scalping_actual / scalping_objective * 100) if scalping_objective > 0 else 0
            print(f"     实际/理论: {ratio:.1f}%  【V8.4.8目标: 50-70%】")
            # 【V8.4.9.2调试】统计ATR倍数分布
            if len(scalping_opps) > 0:
                sample_size = min(10, len(scalping_opps))
                sample_opps = scalping_opps[:sample_size]
                print(f"  🔍 【V8.4.9.3调试】前{sample_size}个机会的ATR倍数:")
                for idx, opp in enumerate(sample_opps, 1):
                    obj_profit = opp.get('objective_profit', 0)
                    atr = opp.get('atr', 0)
                    entry = opp.get('entry_price', 0)
                    atr_pct = (atr / entry * 100) if entry > 0 else 0
                    theoretical = (obj_profit / atr_pct) if atr_pct > 0 else 0
                    target = theoretical * 0.7
                    final = max(2.0, min(6.0, target))
                    print(f"     [{idx}] 理论{obj_profit:.1f}% / ATR{atr_pct:.2f}% = {theoretical:.2f} → 70%={target:.2f} → 最终={final:.2f}")
    
    if swing_opps:
        swing_objective = np.mean([o['objective_profit'] for o in swing_opps])
        swing_actual = np.mean([o.get('actual_profit_pct', 0) for o in swing_opps])
        print(f"\n  📊 波段对比:")
        print(f"     理论利润: {swing_objective:.2f}%")
        print(f"     实际利润: {swing_actual:.2f}%")
        print(f"     差距: {swing_objective - swing_actual:.2f}%")
        if use_dynamic_atr:
            ratio = (swing_actual / swing_objective * 100) if swing_objective > 0 else 0
            print(f"     实际/理论: {ratio:.1f}%  【V8.4.8目标: 50-70%】")
            # 【V8.4.9.2调试】统计ATR倍数分布
            if len(swing_opps) > 0:
                sample_size = min(10, len(swing_opps))
                sample_opps = swing_opps[:sample_size]
                print(f"  🔍 【V8.4.9.3调试】前{sample_size}个机会的ATR倍数:")
                for idx, opp in enumerate(sample_opps, 1):
                    obj_profit = opp.get('objective_profit', 0)
                    atr = opp.get('atr', 0)
                    entry = opp.get('entry_price', 0)
                    atr_pct = (atr / entry * 100) if entry > 0 else 0
                    theoretical = (obj_profit / atr_pct) if atr_pct > 0 else 0
                    target = theoretical * 0.7
                    final = max(3.0, min(10.0, target))
                    print(f"     [{idx}] 理论{obj_profit:.1f}% / ATR{atr_pct:.2f}% = {theoretical:.2f} → 70%={target:.2f} → 最终={final:.2f}")
    
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

