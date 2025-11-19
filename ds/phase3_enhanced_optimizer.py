#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
【V8.5.2.4.41】Phase 3增强优化器

核心功能:
1. 叠加Phase 2的learned_features（signal_score权重、top5参数组合）
2. 使用优化后的signal_score权重重新计算所有机会
3. 多起点搜索（AI建议 + Phase2最优 + Top5组合）
4. 组合筛选测试（consensus × signal_score矩阵）
5. AI协助分析和推荐最优参数
"""

import json
from pathlib import Path
from typing import Dict, List, Any, Tuple
import sys


def phase3_enhanced_optimization(
    all_opportunities: List[Dict],
    phase1_baseline: Dict,
    phase2_baseline: Dict,
    kline_snapshots,
    model_name: str = "deepseek"
) -> Dict:
    """
    【V8.5.2.4.41】Phase 3增强优化
    
    Args:
        all_opportunities: 所有识别的机会
        phase1_baseline: Phase 1的统计基线
        phase2_baseline: Phase 2的优化结果（包含learned_features）
        kline_snapshots: 市场快照数据
        model_name: 模型名称（用于AI调用）
    
    Returns:
        phase3_result: Phase 3优化结果
    """
    print(f"\n{'='*70}")
    print(f"⚖️  【Phase 3】风险控制与利润最大化")
    print(f"{'='*70}")
    print(f"  策略：叠加Phase 2成果 + 多起点搜索 + AI辅助决策")
    print(f"  特色：使用优化权重 + consensus筛选 + 信号分矩阵")
    print(f"{'='*70}")
    
    # 【步骤1】提取Phase 2学到的特征
    learned_features = phase2_baseline.get('learned_features', {})
    best_scalping_weights = learned_features.get('best_scalping_weights', {})
    best_swing_weights = learned_features.get('best_swing_weights', {})
    top5_param_combos = learned_features.get('top5_param_combos', [])
    
    print(f"\n  📚 【Phase 2学习成果加载】")
    print(f"     ⚡ 超短线最优权重: {best_scalping_weights.get('name', 'N/A')}")
    print(f"     🌊 波段最优权重: {best_swing_weights.get('name', 'N/A')}")
    print(f"     🎯 Top5参数组合: {len(top5_param_combos)}个")
    
    # 【步骤2】使用优化权重重新计算signal_score
    print(f"\n  🔄 【重新计算signal_score】")
    print(f"     使用Phase 2优化的权重配置...")
    
    # 导入重新计算函数
    sys.path.insert(0, str(Path(__file__).parent))
    from deepseek_多币种智能版 import recalculate_signal_score_from_snapshot
    
    recalc_count = 0
    for opp in all_opportunities:
        signal_type = opp.get('signal_type', 'swing')
        
        # 选择对应的权重配置
        if signal_type == 'scalping' and best_scalping_weights:
            weight_config = best_scalping_weights.get('weights', {})
        elif signal_type == 'swing' and best_swing_weights:
            weight_config = best_swing_weights.get('weights', {})
        else:
            weight_config = None
        
        # 重新计算signal_score
        if weight_config:
            # 构建learning_config格式
            learning_config = {
                'scalping_weights': best_scalping_weights.get('weights', {}) if signal_type == 'scalping' else {},
                'swing_weights': best_swing_weights.get('weights', {}) if signal_type == 'swing' else {}
            }
            
            new_signal_score = recalculate_signal_score_from_snapshot(
                opp, signal_type, learning_config
            )
            
            # 保存旧值（调试用）
            opp['_old_signal_score'] = opp.get('signal_score', 0)
            opp['signal_score'] = new_signal_score
            recalc_count += 1
    
    print(f"     ✓ 重新计算: {recalc_count}/{len(all_opportunities)}个机会")
    
    # 【步骤3】多起点搜索
    print(f"\n  🎯 【多起点搜索】")
    print(f"     策略：从多个优质起点出发，避免局部最优")
    
    candidate_starting_points = []
    
    # 起点1: Phase 2最优参数
    if phase2_baseline.get('params'):
        candidate_starting_points.append({
            'name': 'Phase2最优',
            'params': phase2_baseline['params'].copy(),
            'source': 'phase2_best'
        })
    
    # 起点2: Phase 1 AI建议（如果有）
    if phase1_baseline and phase1_baseline.get('ai_suggested_params'):
        candidate_starting_points.append({
            'name': 'AI建议',
            'params': phase1_baseline['ai_suggested_params'].copy(),
            'source': 'ai_suggestion'
        })
    
    # 起点3-5: Top5组合的前3个
    for i, combo in enumerate(top5_param_combos[:3], 1):
        if combo.get('params'):
            candidate_starting_points.append({
                'name': f"Top{i}组合",
                'params': combo['params'].copy(),
                'source': f'top5_{i}'
            })
    
    print(f"     候选起点: {len(candidate_starting_points)}个")
    for sp in candidate_starting_points:
        print(f"       - {sp['name']}")
    
    # 为每个起点进行局部搜索
    from backtest_optimizer_v8321 import optimize_params_v8321_lightweight
    
    all_search_results = []
    
    for i, starting_point in enumerate(candidate_starting_points, 1):
        print(f"\n     [{i}/{len(candidate_starting_points)}] 从"{starting_point['name']}"出发...")
        
        try:
            # 为这个起点做局部搜索（50组测试）
            search_result = optimize_params_v8321_lightweight(
                opportunities=all_opportunities,
                starting_params=starting_point['params'],
                max_combinations=50,
                search_mode='local'  # 局部搜索模式
            )
            
            if search_result:
                search_result['starting_point'] = starting_point['name']
                all_search_results.append(search_result)
                print(f"        ✓ 找到优化参数，利润: {search_result.get('total_profit', 0):.1f}%")
        except Exception as e:
            print(f"        ⚠️  搜索失败: {e}")
    
    # 选择最佳结果
    if all_search_results:
        best_search_result = max(all_search_results, key=lambda x: x.get('total_profit', 0))
        print(f"\n     🏆 最佳起点: {best_search_result.get('starting_point')}")
        print(f"        总利润: {best_search_result.get('total_profit', 0):.1f}%")
        print(f"        捕获率: {best_search_result.get('capture_rate', 0)*100:.1f}%")
    else:
        best_search_result = None
        print(f"\n     ⚠️  未找到有效结果，使用Phase 2参数")
    
    # 【步骤4】组合筛选矩阵测试
    print(f"\n  📊 【组合筛选矩阵】")
    print(f"     测试不同的consensus × signal_score组合")
    
    filter_combinations = [
        {'min_consensus': 1, 'min_signal_score': 75, 'name': '极宽松（最大召回）'},
        {'min_consensus': 1, 'min_signal_score': 80, 'name': '宽松'},
        {'min_consensus': 2, 'min_signal_score': 80, 'name': '平衡-偏宽'},
        {'min_consensus': 2, 'min_signal_score': 85, 'name': '平衡'},
        {'min_consensus': 2, 'min_signal_score': 90, 'name': '平衡-偏严'},
        {'min_consensus': 3, 'min_signal_score': 85, 'name': '严格-高共振'},
        {'min_consensus': 3, 'min_signal_score': 90, 'name': '严格'},
        {'min_consensus': 1, 'min_signal_score': 90, 'name': '信号分优先'},
        {'min_consensus': 3, 'min_signal_score': 80, 'name': '共振优先'},
    ]
    
    # 导入actual_profit计算
    from calculate_actual_profit import calculate_single_actual_profit
    
    matrix_results = []
    
    for combo in filter_combinations:
        # 过滤机会
        filtered_opps = [
            opp for opp in all_opportunities
            if (opp.get('indicator_consensus', 0) >= combo['min_consensus'] and
                opp.get('signal_score', 0) >= combo['min_signal_score'])
        ]
        
        if not filtered_opps:
            continue
        
        # 计算actual_profit（使用best_search_result的参数，如果有）
        params = best_search_result.get('params', phase2_baseline.get('params', {})) if best_search_result else phase2_baseline.get('params', {})
        
        for opp in filtered_opps:
            signal_type = opp.get('signal_type', 'swing')
            
            # 根据signal_type使用默认值
            if signal_type == 'scalping':
                default_tp = 2.0
                default_sl = 1.5
                default_holding = 12
            else:
                default_tp = 6.0
                default_sl = 2.5
                default_holding = 72
            
            strategy_params = {
                **params,
                'atr_tp_multiplier': params.get('atr_tp_multiplier', default_tp),
                'atr_stop_multiplier': params.get('atr_stop_multiplier', default_sl),
                'max_holding_hours': params.get('max_holding_hours', default_holding)
            }
            
            actual_profit = calculate_single_actual_profit(
                opp,
                strategy_params=strategy_params,
                use_dynamic_atr=False
            )
            opp['_matrix_actual_profit'] = actual_profit
        
        # 统计结果
        capture_rate = len(filtered_opps) / len(all_opportunities) if all_opportunities else 0
        avg_profit = sum(o.get('_matrix_actual_profit', 0) for o in filtered_opps) / len(filtered_opps) if filtered_opps else 0
        total_profit = sum(o.get('_matrix_actual_profit', 0) for o in filtered_opps)
        
        # 计算综合得分
        score = total_profit * 0.7 + capture_rate * 100 * 0.3
        
        matrix_results.append({
            'name': combo['name'],
            'min_consensus': combo['min_consensus'],
            'min_signal_score': combo['min_signal_score'],
            'captured_count': len(filtered_opps),
            'capture_rate': capture_rate,
            'avg_profit': avg_profit,
            'total_profit': total_profit,
            'score': score
        })
    
    # 排序并显示Top 3
    matrix_results_sorted = sorted(matrix_results, key=lambda x: x['score'], reverse=True)
    
    print(f"\n     组合筛选Top 3:")
    for i, result in enumerate(matrix_results_sorted[:3], 1):
        print(f"       #{i} [{result['name']}]")
        print(f"          consensus>={result['min_consensus']}, signal_score>={result['min_signal_score']}")
        print(f"          捕获: {result['captured_count']}个 ({result['capture_rate']*100:.1f}%)")
        print(f"          平均利润: {result['avg_profit']:.2f}%, 总利润: {result['total_profit']:.1f}%")
        print(f"          综合得分: {result['score']:.1f}")
    
    best_matrix_combo = matrix_results_sorted[0] if matrix_results_sorted else None
    
    # 【步骤5】AI辅助决策
    print(f"\n  🤖 【AI辅助决策】")
    print(f"     请求AI分析数据并推荐最优参数...")
    
    ai_recommendation = request_ai_analysis(
        all_opportunities=all_opportunities,
        phase1_baseline=phase1_baseline,
        phase2_baseline=phase2_baseline,
        search_results=all_search_results,
        matrix_results=matrix_results_sorted[:5],
        model_name=model_name
    )
    
    # 【步骤6】综合决策
    print(f"\n  🎯 【综合决策】")
    
    # 优先级：AI推荐 > 最佳搜索结果 > 最佳矩阵组合 > Phase 2参数
    if ai_recommendation and ai_recommendation.get('recommended_params'):
        final_params = ai_recommendation['recommended_params']
        decision_source = 'AI推荐'
    elif best_search_result:
        final_params = best_search_result.get('params', {})
        decision_source = f"多起点搜索（{best_search_result.get('starting_point')}）"
    elif best_matrix_combo:
        final_params = {
            **phase2_baseline.get('params', {}),
            'min_indicator_consensus': best_matrix_combo['min_consensus'],
            'min_signal_score': best_matrix_combo['min_signal_score']
        }
        decision_source = f"矩阵筛选（{best_matrix_combo['name']}）"
    else:
        final_params = phase2_baseline.get('params', {})
        decision_source = 'Phase 2最优'
    
    print(f"     决策来源: {decision_source}")
    print(f"     关键参数:")
    print(f"       - min_consensus: {final_params.get('min_indicator_consensus', 'N/A')}")
    print(f"       - min_signal_score: {final_params.get('min_signal_score', 'N/A')}")
    print(f"       - min_risk_reward: {final_params.get('min_risk_reward', 'N/A')}")
    
    # 返回Phase 3结果
    return {
        'final_params': final_params,
        'decision_source': decision_source,
        'learned_features': learned_features,
        'multi_start_search': {
            'starting_points': len(candidate_starting_points),
            'all_results': all_search_results,
            'best_result': best_search_result
        },
        'filter_matrix': {
            'tested_combinations': len(matrix_results),
            'all_results': matrix_results_sorted,
            'best_combo': best_matrix_combo
        },
        'ai_recommendation': ai_recommendation,
        'recalculated_opportunities': len(all_opportunities)
    }


def request_ai_analysis(
    all_opportunities: List[Dict],
    phase1_baseline: Dict,
    phase2_baseline: Dict,
    search_results: List[Dict],
    matrix_results: List[Dict],
    model_name: str
) -> Dict:
    """
    【V8.5.2.4.41】请求AI分析数据并推荐最优参数
    
    Args:
        all_opportunities: 所有机会
        phase1_baseline: Phase 1基线
        phase2_baseline: Phase 2基线
        search_results: 多起点搜索结果
        matrix_results: 矩阵筛选结果
        model_name: 模型名称
    
    Returns:
        ai_recommendation: AI推荐结果
    """
    try:
        # 构建AI提示词
        prompt = build_ai_analysis_prompt(
            all_opportunities, phase1_baseline, phase2_baseline,
            search_results, matrix_results
        )
        
        # 调用AI（使用系统中的AI调用函数）
        sys.path.insert(0, str(Path(__file__).parent))
        
        if model_name == "deepseek":
            from deepseek_多币种智能版 import call_deepseek_api
            ai_response = call_deepseek_api(prompt, force_call=True)
        else:
            from qwen_多币种智能版 import call_qwen_api
            ai_response = call_qwen_api(prompt, force_call=True)
        
        # 解析AI响应
        recommendation = parse_ai_recommendation(ai_response)
        
        print(f"     ✓ AI分析完成")
        print(f"     推荐策略: {recommendation.get('strategy', 'N/A')}")
        print(f"     理由: {recommendation.get('reason', 'N/A')[:80]}...")
        
        return recommendation
        
    except Exception as e:
        print(f"     ⚠️  AI调用失败: {e}")
        return {}


def build_ai_analysis_prompt(
    all_opportunities: List[Dict],
    phase1_baseline: Dict,
    phase2_baseline: Dict,
    search_results: List[Dict],
    matrix_results: List[Dict]
) -> str:
    """构建AI分析提示词"""
    
    # 统计数据
    total_opps = len(all_opportunities)
    scalping_count = sum(1 for o in all_opportunities if o.get('signal_type') == 'scalping')
    swing_count = total_opps - scalping_count
    
    # consensus分布
    consensus_dist = {}
    for opp in all_opportunities:
        c = opp.get('indicator_consensus', 0)
        consensus_dist[c] = consensus_dist.get(c, 0) + 1
    
    # signal_score分布
    signal_score_ranges = {'0-70': 0, '70-80': 0, '80-90': 0, '90-100': 0}
    for opp in all_opportunities:
        score = opp.get('signal_score', 0)
        if score < 70:
            signal_score_ranges['0-70'] += 1
        elif score < 80:
            signal_score_ranges['70-80'] += 1
        elif score < 90:
            signal_score_ranges['80-90'] += 1
        else:
            signal_score_ranges['90-100'] += 1
    
    prompt = f"""作为交易系统优化专家，请分析以下数据并推荐最优参数配置。

