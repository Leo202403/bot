"""
【V8.3.22】开仓时机分析模块
【V8.3.23】AI自主学习版：使用AI深度分析并生成英文洞察
独立文件便于维护和测试
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
import os
from openai import OpenAI


def analyze_entry_timing(yesterday_trades, kline_snapshots, missed_opportunities):
    """
    【V8.3.22】分析开仓时机质量
    
    四个维度分析：
    1. 虚假信号开仓：开仓后快速止损，且市场未按预期方向走
    2. 延迟开仓：错过最佳入场点，导致R:R降低或盈利减少
    3. 过早开仓：趋势未确认就入场，导致被洗盘止损
    4. 错过机会深度分析：为什么没开仓（参数/信号/趋势问题）
    
    Args:
        yesterday_trades: DataFrame, 昨日开仓的交易
        kline_snapshots: DataFrame, K线快照数据
        missed_opportunities: list, 错过的机会列表（来自analyze_missed_opportunities）
    
    Returns:
        {
            'entry_stats': {...},  # 统计数据
            'false_entries': [...],  # 虚假信号案例
            'delayed_entries': [...],  # 延迟开仓案例
            'premature_entries': [...],  # 过早开仓案例
            'missed_quality_analysis': {...},  # 错过机会的深度分析
            'entry_lessons': [...]  # 可执行的改进建议
        }
    """
    
    entry_stats = {
        'total_entries': len(yesterday_trades),
        'false_entries': 0,
        'delayed_entries': 0,
        'premature_entries': 0,
        'optimal_entries': 0
    }
    
    false_entries = []
    delayed_entries = []
    premature_entries = []
    entry_lessons = []
    
    # ===== 分析1：虚假信号开仓 =====
    for idx, trade in yesterday_trades.iterrows():
        coin = trade.get('币种', '')
        side = trade.get('方向', '')
        entry_time_str = trade.get('开仓时间', '')
        entry_price = trade.get('开仓价格', 0)
        pnl = trade.get('盈亏', 0)
        exit_reason = trade.get('平仓原因', '')
        
        if not entry_time_str or entry_price == 0:
            continue
        
        try:
            entry_time = pd.to_datetime(entry_time_str)
        except:
            continue
        
        # 获取该币种的K线数据
        coin_klines = kline_snapshots[kline_snapshots['coin'] == coin].copy()
        if coin_klines.empty:
            continue
        
        coin_klines['time'] = pd.to_datetime(coin_klines['time'])
        coin_klines = coin_klines.sort_values('time')
        
        # 【虚假信号判断】：开仓后2小时内止损，且后续4小时未回到入场价
        if '止损' in exit_reason and pnl < 0:
            # 获取开仓后的K线（2小时窗口用于止损判断）
            sl_window_klines = coin_klines[
                (coin_klines['time'] >= entry_time) & 
                (coin_klines['time'] <= entry_time + timedelta(hours=2))
            ]
            
            # 获取止损后的K线（4小时窗口用于验证方向）
            validation_klines = coin_klines[
                (coin_klines['time'] > entry_time + timedelta(hours=2)) & 
                (coin_klines['time'] <= entry_time + timedelta(hours=6))
            ]
            
            if not sl_window_klines.empty and not validation_klines.empty:
                # 检查止损后市场是否按预期方向走
                if side == '多':
                    # 多单止损后，如果后续价格仍未上涨回入场价，说明是虚假信号
                    max_price_after = validation_klines['high'].max()
                    is_false_signal = max_price_after < entry_price * 0.99  # 未回到入场价的99%
                else:
                    # 空单止损后，如果后续价格仍未下跌回入场价，说明是虚假信号
                    min_price_after = validation_klines['low'].min()
                    is_false_signal = min_price_after > entry_price * 1.01  # 未回到入场价的101%
                
                if is_false_signal:
                    entry_stats['false_entries'] += 1
                    
                    # 分析信号质量（从trade记录中提取）
                    signal_score = trade.get('信号评分', 0)
                    consensus = trade.get('共振指标', 0)
                    
                    false_entries.append({
                        'coin': coin,
                        'side': side,
                        'entry_time': entry_time_str,
                        'entry_price': entry_price,
                        'pnl': pnl,
                        'signal_score': signal_score,
                        'consensus': consensus,
                        'issue': f"开仓后{len(sl_window_klines)*5}分钟止损，且后续{len(validation_klines)*5}分钟未恢复",
                        'lesson': f"信号{signal_score}分+共振{consensus}不足以过滤此虚假信号"
                    })
        
        # 【延迟开仓判断】：检查入场前是否有更好的价格
        entry_window_klines = coin_klines[
            (coin_klines['time'] >= entry_time - timedelta(hours=2)) & 
            (coin_klines['time'] < entry_time)
        ]
        
        if not entry_window_klines.empty:
            if side == '多':
                # 多单：入场前2小时的最低价
                best_entry_price = entry_window_klines['low'].min()
                price_improvement_pct = (entry_price - best_entry_price) / best_entry_price * 100
                
                # 如果实际入场价比最佳价高2%以上，视为延迟
                if price_improvement_pct > 2.0:
                    entry_stats['delayed_entries'] += 1
                    delayed_entries.append({
                        'coin': coin,
                        'side': side,
                        'entry_time': entry_time_str,
                        'actual_entry': entry_price,
                        'best_entry': best_entry_price,
                        'missed_improvement': price_improvement_pct,
                        'issue': f"错过更低{price_improvement_pct:.1f}%的入场点",
                        'lesson': f"信号出现时应立即执行，避免等待"
                    })
            else:
                # 空单：入场前2小时的最高价
                best_entry_price = entry_window_klines['high'].max()
                price_improvement_pct = (best_entry_price - entry_price) / entry_price * 100
                
                if price_improvement_pct > 2.0:
                    entry_stats['delayed_entries'] += 1
                    delayed_entries.append({
                        'coin': coin,
                        'side': side,
                        'entry_time': entry_time_str,
                        'actual_entry': entry_price,
                        'best_entry': best_entry_price,
                        'missed_improvement': price_improvement_pct,
                        'issue': f"错过更高{price_improvement_pct:.1f}%的入场点",
                        'lesson': f"信号出现时应立即执行，避免等待"
                    })
        
        # 【过早开仓判断】：入场后短期震荡，被洗盘止损
        if '止损' in exit_reason and pnl < 0:
            # 检查止损后是否市场按预期方向走了
            post_exit_klines = coin_klines[
                (coin_klines['time'] > entry_time) & 
                (coin_klines['time'] <= entry_time + timedelta(hours=6))
            ]
            
            if not post_exit_klines.empty:
                if side == '多':
                    # 多单止损后，如果后续上涨超过5%，说明方向对但入场早了
                    max_price_later = post_exit_klines['high'].max()
                    later_rally_pct = (max_price_later - entry_price) / entry_price * 100
                    
                    if later_rally_pct > 5.0:
                        entry_stats['premature_entries'] += 1
                        premature_entries.append({
                            'coin': coin,
                            'side': side,
                            'entry_time': entry_time_str,
                            'entry_price': entry_price,
                            'pnl': pnl,
                            'later_move': later_rally_pct,
                            'issue': f"被洗盘止损，但后续上涨{later_rally_pct:.1f}%",
                            'lesson': f"应等待回调确认或更明确的突破信号"
                        })
                else:
                    # 空单止损后，如果后续下跌超过5%，说明方向对但入场早了
                    min_price_later = post_exit_klines['low'].min()
                    later_drop_pct = (entry_price - min_price_later) / entry_price * 100
                    
                    if later_drop_pct > 5.0:
                        entry_stats['premature_entries'] += 1
                        premature_entries.append({
                            'coin': coin,
                            'side': side,
                            'entry_time': entry_time_str,
                            'entry_price': entry_price,
                            'pnl': pnl,
                            'later_move': later_drop_pct,
                            'issue': f"被洗盘止损，但后续下跌{later_drop_pct:.1f}%",
                            'lesson': f"应等待回调确认或更明确的突破信号"
                        })
    
    # 计算最优入场数量
    entry_stats['optimal_entries'] = entry_stats['total_entries'] - (
        entry_stats['false_entries'] + 
        entry_stats['delayed_entries'] + 
        entry_stats['premature_entries']
    )
    
    # ===== 分析2：错过机会的深度分类 =====
    missed_quality_analysis = analyze_missed_opportunities_deep(missed_opportunities)
    
    # ===== 生成可执行的改进建议 =====
    
    # 建议1：虚假信号过滤
    if entry_stats['false_entries'] > 0:
        false_rate = entry_stats['false_entries'] / entry_stats['total_entries'] * 100
        if false_rate > 30:
            # 提取虚假信号的共同特征
            valid_scores = [e['signal_score'] for e in false_entries if e['signal_score'] > 0]
            valid_consensus = [e['consensus'] for e in false_entries if e['consensus'] > 0]
            
            if valid_scores:
                avg_signal = np.mean(valid_scores)
                entry_lessons.append(
                    f"虚假信号率{false_rate:.0f}%：提高入场门槛至信号≥{avg_signal+5:.0f}分"
                )
            if valid_consensus:
                avg_consensus = np.mean(valid_consensus)
                entry_lessons.append(
                    f"虚假信号率{false_rate:.0f}%：提高共振要求至≥{avg_consensus+1:.0f}"
                )
        elif false_rate > 15:
            entry_lessons.append(
                f"虚假信号率{false_rate:.0f}%：增加趋势确认要求（至少2小时趋势年龄）"
            )
    
    # 建议2：延迟开仓改进
    if entry_stats['delayed_entries'] > 0:
        delayed_rate = entry_stats['delayed_entries'] / entry_stats['total_entries'] * 100
        if delayed_rate > 20:
            avg_missed_pct = np.mean([e['missed_improvement'] for e in delayed_entries])
            entry_lessons.append(
                f"延迟开仓率{delayed_rate:.0f}%（平均错过{avg_missed_pct:.1f}%）：信号触发后立即执行，避免等待"
            )
    
    # 建议3：过早开仓改进
    if entry_stats['premature_entries'] > 0:
        premature_rate = entry_stats['premature_entries'] / entry_stats['total_entries'] * 100
        if premature_rate > 20:
            entry_lessons.append(
                f"过早开仓率{premature_rate:.0f}%：等待回调确认或突破后回踩支撑"
            )
    
    # 建议4：错过机会改进
    if missed_quality_analysis['total_missed'] > 0:
        top_reason = missed_quality_analysis['miss_reasons_distribution'][0] if missed_quality_analysis['miss_reasons_distribution'] else None
        if top_reason:
            reason_type = top_reason['reason']
            reason_pct = top_reason['percentage']
            
            if 'R:R' in reason_type and reason_pct > 40:
                entry_lessons.append(
                    f"错过机会{reason_pct:.0f}%因R:R过严：考虑分级R:R（低风险4:1，中风险3:1）"
                )
            elif '趋势不一致' in reason_type and reason_pct > 40:
                entry_lessons.append(
                    f"错过机会{reason_pct:.0f}%因趋势不一致：允许2/3趋势一致即可开仓"
                )
            elif '信号' in reason_type and reason_pct > 40:
                entry_lessons.append(
                    f"错过机会{reason_pct:.0f}%因信号评分不足：降低信号要求至{top_reason.get('suggested_threshold', 60)}分"
                )
    
    return {
        'entry_stats': entry_stats,
        'entry_details': yesterday_trades,  # 🔧 V8.3.25.3: 添加entry_details字段供AI分析使用
        'false_entries': false_entries[:5],  # TOP5
        'delayed_entries': delayed_entries[:5],  # TOP5
        'premature_entries': premature_entries[:5],  # TOP5
        'missed_quality_analysis': missed_quality_analysis,
        'entry_lessons': entry_lessons
    }


def analyze_missed_opportunities_deep(missed_opportunities):
    """
    【V8.3.22】深度分析错过的机会，分类统计原因
    
    Args:
        missed_opportunities: list, 错过的机会列表
    
    Returns:
        {
            'total_missed': int,
            'miss_reasons_distribution': [...],  # 原因分布（按占比排序）
            'high_quality_missed': [...],  # 高质量错过机会（利润>10%）
            'actionable_insights': [...]  # 可执行的洞察
        }
    """
    if not missed_opportunities or len(missed_opportunities) == 0:
        return {
            'total_missed': 0,
            'miss_reasons_distribution': [],
            'high_quality_missed': [],
            'actionable_insights': []
        }
    
    # 统计错过原因
    reason_counts = {}
    high_quality_missed = []
    
    for opp in missed_opportunities:
        reason = opp.get('reason', 'unknown')
        profit = opp.get('potential_profit_pct', 0)
        
        # 分类原因（简化版）
        if 'R:R' in reason or '盈亏比' in reason:
            reason_category = 'R:R过严'
        elif '趋势不一致' in reason or '趋势' in reason:
            reason_category = '趋势不一致'
        elif '信号' in reason or '评分' in reason:
            reason_category = '信号评分不足'
        elif '共振' in reason:
            reason_category = '共振要求过高'
        else:
            reason_category = '其他'
        
        reason_counts[reason_category] = reason_counts.get(reason_category, 0) + 1
        
        # 识别高质量错过（利润>10%）
        if profit > 10:
            high_quality_missed.append({
                'coin': opp['trend']['coin'],
                'type': opp['trend']['type'],
                'profit': profit,
                'reason': reason_category
            })
    
    # 计算原因分布
    total = len(missed_opportunities)
    miss_reasons_distribution = [
        {
            'reason': reason,
            'count': count,
            'percentage': count / total * 100,
            'suggested_threshold': get_suggested_threshold(reason, count, total)
        }
        for reason, count in sorted(reason_counts.items(), key=lambda x: x[1], reverse=True)
    ]
    
    # 生成可执行洞察
    actionable_insights = []
    for reason_item in miss_reasons_distribution[:3]:  # TOP3原因
        if reason_item['percentage'] > 30:  # 占比超过30%才值得关注
            actionable_insights.append(
                f"TOP原因：{reason_item['reason']}占{reason_item['percentage']:.0f}% "
                f"→ 建议调整阈值至{reason_item['suggested_threshold']}"
            )
    
    return {
        'total_missed': total,
        'miss_reasons_distribution': miss_reasons_distribution,
        'high_quality_missed': high_quality_missed[:5],  # TOP5
        'actionable_insights': actionable_insights
    }


def get_suggested_threshold(reason_type, count, total):
    """
    【V8.3.22】根据错过原因推荐新阈值
    
    基于统计学原理：如果某个原因导致>30%的机会被错过，需要放宽条件
    """
    if 'R:R' in reason_type:
        return "3.5:1 (从4.9降低)"
    elif '信号评分' in reason_type:
        return "60分 (从65降低)"
    elif '共振' in reason_type:
        return "2个 (从3降低)"
    elif '趋势' in reason_type:
        return "2/3趋势一致即可"
    else:
        return "需人工review"


def generate_ai_entry_insights(entry_analysis, exit_analysis, market_context=None, ai_decisions=None):
    """
    【V8.3.23】使用AI深度分析开仓质量并生成英文洞察
    【V8.3.24】增强：包含AI原始决策理由的自我反思
    
    Args:
        entry_analysis: dict, 开仓分析结果（来自analyze_entry_timing）
        exit_analysis: dict, 平仓分析结果（来自analyze_exit_timing）
        market_context: dict, 市场环境数据（可选）
        ai_decisions: list, AI历史决策记录（包含思考过程）
    
    Returns:
        {
            'diagnosis': str,  # 问题诊断（英文）
            'root_causes': [str],  # 根本原因列表
            'recommendations': [  # 具体建议
                {
                    'issue': str,  # 问题
                    'action': str,  # 行动
                    'threshold': str,  # 具体阈值
                    'expected_impact': str  # 预期效果
                }
            ],
            'learning_insights': [str],  # 可传递给实时AI的关键洞察
            'generated_at': str
        }
    """
    try:
        # 🔧 V8.3.25.4: 自动检测API密钥和base_url（支持Qwen和DeepSeek）
        deepseek_key = os.getenv('DEEPSEEK_API_KEY')
        qwen_key = os.getenv('QWEN_API_KEY')
        
        if deepseek_key:
            api_key = deepseek_key.strip()
            base_url = "https://api.deepseek.com"
            model_type = "DeepSeek"
            model_name = "deepseek-chat"  # 🔧 V8.5.2.4.28: 使用deepseek-chat代替reasoner（reasoner可能返回空响应）
        elif qwen_key:
            api_key = qwen_key.strip()
            base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
            model_type = "Qwen"
            model_name = "qwen3-max"  # 🔧 V8.3.25.5: 使用Qwen的最强模型
        else:
            raise ValueError("未找到API密钥：请设置 DEEPSEEK_API_KEY 或 QWEN_API_KEY 环境变量")
        
        print(f"[AI Entry Analysis] 使用{model_type} API ({model_name})进行深度分析...")
        
        # 初始化OpenAI客户端
        client = OpenAI(
            api_key=api_key,
            base_url=base_url
        )
        
        # 压缩数据（避免超长prompt）
        entry_stats = entry_analysis['entry_stats']
        
        # 构建精简的案例摘要
        false_signals_summary = []
        for entry in entry_analysis.get('false_entries', [])[:3]:
            false_signals_summary.append({
                'coin': entry['coin'],
                'side': entry.get('side', 'N/A'),  # 🔧 V8.3.25.19: V2可能没有side字段
                'signal_score': entry.get('signal_score', 0),
                'consensus': entry.get('consensus', 0),
                'issue': entry.get('issue', entry.get('reason', 'N/A'))  # 🔧 V8.3.25.19: 兼容reason字段
            })
        
        delayed_entries_summary = []
        for entry in entry_analysis.get('delayed_entries', [])[:3]:
            delayed_entries_summary.append({
                'coin': entry['coin'],
                'missed_improvement_pct': entry['missed_improvement']
            })
        
        premature_entries_summary = []
        for entry in entry_analysis.get('premature_entries', [])[:3]:
            premature_entries_summary.append({
                'coin': entry['coin'],
                'later_move_pct': entry['later_move']
            })
        
        # 构建exit stats摘要
        exit_stats_summary = {
            'sl_rate': 0,
            'premature_exits': 0,
            'avg_missed_profit': 0
        }
        if exit_analysis:
            exit_stats = exit_analysis.get('exit_stats', {})
            total_exits = max(exit_stats.get('total_exits', 1), 1)
            exit_stats_summary = {
                'sl_rate': exit_stats.get('sl_exits', 0) / total_exits * 100,
                'premature_exits': exit_stats.get('premature_exits', 0),
                'avg_missed_profit': exit_stats.get('avg_missed_profit_pct', 0)
            }
        
        # 🆕 V8.3.24: 提取AI决策理由（用于自我反思）
        # 🔧 V8.3.25: 增强 - 为每笔交易匹配对应的AI决策（时间窗口±5分钟）
        from datetime import datetime, timedelta
        
        def find_ai_decision_for_trade(trade_time_str, coin, ai_decisions):
            """为交易匹配AI决策（容错跳过）"""
            if not trade_time_str or not ai_decisions:
                return None
            
            try:
                # 解析交易时间
                trade_time = datetime.strptime(trade_time_str, '%Y-%m-%d %H:%M:%S')
                
                # 在±5分钟窗口内查找
                for decision in ai_decisions:
                    decision_time_str = decision.get('timestamp', '')
                    if not decision_time_str:
                        continue
                    
                    try:
                        decision_time = datetime.strptime(decision_time_str, '%Y-%m-%d %H:%M:%S')
                        time_diff = abs((trade_time - decision_time).total_seconds())
                        
                        # 时间窗口：5分钟 = 300秒
                        if time_diff <= 300:
                            # 检查是否包含该币种的开仓action
                            for action in decision.get('actions', []):
                                if coin in action.get('symbol', '') and 'OPEN' in action.get('action', ''):
                                    return {
                                        'timestamp': decision_time_str,
                                        'thinking': decision.get('思考过程', '')[:150],
                                        'action_reason': action.get('reason', '')[:100],
                                        'time_diff_seconds': int(time_diff)
                                    }
                    except:
                        continue
            except:
                pass
            
            return None
        
        # 为每笔交易匹配AI决策
        ai_reasoning_samples = []
        matched_count = 0
        
        # 🔧 V8.3.25.8: 兼容V2分析模块（没有entry_details，只有entry_table_data）
        if 'entry_details' not in entry_analysis:
            print(f"  ℹ️  Entry analysis from V2 module (no entry_details), using simplified AI reflection")
            # V2模块返回的数据结构不同，我们跳过详细的trade匹配，只使用最近的AI决策
            if ai_decisions and len(ai_decisions) > 0:
                for decision in ai_decisions[-10:]:  # 使用最近10条决策
                    ai_reasoning_samples.append({
                        'timestamp': decision.get('timestamp', ''),
                        'thinking': decision.get('思考过程', '')[:150],
                        'actions': [
                            {
                                'coin': a.get('symbol', '').split('/')[0] if '/' in a.get('symbol', '') else a.get('symbol', ''),
                                'action': a.get('action', ''),
                                'reason': a.get('reason', '')[:100]
                            }
                            for a in decision.get('actions', [])[:2]
                        ]
                    })
                print(f"  ✓ 使用了{len(ai_reasoning_samples)}条最近AI决策用于自我反思")
        elif ai_decisions and len(ai_decisions) > 0:
            # 旧的逻辑：遍历开仓交易，匹配AI决策
            for _, trade in entry_analysis['entry_details'].iterrows():
                coin = trade.get('coin', '')
                open_time = trade.get('开仓时间', '')
                
                ai_decision = find_ai_decision_for_trade(open_time, coin, ai_decisions)
                if ai_decision:
                    ai_reasoning_samples.append({
                        'coin': coin,
                        'trade_time': open_time,
                        **ai_decision
                    })
                    matched_count += 1
            
            # 如果匹配数少于5条，补充其他决策（保证有足够的上下文）
            if len(ai_reasoning_samples) < 5 and len(ai_decisions) > 0:
                for decision in ai_decisions[-5:]:
                    if len(ai_reasoning_samples) >= 5:
                        break
                    
                    # 避免重复
                    if decision.get('timestamp') not in [r['timestamp'] for r in ai_reasoning_samples]:
                        ai_reasoning_samples.append({
                            'timestamp': decision.get('timestamp', ''),
                            'thinking': decision.get('思考过程', '')[:150],
                            'actions': [
                                {
                                    'coin': a.get('symbol', '').split('/')[0],
                                    'action': a.get('action', ''),
                                    'reason': a.get('reason', '')[:100]
                                }
                                for a in decision.get('actions', [])[:2]
                            ]
                        })
            
            print(f"  ✓ 匹配了{matched_count}笔交易的AI决策（±5分钟窗口）")
        
        # 🆕 V8.3.25: 为错过的机会也匹配AI决策（分析"为什么没开仓"）
        missed_with_ai_decisions = []
        if ai_decisions and 'missed_opportunities' in locals():
            for opp in missed_opportunities[:10]:  # 只分析TOP10错过的机会
                opp_time = opp.get('time', '')
                opp_coin = opp.get('coin', '')
                
                if not opp_time or not opp_coin:
                    continue
                
                # 在±5分钟窗口内查找AI决策
                try:
                    opp_dt = datetime.strptime(opp_time, '%Y-%m-%d %H:%M:%S')
                    
                    for decision in ai_decisions:
                        decision_time_str = decision.get('timestamp', '')
                        if not decision_time_str:
                            continue
                        
                        try:
                            decision_dt = datetime.strptime(decision_time_str, '%Y-%m-%d %H:%M:%S')
                            time_diff = abs((opp_dt - decision_dt).total_seconds())
                            
                            # 时间窗口：5分钟
                            if time_diff <= 300:
                                # 检查AI是否考虑过这个币种
                                ai_mentioned_coin = False
                                for action in decision.get('actions', []):
                                    if opp_coin in action.get('symbol', ''):
                                        ai_mentioned_coin = True
                                        break
                                
                                # 如果AI没提这个币，说明可能被过滤了
                                # 🆕 V8.5.1.8: 添加信号分数和共振数，帮助AI分析过滤逻辑是否合理
                                missed_with_ai_decisions.append({
                                    'coin': opp_coin,
                                    'missed_time': opp_time,
                                    'missed_reason': opp.get('reason', 'unknown'),
                                    'profit_potential': opp.get('profit', 0),
                                    'signal_score': opp.get('signal_score', 0),  # 🆕 V8.5.1.8
                                    'consensus': opp.get('consensus', 0),        # 🆕 V8.5.1.8
                                    'ai_decision_time': decision_time_str,
                                    'ai_considered': ai_mentioned_coin,
                                    'ai_thinking': decision.get('思考过程', '')[:100],
                                    'time_diff_seconds': int(time_diff)
                                })
                                break
                        except:
                            continue
                except:
                    continue
            
            if missed_with_ai_decisions:
                print(f"  ✓ 匹配了{len(missed_with_ai_decisions)}个错过机会的AI决策")
        
        # 构建数据包
        # 🔧 V8.3.25.8: 兼容V2模块（使用total_opportunities而不是total_entries）
        total_count = entry_stats.get('total_entries', entry_stats.get('total_opportunities', entry_stats.get('ai_opened', 1)))
        false_entries = entry_stats.get('false_entries', 0)
        delayed_entries = entry_stats.get('delayed_entries', entry_stats.get('timing_issues', 0))  # V2用timing_issues
        premature_entries = entry_stats.get('premature_entries', 0)
        optimal_entries = entry_stats.get('optimal_entries', entry_stats.get('correct_entries', 0))  # V2用correct_entries
        
        # 🆕 V8.5.1.8: 计算信号质量统计（对比虚假信号 vs 正确信号）
        signal_quality_comparison = {}
        try:
            if false_signals_summary:
                false_scores = [f.get('signal_score', 0) for f in false_signals_summary if f.get('signal_score', 0) > 0]
                false_consensus = [f.get('consensus', 0) for f in false_signals_summary if f.get('consensus', 0) > 0]
                
                if false_scores and false_consensus:
                    signal_quality_comparison['false_signals'] = {
                        'avg_signal_score': np.mean(false_scores),
                        'avg_consensus': np.mean(false_consensus),
                        'count': len(false_scores)
                    }
            
            # 获取正确开仓的数据（如果有）
            correct_entries_data = entry_analysis.get('correct_entries', [])
            if correct_entries_data:
                correct_scores = [c.get('signal_score', 0) for c in correct_entries_data if c.get('signal_score', 0) > 0]
                correct_consensus = [c.get('consensus', 0) for c in correct_entries_data if c.get('consensus', 0) > 0]
                
                if correct_scores and correct_consensus:
                    signal_quality_comparison['correct_entries'] = {
                        'avg_signal_score': np.mean(correct_scores),
                        'avg_consensus': np.mean(correct_consensus),
                        'count': len(correct_scores)
                    }
        except Exception as e:
            print(f"  ⚠️ 信号质量统计失败: {e}")
        
        analysis_data = {
            'entry_quality': {
                'total_entries': total_count,
                'false_signal_rate': false_entries / max(total_count, 1) * 100,
                'delayed_rate': delayed_entries / max(total_count, 1) * 100,
                'premature_rate': premature_entries / max(total_count, 1) * 100,
                'optimal_rate': optimal_entries / max(total_count, 1) * 100
            },
            'false_signals': false_signals_summary,
            'delayed_entries': delayed_entries_summary,
            'premature_entries': premature_entries_summary,
            'exit_quality': exit_stats_summary,
            'market_context': market_context or {},
            'ai_reasoning_samples': ai_reasoning_samples,  # 🆕 AI决策理由
            'missed_with_ai': missed_with_ai_decisions,  # 🆕 V8.3.25: 错过机会的AI决策
            'signal_quality_comparison': signal_quality_comparison  # 🆕 V8.5.1.8: 信号质量对比
        }
        
        # 构建AI prompt（纯英文 + 自我反思）
        ai_reasoning_note = ""
        if ai_reasoning_samples:
            ai_reasoning_note = f"""

