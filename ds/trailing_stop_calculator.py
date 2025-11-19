#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
【V8.5.2.4.42】移动止盈止损计算模块

核心功能:
1. 计算带移动止损的实际利润
2. 支持静态止损和移动止损的对比
3. 提供详细的退出原因分析
"""

from typing import Dict, List, Tuple, Any
import pandas as pd


def calculate_profit_with_trailing_stop(
    opportunity: Dict,
    params: Dict,
    future_data: pd.DataFrame = None
) -> Tuple[float, str, Dict]:
    """
    【V8.5.2.4.42】计算带移动止损的实际利润
    
    Args:
        opportunity: 机会数据，包含entry_price, atr等
        params: 策略参数，包含atr_tp_multiplier, atr_stop_multiplier, trailing_stop_enabled等
        future_data: 未来价格数据（如果没有，使用opportunity中的max_profit数据）
    
    Returns:
        (actual_profit, exit_reason, details): 实际利润%, 退出原因, 详细信息
    """
    # 获取基础数据
    entry_price = float(opportunity.get('entry_price', 0))
    atr = float(opportunity.get('atr', 0))
    
    if entry_price <= 0 or atr <= 0:
        return 0.0, 'invalid_data', {}
    
    # 获取参数
    atr_tp_multiplier = float(params.get('atr_tp_multiplier', 3.0))
    atr_stop_multiplier = float(params.get('atr_stop_multiplier', 1.5))
    trailing_stop_enabled = params.get('trailing_stop_enabled', False)
    max_holding_hours = int(params.get('max_holding_hours', 24))
    
    # 计算初始止损/止盈
    initial_sl = entry_price - atr * atr_stop_multiplier
    initial_tp = entry_price + atr * atr_tp_multiplier
    
    # 如果有未来数据，使用实际价格
    if future_data is not None and len(future_data) > 0:
        return _calculate_with_future_data(
            entry_price, initial_sl, initial_tp, atr, atr_stop_multiplier,
            trailing_stop_enabled, max_holding_hours, future_data
        )
    
    # 如果没有未来数据，使用opportunity中的max_profit进行模拟
    return _calculate_with_max_profit(
        opportunity, entry_price, initial_sl, initial_tp, atr, atr_stop_multiplier,
        trailing_stop_enabled, max_holding_hours
    )


def _calculate_with_future_data(
    entry_price: float,
    initial_sl: float,
    initial_tp: float,
    atr: float,
    atr_stop_multiplier: float,
    trailing_stop_enabled: bool,
    max_holding_hours: int,
    future_data: pd.DataFrame
) -> Tuple[float, str, Dict]:
    """
    使用实际未来价格数据计算利润
    """
    if not trailing_stop_enabled:
        # 静态止损/止盈
        for idx, row in future_data.iterrows():
            price = float(row['close'])
            
            # 检查止损
            if price <= initial_sl:
                profit = (initial_sl - entry_price) / entry_price * 100
                return profit, 'stop_loss', {
                    'exit_price': initial_sl,
                    'bars_held': idx + 1
                }
            
            # 检查止盈
            if price >= initial_tp:
                profit = (initial_tp - entry_price) / entry_price * 100
                return profit, 'take_profit', {
                    'exit_price': initial_tp,
                    'bars_held': idx + 1
                }
        
        # 持仓到期
        final_price = float(future_data.iloc[-1]['close'])
        profit = (final_price - entry_price) / entry_price * 100
        return profit, 'holding_expired', {
            'exit_price': final_price,
            'bars_held': len(future_data)
        }
    
    else:
        # 移动止损逻辑
        highest_price = entry_price
        trailing_sl = initial_sl
        
        for idx, row in future_data.iterrows():
            price = float(row['close'])
            
            # 更新最高价和移动止损线
            if price > highest_price:
                highest_price = price
                # 移动止损上移（保护利润）
                trailing_sl = highest_price - atr * atr_stop_multiplier
            
            # 检查移动止损
            if price <= trailing_sl:
                profit = (trailing_sl - entry_price) / entry_price * 100
                return profit, 'trailing_stop', {
                    'exit_price': trailing_sl,
                    'highest_price': highest_price,
                    'bars_held': idx + 1
                }
            
            # 检查止盈
            if price >= initial_tp:
                profit = (initial_tp - entry_price) / entry_price * 100
                return profit, 'take_profit', {
                    'exit_price': initial_tp,
                    'highest_price': highest_price,
                    'bars_held': idx + 1
                }
        
        # 持仓到期
        final_price = float(future_data.iloc[-1]['close'])
        profit = (final_price - entry_price) / entry_price * 100
        return profit, 'holding_expired', {
            'exit_price': final_price,
            'highest_price': highest_price,
            'bars_held': len(future_data)
        }


def _calculate_with_max_profit(
    opportunity: Dict,
    entry_price: float,
    initial_sl: float,
    initial_tp: float,
    atr: float,
    atr_stop_multiplier: float,
    trailing_stop_enabled: bool,
    max_holding_hours: int
) -> Tuple[float, str, Dict]:
    """
    使用opportunity中的max_profit数据模拟价格走势
    
    模拟逻辑：
    - 假设价格会达到max_potential_profit对应的价格
    - 如果在到达前触发止损，返回止损利润
    - 如果到达后回落，移动止损可能触发
    """
    max_potential_profit = float(opportunity.get('max_potential_profit', 0))
    
    if max_potential_profit <= 0:
        # 无利润空间，可能触发止损
        profit = (initial_sl - entry_price) / entry_price * 100
        return profit, 'stop_loss', {'exit_price': initial_sl}
    
    # 计算最高价格
    max_price = entry_price * (1 + max_potential_profit / 100)
    
    # 检查是否能达到止盈
    if max_price >= initial_tp:
        # 能达到止盈
        profit = (initial_tp - entry_price) / entry_price * 100
        return profit, 'take_profit', {
            'exit_price': initial_tp,
            'max_price': max_price
        }
    
    if not trailing_stop_enabled:
        # 静态止损：到达最高价后持仓到期
        profit = max_potential_profit
        return profit, 'holding_expired', {
            'exit_price': max_price,
            'max_price': max_price
        }
    
    else:
        # 移动止损：假设价格上涨到max_price后回落
        # 移动止损线会在最高价处
        trailing_sl_at_peak = max_price - atr * atr_stop_multiplier
        
        # 如果移动止损线高于初始止损线，说明保护了利润
        if trailing_sl_at_peak > initial_sl:
            # 假设价格回落触发移动止损
            profit = (trailing_sl_at_peak - entry_price) / entry_price * 100
            return profit, 'trailing_stop', {
                'exit_price': trailing_sl_at_peak,
                'max_price': max_price
            }
        else:
            # 移动止损还没起作用，到达最高价后持仓到期
            profit = max_potential_profit
            return profit, 'holding_expired', {
                'exit_price': max_price,
                'max_price': max_price
            }


def batch_calculate_profits(
    opportunities: List[Dict],
    params: Dict,
    future_data_dict: Dict[str, pd.DataFrame] = None
) -> List[Dict]:
    """
    批量计算多个机会的利润
    
    Args:
        opportunities: 机会列表
        params: 策略参数
        future_data_dict: 未来数据字典 {opportunity_id: future_df}
    
    Returns:
        results: 结果列表，每个包含profit, exit_reason, details
    """
    results = []
    
    for opp in opportunities:
        opp_id = f"{opp.get('coin', 'UNKNOWN')}_{opp.get('timestamp', '')}"
        future_data = None
        
        if future_data_dict and opp_id in future_data_dict:
            future_data = future_data_dict[opp_id]
        
        profit, exit_reason, details = calculate_profit_with_trailing_stop(
            opp, params, future_data
        )
        
        results.append({
            'opportunity': opp,
            'profit': profit,
            'exit_reason': exit_reason,
            'details': details
        })
    
    return results


def compare_static_vs_trailing(
    opportunities: List[Dict],
    base_params: Dict,
    future_data_dict: Dict[str, pd.DataFrame] = None
) -> Dict:
    """
    对比静态止损和移动止损的效果
    
    Returns:
        comparison: {
            'static': {...},
            'trailing': {...},
            'improvement': float
        }
    """
    # 静态止损
    static_params = {**base_params, 'trailing_stop_enabled': False}
    static_results = batch_calculate_profits(opportunities, static_params, future_data_dict)
    
    # 移动止损
    trailing_params = {**base_params, 'trailing_stop_enabled': True}
    trailing_results = batch_calculate_profits(opportunities, trailing_params, future_data_dict)
    
    # 统计
    static_avg = sum(r['profit'] for r in static_results) / len(static_results) if static_results else 0
    trailing_avg = sum(r['profit'] for r in trailing_results) / len(trailing_results) if trailing_results else 0
    
    improvement = ((trailing_avg - static_avg) / abs(static_avg) * 100) if static_avg != 0 else 0
    
    return {
        'static': {
            'avg_profit': static_avg,
            'results': static_results
        },
        'trailing': {
            'avg_profit': trailing_avg,
            'results': trailing_results
        },
        'improvement': improvement
    }

