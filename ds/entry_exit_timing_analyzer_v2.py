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


def classify_entry_quality(trade, objective_profit=None, matched_opportunity=None):
    """
    【V8.5.2.4.88】基于开仓信号质量的分类
    
    核心逻辑：
    1. 已平仓交易：根据实际盈亏分类
       - ✅ 正确开仓：盈利>1U
       - ⚠️ 时机问题：-2U到1U
       - ❌ 虚假信号：亏损>2U
    2. 持仓中交易：根据匹配到的机会信号质量分类
       - 🟢 强信号持仓：signal_score>=90, consensus>=3
       - 🟡 中等信号持仓：signal_score>=80, consensus>=2
       - 🔴 弱信号持仓：其他情况
    
    Args:
        trade: dict or Series, 交易记录
        objective_profit: float, 客观最大利润（暂不使用）
        matched_opportunity: dict, 匹配到的Phase 1机会（用于持仓中分析）
    
    Returns:
        str: 'correct', 'timing_issue', 'false_signal', 'holding_strong', 'holding_moderate', 'holding_weak'
    """
    # 获取平仓时间（判断是否持仓中）
    close_time = trade.get('平仓时间', trade.get('close_time'))
    
    # 情况1：已平仓 - 根据实际盈亏
    if close_time and not pd.isna(close_time) and str(close_time).strip():
        pnl_raw = trade.get('盈亏(U)', trade.get('盈亏', trade.get('PnL', trade.get('实际盈亏'))))
        if pnl_raw is None or pd.isna(pnl_raw):
            pnl = 0
        else:
            try:
                pnl = float(pnl_raw)
            except:
                pnl = 0
        
        if pnl > 1.0:
            return 'correct'
        elif pnl < -2.0:
            return 'false_signal'
        else:
            return 'timing_issue'
    
    # 情况2：持仓中 - 根据开仓信号质量
    if matched_opportunity:
        signal_score = matched_opportunity.get('signal_score', 0)
        consensus = matched_opportunity.get('consensus', 0)
        
        if signal_score >= 90 and consensus >= 3:
            return 'holding_strong'  # 强信号持仓
        elif signal_score >= 80 and consensus >= 2:
            return 'holding_moderate'  # 中等信号持仓
        else:
            return 'holding_weak'  # 弱信号持仓
    
    # 无法匹配机会
    return 'holding_unknown'


