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
    # 🔧 V8.3.25.8: 使用snapshot_date列（YYYYMMDD格式）而不是解析time列
    yesterday_date_yyyymmdd = yesterday_date_str.replace('-', '')  # "2025-11-11" -> "20251111"
    
    if 'snapshot_date' not in market_snapshots_df.columns:
        print(f"⚠️ 市场快照数据缺少snapshot_date列（旧格式），无法筛选昨日数据")
        return {
            'entry_stats': entry_stats,
            'correct_entries': [],
            'false_entries': [],
            'missed_opportunities': [],
            'timing_issues': [],
            'entry_table_data': [],
            'entry_lessons': ['市场快照数据格式不兼容（缺少snapshot_date列）']
        }
    
    yesterday_snapshots = market_snapshots_df[
        market_snapshots_df['snapshot_date'] == yesterday_date_yyyymmdd
    ].copy()
    
    if yesterday_snapshots.empty:
        print(f"⚠️ 昨日({yesterday_date_yyyymmdd})无市场快照数据")
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
    
    # 🔧 V8.3.25.12: 调试快照数据
    if len(yesterday_snapshots) > 0:
        first_snapshot = yesterday_snapshots.iloc[0]
        print(f"  🔍 【调试】第一个快照数据:")
        print(f"      币种: {first_snapshot.get('coin')}")
        print(f"      time: {first_snapshot.get('time')}")
        print(f"      snapshot_date: {first_snapshot.get('snapshot_date')}")
        print(f"      full_datetime: {first_snapshot.get('full_datetime') if 'full_datetime' in first_snapshot else 'N/A'}")
    
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
        
        # 🔧 V8.3.25.12: 添加调试信息（打印前3笔交易数据）
        if len(yesterday_trades_df) > 0:
            print(f"\n  🔍 调试：前3笔交易数据样本")
            for idx_debug, trade_debug in yesterday_trades_df.head(3).iterrows():
                # 🔧 V8.3.25.12: 尝试多个字段名
                pnl_debug = trade_debug.get('盈亏(U)', trade_debug.get('盈亏', trade_debug.get('PnL', trade_debug.get('实际盈亏'))))
                print(f"     [{idx_debug}] 币种: {trade_debug.get('币种')}")
                print(f"         开仓时间: {trade_debug.get('开仓时间')}")
                print(f"         平仓时间: '{trade_debug.get('平仓时间')}' (type: {type(trade_debug.get('平仓时间')).__name__}, isna: {pd.isna(trade_debug.get('平仓时间'))})")
                print(f"         盈亏(U): {pnl_debug} (type: {type(pnl_debug).__name__})")
                print()
        
        # ===== Step 3: 对比分析每个机会点 =====
        # 🔧 V8.3.25.12: 统计有多少交易被匹配
        matched_trades_count = 0
        debug_first_snapshot = True  # 调试第一个snapshot
        
        for idx, snapshot in yesterday_snapshots.iterrows():
            coin = snapshot.get('coin', '')
            snapshot_time = snapshot.get('time')  # HH:MM格式
            signal_score = snapshot.get('signal_score', 0)
            consensus = snapshot.get('consensus', 0)
            
            # 查找是否有对应的开仓记录（±5分钟窗口）
            # 🔧 V8.3.25.8: 使用full_datetime列（包含日期和时间）
            if 'full_datetime' in snapshot and pd.notna(snapshot['full_datetime']):
                snapshot_time_dt = snapshot['full_datetime']
            else:
                # Fallback：尝试从snapshot_date和time构建时间戳
                try:
                    snapshot_time_dt = pd.to_datetime(f"{snapshot['snapshot_date']} {snapshot_time}", format='%Y%m%d %H:%M')
                except:
                    continue  # 无法解析时间，跳过此快照
            
            # 🔧 V8.3.25.12: 调试第一个snapshot
            if debug_first_snapshot:
                print(f"  🔍 【调试】第一个snapshot:")
                print(f"      币种: {coin}")
                print(f"      snapshot_time_dt: {snapshot_time_dt} (type: {type(snapshot_time_dt)})")
                print(f"      匹配窗口: {snapshot_time_dt - timedelta(minutes=5)} ~ {snapshot_time_dt + timedelta(minutes=5)}")
                if len(yesterday_trades_df) > 0:
                    first_trade_open_time = pd.to_datetime(yesterday_trades_df.iloc[0]['开仓时间'])
                    print(f"      第一笔交易开仓时间: {first_trade_open_time}")
                debug_first_snapshot = False
            
            matching_trades = yesterday_trades_df[
                (yesterday_trades_df['币种'] == coin) &
                (pd.to_datetime(yesterday_trades_df['开仓时间']) >= snapshot_time_dt - timedelta(minutes=5)) &
                (pd.to_datetime(yesterday_trades_df['开仓时间']) <= snapshot_time_dt + timedelta(minutes=5))
            ]
            
            if matching_trades.empty:
                # 情况1: AI没开仓（错过机会 or 正确过滤）
                # 🔧 V8.3.25.8: 简化逻辑 - 高信号分视为错过机会，低信号分视为正确过滤
                # 注：完整评估需要后续K线数据，暂时用信号质量近似判断
                
                # 使用信号质量作为判断标准
                is_high_quality = (signal_score >= 75 and consensus >= 3) or signal_score >= 85
                
                if is_high_quality:
                    # 高质量信号但未开仓 → 可能是错过的机会
                    missed_opportunities.append({
                        'coin': coin,
                        'time': str(snapshot_time),
                        'signal_score': signal_score,
                        'consensus': consensus,
                        'potential_profit': 0,  # 需要后续K线数据才能计算，暂时0
                        'reason': f'高质量信号（{signal_score}分/{consensus}共振）但参数过滤'
                    })
                    entry_stats['missed_profitable'] += 1
                else:
                    # 低质量信号未开仓 → 正确过滤
                    entry_stats['correctly_filtered'] += 1
            else:
                # 情况2: AI开仓了
                matched_trades_count += len(matching_trades)  # 🔧 V8.3.25.12: 统计匹配数
                trade = matching_trades.iloc[0]
                # 🔧 V8.3.25.12: 兼容多种字段名（盈亏(U)/盈亏/PnL/实际盈亏）+ 处理None
                pnl_raw = trade.get('盈亏(U)', trade.get('盈亏', trade.get('PnL', trade.get('实际盈亏'))))
                # 🔧 V8.3.25.12: 处理None/NaN/空值，默认为0
                if pnl_raw is None or pd.isna(pnl_raw):
                    pnl = 0
                else:
                    try:
                        pnl = float(pnl_raw)
                    except (ValueError, TypeError):
                        pnl = 0
                
                exit_reason = trade.get('平仓原因', trade.get('平仓类型', ''))
                
                # 🔧 V8.3.25.12: 增强is_closed判断，处理空字符串和NaN
                exit_time_value = trade.get('平仓时间')
                exit_price_value = trade.get('平仓价格', 0)
                is_closed = (
                    not pd.isna(exit_time_value) and
                    exit_time_value != '' and
                    exit_time_value != 'N/A' and
                    str(exit_time_value).strip() != '' and
                    exit_price_value > 0 and  # 额外检查：平仓价格必须>0
                    pnl != 0  # 🔧 V8.3.25.12: 如果pnl为0且有平仓时间，可能是数据未同步
                )
                
                # 🔧 V8.3.25.12: 调试输出（仅前3笔）+ 添加AI决策理由
                if entry_stats['ai_opened'] <= 3:
                    open_reason = trade.get('开仓理由', 'N/A')
                    close_reason = trade.get('平仓理由', 'N/A')
                    print(f"     🔍 [{coin}] is_closed判断:")
                    print(f"        平仓时间: '{exit_time_value}' (isna: {pd.isna(exit_time_value)})")
                    print(f"        平仓价格: {exit_price_value}")
                    print(f"        盈亏: {pnl}")
                    print(f"        结果: is_closed={is_closed}")
                    print(f"        📝 开仓理由: {open_reason[:100]}...")  # 显示前100字符
                    print(f"        🔒 平仓理由: {close_reason[:100] if close_reason != 'N/A' else 'N/A'}...")
                
                # 🔧 V8.3.25.12: 如果交易还未平仓，标记为"进行中"
                if not is_closed:
                    # 未平仓交易，暂时标记为"进行中"
                    timing_issues.append({
                        'coin': coin,
                        'time': str(snapshot_time),
                        'signal_score': signal_score,
                        'consensus': consensus,
                        'pnl': 0,
                        'reason': '交易进行中（未平仓）'
                    })
                    entry_stats['timing_issues'] += 1
                    
                    # 添加到表格数据
                    entry_table_data.append({
                        'coin': coin,
                        'time': str(snapshot_time),
                        'signal_score': signal_score,
                        'consensus': consensus,
                        'ai_action': '✅ 开仓',
                        'result': '进行中',
                        'evaluation': '⏳ 进行中'
                    })
                else:
                    # 已平仓交易，判断开仓质量
                    # 🔧 V8.3.25.12: 提取开仓/平仓理由，传递给AI深度分析
                    open_reason_full = trade.get('开仓理由', 'N/A')
                    close_reason_full = trade.get('平仓理由', 'N/A')
                    
                    if pnl < -0.5 and ('止损' in exit_reason or 'SL' in exit_reason.upper()):
                        # 虚假信号：开仓后快速止损
                        false_entries.append({
                            'coin': coin,
                            'time': str(snapshot_time),
                            'signal_score': signal_score,
                            'consensus': consensus,
                            'pnl': pnl,
                            'reason': '虚假信号：开仓后快速止损',
                            'ai_open_reason': open_reason_full,  # 🆕 AI开仓理由
                            'ai_close_reason': close_reason_full  # 🆕 AI平仓理由
                        })
                        entry_stats['false_entries'] += 1
                    elif pnl > 0.1:  # 🔧 V8.3.25.11: 至少盈利0.1U才算正确
                        # 正确开仓
                        correct_entries.append({
                            'coin': coin,
                            'time': str(snapshot_time),
                            'signal_score': signal_score,
                            'consensus': consensus,
                            'pnl': pnl,
                            'reason': f'正确开仓：盈利{pnl:.2f}U',
                            'ai_open_reason': open_reason_full,  # 🆕 AI开仓理由
                            'ai_close_reason': close_reason_full  # 🆕 AI平仓理由
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
                            'reason': f'时机问题：盈亏接近0（{pnl:+.2f}U）',
                            'ai_open_reason': open_reason_full,  # 🆕 AI开仓理由
                            'ai_close_reason': close_reason_full  # 🆕 AI平仓理由
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
                        'evaluation': '✅ 正确' if pnl > 0.1 else '❌ 虚假信号' if pnl < -0.5 else '⚠️ 时机问题'
                    })
        
        # 🔧 V8.3.25.12: 打印错过机会的详细信息（包括AI决策）
        if missed_opportunities:
            print(f"\n  💡 错过机会详细分析（TOP 5）:")
            for idx, opp in enumerate(missed_opportunities[:5], 1):
                print(f"     [{idx}] {opp['coin']} @ {opp['time']}")
                print(f"         信号质量: {opp['signal_score']}分 / {opp['consensus']}共振")
                print(f"         错过原因: {opp['reason']}")
                
                # 🔧 V8.3.25.12: 尝试从ai_decisions_list获取当时的AI决策
                if ai_decisions_list:
                    # 匹配时间窗口
                    opp_time = opp['time']  # HH:MM格式
                    matching_decisions = []
                    for decision in ai_decisions_list:
                        decision_time = decision.get('timestamp', '')
                        if opp_time in decision_time:  # 简单匹配HH:MM
                            # 检查是否有关于该币种的决策
                            actions = decision.get('actions', [])
                            for action in actions:
                                if opp['coin'] in action.get('coin', ''):
                                    matching_decisions.append(action.get('reason', 'N/A'))
                    
                    if matching_decisions:
                        print(f"         🤖 AI当时决策: {matching_decisions[0][:80]}...")
                    else:
                        print(f"         🤖 AI当时决策: 无匹配记录（可能未到达决策阈值）")
                print()
        
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
    print(f"  🔍 【调试】共匹配到 {matched_trades_count} 笔交易与market snapshot关联")
    print(f"  🔍 【调试】昨日交易总数: {len(yesterday_trades_df)} 笔")
    
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
        entry_time_str = trade.get('开仓时间', '')  # 🔧 V8.3.25.9: 添加开仓时间
        exit_time_str = trade.get('平仓时间', '')
        exit_reason = trade.get('平仓原因', '')
        pnl = trade.get('盈亏', 0)
        signal_score = trade.get('信号评分', 0)  # 🔧 V8.3.25.9: 添加信号评分
        consensus = trade.get('共振数', 0)  # 🔧 V8.3.25.9: 添加共振数
        
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
                coin_klines['time'] = pd.to_datetime(coin_klines['time'])
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
                    
                    # 🔧 V8.3.25.12: 提取完整的开仓/平仓理由，传递给AI深度分析
                    ai_open_reason = trade.get('开仓理由', 'N/A')
                    ai_close_reason = trade.get('平仓理由', 'N/A')
                    
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
                            'recommendation': f'TP扩大{1.3:.1f}倍' if missed_profit_pct > 3 else 'TP扩大1.2倍',
                            'ai_open_reason': ai_open_reason,  # 🆕 AI开仓理由
                            'ai_close_reason': ai_close_reason  # 🆕 AI平仓理由
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
                            'recommendation': '提前止损或扩大止损距离',
                            'ai_open_reason': ai_open_reason,  # 🆕 AI开仓理由
                            'ai_close_reason': ai_close_reason  # 🆕 AI平仓理由
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
                            'recommendation': '继续保持',
                            'ai_open_reason': ai_open_reason,  # 🆕 AI开仓理由
                            'ai_close_reason': ai_close_reason  # 🆕 AI平仓理由
                        })
                    
                    # 添加到表格数据
                    # 🔧 V8.3.25.9: 添加entry_time, signal_score, consensus字段
                    exit_table_data.append({
                        'coin': coin,
                        'side': side,
                        'entry_time': entry_time_str,  # 🆕 开仓时间
                        'entry_price': entry_price,
                        'exit_price': exit_price,
                        'exit_type': exit_type,
                        'pnl': pnl,
                        'signal_score': signal_score,  # 🆕 信号评分
                        'consensus': consensus,  # 🆕 共振数
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
        
        # 🔧 V8.3.25.9: 添加entry_time, signal_score, consensus字段
        exit_table_data.append({
            'coin': coin,
            'side': side,
            'entry_time': entry_time_str,  # 🆕 开仓时间
            'entry_price': entry_price,
            'exit_price': exit_price,
            'exit_type': exit_type,
            'pnl': pnl,
            'signal_score': signal_score,  # 🆕 信号评分
            'consensus': consensus,  # 🆕 共振数
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

