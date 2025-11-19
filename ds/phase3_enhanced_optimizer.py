#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
【V8.5.2.4.42】Phase 3增强优化器

核心功能:
1. 叠加Phase 2的learned_features（signal_score权重、top5参数组合）
2. 使用优化后的signal_score权重重新计算所有机会
3. 多起点搜索（AI建议 + Phase2最优 + Top5组合）
4. 组合筛选测试（consensus × signal_score矩阵）
5. AI协助分析和推荐最优参数
6. 【V8.5.2.4.42新增】分离优化超短线和波段参数
7. 【V8.5.2.4.42新增】测试移动止盈止损效果
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
        print(f"\n     [{i}/{len(candidate_starting_points)}] 从'{starting_point['name']}'出发...")
        
        try:
            # 为这个起点做局部搜索
            # 【V8.5.2.4.47优化】从50组减到10组，避免内存耗尽（与实时AI共存）
            # 【V8.5.2.4.47修复】使用current_params代替starting_params，添加signal_type
            search_result = optimize_params_v8321_lightweight(
                opportunities=all_opportunities,
                current_params=starting_point['params'],
                signal_type='swing',  # 默认使用swing（或根据实际情况判断）
                max_combinations=10  # 【V8.5.2.4.47】50→30→15→10，节省80%内存
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
        # 【V8.5.2.4.47修复】字段名统一为consensus（Phase 1设置的字段名）
        filtered_opps = [
            opp for opp in all_opportunities
            if (opp.get('consensus', 0) >= combo['min_consensus'] and
                opp.get('signal_score', 0) >= combo['min_signal_score'])
        ]
        
        if not filtered_opps:
            continue
        
        # 计算actual_profit（使用best_search_result的参数，如果有）
        params = best_search_result.get('params', phase2_baseline.get('params', {})) if best_search_result else phase2_baseline.get('params', {})
        
        for opp in filtered_opps:
            signal_type = opp.get('signal_type', 'swing')
            
            # 【V8.5.2.4.60】从learned_features提取最优TP/SL
            optimal_tp_sl = learned_features.get('optimal_tp_sl', {})
            
            # 根据signal_type使用最优TP/SL（优先）或默认值（降级）
            if signal_type == 'scalping':
                scalping_optimal = optimal_tp_sl.get('scalping', {})
                default_tp = scalping_optimal.get('atr_tp_multiplier', 2.0)
                default_sl = scalping_optimal.get('atr_stop_multiplier', 1.5)
                default_holding = 12
            else:
                swing_optimal = optimal_tp_sl.get('swing', {})
                default_tp = swing_optimal.get('atr_tp_multiplier', 6.0)
                default_sl = swing_optimal.get('atr_stop_multiplier', 2.5)
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
    
    # 【步骤6】分离优化超短线和波段
    print(f"\n  📊 【分离优化】")
    print(f"     分别为超短线和波段寻找最大利润参数...")
    
    # 分离机会
    scalping_opps = [o for o in all_opportunities if o.get('signal_type') == 'scalping']
    swing_opps = [o for o in all_opportunities if o.get('signal_type') == 'swing']
    
    print(f"     超短线机会: {len(scalping_opps)}个")
    print(f"     波段机会: {len(swing_opps)}个")
    
    # 优化超短线参数
    scalping_result = optimize_for_signal_type(
        opportunities=scalping_opps,
        signal_type='scalping',
        learned_features=learned_features,
        starting_points=candidate_starting_points,
        kline_snapshots=kline_snapshots
    )
    
    # 【V8.5.2.4.47】超短线优化完成，立即释放内存
    import gc
    del scalping_opps  # 删除已用完的超短线机会列表
    gc.collect()
    print(f"     💾 超短线优化完成，已释放内存")
    
    # 优化波段参数
    swing_result = optimize_for_signal_type(
        opportunities=swing_opps,
        signal_type='swing',
        learned_features=learned_features,
        starting_points=candidate_starting_points,
        kline_snapshots=kline_snapshots
    )
    
    print(f"\n  ✅ Phase 3优化完成")
    print(f"     超短线: 捕获率{scalping_result['capture_rate']*100:.1f}%, 平均利润{scalping_result['avg_profit']:.2f}%")
    print(f"     波段: 捕获率{swing_result['capture_rate']*100:.1f}%, 平均利润{swing_result['avg_profit']:.2f}%")
    
    # 【V8.5.2.4.42】返回分离的Phase 3结果
    return {
        'scalping': {
            'params': scalping_result['best_params'],
            'capture_rate': scalping_result['capture_rate'],
            'avg_profit': scalping_result['avg_profit'],
            'total_profit': scalping_result['total_profit'],
            'captured_count': scalping_result['captured_count']
        },
        'swing': {
            'params': swing_result['best_params'],
            'capture_rate': swing_result['capture_rate'],
            'avg_profit': swing_result['avg_profit'],
            'total_profit': swing_result['total_profit'],
            'captured_count': swing_result['captured_count']
        },
        'decision_source': 'Multi-start search with trailing stop',
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
    
    统一AI调用接口，支持deepseek和qwen
    使用英文与AI沟通以获得更好的推理能力
    
    Args:
        all_opportunities: 所有机会
        phase1_baseline: Phase 1基线
        phase2_baseline: Phase 2基线
        search_results: 多起点搜索结果
        matrix_results: 矩阵筛选结果
        model_name: 模型名称 ("deepseek" 或 "qwen")
    
    Returns:
        ai_recommendation: AI推荐结果
    """
    try:
        # 构建AI提示词（英文）
        prompt = build_ai_analysis_prompt(
            all_opportunities, phase1_baseline, phase2_baseline,
            search_results, matrix_results
        )
        
        # 统一AI调用逻辑
        ai_response = call_ai_unified(prompt, model_name)
        
        # 解析AI响应
        recommendation = parse_ai_recommendation(ai_response)
        
        print(f"     ✓ AI Analysis Completed")
        print(f"     Recommended Strategy: {recommendation.get('strategy', 'N/A')}")
        print(f"     Reason: {recommendation.get('reason', 'N/A')[:80]}...")
        
        return recommendation
        
    except Exception as e:
        print(f"     ⚠️  AI Call Failed: {e}")
        return {}


def call_ai_unified(prompt: str, model_name: str) -> str:
    """
    【V8.5.2.4.41】统一AI调用接口
    
    支持deepseek和qwen，使用相同的API调用逻辑
    
    Args:
        prompt: 英文提示词
        model_name: 模型名称
    
    Returns:
        ai_response: AI响应文本
    """
    import os
    import requests
    import json
    
    # 根据模型选择API配置
    if model_name == "deepseek":
        api_key = os.getenv("DEEPSEEK_API_KEY")
        api_url = "https://api.deepseek.com/v1/chat/completions"
        model_id = "deepseek-chat"
    else:  # qwen
        api_key = os.getenv("DASHSCOPE_API_KEY")
        api_url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
        model_id = "qwen-plus"
    
    if not api_key:
        raise ValueError(f"API key not found for {model_name}")
    
    # 构建请求
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    payload = {
        "model": model_id,
        "messages": [
            {
                "role": "system",
                "content": "You are an expert trading system optimizer. Analyze data and provide recommendations in JSON format. Always respond in English."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.7,
        "max_tokens": 2000
    }
    
    # 发送请求
    response = requests.post(api_url, headers=headers, json=payload, timeout=30)
    response.raise_for_status()
    
    # 解析响应
    result = response.json()
    ai_response = result["choices"][0]["message"]["content"]
    
    return ai_response


def build_ai_analysis_prompt(
    all_opportunities: List[Dict],
    phase1_baseline: Dict,
    phase2_baseline: Dict,
    search_results: List[Dict],
    matrix_results: List[Dict]
) -> str:
    """
    Build AI analysis prompt in English
    
    English prompts provide better reasoning capabilities for AI models
    """
    
    # Statistics
    total_opps = len(all_opportunities)
    scalping_count = sum(1 for o in all_opportunities if o.get('signal_type') == 'scalping')
    swing_count = total_opps - scalping_count
    
    # Consensus distribution
    consensus_dist = {}
    for opp in all_opportunities:
        c = opp.get('consensus', 0)  # 【V8.5.2.4.47修复】字段名统一
        consensus_dist[c] = consensus_dist.get(c, 0) + 1
    
    # Signal score distribution
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
    
    prompt = f"""As a trading system optimization expert, please analyze the following data and recommend optimal parameter configuration.

【Phase 1 Objective Statistics】
- Total Opportunities: {total_opps}
- Scalping: {scalping_count}, Swing: {swing_count}
- Average Max Profit: {phase1_baseline.get('avg_max_profit', 0):.2f}%

【Phase 2 Learning Results】
- Best Scalping Weights: {phase2_baseline.get('learned_features', {}).get('best_scalping_weights', {}).get('name', 'N/A')}
- Best Swing Weights: {phase2_baseline.get('learned_features', {}).get('best_swing_weights', {}).get('name', 'N/A')}
- Phase 2 Capture Rate: {phase2_baseline.get('capture_rate', 0)*100:.1f}%
- Phase 2 Avg Profit: {phase2_baseline.get('avg_profit', 0):.2f}%

【Data Distribution】
Consensus Distribution: {consensus_dist}
Signal Score Distribution: {signal_score_ranges}

【Multi-Start Search Results】(Top 3)
"""
    
    for i, result in enumerate(search_results[:3], 1):
        prompt += f"""
{i}. Starting Point: {result.get('starting_point', 'N/A')}
   Total Profit: {result.get('total_profit', 0):.1f}%
   Capture Rate: {result.get('capture_rate', 0)*100:.1f}%
   Params: consensus>={result.get('params', {}).get('min_indicator_consensus', 'N/A')}, 
           signal_score>={result.get('params', {}).get('min_signal_score', 'N/A')}
"""
    
    prompt += f"""
【Filter Matrix Results】(Top 3)
"""
    
    for i, result in enumerate(matrix_results[:3], 1):
        prompt += f"""
{i}. {result.get('name', 'N/A')}
   consensus>={result['min_consensus']}, signal_score>={result['min_signal_score']}
   Capture Rate: {result['capture_rate']*100:.1f}%
   Avg Profit: {result['avg_profit']:.2f}%
   Total Profit: {result['total_profit']:.1f}%
   Composite Score: {result['score']:.1f}
"""
    
    prompt += """
【Questions】
1. Comprehensive Evaluation: Which configuration is optimal and why?
2. Parameter Recommendation: What are the recommended min_consensus and min_signal_score?
3. Risk Warning: What are the potential risks of this configuration?

Please respond in JSON format (English):
{
    "recommended_params": {
        "min_indicator_consensus": <number>,
        "min_signal_score": <number>,
        "min_risk_reward": <number>
    },
    "strategy": "<brief description>",
    "reason": "<detailed reasoning>",
    "risks": "<potential risks>"
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


def optimize_for_signal_type(
    opportunities: List[Dict],
    signal_type: str,
    learned_features: Dict,
    starting_points: List[Dict],
    kline_snapshots=None
) -> Dict:
    """
    【V8.5.2.4.42】为特定信号类型优化参数
    
    分别为超短线和波段寻找最优参数配置（包括移动止损）
    
    Args:
        opportunities: 该信号类型的机会列表
        signal_type: 'scalping' 或 'swing'
        learned_features: Phase 2学习的特征
        starting_points: 候选起点列表
        kline_snapshots: 市场快照数据
    
    Returns:
        result: {
            'best_params': {...},
            'capture_rate': float,
            'avg_profit': float,
            'total_profit': float,
            'captured_count': int
        }
    """
    # 【V8.5.2.4.69】使用calculate_actual_profit_batch而不是batch_calculate_profits
    # 原因: batch_calculate_profits会走到模拟逻辑_calculate_with_max_profit
    #       而没有使用V8.5.2.4.65的波动幅度修复
    from calculate_actual_profit import calculate_actual_profit_batch
    import gc
    
    print(f"\n  🎯 【{signal_type.upper()}参数优化】")
    print(f"     机会数量: {len(opportunities)}个")
    
    # 【V8.5.2.4.47】内存优化：对大量机会进行采样
    if len(opportunities) > 1000:
        import random
        sample_size = 1000
        sampled_opportunities = random.sample(opportunities, sample_size)
        print(f"     💾 内存优化：采样{sample_size}个机会（保留{sample_size/len(opportunities)*100:.1f}%）")
        opportunities = sampled_opportunities
        gc.collect()
    
    # 【V8.5.2.4.49】基于利润密度动态调整参数搜索空间
    # 核心理念：高密度→快进快出，低密度→长期持有
    
    import numpy as np
    
    # 提取该类型的平均密度和持仓时间
    densities = [o.get('profit_density', 0) for o in opportunities if o.get('profit_density', 0) > 0]
    holding_hours_list = [o.get('holding_hours', 0) for o in opportunities if o.get('holding_hours', 0) > 0]
    avg_profit = np.mean([o.get('objective_profit', 0) for o in opportunities]) if opportunities else 15.0
    
    avg_density = np.mean(densities) if densities else (10.0 if signal_type == 'scalping' else 1.0)
    avg_holding = np.mean(holding_hours_list) if holding_hours_list else (4.0 if signal_type == 'scalping' else 20.0)
    
    print(f"     💡 {signal_type}特征: 密度{avg_density:.1f}, 持仓{avg_holding:.1f}h, 平均利润{avg_profit:.1f}%")
    
    # 【V8.5.2.4.68】从learned_features提取Phase 2测试的最优TP/SL
    # Phase 3目标：固定TP/SL，优化筛选条件（去掉杂音，提高平均利润）
    optimal_tp_sl = learned_features.get('optimal_tp_sl', {})
    
    if signal_type == 'scalping':
        # 【V8.5.2.4.68】固定Phase 2最优TP/SL，重点测试筛选条件
        scalping_optimal = optimal_tp_sl.get('scalping', {})
        optimal_tp = scalping_optimal.get('atr_tp_multiplier', 12.0)  # Phase 2找到的最优值
        optimal_sl = scalping_optimal.get('atr_stop_multiplier', 2.0)
        
        # 【V8.5.2.4.74】8维度筛选可选化
        # 从learned_features或全局配置中获取（默认关闭）
        enable_advanced_filters = learned_features.get('enable_advanced_filters', False)
        
        # 【V8.5.2.4.73】Phase 3全维度智能筛选 + 微调TP/SL
        # 目标：在Phase 2基础上提高利润（当前6.46% → 目标10-15%）
        # 策略：K线形态+趋势强度+支撑阻力+利润密度+微调TP
        param_grid = {
            # 核心筛选条件
            'min_indicator_consensus': [1, 2, 3],             # 共振度
            'min_signal_score': [75, 80, 85],                # 信号分（减少1个，因为增加其他维度）
            
            # 质量控制条件
            'min_risk_reward': [1.5, 2.0],                   # R:R（减少1个）
            'min_profit_density': [8.0, 10.0, 12.0],         # 利润密度（超短线）
            
            # TP/SL优化
            'atr_tp_multiplier': [optimal_tp * 0.9, optimal_tp, optimal_tp * 1.1],
            'atr_stop_multiplier': [optimal_sl],
            'max_holding_hours': [int(avg_holding)],
        }
        
        # 【V8.5.2.4.74】高级筛选（仅在启用时添加）
        if enable_advanced_filters:
            param_grid.update({
                'require_strong_pattern': [False, True],
                'min_trend_strength': ['any', 'normal', 'strong'],
                'require_near_sr': [False, True],
                'trailing_stop_enabled': [False, True],
            })
            print(f"     🎨 【V8.5.2.4.74】高级筛选已启用（8维度探索+移动止损）")
        else:
            # 【V8.5.2.4.74】默认启用移动止损，但不启用其他高级筛选
            param_grid.update({
                'require_strong_pattern': [False],
                'min_trend_strength': ['any'],
                'require_near_sr': [False],
                'trailing_stop_enabled': [True],
            })
            print(f"     🎯 【V8.5.2.4.74】使用标准筛选+移动止损（5维度：基础+质量+TP）")
        
        print(f"     📐 基础条件: score≥{param_grid['min_signal_score']}, consensus≥{param_grid['min_indicator_consensus']}")
        print(f"     💡 质量控制: R:R≥{param_grid['min_risk_reward']}, 密度≥{param_grid['min_profit_density']}")
        print(f"     🎯 TP微调（±10%）: 范围[{optimal_tp*0.9:.1f}, {optimal_tp:.1f}, {optimal_tp*1.1:.1f}], SL={optimal_sl:.1f}")
        print(f"     🚀 目标：{'全维度筛选' if enable_advanced_filters else '标准筛选+移动止损'}，提高平均利润（当前6.46% → 目标10-15%）")
    else:  # swing
        # 【V8.5.2.4.68】固定Phase 2最优TP/SL，重点测试筛选条件
        swing_optimal = optimal_tp_sl.get('swing', {})
        optimal_tp = swing_optimal.get('atr_tp_multiplier', 18.0)  # Phase 2找到的最优值
        optimal_sl = swing_optimal.get('atr_stop_multiplier', 2.5)
        
        # 【V8.5.2.4.74】8维度筛选可选化
        # 从learned_features或全局配置中获取（默认关闭）
        enable_advanced_filters = learned_features.get('enable_advanced_filters', False)
        
        # 【V8.5.2.4.73】Phase 3全维度智能筛选 + 微调TP/SL
        # 目标：在Phase 2基础上提高利润（当前6.49% → 目标10-15%）
        # 策略：K线形态+趋势强度+支撑阻力+利润密度+微调TP
        param_grid = {
            # 核心筛选条件
            'min_indicator_consensus': [1, 2, 3],             # 共振度
            'min_signal_score': [80, 85, 90],                # 信号分（减少1个）
            
            # 质量控制条件
            'min_risk_reward': [1.5, 2.0],                   # R:R（减少1个）
            'min_profit_density': [0.5, 0.8, 1.0],           # 利润密度（波段）
            
            # TP/SL优化
            'atr_tp_multiplier': [optimal_tp * 0.9, optimal_tp, optimal_tp * 1.1],
            'atr_stop_multiplier': [optimal_sl],
            'max_holding_hours': [int(avg_holding)],
        }
        
        # 【V8.5.2.4.74】高级筛选（仅在启用时添加）
        if enable_advanced_filters:
            param_grid.update({
                'require_strong_pattern': [False, True],
                'min_trend_strength': ['any', 'normal', 'strong'],
                'require_near_sr': [False, True],
                'trailing_stop_enabled': [False, True],
            })
            print(f"     🎨 【V8.5.2.4.74】高级筛选已启用（8维度探索+移动止损）")
        else:
            # 【V8.5.2.4.74】默认启用移动止损，但不启用其他高级筛选
            param_grid.update({
                'require_strong_pattern': [False],
                'min_trend_strength': ['any'],
                'require_near_sr': [False],
                'trailing_stop_enabled': [True],
            })
            print(f"     🎯 【V8.5.2.4.74】使用标准筛选+移动止损（5维度：基础+质量+TP）")
        
        print(f"     📐 基础条件: score≥{param_grid['min_signal_score']}, consensus≥{param_grid['min_indicator_consensus']}")
        print(f"     💡 质量控制: R:R≥{param_grid['min_risk_reward']}, 密度≥{param_grid['min_profit_density']}")
        print(f"     🎯 TP微调（±10%）: 范围[{optimal_tp*0.9:.1f}, {optimal_tp:.1f}, {optimal_tp*1.1:.1f}], SL={optimal_sl:.1f}")
        print(f"     🚀 目标：{'全维度筛选' if enable_advanced_filters else '标准筛选+移动止损'}，提高平均利润（当前6.49% → 目标10-15%）")
        print(f"     🎯 目标：去掉杂音，提高平均利润（预期7% → 10-14%）")
    
    # 多起点搜索
    all_results = []
    
    for sp_idx, starting_point in enumerate(starting_points, 1):
        print(f"     [{sp_idx}/{len(starting_points)}] 从'{starting_point['name']}'出发...")
        
        # 【V8.5.2.4.68】生成测试组合：signal_score × consensus × min_risk_reward
        # 由于TP/SL已固定，重点测试筛选条件组合
        test_combinations = []
        
        # 【V8.5.2.4.73】测试所有筛选条件组合（8维度）
        for consensus in param_grid['min_indicator_consensus']:
            for signal_score in param_grid['min_signal_score']:
                for risk_reward in param_grid['min_risk_reward']:
                    for profit_density in param_grid['min_profit_density']:
                        for require_pattern in param_grid['require_strong_pattern']:
                            for trend_strength in param_grid['min_trend_strength']:
                                for require_sr in param_grid['require_near_sr']:
                                    for tp_multiplier in param_grid['atr_tp_multiplier']:
                                        test_params = {
                                            'min_indicator_consensus': consensus,
                                            'min_signal_score': signal_score,
                                            'min_risk_reward': risk_reward,
                                            'min_profit_density': profit_density,
                                            'require_strong_pattern': require_pattern,    # 【V8.5.2.4.73】新增
                                            'min_trend_strength': trend_strength,         # 【V8.5.2.4.73】新增
                                            'require_near_sr': require_sr,                # 【V8.5.2.4.73】新增
                                            'atr_tp_multiplier': tp_multiplier,
                                            'atr_stop_multiplier': param_grid['atr_stop_multiplier'][0],
                                            'max_holding_hours': param_grid['max_holding_hours'][0],
                                            'trailing_stop_enabled': False
                                        }
                                        test_combinations.append(test_params)
        
        # 【V8.5.2.4.73】测试组合数量：3×3×2×3×2×3×2×3=1944组（8维度全面测试）
        # 维度：score×consensus×R:R×密度×K线形态×趋势强度×S/R×TP
        print(f"     📊 测试组合数: {len(test_combinations)}组 (8维度：基础+形态+趋势+S/R+TP)")
        
        # 测试每个组合
        best_for_this_start = None
        for params in test_combinations:
            # 【V8.5.2.4.73】全维度智能筛选：基础条件 + K线形态 + 趋势强度 + 支撑阻力
            filtered_opps = []
            for opp in opportunities:
                # 基础条件
                if opp.get('consensus', 0) < params['min_indicator_consensus']:
                    continue
                if opp.get('signal_score', 0) < params['min_signal_score']:
                    continue
                if opp.get('risk_reward', 0) < params.get('min_risk_reward', 0):
                    continue
                if opp.get('profit_density', 0) < params.get('min_profit_density', 0):
                    continue
                
                # 【V8.5.2.4.73】K线形态筛选
                if params.get('require_strong_pattern', False):
                    snapshot = opp.get('snapshot', {})
                    has_pin_bar = snapshot.get('has_pin_bar', False)
                    has_engulfing = snapshot.get('has_engulfing', False)
                    has_breakout = snapshot.get('has_breakout', False)
                    if not (has_pin_bar or has_engulfing or has_breakout):
                        continue  # 必须有强K线形态
                
                # 【V8.5.2.4.73】趋势强度筛选
                min_strength = params.get('min_trend_strength', 'any')
                if min_strength != 'any':
                    snapshot = opp.get('snapshot', {})
                    trend_4h_strength = snapshot.get('trend_4h_strength', 'weak')
                    if min_strength == 'strong' and trend_4h_strength != 'strong':
                        continue  # 必须是强势趋势
                    elif min_strength == 'normal' and trend_4h_strength == 'weak':
                        continue  # 至少有正常趋势
                
                # 【V8.5.2.4.73】支撑/阻力位筛选
                if params.get('require_near_sr', False):
                    snapshot = opp.get('snapshot', {})
                    # 检查价格是否在S/R的±3%范围内
                    current_price = snapshot.get('current_price', 0)
                    if current_price > 0:
                        sr = snapshot.get('support_resistance', {})
                        nearest_support = sr.get('nearest_support') or {}
                        nearest_resistance = sr.get('nearest_resistance') or {}
                        support_price = nearest_support.get('price', 0)
                        resistance_price = nearest_resistance.get('price', 0)
                        
                        near_support = support_price > 0 and abs(current_price - support_price) / current_price < 0.03
                        near_resistance = resistance_price > 0 and abs(current_price - resistance_price) / current_price < 0.03
                        
                        if not (near_support or near_resistance):
                            continue  # 必须靠近S/R
                
                # 通过所有筛选条件
                filtered_opps.append(opp)
            
            if not filtered_opps:
                continue
            
            # 【V8.5.2.4.69】使用calculate_actual_profit_batch计算利润
            # 它会使用future_data和V8.5.2.4.65的波动幅度修复
            profit_results = calculate_actual_profit_batch(
                filtered_opps, 
                params, 
                batch_size=1000, 
                use_dynamic_atr=True, 
                include_trading_costs=True
            )
            
            # 统计
            captured_count = len(profit_results)
            capture_rate = captured_count / len(opportunities) if opportunities else 0
            # 【V8.5.2.4.69】修复：字段名应为actual_profit_pct（calculate_actual_profit_batch返回的字段名）
            total_profit = sum(r.get('actual_profit_pct', 0) for r in profit_results)
            avg_profit = total_profit / captured_count if captured_count > 0 else 0
            
            # 【V8.5.2.4.47】只保存当前起点的最佳结果
            if best_for_this_start is None or total_profit > best_for_this_start['total_profit']:
                best_for_this_start = {
                    'params': params,
                    'starting_point': starting_point['name'],
                    'captured_count': captured_count,
                    'capture_rate': capture_rate,
                    'avg_profit': avg_profit,
                    'total_profit': total_profit
                }
        
        # 【V8.5.2.4.47】每个起点测试完后立即保存最佳结果并释放内存
        if best_for_this_start:
            all_results.append(best_for_this_start)
        gc.collect()  # 立即释放内存
    
    if not all_results:
        print(f"     ⚠️  未找到有效结果")
        return {
            'best_params': {},
            'capture_rate': 0,
            'avg_profit': 0,
            'total_profit': 0,
            'captured_count': 0
        }
    
    # 选择总利润最高的组合
    best_result = max(all_results, key=lambda x: x['total_profit'])
    
    print(f"     ✓ 最优参数找到！")
    print(f"        起点: {best_result['starting_point']}")
    print(f"        捕获率: {best_result['capture_rate']*100:.1f}% ({best_result['captured_count']}/{len(opportunities)})")
    print(f"        平均利润: {best_result['avg_profit']:.2f}%")
    print(f"        总利润: {best_result['total_profit']:.1f}%")
    print(f"        移动止损: {'✅ 启用' if best_result['params']['trailing_stop_enabled'] else '❌ 禁用'}")
    
    return {
        'best_params': best_result['params'],
        'capture_rate': best_result['capture_rate'],
        'avg_profit': best_result['avg_profit'],
        'total_profit': best_result['total_profit'],
        'captured_count': best_result['captured_count'],
        'starting_point': best_result['starting_point']
    }

