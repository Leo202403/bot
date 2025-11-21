"""
【V8.3.25.8】完整的开平仓时机分析模块

核心逻辑：
1. 开仓分析：对比昨日市场快照（所有识别的机会点）vs AI实际开仓决策
2. 平仓分析：对比实际平仓点 vs 最优平仓点（基于后续K线走势）
3. 结合AI决策记录，分析决策逻辑是否正确

作者：AI Assistant
日期：2025-11-12
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
from pathlib import Path
import os
from openai import OpenAI


def analyze_entry_timing_v2(
    yesterday_trades_df,
    market_snapshots_df,
    ai_decisions_list,
    yesterday_date_str
):
    """
    【V8.3.25.8】完整的开仓时机分析
    
    核心逻辑：
    1. 获取昨日所有市场快照（AI识别的所有机会点）
    2. 对比AI实际开仓记录
    3. 分类分析：
       - 正确开仓：AI开了，市场走势验证是对的
       - 错误开仓：AI开了，但快速止损（虚假信号）
       - 错过机会：市场有机会，AI没开（分析为什么）
       - 时机问题：开了但太早/太晚
    
    Args:
        yesterday_trades_df: DataFrame, 昨日开仓的交易
        market_snapshots_df: DataFrame, 昨日市场快照（所有识别的机会点）
        ai_decisions_list: list, AI历史决策记录
        yesterday_date_str: str, 昨日日期（YYYY-MM-DD格式）
    
    Returns:
        {
            'entry_stats': {...},  # 统计数据
            'correct_entries': [...],  # 正确开仓案例
            'false_entries': [...],  # 虚假信号开仓
            'missed_opportunities': [...],  # 错过的机会（AI没开）
            'timing_issues': [...],  # 时机问题（太早/太晚）
            'entry_table_data': [...],  # 邮件表格数据
            'entry_lessons': [...]  # 改进建议
        }
    """
    
    print(f"\n【开仓时机完整分析 V8.3.25.8】")
    
    # 初始化统计
    entry_stats = {
        'total_opportunities': 0,  # 昨日识别的总机会数
        'ai_opened': 0,  # AI实际开仓数
        'correct_entries': 0,  # 正确开仓
        'false_entries': 0,  # 虚假信号
        'missed_profitable': 0,  # 错过的盈利机会
        'correctly_filtered': 0,  # 正确过滤的虚假信号
        'timing_issues': 0  # 时机问题（太早/太晚）
    }
    
    correct_entries = []
    false_entries = []
    missed_opportunities = []
    timing_issues = []
    entry_table_data = []
    
    # ===== Step 1: 获取昨日所有市场快照 =====
    if market_snapshots_df is None or market_snapshots_df.empty:
        print(f"⚠️ 无市场快照数据，无法进行开仓时机分析")
        return {
            'entry_stats': entry_stats,
            'correct_entries': [],
            'false_entries': [],
            'missed_opportunities': [],
            'timing_issues': [],
            'entry_table_data': [],
            'entry_lessons': ['无市场快照数据，无法分析']
        }
    
    # 筛选昨日的市场快照
    market_snapshots_df['date'] = pd.to_datetime(market_snapshots_df['time'], format='mixed', errors='coerce').dt.date
    yesterday_date_obj = datetime.strptime(yesterday_date_str, '%Y-%m-%d').date()
    yesterday_snapshots = market_snapshots_df[
        market_snapshots_df['date'] == yesterday_date_obj
    ].copy()
    
    if yesterday_snapshots.empty:
        # print(f"ℹ️ 昨日市场快照数据不足（跳过开仓时机分析）")  # 精简日志
        return {
            'entry_stats': entry_stats,
            'correct_entries': [],
            'false_entries': [],
            'missed_opportunities': [],
            'timing_issues': [],
            'entry_table_data': [],
            'entry_lessons': ['昨日无市场快照数据']
        }
    
    entry_stats['total_opportunities'] = len(yesterday_snapshots)
    print(f"  ✓ 昨日识别到 {entry_stats['total_opportunities']} 个机会点")
    
    # ===== Step 2: 获取昨日AI实际开仓记录 =====
    if yesterday_trades_df.empty:
        print(f"  ℹ️  昨日无实际开仓")
        # 所有机会都是错过的
        for idx, snapshot in yesterday_snapshots.iterrows():
            missed_opportunities.append({
                'coin': snapshot.get('coin', ''),
                'time': str(snapshot.get('time', '')),
                'signal_score': snapshot.get('signal_score', 0),
                'consensus': snapshot.get('consensus', 0),
                'potential_profit': snapshot.get('potential_profit', 0),
                'reason': '未开仓（需分析AI决策原因）'
            })
        entry_stats['missed_profitable'] = len(missed_opportunities)
    else:
        entry_stats['ai_opened'] = len(yesterday_trades_df)
        print(f"  ✓ 昨日AI实际开仓 {entry_stats['ai_opened']} 笔")
        
        # ===== Step 3: 对比分析每个机会点 =====
        for idx, snapshot in yesterday_snapshots.iterrows():
            coin = snapshot.get('coin', '')
            snapshot_time = snapshot.get('time')
            signal_score = snapshot.get('signal_score', 0)
            consensus = snapshot.get('consensus', 0)
            
            # 查找是否有对应的开仓记录（±5分钟窗口）
            snapshot_time_dt = pd.to_datetime(snapshot_time)
            matching_trades = yesterday_trades_df[
                (yesterday_trades_df['币种'] == coin) &
                (pd.to_datetime(yesterday_trades_df['开仓时间']) >= snapshot_time_dt - timedelta(minutes=5)) &
                (pd.to_datetime(yesterday_trades_df['开仓时间']) <= snapshot_time_dt + timedelta(minutes=5))
            ]
            
            if matching_trades.empty:
                # 情况1: AI没开仓（错过机会 or 正确过滤）
                # 需要检查实际走势：如果后续有利润，说明错过了；如果止损，说明正确过滤
                potential_profit = snapshot.get('potential_profit_pct', 0)
                
                if potential_profit > 2:  # 实际有>2%的利润
                    missed_opportunities.append({
                        'coin': coin,
                        'time': str(snapshot_time),
                        'signal_score': signal_score,
                        'consensus': consensus,
                        'potential_profit': potential_profit,
                        'reason': f'参数过滤（信号{signal_score}/共振{consensus}）'
                    })
                    entry_stats['missed_profitable'] += 1
                else:
                    # 正确过滤了虚假信号
                    entry_stats['correctly_filtered'] += 1
            else:
                # 情况2: AI开仓了
                trade = matching_trades.iloc[0]
                pnl = trade.get('盈亏', 0)
                exit_reason = trade.get('平仓原因', '')
                
                # 判断开仓质量
                if pnl < -0.5 and '止损' in exit_reason:
                    # 虚假信号：开仓后快速止损
                    false_entries.append({
                        'coin': coin,
                        'time': str(snapshot_time),
                        'signal_score': signal_score,
                        'consensus': consensus,
                        'pnl': pnl,
                        'reason': '虚假信号：开仓后快速止损'
                    })
                    entry_stats['false_entries'] += 1
                elif pnl > 0:
                    # 正确开仓
                    correct_entries.append({
                        'coin': coin,
                        'time': str(snapshot_time),
                        'signal_score': signal_score,
                        'consensus': consensus,
                        'pnl': pnl,
                        'reason': f'正确开仓：盈利{pnl:.2f}U'
                    })
                    entry_stats['correct_entries'] += 1
                else:
                    # 中性/小亏（可能是时机问题）
                    timing_issues.append({
                        'coin': coin,
                        'time': str(snapshot_time),
                        'signal_score': signal_score,
                        'consensus': consensus,
                        'pnl': pnl,
                        'reason': '时机问题：盈亏接近0'
                    })
                    entry_stats['timing_issues'] += 1
                
                # 添加到表格数据
                entry_table_data.append({
                    'coin': coin,
                    'time': str(snapshot_time),
                    'signal_score': signal_score,
                    'consensus': consensus,
                    'ai_action': '✅ 开仓',
                    'result': f'{pnl:+.2f}U',
                    'evaluation': '✅ 正确' if pnl > 0 else '❌ 虚假信号' if pnl < -0.5 else '⚠️ 时机问题'
                })
        
        # 添加错过的机会到表格
        for opp in missed_opportunities[:10]:  # TOP10
            entry_table_data.append({
                'coin': opp['coin'],
                'time': opp['time'],
                'signal_score': opp['signal_score'],
                'consensus': opp['consensus'],
                'ai_action': '❌ 未开',
                'result': f"潜在+{opp['potential_profit']:.1f}%",
                'evaluation': '⚠️ 错过机会'
            })
    
    # ===== Step 4: 生成改进建议 =====
    entry_lessons = []
    
    if entry_stats['false_entries'] > 0:
        false_rate = entry_stats['false_entries'] / max(entry_stats['ai_opened'], 1) * 100
        entry_lessons.append(f"虚假信号率{false_rate:.0f}%：提高信号评分阈值或增加确认条件")
    
    if entry_stats['missed_profitable'] > 0:
        miss_rate = entry_stats['missed_profitable'] / max(entry_stats['total_opportunities'], 1) * 100
        if miss_rate > 30:
            entry_lessons.append(f"错过{entry_stats['missed_profitable']}个机会（{miss_rate:.0f}%）：适当放宽参数过滤")
    
    if entry_stats['timing_issues'] > 0:
        entry_lessons.append(f"时机问题{entry_stats['timing_issues']}笔：优化开仓时机判断（等待更强确认信号）")
    
    # 打印统计
    print(f"\n  📊 开仓质量统计：")
    print(f"     总机会数: {entry_stats['total_opportunities']}")
    print(f"     AI开仓: {entry_stats['ai_opened']} ({entry_stats['ai_opened']/max(entry_stats['total_opportunities'],1)*100:.0f}%)")
    print(f"     ├─ ✅ 正确开仓: {entry_stats['correct_entries']}")
    print(f"     ├─ ❌ 虚假信号: {entry_stats['false_entries']}")
    print(f"     └─ ⚠️ 时机问题: {entry_stats['timing_issues']}")
    print(f"     错过机会: {entry_stats['missed_profitable']}")
    print(f"     正确过滤: {entry_stats['correctly_filtered']}")
    
    return {
        'entry_stats': entry_stats,
        'correct_entries': correct_entries,
        'false_entries': false_entries,
        'missed_opportunities': missed_opportunities,
        'timing_issues': timing_issues,
        'entry_table_data': entry_table_data,
        'entry_lessons': entry_lessons
    }


def analyze_exit_timing_v2(
    yesterday_closed_trades_df,
    kline_snapshots_df
):
    """
    【V8.3.25.8】完整的平仓时机分析
    
    核心逻辑：
    1. 对每笔昨日平仓的交易，分析平仓点是否最优
    2. 基于后续K线走势，判断：
       - 过早平仓：平仓后价格继续朝有利方向走
       - 延迟平仓：应该止损但拖延，扩大亏损
       - 最优平仓：在合理点位平仓
    3. 统计不同平仓类型（止盈/止损/手动）的质量
    
    Args:
        yesterday_closed_trades_df: DataFrame, 昨日平仓的交易
        kline_snapshots_df: DataFrame, K线快照数据
    
    Returns:
        {
            'exit_stats': {...},  # 统计数据
            'premature_exits': [...],  # 过早平仓案例
            'delayed_exits': [...],  # 延迟平仓案例
            'optimal_exits': [...],  # 最优平仓案例
            'exit_table_data': [...],  # 邮件表格数据
            'exit_lessons': [...]  # 改进建议
        }
    """
    
    print(f"\n【平仓时机完整分析 V8.3.25.8】")
    
    # 初始化统计
    exit_stats = {
        'total_exits': len(yesterday_closed_trades_df),
        'tp_exits': 0,  # 止盈平仓
        'sl_exits': 0,  # 止损平仓
        'manual_exits': 0,  # 手动平仓
        'premature_exits': 0,  # 过早平仓
        'delayed_exits': 0,  # 延迟平仓
        'optimal_exits': 0,  # 最优平仓
        'avg_missed_profit_pct': 0  # 平均错过利润
    }
    
    premature_exits = []
    delayed_exits = []
    optimal_exits = []
    exit_table_data = []
    
    if yesterday_closed_trades_df.empty:
        print(f"⚠️ 昨日无平仓交易")
        return {
            'exit_stats': exit_stats,
            'premature_exits': [],
            'delayed_exits': [],
            'optimal_exits': [],
            'exit_table_data': [],
            'exit_lessons': ['昨日无平仓交易']
        }
    
    print(f"  ✓ 分析 {exit_stats['total_exits']} 笔平仓交易")
    
    # ===== 分析每笔平仓交易 =====
    for idx, trade in yesterday_closed_trades_df.iterrows():
        coin = trade.get('币种', '')
        side = trade.get('方向', '')
        entry_price = trade.get('开仓价格', 0)
        exit_price = trade.get('平仓价格', 0)
        exit_time_str = trade.get('平仓时间', '')
        exit_reason = trade.get('平仓原因', '')
        pnl = trade.get('盈亏', 0)
        
        if not exit_time_str or exit_price == 0:
            continue
        
        try:
            exit_time = pd.to_datetime(exit_time_str)
        except:
            continue
        
        # 判断平仓类型
        if '止盈' in exit_reason or 'TP' in exit_reason.upper():
            exit_type = '止盈'
            exit_stats['tp_exits'] += 1
        elif '止损' in exit_reason or 'SL' in exit_reason.upper():
            exit_type = '止损'
            exit_stats['sl_exits'] += 1
        else:
            exit_type = '手动'
            exit_stats['manual_exits'] += 1
        
        # 获取平仓后的K线数据（后续4小时）
        if kline_snapshots_df is not None and not kline_snapshots_df.empty:
            coin_klines = kline_snapshots_df[kline_snapshots_df['coin'] == coin].copy()
            if not coin_klines.empty:
                coin_klines['time'] = pd.to_datetime(coin_klines['time'], format='mixed', errors='coerce')
                coin_klines = coin_klines.sort_values('time')
                
                future_klines = coin_klines[
                    (coin_klines['time'] > exit_time) &
                    (coin_klines['time'] <= exit_time + timedelta(hours=4))
                ]
                
                if not future_klines.empty:
                    # 计算最大潜在利润
                    if side == '多':
                        max_price_after = future_klines['high'].max()
                        missed_profit_pct = (max_price_after - exit_price) / exit_price * 100
                    else:  # 空单
                        min_price_after = future_klines['low'].min()
                        missed_profit_pct = (exit_price - min_price_after) / exit_price * 100
                    
                    # 判断平仓质量
                    is_premature = False
                    is_delayed = False
                    
                    if exit_type == '止盈' and missed_profit_pct > 2:
                        # 止盈后还有>2%利润，说明过早平仓
                        is_premature = True
                        exit_stats['premature_exits'] += 1
                        premature_exits.append({
                            'coin': coin,
                            'side': side,
                            'entry_price': entry_price,
                            'exit_price': exit_price,
                            'exit_type': exit_type,
                            'exit_reason': exit_reason[:50],
                            'pnl': pnl,
                            'missed_profit_pct': missed_profit_pct,
                            'recommendation': f'TP扩大{1.3:.1f}倍' if missed_profit_pct > 3 else 'TP扩大1.2倍'
                        })
                    elif exit_type == '止损' and pnl < -1 and missed_profit_pct < -1:
                        # 止损后价格继续朝不利方向走，说明延迟止损
                        is_delayed = True
                        exit_stats['delayed_exits'] += 1
                        delayed_exits.append({
                            'coin': coin,
                            'side': side,
                            'entry_price': entry_price,
                            'exit_price': exit_price,
                            'exit_type': exit_type,
                            'exit_reason': exit_reason[:50],
                            'pnl': pnl,
                            'extra_loss_pct': abs(missed_profit_pct),
                            'recommendation': '提前止损或扩大止损距离'
                        })
                    else:
                        # 最优平仓
                        exit_stats['optimal_exits'] += 1
                        optimal_exits.append({
                            'coin': coin,
                            'side': side,
                            'entry_price': entry_price,
                            'exit_price': exit_price,
                            'exit_type': exit_type,
                            'pnl': pnl,
                            'recommendation': '继续保持'
                        })
                    
                    # 添加到表格数据
                    exit_table_data.append({
                        'coin': coin,
                        'side': side,
                        'entry_price': entry_price,
                        'exit_price': exit_price,
                        'exit_type': exit_type,
                        'pnl': pnl,
                        'max_potential_profit_pct': missed_profit_pct if not is_delayed else 0,
                        'evaluation': '⚠️ 早平' if is_premature else '⚠️ 延迟' if is_delayed else '✅ 最优',
                        'recommendation': premature_exits[-1]['recommendation'] if is_premature else 
                                        delayed_exits[-1]['recommendation'] if is_delayed else '继续保持'
                    })
                    
                    continue
        
        # 如果没有K线数据，只能基于PNL判断
        if pnl > 0:
            exit_stats['optimal_exits'] += 1
        elif exit_type == '止损':
            exit_stats['optimal_exits'] += 1  # 止损是正常的风控
        else:
            exit_stats['premature_exits'] += 1
        
        exit_table_data.append({
            'coin': coin,
            'side': side,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'exit_type': exit_type,
            'pnl': pnl,
            'max_potential_profit_pct': 0,
            'evaluation': '✅ 最优' if pnl > 0 else '🚱 止损' if exit_type == '止损' else '⚠️ 早平',
            'recommendation': '继续保持' if pnl > 0 else '正常止损' if exit_type == '止损' else 'TP扩大1.2倍'
        })
    
    # 计算平均错过利润
    if premature_exits:
        exit_stats['avg_missed_profit_pct'] = sum(e['missed_profit_pct'] for e in premature_exits) / len(premature_exits)
    
    # 生成改进建议
    exit_lessons = []
    
    if exit_stats['premature_exits'] > 0:
        premature_rate = exit_stats['premature_exits'] / max(exit_stats['total_exits'], 1) * 100
        exit_lessons.append(
            f"过早平仓{exit_stats['premature_exits']}笔（{premature_rate:.0f}%）：" +
            f"平均错过{exit_stats['avg_missed_profit_pct']:.1f}%利润，建议TP扩大1.3倍"
        )
    
    if exit_stats['delayed_exits'] > 0:
        exit_lessons.append(
            f"延迟止损{exit_stats['delayed_exits']}笔：扩大亏损，建议更严格的止损规则"
        )
    
    if exit_stats['optimal_exits'] / max(exit_stats['total_exits'], 1) > 0.7:
        exit_lessons.append(f"平仓质量良好：{exit_stats['optimal_exits']}/{exit_stats['total_exits']}笔为最优")
    
    # 打印统计
    print(f"\n  📊 平仓质量统计：")
    print(f"     总平仓数: {exit_stats['total_exits']}")
    print(f"     ├─ 止盈: {exit_stats['tp_exits']}笔")
    print(f"     ├─ 止损: {exit_stats['sl_exits']}笔")
    print(f"     └─ 手动: {exit_stats['manual_exits']}笔")
    print(f"     质量评估：")
    print(f"     ├─ ✅ 最优: {exit_stats['optimal_exits']}笔")
    print(f"     ├─ ⚠️ 过早: {exit_stats['premature_exits']}笔 (平均错过{exit_stats['avg_missed_profit_pct']:.1f}%)")
    print(f"     └─ ⚠️ 延迟: {exit_stats['delayed_exits']}笔")
    
    return {
        'exit_stats': exit_stats,
        'premature_exits': premature_exits,
        'delayed_exits': delayed_exits,
        'optimal_exits': optimal_exits,
        'exit_table_data': exit_table_data,
        'exit_lessons': exit_lessons
    }