# 🧠 AI Self-Reflection Context
The AI system has been making decisions with the following reasoning patterns:
```json
{json.dumps(ai_reasoning_samples[-3:], indent=2)}
```

**CRITICAL**: Analyze these reasoning patterns against the actual results. 
- What logical flaws led to false signals?
- What assumptions were wrong?
- What market conditions were misinterpreted?

Provide specific critique of the AI's decision-making process."""
        
        # 🆕 V8.3.25: 添加错过机会的AI反思
        # 🔧 V8.5.1.8: 增强prompt，引导AI分析信号质量与过滤逻辑的关系
        missed_ai_note = ""
        if missed_with_ai_decisions:
            # 🆕 V8.5.1.8: 计算错过机会的平均信号质量
            avg_missed_score = np.mean([m.get('signal_score', 0) for m in missed_with_ai_decisions]) if missed_with_ai_decisions else 0
            avg_missed_consensus = np.mean([m.get('consensus', 0) for m in missed_with_ai_decisions]) if missed_with_ai_decisions else 0
            high_quality_missed = [m for m in missed_with_ai_decisions if m.get('signal_score', 0) >= 75 and m.get('consensus', 0) >= 3]
            
            missed_ai_note = f"""

# 🔍 Missed Opportunities with AI Decision Context
Analysis of why the AI didn't enter these profitable opportunities:
```json
{json.dumps(missed_with_ai_decisions[:5], indent=2)}
```

**CRITICAL SIGNAL QUALITY ANALYSIS** (V8.5.1.8 Enhanced):
- Average signal_score of missed opportunities: {avg_missed_score:.1f}
- Average consensus of missed opportunities: {avg_missed_consensus:.1f}
- High-quality missed (score>=75, consensus>=3): {len(high_quality_missed)} opportunities

**KEY QUESTIONS**:
1. **Signal Quality Check**: 
   - If avg signal_score > 70 and consensus > 2.5, these were HIGH-QUALITY signals
   - Why were they filtered? Were thresholds too strict?
   
2. **AI Consideration**:
   - Did the AI consider this coin at that time? (ai_considered field)
   - If yes, why did it decide NOT to open? Was the logic correct or overly conservative?
   - If no, why was this coin filtered out? Was it a systematic blind spot?
   
3. **Profit vs Quality**:
   - Given the profit_potential (actual profit if entered) vs signal_score/consensus
   - Were the filtering criteria appropriate?

**ACTIONABLE OUTPUT REQUIRED**:
- If high-quality signals (score>=75, consensus>=3) were missed → RECOMMEND lowering thresholds
- If low-quality signals were correctly filtered → VALIDATE current thresholds
- Specify exact threshold adjustments: "min_signal_score >= X", "min_consensus >= Y"

Provide specific, quantified insights on whether the AI's filtering logic needs adjustment."""

        # 🆕 V8.5.1.8: 构建信号质量对比摘要（显式展示给AI）
        quality_comparison_note = ""
        if signal_quality_comparison:
            false_sig = signal_quality_comparison.get('false_signals', {})
            correct_sig = signal_quality_comparison.get('correct_entries', {})
            
            if false_sig and correct_sig:
                score_diff = correct_sig['avg_signal_score'] - false_sig['avg_signal_score']
                consensus_diff = correct_sig['avg_consensus'] - false_sig['avg_consensus']
                recommended_score = correct_sig['avg_signal_score'] * 0.95  # 建议阈值：正确信号平均值的95%
                recommended_consensus = max(2, correct_sig['avg_consensus'] * 0.9)  # 建议阈值：正确信号平均值的90%，最少2
                
                quality_comparison_note = f"""

# 📊 Signal Quality Comparison (V8.5.1.8 Enhanced)
**FALSE SIGNALS** ({false_sig['count']} samples):
- Average signal_score: {false_sig['avg_signal_score']:.1f}
- Average consensus: {false_sig['avg_consensus']:.1f}

**CORRECT ENTRIES** ({correct_sig['count']} samples):
- Average signal_score: {correct_sig['avg_signal_score']:.1f}
- Average consensus: {correct_sig['avg_consensus']:.1f}

**QUALITY GAP**:
- Signal score difference: {score_diff:+.1f} points (correct entries are {score_diff:.1f} points higher)
- Consensus difference: {consensus_diff:+.1f} indicators (correct entries have {consensus_diff:.1f} more)

**RECOMMENDED THRESHOLDS** (based on data):
- min_signal_score >= {recommended_score:.0f} (95% of correct entries' average)
- min_consensus >= {recommended_consensus:.0f} (90% of correct entries' average)

→ Use these statistics to calibrate your threshold recommendations!"""
            elif false_sig:
                quality_comparison_note = f"""

# 📊 Signal Quality Analysis (V8.5.1.8)
**FALSE SIGNALS** ({false_sig['count']} samples):
- Average signal_score: {false_sig['avg_signal_score']:.1f}
- Average consensus: {false_sig['avg_consensus']:.1f}

→ Consider raising thresholds above these averages to filter false signals."""
        
        prompt = f"""You are an expert quantitative trading analyst performing AI self-reflection analysis. 

# Entry Quality Data
```json
{json.dumps(analysis_data, indent=2)}
```
{quality_comparison_note}
{ai_reasoning_note}
{missed_ai_note}

# Your Task
Perform deep self-critical analysis:
1. **Review AI's past reasoning** (if provided above) and identify logical errors
2. **Analyze entry quality results** to find patterns of failure
3. **Connect the dots**: How did flawed reasoning lead to poor results?
4. **Generate corrective insights** that address root causes in decision logic

# Requirements
1. **Diagnosis**: Identify the core issue in AI's decision-making process (1-2 sentences)
2. **Root Causes**: List 2-3 fundamental logical flaws (with specific examples from reasoning if available)
3. **Recommendations**: Provide 3-5 actionable recommendations:
   - Specific threshold adjustments (with numbers)
   - Decision logic corrections (e.g., "Don't trust MACD golden cross when RSI>70")
   - Expected impact (quantified if possible)
   - Implementation priority (High/Medium/Low)
   - **CRITICAL**: For threshold field, use EXACT format: "parameter_name >= value" or "parameter_name: value"
     Examples: "min_risk_reward >= 3.0", "min_signal_score >= 70", "atr_stop_multiplier: 1.8"
4. **Learning Insights**: Generate 3-5 key learnings that critique and correct AI's reasoning patterns

# Output Format (JSON)
{{
  "diagnosis": "Brief summary of the main issue",
  "root_causes": [
    "Cause 1: ...",
    "Cause 2: ..."
  ],
  "recommendations": [
    {{
      "issue": "What problem this addresses",
      "action": "Specific action to take",
      "threshold": "min_risk_reward >= 3.0",
      "expected_impact": "e.g., Reduce false signal rate by 10-15%",
      "priority": "High/Medium/Low"
    }}
  ],
  "learning_insights": [
    "Insight 1: Pattern observed...",
    "Insight 2: Condition discovered..."
  ]
}}

# Important
- Focus on patterns, not individual cases
- Provide specific numbers for thresholds
- **threshold field MUST use format: "parameter_name >= value" or "parameter_name: value"**
- Ensure insights are actionable for AI
- Output must be valid JSON
"""
        
        # 调用AI分析
        print(f"[AI Entry Analysis] Calling {model_type} AI ({model_name}) for deep insights...")
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {
                    "role": "system",
                    "content": "You are a professional quant trading analyst specialized in entry timing optimization. Always output valid JSON."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.3,  # 低温度保证稳定性
            max_tokens=4000  # 🔧 V8.3.25.21: DeepSeek reasoner需要更多tokens（思考过程长）
        )
        
        # 解析AI响应
        ai_content = response.choices[0].message.content.strip()
        
        # 🔧 V8.3.25.26: 调试输出原始响应
        print(f"[AI Entry Analysis] 📝 原始响应长度: {len(ai_content)} 字符")
        print(f"[AI Entry Analysis] 📝 响应前500字符:\n{ai_content[:500]}")
        print(f"[AI Entry Analysis] 📝 响应后200字符:\n{ai_content[-200:]}")
        
        # 提取JSON（可能被markdown包裹）
        if '```json' in ai_content:
            ai_content = ai_content.split('```json')[1].split('```')[0].strip()
        elif '```' in ai_content:
            ai_content = ai_content.split('```')[1].split('```')[0].strip()
        
        # 🔧 V8.3.25.14: 增强JSON解析 - 处理DeepSeek的格式问题
        try:
            ai_insights = json.loads(ai_content)
        except json.JSONDecodeError as json_err:
            print(f"[AI Entry Analysis] ⚠️ JSON解析失败: {json_err}")
            print(f"[AI Entry Analysis] 📝 失败的JSON内容:\n{ai_content}")
            print(f"[AI Entry Analysis] 🔧 尝试修复JSON格式...")
            
            # 🔧 V8.3.25.26: 增强JSON修复逻辑
            try:
                # 1. 移除可能的不完整JSON尾部
                if ai_content.rstrip().endswith(','):
                    ai_content = ai_content.rstrip()[:-1]
                
                # 2. 查找第一个{和最后一个}，提取完整JSON对象
                first_brace = ai_content.find('{')
                last_brace = ai_content.rfind('}')
                
                if first_brace >= 0 and last_brace > first_brace:
                    ai_content = ai_content[first_brace:last_brace+1]
                    print(f"[AI Entry Analysis] 🔧 提取JSON片段: {first_brace}到{last_brace}")
                
                # 3. 修复常见的字符串截断问题
                # 检查是否有未闭合的引号（在最后一个值处）
                open_quotes = ai_content.count('"')
                if open_quotes % 2 != 0:
                    # 奇数个引号，尝试找到最后一个完整的字段
                    # 回溯到上一个完整的字段
                    patterns = [
                        r',\s*"[^"]+"\s*:\s*"[^"]*$',  # 未闭合的字符串值
                        r',\s*"[^"]+"\s*:\s*\[[^\]]*$',  # 未闭合的数组
                    ]
                    import re
                    for pattern in patterns:
                        match = re.search(pattern, ai_content)
                        if match:
                            ai_content = ai_content[:match.start()] + '}'
                            print(f"[AI Entry Analysis] 🔧 修复未闭合字段，截取到位置{match.start()}")
                            break
                
                # 4. 再次尝试解析
                ai_insights = json.loads(ai_content)
                print(f"[AI Entry Analysis] ✅ JSON修复成功")
            except Exception as fix_err:
                print(f"[AI Entry Analysis] ❌ JSON修复失败: {fix_err}")
                print(f"[AI Entry Analysis] 💡 建议: 增加max_tokens或使用非reasoner模型")
                return {
                    'diagnosis': 'JSON解析失败，无法提取AI洞察',
                    'learning_insights': [],
                    'key_recommendations': [],
                    'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
        
        # 添加时间戳
        ai_insights['generated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ai_insights['tokens_used'] = response.usage.total_tokens
        ai_insights['cost_usd'] = response.usage.total_tokens * 0.0000014  # DeepSeek pricing
        
        print(f"[AI Entry Analysis] ✓ Generated {len(ai_insights.get('recommendations', []))} recommendations")
        print(f"[AI Entry Analysis] ✓ Tokens: {ai_insights['tokens_used']}, Cost: ${ai_insights['cost_usd']:.6f}")
        
        return ai_insights
        
    except Exception as e:
        print(f"[AI Entry Analysis] ⚠️ Failed: {e}")
        import traceback
        traceback.print_exc()
        
        # 降级返回空结构
        from datetime import datetime as dt_fallback  # 🔧 V8.3.25.19: 避免UnboundLocalError
        return {
            'diagnosis': f"AI analysis failed: {str(e)}",
            'root_causes': [],
            'recommendations': [],
            'learning_insights': [],
            'generated_at': dt_fallback.now().strftime('%Y-%m-%d %H:%M:%S'),
            'error': str(e)
        }


def generate_ai_exit_insights(exit_analysis, entry_analysis=None, market_context=None, ai_decisions=None):
    """
    【V8.3.23】使用AI深度分析平仓质量并生成英文洞察
    【V8.3.24】增强：包含AI原始决策理由的自我反思
    
    Args:
        exit_analysis: dict, 平仓分析结果（来自analyze_exit_timing）
        entry_analysis: dict, 开仓分析结果（可选，用于关联分析）
        market_context: dict, 市场环境数据（可选）
        ai_decisions: list, AI历史决策记录（包含思考过程）
    
    Returns: 同generate_ai_entry_insights格式
    """
    try:
        # 🔧 V8.3.25.4: 自动检测API密钥和base_url（支持Qwen和DeepSeek）
        deepseek_key = os.getenv('DEEPSEEK_API_KEY')
        qwen_key = os.getenv('QWEN_API_KEY')
        
        if deepseek_key:
            api_key = deepseek_key.strip()
            base_url = "https://api.deepseek.com"
            model_type = "DeepSeek"
            model_name = "deepseek-chat"  # 🔧 V8.5.2.4.28: 使用deepseek-chat代替reasoner（reasoner可能返回空响应）
        elif qwen_key:
            api_key = qwen_key.strip()
            base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
            model_type = "Qwen"
            model_name = "qwen3-max"  # 🔧 V8.3.25.5: 使用Qwen的最强模型
        else:
            raise ValueError("未找到API密钥：请设置 DEEPSEEK_API_KEY 或 QWEN_API_KEY 环境变量")
        
        print(f"[AI Exit Analysis] 使用{model_type} API ({model_name})进行深度分析...")
        
        # 初始化OpenAI客户端
        client = OpenAI(
            api_key=api_key,
            base_url=base_url
        )
        
        # 压缩数据
        exit_stats = exit_analysis['exit_stats']
        
        # 构建案例摘要
        premature_exits_summary = []
        for trade in exit_analysis.get('suboptimal_exits', [])[:5]:
            premature_exits_summary.append({
                'coin': trade.get('coin', 'N/A'),
                'side': trade.get('side', 'N/A'),
                'missed_profit_pct': trade.get('missed_profit_pct', 0),
                'exit_type': trade.get('exit_type', 'N/A'),
                'evaluation': trade.get('evaluation', 'N/A')
            })
        
        good_exits_summary = []
        for trade in exit_analysis.get('good_exits', [])[:3]:
            good_exits_summary.append({
                'coin': trade.get('coin', 'N/A'),
                'evaluation': trade.get('evaluation', 'N/A')
            })
        
        # 🆕 V8.3.24: 提取AI决策理由（平仓相关）
        ai_exit_reasoning = []
        if ai_decisions and len(ai_decisions) > 0:
            recent_decisions = ai_decisions[-10:] if len(ai_decisions) > 10 else ai_decisions
            for decision in recent_decisions:
                # 只提取CLOSE_LONG/CLOSE_SHORT相关的决策
                exit_actions = [
                    action for action in decision.get('actions', [])
                    if 'CLOSE' in action.get('action', '')
                ]
                if exit_actions:
                    ai_exit_reasoning.append({
                        'timestamp': decision.get('timestamp', ''),
                        'thinking': decision.get('思考过程', '')[:150],
                        'exit_actions': [
                            {
                                'coin': a.get('symbol', '').split('/')[0],
                                'action': a.get('action', ''),
                                'reason': a.get('reason', '')[:100]
                            }
                            for a in exit_actions[:2]
                        ]
                    })
        
        # 构建数据包
        analysis_data = {
            'exit_quality': {
                'total_exits': exit_stats['total_exits'],
                'tp_rate': exit_stats['tp_exits'] / max(exit_stats['total_exits'], 1) * 100,
                'sl_rate': exit_stats['sl_exits'] / max(exit_stats['total_exits'], 1) * 100,
                'premature_exits': exit_stats['premature_exits'],
                'optimal_exits': exit_stats['optimal_exits'],
                'avg_missed_profit_pct': exit_stats.get('avg_missed_profit_pct', 0)
            },
            'premature_cases': premature_exits_summary,
            'good_cases': good_exits_summary,
            'exit_lessons': exit_analysis.get('exit_lessons', []),
            'ai_exit_reasoning': ai_exit_reasoning  # 🆕 AI平仓决策理由
        }
        
        # 构建AI prompt（包含自我反思）
        ai_reasoning_note = ""
        if ai_exit_reasoning:
            ai_reasoning_note = f"""

# 🧠 AI Self-Reflection: Exit Decision Reasoning
The AI's past exit decisions and reasoning:
```json
{json.dumps(ai_exit_reasoning[-3:], indent=2)}
```

**CRITICAL**: Analyze if the AI's exit reasoning was sound:
- Did it exit too early based on fear rather than data?
- Did it ignore bullish continuation signals?
- Were take-profit targets too conservative?
"""

        prompt = f"""You are an expert quantitative trading analyst performing AI self-reflection on exit timing.

# Exit Quality Data
```json
{json.dumps(analysis_data, indent=2)}
```

# Your Task
Perform deep analysis and generate insights that can be used by the AI trading system to improve future exit decisions.

# Requirements
1. **Diagnosis**: Identify the core issue with exit timing
2. **Root Causes**: List 2-3 fundamental reasons for suboptimal exits
3. **Recommendations**: Provide 3-5 actionable recommendations for:
   - Take-profit strategy optimization
   - Stop-loss adjustment
   - Trailing stop implementation
   - Risk-reward ratio refinement
   - **CRITICAL**: For threshold field, use EXACT format: "parameter_name >= value" or "parameter_name: value"
     Examples: "atr_tp_multiplier: 3.5", "min_risk_reward >= 2.5", "trailing_stop_pct: 0.8"
4. **Learning Insights**: Generate 3-5 key learnings for real-time AI reference

# Output Format (JSON)
{{
  "diagnosis": "Brief summary of exit timing issues",
  "root_causes": ["Cause 1", "Cause 2"],
  "recommendations": [
    {{
      "issue": "Problem",
      "action": "Solution",
      "threshold": "atr_tp_multiplier: 3.5",
      "expected_impact": "Quantified improvement",
      "priority": "High/Medium/Low"
    }}
  ],
  "learning_insights": [
    "Insight 1: Exit pattern observed...",
    "Insight 2: Condition for optimal exit..."
  ]
}}

# Important
- Focus on systematic patterns
- **threshold field MUST use format: "parameter_name >= value" or "parameter_name: value"**
- Provide specific threshold adjustments
- Ensure insights are immediately actionable
- Output valid JSON only
"""
        
        # 调用AI分析
        print(f"[AI Exit Analysis] Calling {model_type} AI ({model_name}) for deep insights...")
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {
                    "role": "system",
                    "content": "You are a professional quant trading analyst specialized in exit timing optimization. Always output valid JSON."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.3,
            max_tokens=4000  # 🔧 V8.3.25.21: DeepSeek reasoner需要更多tokens（思考过程长）
        )
        
        # 解析AI响应
        ai_content = response.choices[0].message.content.strip()
        
        # 提取JSON
        if '```json' in ai_content:
            ai_content = ai_content.split('```json')[1].split('```')[0].strip()
        elif '```' in ai_content:
            ai_content = ai_content.split('```')[1].split('```')[0].strip()
        
        # 🔧 V8.3.25.14: 增强JSON解析 - 处理DeepSeek的格式问题
        try:
            ai_insights = json.loads(ai_content)
        except json.JSONDecodeError as json_err:
            print(f"[AI Exit Analysis] ⚠️ JSON解析失败: {json_err}")
            print(f"[AI Exit Analysis] 🔧 尝试修复JSON格式...")
            
            # 尝试修复常见问题：未闭合的字符串
            try:
                # 移除可能的不完整JSON尾部
                if ai_content.rstrip().endswith(','):
                    ai_content = ai_content.rstrip()[:-1]
                
                # 尝试找到最后一个完整的对象
                last_brace = ai_content.rfind('}')
                if last_brace > 0:
                    ai_content = ai_content[:last_brace+1]
                
                ai_insights = json.loads(ai_content)
                print(f"[AI Exit Analysis] ✅ JSON修复成功")
            except:
                print(f"[AI Exit Analysis] ❌ JSON修复失败，返回空结果")
                return {
                    'diagnosis': 'JSON解析失败，无法提取AI洞察',
                    'learning_insights': [],
                    'key_recommendations': [],
                    'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
        
        # 添加元数据
        ai_insights['generated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ai_insights['tokens_used'] = response.usage.total_tokens
        ai_insights['cost_usd'] = response.usage.total_tokens * 0.0000014
        
        print(f"[AI Exit Analysis] ✓ Generated {len(ai_insights.get('recommendations', []))} recommendations")
        print(f"[AI Exit Analysis] ✓ Tokens: {ai_insights['tokens_used']}, Cost: ${ai_insights['cost_usd']:.6f}")
        
        return ai_insights
        
    except Exception as e:
        print(f"[AI Exit Analysis] ⚠️ Failed: {e}")
        import traceback
        traceback.print_exc()
        
        from datetime import datetime as dt_fallback  # 🔧 V8.3.25.19: 避免UnboundLocalError
        return {
            'diagnosis': f"AI analysis failed: {str(e)}",
            'root_causes': [],
            'recommendations': [],
            'learning_insights': [],
            'generated_at': dt_fallback.now().strftime('%Y-%m-%d %H:%M:%S'),
            'error': str(e)
        }