【Phase 1客观统计】
- 总机会数: {total_opps}个
- 超短线: {scalping_count}个, 波段: {swing_count}个
- 平均最大利润: {phase1_baseline.get('avg_max_profit', 0):.2f}%

【Phase 2学习成果】
- 最优超短线权重: {phase2_baseline.get('learned_features', {}).get('best_scalping_weights', {}).get('name', 'N/A')}
- 最优波段权重: {phase2_baseline.get('learned_features', {}).get('best_swing_weights', {}).get('name', 'N/A')}
- Phase 2捕获率: {phase2_baseline.get('capture_rate', 0)*100:.1f}%
- Phase 2平均利润: {phase2_baseline.get('avg_profit', 0):.2f}%

【数据分布】
consensus分布: {consensus_dist}
signal_score分布: {signal_score_ranges}

【多起点搜索结果】（Top 3）
"""
    
    for i, result in enumerate(search_results[:3], 1):
        prompt += f"""
{i}. 起点: {result.get('starting_point', 'N/A')}
   总利润: {result.get('total_profit', 0):.1f}%
   捕获率: {result.get('capture_rate', 0)*100:.1f}%
   参数: consensus>={result.get('params', {}).get('min_indicator_consensus', 'N/A')}, 
         signal_score>={result.get('params', {}).get('min_signal_score', 'N/A')}
