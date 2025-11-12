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


def generate_ai_entry_insights(entry_analysis, exit_analysis, market_context=None):
    """
    【V8.3.23】使用AI深度分析开仓质量并生成英文洞察
    
    Args:
        entry_analysis: dict, 开仓分析结果（来自analyze_entry_timing）
        exit_analysis: dict, 平仓分析结果（来自analyze_exit_timing）
        market_context: dict, 市场环境数据（可选）
    
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
        # 初始化OpenAI客户端
        client = OpenAI(
            api_key=os.getenv('DEEPSEEK_API_KEY'),
            base_url="https://api.deepseek.com"
        )
        
        # 压缩数据（避免超长prompt）
        entry_stats = entry_analysis['entry_stats']
        
        # 构建精简的案例摘要
        false_signals_summary = []
        for entry in entry_analysis.get('false_entries', [])[:3]:
            false_signals_summary.append({
                'coin': entry['coin'],
                'side': entry['side'],
                'signal_score': entry.get('signal_score', 0),
                'consensus': entry.get('consensus', 0),
                'issue': entry['issue']
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
        
        # 构建数据包
        analysis_data = {
            'entry_quality': {
                'total_entries': entry_stats['total_entries'],
                'false_signal_rate': entry_stats['false_entries'] / max(entry_stats['total_entries'], 1) * 100,
                'delayed_rate': entry_stats['delayed_entries'] / max(entry_stats['total_entries'], 1) * 100,
                'premature_rate': entry_stats['premature_entries'] / max(entry_stats['total_entries'], 1) * 100,
                'optimal_rate': entry_stats['optimal_entries'] / max(entry_stats['total_entries'], 1) * 100
            },
            'false_signals': false_signals_summary,
            'delayed_entries': delayed_entries_summary,
            'premature_entries': premature_entries_summary,
            'exit_quality': exit_stats_summary,
            'market_context': market_context or {}
        }
        
        # 构建AI prompt（纯英文）
        prompt = f"""You are an expert quantitative trading analyst. Analyze the entry timing quality data and provide deep insights for AI self-learning.

# Entry Quality Data
```json
{json.dumps(analysis_data, indent=2)}
```

# Your Task
Perform deep analysis and generate insights that can be used by the AI trading system to improve future entry decisions.

# Requirements
1. **Diagnosis**: Identify the core issue (1-2 sentences)
2. **Root Causes**: List 2-3 fundamental reasons (not just symptoms)
3. **Recommendations**: Provide 3-5 actionable recommendations with:
   - Specific threshold adjustments (with numbers)
   - Expected impact (quantified if possible)
   - Implementation priority (High/Medium/Low)
4. **Learning Insights**: Generate 3-5 key learnings in concise format that can be stored in knowledge base and referenced by real-time AI

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
      "threshold": "e.g., signal_score >= 70 (from 65)",
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
- Ensure insights are actionable for AI
- Output must be valid JSON
"""
        
        # 调用AI分析
        print(f"[AI Entry Analysis] Calling DeepSeek AI for deep insights...")
        response = client.chat.completions.create(
            model="deepseek-chat",
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
            max_tokens=2000
        )
        
        # 解析AI响应
        ai_content = response.choices[0].message.content.strip()
        
        # 提取JSON（可能被markdown包裹）
        if '```json' in ai_content:
            ai_content = ai_content.split('```json')[1].split('```')[0].strip()
        elif '```' in ai_content:
            ai_content = ai_content.split('```')[1].split('```')[0].strip()
        
        ai_insights = json.loads(ai_content)
        
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
        return {
            'diagnosis': f"AI analysis failed: {str(e)}",
            'root_causes': [],
            'recommendations': [],
            'learning_insights': [],
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'error': str(e)
        }


def generate_ai_exit_insights(exit_analysis, entry_analysis=None, market_context=None):
    """
    【V8.3.23】使用AI深度分析平仓质量并生成英文洞察
    
    Args:
        exit_analysis: dict, 平仓分析结果（来自analyze_exit_timing）
        entry_analysis: dict, 开仓分析结果（可选，用于关联分析）
        market_context: dict, 市场环境数据（可选）
    
    Returns: 同generate_ai_entry_insights格式
    """
    try:
        # 初始化OpenAI客户端
        client = OpenAI(
            api_key=os.getenv('DEEPSEEK_API_KEY'),
            base_url="https://api.deepseek.com"
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
            'exit_lessons': exit_analysis.get('exit_lessons', [])
        }
        
        # 构建AI prompt
        prompt = f"""You are an expert quantitative trading analyst. Analyze the exit timing quality data and provide deep insights for AI self-learning.

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
4. **Learning Insights**: Generate 3-5 key learnings for real-time AI reference

# Output Format (JSON)
{{
  "diagnosis": "Brief summary of exit timing issues",
  "root_causes": ["Cause 1", "Cause 2"],
  "recommendations": [
    {{
      "issue": "Problem",
      "action": "Solution",
      "threshold": "Specific parameter adjustment",
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
- Provide specific threshold adjustments
- Ensure insights are immediately actionable
- Output valid JSON only
"""
        
        # 调用AI分析
        print(f"[AI Exit Analysis] Calling DeepSeek AI for deep insights...")
        response = client.chat.completions.create(
            model="deepseek-chat",
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
            max_tokens=2000
        )
        
        # 解析AI响应
        ai_content = response.choices[0].message.content.strip()
        
        # 提取JSON
        if '```json' in ai_content:
            ai_content = ai_content.split('```json')[1].split('```')[0].strip()
        elif '```' in ai_content:
            ai_content = ai_content.split('```')[1].split('```')[0].strip()
        
        ai_insights = json.loads(ai_content)
        
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
        
        return {
            'diagnosis': f"AI analysis failed: {str(e)}",
            'root_causes': [],
            'recommendations': [],
            'learning_insights': [],
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'error': str(e)
        }