def analyze_entry_timing_v2(
    yesterday_trades_df,
    market_snapshots_df,
    ai_decisions_list,
    yesterday_date_str,
    confirmed_opportunities=None
):
    """
    【V8.3.25.15】完整的开仓时机分析（核心改进：使用回测确认的盈利机会）
    【V8.5.2.4.86】简化为3类分类，聚焦开仓质量本质
    
    核心逻辑：
    1. 使用回测确认的盈利机会（而非所有市场快照）作为基准
    2. 对比AI实际开仓记录
    3. 分类分析（3类）：
       - ✅ 正确开仓：盈利>1U（方向对+时机对）
       - ⚠️ 时机问题：-2U到1U（方向基本对，但时机不佳）
       - ❌ 虚假信号：亏损>2U（方向错误）
    
    Args:
        yesterday_trades_df: DataFrame, 昨日开仓的交易
        market_snapshots_df: DataFrame, 昨日市场快照（包含K线数据）
        ai_decisions_list: list, AI历史决策记录
        yesterday_date_str: str, 昨日日期（YYYY-MM-DD格式）
        confirmed_opportunities: list, 回测确认的盈利机会（来自analyze_separated_opportunities）
    
    Returns:
        {
            'entry_stats': {...},  # 统计数据（包含3类分类）
            'correct_entries': [...],  # ✅ 正确开仓
            'timing_issues': [...],  # ⚠️ 时机问题
            'false_entries': [...],  # ❌ 虚假信号
            'missed_opportunities': [...],  # 错过的机会
            'entry_table_data': [...],  # 邮件表格数据
            'entry_lessons': [...]  # 改进建议
        }
    """
    
    print(f"\n【开仓时机完整分析 V8.5.2.4.86 - 3类简化版】")
    
    # 初始化统计（3类分类）
    entry_stats = {
        'total_opportunities': 0,  # 昨日识别的总机会数
        'ai_opened': 0,  # AI实际开仓数
        'correct_entries': 0,  # ✅ 正确开仓
        'timing_issues': 0,  # ⚠️ 时机问题
        'false_entries': 0,  # ❌ 虚假信号
        'missed_profitable': 0,  # 错过的盈利机会
        'correctly_filtered': 0  # 正确过滤的虚假信号
    }
    
    correct_entries = []
    timing_issues = []
    false_entries = []
    missed_opportunities = []
    entry_table_data = []
    
    # ===== Step 1: 获取昨日所有市场快照 =====
    if market_snapshots_df is None or market_snapshots_df.empty:
        print(f"⚠️ 无市场快照数据，无法进行开仓时机分析")
        return {
            'entry_stats': entry_stats,
            'correct_entries': [],
            'timing_issues': [],
            'false_entries': [],
            'missed_opportunities': [],
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
            'excellent_entries': [],
            'good_entries': [],
            'timing_issues': [],
            'false_entries': [],
            'reasonable_loss_entries': [],
            'breakeven_entries': [],
            'holding_entries': [],
            'correct_entries': [],
            'missed_opportunities': [],
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
            'timing_issues': [],
            'false_entries': [],
            'missed_opportunities': [],
            'entry_table_data': [],
            'entry_lessons': ['昨日无市场快照数据']
        }
    
    # 🔧 V8.3.25.15: 如果有confirmed_opportunities，使用它代替yesterday_snapshots
    if confirmed_opportunities and len(confirmed_opportunities) > 0:
        print(f"  ✓ 使用回测确认的盈利机会：{len(confirmed_opportunities)}个")
        entry_stats['total_opportunities'] = len(confirmed_opportunities)
        # 将confirmed_opportunities转换为类似snapshot的格式，方便后续处理
        opportunities_to_check = []
        for opp in confirmed_opportunities:
            opportunities_to_check.append({
                'coin': opp.get('coin'),
                'timestamp': opp.get('timestamp'),
                'signal_score': opp.get('signal_score', 0),
                'consensus': opp.get('consensus', 0),
                'objective_profit': opp.get('objective_profit', 0),
                'direction': opp.get('direction'),
                'entry_price': opp.get('entry_price', 0)
            })
    else:
        print(f"  ⚠️ 未提供confirmed_opportunities，使用原逻辑（所有market snapshots）")
        entry_stats['total_opportunities'] = len(yesterday_snapshots)
        opportunities_to_check = None  # 标记使用原逻辑
    
    print(f"  ✓ 昨日识别到 {entry_stats['total_opportunities']} 个机会点")
    
    # 🔧 V8.3.25.12: 打印AI决策数据摘要
    if ai_decisions_list:
        print(f"  🤖 【AI决策数据】加载了 {len(ai_decisions_list)} 条决策记录")
        if len(ai_decisions_list) > 0:
            first_decision = ai_decisions_list[0]
            print(f"      第一条决策时间: {first_decision.get('timestamp', 'N/A')}")
            
            # 🔧 V8.3.32: 兼容新旧字段名 + 调试字段内容
            actions = first_decision.get('actions') or first_decision.get('operations', [])
            print(f"      包含操作数: {len(actions)}")
            
            # 🔧 V8.3.32: 如果actions为空，打印所有字段以便调试
            if not actions:
                print(f"      ⚠️  actions字段为空，显示所有可用字段:")
                for key in first_decision.keys():
                    value = first_decision[key]
                    if isinstance(value, str):
                        print(f"         {key}: {value[:100] if len(value) > 100 else value}")
                    else:
                        print(f"         {key}: {value}")
            else:
                first_action = actions[0]
                coin_display = first_action.get('coin', first_action.get('symbol', 'N/A'))
                operation_display = first_action.get('operation', first_action.get('action', 'N/A'))
                reason = first_action.get('reason', 'N/A')
                
                print(f"      样例: {coin_display} - {operation_display}")
                print(f"            理由: {reason[:80]}...")
    else:
        print(f"  ⚠️  【AI决策数据】未传入ai_decisions_list，错过机会的AI分析将不可用")
    
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
        
        # 🔧 V8.3.25.12: 添加调试信息（打印前3笔交易数据 + AI决策理由）
        if len(yesterday_trades_df) > 0:
            print(f"\n  🔍 调试：前3笔交易数据样本（含AI决策）")
            for idx_debug, trade_debug in yesterday_trades_df.head(3).iterrows():
                # 🔧 V8.3.25.12: 尝试多个字段名
                pnl_debug = trade_debug.get('盈亏(U)', trade_debug.get('盈亏', trade_debug.get('PnL', trade_debug.get('实际盈亏'))))
                open_reason_debug = trade_debug.get('开仓理由', 'N/A')
                close_reason_debug = trade_debug.get('平仓理由', 'N/A')
                
                print(f"     [{idx_debug}] 币种: {trade_debug.get('币种')}")
                print(f"         开仓时间: {trade_debug.get('开仓时间')}")
                print(f"         平仓时间: '{trade_debug.get('平仓时间')}' (type: {type(trade_debug.get('平仓时间')).__name__}, isna: {pd.isna(trade_debug.get('平仓时间'))})")
                print(f"         盈亏(U): {pnl_debug} (type: {type(pnl_debug).__name__})")
                print(f"         📝 开仓理由: {open_reason_debug[:100] if open_reason_debug != 'N/A' else 'N/A'}...")
                print(f"         🔒 平仓理由: {close_reason_debug[:100] if close_reason_debug != 'N/A' else 'N/A'}...")
                print()
        
        # ===== Step 3: 对比分析每个机会点 =====
        # 🔧 V8.3.25.15: 根据opportunities_to_check选择不同的处理路径
        matched_trades_count = 0
        debug_first_snapshot = True  # 调试第一个snapshot
        
        if opportunities_to_check is not None:
            # 【新逻辑】使用confirmed_opportunities
            for opp in opportunities_to_check:
                coin = opp.get('coin', '')
                timestamp_str = opp.get('timestamp', '')  # YYYYMMDD HH:MM:SS格式
                signal_score = opp.get('signal_score', 0)
                consensus = opp.get('consensus', 0)
                objective_profit = opp.get('objective_profit', 0)
                
                # 解析时间戳
                try:
                    opp_time_dt = pd.to_datetime(timestamp_str)
                except:
                    continue
                
                # 匹配AI开仓记录（±5分钟）
                matching_trades = yesterday_trades_df[
                    (yesterday_trades_df['币种'] == coin) &
                    (pd.to_datetime(yesterday_trades_df['开仓时间']) >= opp_time_dt - timedelta(minutes=5)) &
                    (pd.to_datetime(yesterday_trades_df['开仓时间']) <= opp_time_dt + timedelta(minutes=5))
                ]
                
                if matching_trades.empty:
                    # AI没开仓 → 错过的机会
                    # 查找AI当时的决策理由
                    ai_reason = "未找到AI决策记录"
                    
                    # 🔧 V8.3.32: 添加调试输出
                    if False:  # 设置为True时启用调试
                        print(f"  🔍 【调试AI匹配】错过的机会")
                        print(f"     币种: {coin}")
                        print(f"     机会时间: {timestamp_str}")
                        print(f"     机会时间解析: {opp_time_dt}")
                        print(f"     AI决策数: {len(ai_decisions_list) if ai_decisions_list else 0}")
                        if ai_decisions_list and len(ai_decisions_list) > 0:
                            first_dec = ai_decisions_list[0]
                            print(f"     第一条AI决策时间: {first_dec.get('timestamp', 'N/A')}")
                            print(f"     第一条AI决策actions数: {len(first_dec.get('actions', []))}")
                    
                    if ai_decisions_list:
                        # 🔧 V8.3.32.8: 优化AI决策匹配，区分"未运行"和"主动不开仓"
                        # 1. 获取AI决策的时间范围
                        earliest_ai_time = None
                        latest_ai_time = None
                        try:
                            timestamps_ai = [pd.to_datetime(d.get('timestamp', '')) for d in ai_decisions_list if d.get('timestamp')]
                            if timestamps_ai:
                                earliest_ai_time = min(timestamps_ai)
                                latest_ai_time = max(timestamps_ai)
                        except:
                            pass
                        
                        # 2. 判断机会时间是否在AI运行期间
                        if earliest_ai_time and opp_time_dt < earliest_ai_time:
                            # 机会发生在AI最早记录之前 → 机器人未运行
                            time_before_start = (earliest_ai_time - opp_time_dt).total_seconds() / 3600
                            ai_reason = f"机器人未运行（机会时间早于AI最早记录{time_before_start:.1f}小时）"
                        elif latest_ai_time and opp_time_dt > latest_ai_time + pd.Timedelta(hours=2):
                            # 机会发生在AI最晚记录2小时之后 → 机器人可能已停止
                            time_after_stop = (opp_time_dt - latest_ai_time).total_seconds() / 3600
                            ai_reason = f"机器人可能已停止（机会时间晚于AI最晚记录{time_after_stop:.1f}小时）"
                        else:
                            # 机会在AI运行期间 → 找最接近的决策
                            closest_decision = None
                            min_time_diff = float('inf')
                            
                            for decision in ai_decisions_list:
                                decision_time_str = decision.get('timestamp', '')
                                if decision_time_str:
                                    try:
                                        decision_time = pd.to_datetime(decision_time_str)
                                        time_diff_seconds = abs((decision_time - opp_time_dt).total_seconds())
                                        
                                        # 只匹配2小时内的决策
                                        if time_diff_seconds < 7200 and time_diff_seconds < min_time_diff:
                                            min_time_diff = time_diff_seconds
                                            closest_decision = decision
                                    except Exception as e:
                                        continue
                            
                            # 如果找到最接近的决策
                            if closest_decision:
                                # 获取AI的决策理由（按价值优先级）
                                analysis_summary = closest_decision.get('analysis', '')
                                risk_assessment = closest_decision.get('risk_assessment', '')
                                thinking_process = closest_decision.get('思考过程', '')
                                
                                # 获取操作记录（用于补充说明）
                                operations = closest_decision.get('operations') or closest_decision.get('actions', [])
                                
                                # 计算时间差（分钟）
                                time_diff_minutes = min_time_diff / 60
                                
                                # 构建AI决策理由（优先顺序：analysis > risk_assessment > 思考过程）
                                if analysis_summary:
                                    ai_reason = f"【AI分析·{time_diff_minutes:.0f}min】{analysis_summary[:120]}"
                                elif risk_assessment:
                                    ai_reason = f"【风险评估·{time_diff_minutes:.0f}min】{risk_assessment[:120]}"
                                elif thinking_process:
                                    ai_reason = f"【AI思考·{time_diff_minutes:.0f}min】{thinking_process[:120]}"
                                else:
                                    ai_reason = f"AI有决策记录但分析字段缺失（时间差{time_diff_minutes:.0f}分钟）"
                                
                                # 补充：显示实际开仓的币种（过滤掉HOLD，只关注实际操作）
                                if operations:
                                    real_ops = [op for op in operations if op.get('action', op.get('operation', '')) not in ['HOLD', 'hold', 'Hold']]
                                    if real_ops:
                                        operated_coins = [f"{op.get('coin', op.get('symbol', ''))[:3]}-{op.get('action', op.get('operation', ''))[:4]}" for op in real_ops[:2]]
                                        ai_reason += f" ║操作:{','.join(operated_coins)}"
                            else:
                                ai_reason = "AI运行期间但无匹配决策（可能记录被覆盖）"
                    else:
                        ai_reason = "无AI决策记录（AI决策列表为空）"
                    
                    missed_opportunities.append({
                        'coin': coin,
                        'time': timestamp_str,
                        'signal_score': signal_score,
                        'consensus': consensus,
                        'potential_profit': objective_profit,
                        'reason': f'回测确认盈利{objective_profit:.1f}%，AI决策：{ai_reason}'
                    })
                    entry_stats['missed_profitable'] += 1
                else:
                    # AI开仓了 → 使用新的3类分类
                    matched_trades_count += len(matching_trades)
                    trade = matching_trades.iloc[0]
                    
                    # 【V8.5.2.4.88】传递匹配到的机会信息（用于持仓中分析）
                    matched_opp = {
                        'signal_score': signal_score,
                        'consensus': consensus,
                        'objective_profit': objective_profit
                    }
                    category = classify_entry_quality(trade, objective_profit, matched_opp)
                    
                    # 获取盈亏（用于显示）
                    pnl_raw = trade.get('盈亏(U)', trade.get('盈亏', trade.get('PnL')))
                    pnl = float(pnl_raw) if pnl_raw and not pd.isna(pnl_raw) else 0
                    
                    # 构建基础记录
                    entry_record = {
                            'coin': coin,
                            'time': timestamp_str,
                            'signal_score': signal_score,
                            'consensus': consensus,
                            'pnl': pnl,
                            'ai_open_reason': trade.get('开仓理由', 'N/A'),
                            'ai_close_reason': trade.get('平仓理由', 'N/A')
                    }
                    
                    # 根据分类添加到对应列表
                    if category == 'correct':
                        entry_record['reason'] = f'✅ 正确开仓：盈利{pnl:.2f}U'
                        correct_entries.append(entry_record)
                        entry_stats['correct_entries'] += 1
                    elif category == 'timing_issue':
                        entry_record['reason'] = f'⚠️ 时机问题：盈亏{pnl:+.2f}U'
                        timing_issues.append(entry_record)
                        entry_stats['timing_issues'] += 1
                    elif category == 'false_signal':
                        entry_record['reason'] = f'❌ 虚假信号：亏损{pnl:.2f}U'
                        false_entries.append(entry_record)
                        entry_stats['false_entries'] += 1
                    elif category == 'holding_strong':
                        entry_record['reason'] = f'⏳ 持仓中（强信号：score={signal_score}, consensus={consensus}）'
                        holding_entries.append(entry_record)
                        entry_stats['holding'] += 1
                    elif category == 'holding_moderate':
                        entry_record['reason'] = f'⏳ 持仓中（中等信号：score={signal_score}, consensus={consensus}）'
                        holding_entries.append(entry_record)
                        entry_stats['holding'] += 1
                    elif category in ['holding_weak', 'holding_unknown']:
                        entry_record['reason'] = f'⏳ 持仓中（弱信号或无匹配）'
                        holding_entries.append(entry_record)
                        entry_stats['holding'] += 1
        else:
            # 【原逻辑】使用yesterday_snapshots
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
                    # 🔧 V8.3.25.14: 使用K线回测确认是否真的错过盈利机会
                    
                    # 获取这个snapshot的后续K线数据（后续4小时）
                    coin_klines = market_snapshots_df[
                        (market_snapshots_df['coin'] == coin) &
                        (market_snapshots_df['full_datetime'] > snapshot_time_dt) &
                        (market_snapshots_df['full_datetime'] <= snapshot_time_dt + timedelta(hours=4))
                    ].copy()
                    
                    is_truly_missed = False
                    potential_profit_pct = 0
                    
                    if not coin_klines.empty:
                        # 从snapshot中获取方向和TP/SL信息
                        direction = snapshot.get('direction', 'N/A')  # 'long' or 'short'
                        entry_price = snapshot.get('close', 0)  # 使用snapshot的close价格作为入场价
                        tp_price = snapshot.get('tp', 0)
                        sl_price = snapshot.get('sl', 0)
                        
                        if entry_price > 0 and tp_price > 0:
                            # 检查后续K线是否触及TP
                            if direction == 'long':
                                # 多单：检查high是否触及TP
                                hit_tp = (coin_klines['high'] >= tp_price).any()
                                hit_sl = (coin_klines['low'] <= sl_price).any() if sl_price > 0 else False
                                
                                if hit_tp:
                                    # 检查TP是否在SL之前触发
                                    if hit_sl:
                                        # 找到第一个触及TP和SL的时间
                                        tp_time = coin_klines[coin_klines['high'] >= tp_price]['full_datetime'].min()
                                        sl_time = coin_klines[coin_klines['low'] <= sl_price]['full_datetime'].min()
                                        if tp_time < sl_time:
                                            is_truly_missed = True
                                            potential_profit_pct = (tp_price - entry_price) / entry_price * 100
                                    else:
                                        is_truly_missed = True
                                        potential_profit_pct = (tp_price - entry_price) / entry_price * 100
                            
                            elif direction == 'short':
                                # 空单：检查low是否触及TP
                                hit_tp = (coin_klines['low'] <= tp_price).any()
                                hit_sl = (coin_klines['high'] >= sl_price).any() if sl_price > 0 else False
                                
                                if hit_tp:
                                    # 检查TP是否在SL之前触发
                                    if hit_sl:
                                        tp_time = coin_klines[coin_klines['low'] <= tp_price]['full_datetime'].min()
                                        sl_time = coin_klines[coin_klines['high'] >= sl_price]['full_datetime'].min()
                                        if tp_time < sl_time:
                                            is_truly_missed = True
                                            potential_profit_pct = (entry_price - tp_price) / entry_price * 100
                                    else:
                                        is_truly_missed = True
                                        potential_profit_pct = (entry_price - tp_price) / entry_price * 100
                    
                    if is_truly_missed:
                        # 确认是错过的机会（后续K线确实触及TP）
                        missed_opportunities.append({
                            'coin': coin,
                            'time': str(snapshot_time),
                            'signal_score': signal_score,
                            'consensus': consensus,
                            'potential_profit': potential_profit_pct,
                            'reason': f'K线回测确认：{direction}单 后续触及TP（+{potential_profit_pct:.1f}%）'
                        })
                        entry_stats['missed_profitable'] += 1
                    else:
                        # 正确过滤（后续没有触及TP，或先触及SL）
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
    
    # 【V8.5.2.4.82】Step 3.5: 确保所有交易都被分类
    # 【V8.5.2.4.86】检查是否有未分类的交易（3类分类）
    total_classified = (
        entry_stats['correct_entries'] + 
        entry_stats['timing_issues'] + 
        entry_stats['false_entries']
    )
    
    if total_classified < entry_stats['ai_opened']:
        print(f"\n  ⚠️  【警告】发现{entry_stats['ai_opened'] - total_classified}笔未分类交易")
        print(f"     已分类: {total_classified}笔, 实际开仓: {entry_stats['ai_opened']}笔")
        
        # 找出未分类的交易并强制分类
        classified_times = set()
        for entry_list in [correct_entries, timing_issues, false_entries]:
            for entry in entry_list:
                classified_times.add(entry.get('time', ''))
        
        # 遍历所有交易，找出未分类的
        for idx, trade in yesterday_trades_df.iterrows():
            open_time = str(trade.get('开仓时间', ''))
            if open_time not in classified_times:
                # 未分类的交易，使用分类函数强制分类
                category = classify_entry_quality(trade)
                
                pnl_raw = trade.get('盈亏(U)', trade.get('盈亏', trade.get('PnL')))
                pnl = float(pnl_raw) if pnl_raw and not pd.isna(pnl_raw) else 0
                
                entry_record = {
                    'coin': trade.get('币种', 'N/A'),
                    'time': open_time,
                    'signal_score': 0,
                    'consensus': 0,
                    'pnl': pnl,
                    'reason': f'未匹配机会池的交易（{category}）',
                    'ai_open_reason': trade.get('开仓理由', 'N/A'),
                    'ai_close_reason': trade.get('平仓理由', 'N/A')
                }
                
                # 根据分类添加（持仓中的交易category=None，不计入统计）
                if category == 'correct':
                    correct_entries.append(entry_record)
                    entry_stats['correct_entries'] += 1
                elif category == 'timing_issue':
                    timing_issues.append(entry_record)
                    entry_stats['timing_issues'] += 1
                elif category == 'false_signal':
                    false_entries.append(entry_record)
                    entry_stats['false_entries'] += 1
                # category == None（持仓中）不计入统计
                
                if category:
                    print(f"     └─ 已分类: {trade.get('币种')} @ {open_time} → {category}")
    
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
    
    # 【V8.5.2.4.86】打印统计（3类简化版）
    print(f"\n  📊 开仓质量统计：")
    print(f"     总机会数: {entry_stats['total_opportunities']}")
    print(f"     AI开仓: {entry_stats['ai_opened']} ({entry_stats['ai_opened']/max(entry_stats['total_opportunities'],1)*100:.0f}%)")
    
    # 【V8.5.2.4.88】已平仓交易分类
    closed_count = entry_stats['correct_entries'] + entry_stats['timing_issues'] + entry_stats['false_entries']
    print(f"     ├─ 已平仓: {closed_count}笔")
    print(f"     │  ├─ ✅ 正确开仓: {entry_stats['correct_entries']}笔 ({entry_stats['correct_entries']/max(closed_count,1)*100:.0f}%)")
    print(f"     │  ├─ ⚠️ 时机问题: {entry_stats['timing_issues']}笔 ({entry_stats['timing_issues']/max(closed_count,1)*100:.0f}%)")
    print(f"     │  └─ ❌ 虚假信号: {entry_stats['false_entries']}笔 ({entry_stats['false_entries']/max(closed_count,1)*100:.0f}%)")
    
    # 【V8.5.2.4.88】持仓中交易分类
    holding_count = entry_stats.get('holding', 0)
    if holding_count > 0:
        # 统计持仓中交易的信号质量分布
        holding_strong = len([e for e in holding_entries if '强信号' in e.get('reason', '')])
        holding_moderate = len([e for e in holding_entries if '中等信号' in e.get('reason', '')])
        holding_weak = holding_count - holding_strong - holding_moderate
        
        print(f"     └─ ⏳ 持仓中: {holding_count}笔")
        if holding_strong > 0:
            print(f"        ├─ 🟢 强信号: {holding_strong}笔 (score>=90, consensus>=3)")
        if holding_moderate > 0:
            print(f"        ├─ 🟡 中等信号: {holding_moderate}笔 (score>=80, consensus>=2)")
        if holding_weak > 0:
            print(f"        └─ 🔴 弱信号: {holding_weak}笔")
    
    total_classified = closed_count + holding_count
    print(f"     分类合计: {total_classified}笔 {'✅' if total_classified == entry_stats['ai_opened'] else '❌ 不等于AI开仓数'}")
    print(f"     错过机会: {entry_stats['missed_profitable']}")
    print(f"     正确过滤: {entry_stats['correctly_filtered']}")
    print(f"  🔍 【调试】共匹配到 {matched_trades_count} 笔交易与market snapshot关联")
    print(f"  🔍 【调试】昨日交易总数: {len(yesterday_trades_df)} 笔")
    
    # 🔧 V8.3.25.20: 限制错过机会数量，只保留利润最高的TOP 30，避免AI信息过载
    if len(missed_opportunities) > 30:
        missed_opportunities_sorted = sorted(missed_opportunities, key=lambda x: x.get('potential_profit', 0), reverse=True)
        missed_opportunities_top30 = missed_opportunities_sorted[:30]
        print(f"  ℹ️  【优化】错过机会过多({len(missed_opportunities)}个)，只保留TOP 30用于AI分析")
        missed_opportunities_for_ai = missed_opportunities_top30
    else:
        missed_opportunities_for_ai = missed_opportunities
    
    # 【V8.5.2.4.82】返回7类完整分类
    return {
        'entry_stats': entry_stats,
        # 【V8.5.2.4.86】新的3类分类
        'correct_entries': correct_entries,  # ✅ 正确开仓
        'timing_issues': timing_issues,  # ⚠️ 时机问题
        'false_entries': false_entries,  # ❌ 虚假信号
        'missed_opportunities': missed_opportunities_for_ai,  # 🔧 V8.3.25.20: 传递筛选后的TOP 30
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
        signal_score = trade.get('信号分数', 0)  # 🔧 V8.5.2.3: 修正字段名（与保存时一致）
        consensus = trade.get('共振指标数', 0)  # 🔧 V8.5.2.3: 修正字段名（与保存时一致）
        
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
                # 🔧 V8.3.25.15: 指定format避免warning
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