"""
    
    prompt += f"""
【矩阵筛选结果】（Top 3）
"""
    
    for i, result in enumerate(matrix_results[:3], 1):
        prompt += f"""
{i}. {result.get('name', 'N/A')}
   consensus>={result['min_consensus']}, signal_score>={result['min_signal_score']}
   捕获率: {result['capture_rate']*100:.1f}%
   平均利润: {result['avg_profit']:.2f}%
   总利润: {result['total_profit']:.1f}%
   综合得分: {result['score']:.1f}
"""
    
    prompt += """
【请回答】
1. 综合评估：哪个配置最优？为什么？
2. 参数推荐：推荐的min_consensus和min_signal_score各是多少？
3. 风险提示：这个配置有什么潜在风险？

请以JSON格式回复：
{
    "recommended_params": {
        "min_indicator_consensus": <数字>,
        "min_signal_score": <数字>,
        "min_risk_reward": <数字>
    },
    "strategy": "<简短描述>",
    "reason": "<详细理由>",
    "risks": "<潜在风险>"
}
"""
    
    return prompt


def parse_ai_recommendation(ai_response: str) -> Dict:
    """解析AI推荐响应"""
    try:
        # 尝试提取JSON
        import re
        json_match = re.search(r'\{.*\}', ai_response, re.DOTALL)
        if json_match:
            recommendation = json.loads(json_match.group())
            return recommendation
        else:
            # 无法提取JSON，返回空
            return {}
    except Exception as e:
        print(f"⚠️  解析AI响应失败: {e}")
        return {}

