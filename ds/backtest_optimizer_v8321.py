#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
【V8.3.21】回测优化模块 - 轻量级、成本优化、资源控制

特性：
1. 多维度Grid Search（11个参数维度）
2. V8.3.21上下文过滤（K线/市场结构/S/R历史）
3. 本地统计分析（参数敏感度、异常检测）
4. 成本优化的AI决策（压缩数据、精简Prompt）
5. 资源控制（限制内存、CPU nice值、进程隔离）

适用环境：2核2G服务器
"""

import os
import gc
import psutil
import random
import numpy as np
from typing import Dict, List, Tuple, Any
from datetime import datetime


# ============================================================
# 【步骤2】轻量级Grid Search（资源控制）
# ============================================================

def optimize_params_v8321_lightweight(opportunities: List[Dict], 
                                      current_params: Dict, 
                                      signal_type: str = 'scalping',
                                      max_combinations: int = 200) -> Dict:
    """
    【V8.3.21】轻量级参数优化
    
    设计：
    - 2核CPU：使用随机采样代替遍历（200组 vs 2592组）
    - 2G内存：及时释放内存，每10组GC一次
    - 进程隔离：设置nice值，避免影响实时AI
    
    Args:
        opportunities: 机会列表（已包含V8.3.21字段）
        current_params: 当前参数
        signal_type: 'scalping' or 'swing'
        max_combinations: 最大测试组数（默认200）
    
    Returns:
        {
            'optimized_params': {...},
            'top_10_configs': [...],
            'statistics': {...},
            'cost_saved': 0.xx
        }
    """
    # 设置进程优先级（nice值=10，避免影响实时AI）
    try:
        os.nice(10)
        print(f"   ℹ️  已设置进程优先级（nice=10），避免影响实时AI")
    except:
        pass
    
    print(f"\n{'='*60}")
    print(f"【V8.3.21回测优化】轻量级参数搜索（{signal_type}）")
    print(f"  机会数: {len(opportunities)}")
    print(f"  测试组数: {max_combinations}")
    print(f"  内存限制: 检测到{psutil.virtual_memory().total / (1024**3):.1f}G，将主动控制")
    print(f"{'='*60}\n")
    
    # ===== 阶段1：定义搜索空间 =====
    print("📊 阶段1: 定义搜索空间...")
    
    param_grid = define_param_grid_v8321(signal_type)
    total_combinations = calculate_total_combinations(param_grid)
    
    print(f"   ✅ 搜索空间定义完成")
    print(f"      理论组合数: {total_combinations}组")
    print(f"      实际测试数: {max_combinations}组（随机采样）")
    
    # ===== 阶段2：随机采样Grid Search =====
    print(f"\n🔍 阶段2: 随机采样Grid Search...")
    
    sampled_params = random_sample_param_grid(param_grid, max_combinations)
    all_results = []
    
    for i, params in enumerate(sampled_params):
        # 内存检查（每10组检查一次）
        if i % 10 == 0:
            mem_usage = psutil.Process().memory_info().rss / (1024**2)
            if mem_usage > 300:  # 超过300MB则GC
                gc.collect()
                print(f"      [{i}/{max_combinations}] 内存: {mem_usage:.0f}MB → GC")
        
        # 模拟这个参数配置
        result = simulate_params_with_v8321_filter(opportunities, params)
        score = calculate_v8321_optimization_score(result)
        
        all_results.append({
            'params': params,
            'score': score,
            'metrics': extract_key_metrics(result)
        })
        
        # 进度显示
        if (i + 1) % 20 == 0:
            print(f"      进度: {i+1}/{max_combinations}...")
    
    # 排序并取Top 10
    top_10 = sorted(all_results, key=lambda x: x['score'], reverse=True)[:10]
    
    print(f"   ✅ Grid Search完成")
    print(f"      最高分: {top_10[0]['score']:.3f}")
    print(f"      测试组数: {len(all_results)}")
    
    # 主动GC
    gc.collect()
    
    # ===== 阶段3：本地统计分析 =====
    print(f"\n📈 阶段3: 本地统计分析（免费）...")
    
    # 本地计算：参数敏感度
    param_sensitivity = calculate_param_sensitivity_local(all_results)
    
    # 本地计算：上下文特征相关性
    context_analysis = analyze_context_features_local(opportunities, top_10[0]['params'])
    
    # 本地检测：异常情况
    anomalies = detect_anomalies_local(all_results, param_sensitivity)
    
    print(f"   ✅ 统计分析完成")
    print(f"      关键参数: {list(param_sensitivity.keys())[:3]}")
    print(f"      异常检测: {len(anomalies)}个")
    
    # ===== 阶段4：数据压缩 =====
    print(f"\n🗜️  阶段4: 数据压缩（节省AI成本）...")
    
    compressed_data = compress_optimization_results(
        top_10=top_10,
        param_sensitivity=param_sensitivity,
        context_analysis=context_analysis,
        anomalies=anomalies
    )
    
    estimated_tokens = estimate_token_count(compressed_data)
    original_tokens = len(all_results) * 100  # 假设原始每组100 tokens
    cost_saved = (original_tokens - estimated_tokens) * 0.00002  # GPT-4价格
    
    print(f"   ✅ 数据压缩完成")
    print(f"      原始: ~{original_tokens} tokens")
    print(f"      压缩后: ~{estimated_tokens} tokens")
    print(f"      💰 预计节省: ${cost_saved:.4f}")
    
    return {
        'optimized_params': top_10[0]['params'],
        'top_10_configs': top_10,
        'statistics': {
            'param_sensitivity': param_sensitivity,
            'score_distribution': calculate_score_distribution(all_results)
        },
        'context_analysis': context_analysis,
        'anomalies': anomalies,
        'compressed_data': compressed_data,
        'cost_saved': cost_saved
    }


def define_param_grid_v8321(signal_type: str) -> Dict:
    """
    定义V8.3.21参数搜索空间
    
    包含：
    - 基础参数（4个）
    - V8.3.21上下文过滤参数（7个）
    """
    if signal_type == 'scalping':
        grid = {
            # 基础参数
            'max_holding_hours': [1, 2, 4],
            'atr_tp_multiplier': [2.0, 3.0, 4.0],
            'atr_stop_multiplier': [1.5, 2.0],
            'min_risk_reward': [1.5, 2.0, 2.5],
            
            # V8.3.21新增：入场过滤参数
            'min_signal_score': [50, 60, 70],
            'min_consensus': [2, 3, 4],
            'min_kline_bullish_ratio': [0.6, 0.7],
            'min_price_chg_pct': [0.5, 1.0, 1.5],
            'allowed_mkt_struct': ['all', 'trend_only'],
            'min_trend_age_hours': [0.5, 1.0],
            'max_sr_test_count': [5, 999]
        }
    else:  # swing
        grid = {
            # 基础参数
            'max_holding_hours': [48, 60, 72],
            'atr_tp_multiplier': [2.0, 3.0, 4.0],
            'atr_stop_multiplier': [1.5, 2.0],
            'min_risk_reward': [1.5, 2.0, 2.5],
            
            # V8.3.21新增：入场过滤参数
            'min_signal_score': [50, 60, 70],
            'min_consensus': [2, 3, 4],
            'min_kline_bullish_ratio': [0.6, 0.7],
            'min_price_chg_pct': [0.5, 1.0, 1.5],
            'allowed_mkt_struct': ['all', 'trend_only'],
            'min_trend_age_hours': [1.0, 2.0],
            'max_sr_test_count': [5, 999]
        }
    
    return grid


def random_sample_param_grid(grid: Dict, sample_size: int) -> List[Dict]:
    """
    随机采样参数组合
    
    避免遍历所有组合（2592组→200组）
    """
    samples = []
    
    # 获取所有参数名和取值
    param_names = list(grid.keys())
    param_values = [grid[name] for name in param_names]
    
    # 生成所有组合的索引
    from itertools import product
    all_indices = list(product(*[range(len(vals)) for vals in param_values]))
    
    # 随机采样
    sampled_indices = random.sample(all_indices, min(sample_size, len(all_indices)))
    
    # 构建参数字典
    for indices in sampled_indices:
        params = {
            param_names[i]: param_values[i][indices[i]]
            for i in range(len(param_names))
        }
        samples.append(params)
    
    return samples


def calculate_total_combinations(grid: Dict) -> int:
    """计算总组合数"""
    total = 1
    for values in grid.values():
        total *= len(values)
    return total


# ============================================================
# 【步骤3】V8.3.21上下文过滤函数
# ============================================================

def simulate_params_with_v8321_filter(opportunities: List[Dict], params: Dict) -> Dict:
    """
    【V8.3.21】使用上下文过滤参数模拟交易
    
    过滤层次：
    1. 基础过滤（signal_score/consensus/risk_reward）
    2. K线上下文过滤（阳线比例、价格变化）
    3. 市场结构过滤（swing类型、趋势年龄）
    4. S/R历史过滤（测试次数、假突破）
    """
    captured = []
    missed_reasons = {}
    
    for opp in opportunities:
        # 第1层：基础过滤
        if not passes_basic_filter(opp, params):
            reason = 'basic_params'
            missed_reasons[reason] = missed_reasons.get(reason, 0) + 1
            continue
        
        # 第2层：K线上下文过滤
        if not passes_kline_context_filter(opp, params):
            reason = 'kline_context'
            missed_reasons[reason] = missed_reasons.get(reason, 0) + 1
            continue
        
        # 第3层：市场结构过滤
        if not passes_market_structure_filter(opp, params):
            reason = 'market_structure'
            missed_reasons[reason] = missed_reasons.get(reason, 0) + 1
            continue
        
        # 第4层：S/R历史过滤
        if not passes_sr_history_filter(opp, params):
            reason = 'sr_history'
            missed_reasons[reason] = missed_reasons.get(reason, 0) + 1
            continue
        
        # 通过所有过滤，记录
        captured.append(opp)
    
    # 计算统计指标
    if len(captured) == 0:
        return {
            'total_opportunities': len(opportunities),
            'captured_count': 0,
            'capture_rate': 0,
            'avg_profit': 0,
            'win_rate': 0,
            'time_exit_rate': 0,
            'missed_reasons': missed_reasons
        }
    
    # 计算利润（使用actual_profit_pct作为模拟利润）
    profits = [c['actual_profit_pct'] for c in captured]
    avg_profit = np.mean(profits)
    win_rate = len([p for p in profits if p > 0]) / len(profits)
    
    return {
        'total_opportunities': len(opportunities),
        'captured_count': len(captured),
        'capture_rate': len(captured) / len(opportunities),
        'avg_profit': avg_profit,
        'win_rate': win_rate,
        'time_exit_rate': 0.5,  # 简化：假设50% time_exit
        'missed_reasons': missed_reasons,
        'captured_details': captured  # 详细数据（用于进一步分析）
    }


def passes_basic_filter(opp: Dict, params: Dict) -> bool:
    """基础参数过滤"""
    return (
        opp['signal_score'] >= params.get('min_signal_score', 50) and
        opp['consensus'] >= params.get('min_consensus', 2) and
        opp['risk_reward'] >= params.get('min_risk_reward', 1.5)
    )


def passes_kline_context_filter(opp: Dict, params: Dict) -> bool:
    """K线上下文过滤"""
    # 检查阳线/阴线比例
    bullish_ratio = opp.get('kline_ctx_bullish_ratio', 0)
    min_ratio = params.get('min_kline_bullish_ratio', 0.6)
    
    if opp['direction'] == 'long':
        if bullish_ratio < min_ratio:
            return False
    else:  # short
        if (1 - bullish_ratio) < min_ratio:
            return False
    
    # 检查价格变化幅度
    price_chg = abs(opp.get('kline_ctx_price_chg_pct', 0))
    if price_chg < params.get('min_price_chg_pct', 0.5):
        return False
    
    return True


def passes_market_structure_filter(opp: Dict, params: Dict) -> bool:
    """市场结构过滤"""
    # 检查是否只做趋势市场
    if params.get('allowed_mkt_struct') == 'trend_only':
        swing_type = opp.get('mkt_struct_swing', '')
        if swing_type not in ['HH-HL', 'LL-LH']:
            return False
    
    # 检查趋势年龄
    trend_age = opp.get('mkt_struct_age_hours', 0)
    min_age = params.get('min_trend_age_hours', 0.5)
    if trend_age < min_age:
        return False
    
    return True


def passes_sr_history_filter(opp: Dict, params: Dict) -> bool:
    """S/R历史过滤"""
    # 根据方向选择对应的S/R
    if opp['direction'] == 'long':
        test_cnt = opp.get('support_hist_test_cnt', 0)
        false_bd = opp.get('support_hist_false_bd', 0)
    else:
        test_cnt = opp.get('resist_hist_test_cnt', 0)
        false_bd = opp.get('resist_hist_false_bo', 0)
    
    # 检查测试次数
    max_test = params.get('max_sr_test_count', 999)
    if test_cnt > max_test:
        return False
    
    # 检查假突破（固定≤2次）
    if false_bd > 2:
        return False
    
    return True


# ============================================================
# 【步骤4】本地统计分析函数
# ============================================================

def calculate_param_sensitivity_local(all_results: List[Dict]) -> Dict:
    """
    【本地计算】参数敏感度分析
    
    计算每个参数变化时，score的平均变化量
    """
    sensitivity = {}
    
    # 按参数分组
    param_names = list(all_results[0]['params'].keys())
    
    for param_name in param_names:
        # 获取该参数的所有取值
        param_values = sorted(set([r['params'][param_name] for r in all_results]))
        
        if len(param_values) < 2:
            continue
        
        # 计算相邻取值之间的score变化
        score_changes = []
        for i in range(len(param_values) - 1):
            v1, v2 = param_values[i], param_values[i+1]
            
            # 找到该参数=v1和v2的结果
            results_v1 = [r for r in all_results if r['params'][param_name] == v1]
            results_v2 = [r for r in all_results if r['params'][param_name] == v2]
            
            if results_v1 and results_v2:
                avg_score_v1 = np.mean([r['score'] for r in results_v1])
                avg_score_v2 = np.mean([r['score'] for r in results_v2])
                
                # 计算单位变化的影响
                param_change = abs(v2 - v1) if isinstance(v1, (int, float)) else 1
                score_change = (avg_score_v2 - avg_score_v1) / param_change
                score_changes.append(score_change)
        
        if score_changes:
            avg_impact = np.mean(score_changes)
            sensitivity[param_name] = {
                'avg_impact': round(avg_impact, 3),
                'std_impact': round(np.std(score_changes), 3),
                'importance': 'high' if abs(avg_impact) > 0.1 else 'medium' if abs(avg_impact) > 0.05 else 'low'
            }
    
    return sensitivity


def analyze_context_features_local(opportunities: List[Dict], best_params: Dict) -> Dict:
    """
    【本地计算】上下文特征分析
    
    分析V8.3.21字段与成功的关系
    """
    # 使用最优参数模拟，区分captured和missed
    result = simulate_params_with_v8321_filter(opportunities, best_params)
    captured = result.get('captured_details', [])
    
    if len(captured) == 0:
        return {'error': '无捕获机会'}
    
    analysis = {}
    
    # 分析1：K线上下文
    analysis['kline_context'] = analyze_kline_context_impact(captured)
    
    # 分析2：市场结构
    analysis['market_structure'] = analyze_market_structure_impact(captured)
    
    # 分析3：S/R历史
    analysis['sr_history'] = analyze_sr_history_impact(captured)
    
    # 生成关键洞察
    analysis['key_insights'] = generate_insights_from_analysis(analysis)
    
    return analysis


def analyze_kline_context_impact(captured: List[Dict]) -> Dict:
    """分析K线上下文与成功率的关系"""
    # 按阳线比例分组
    groups = {
        '0.6-0.7': [],
        '0.7-0.8': [],
        '0.8-1.0': []
    }
    
    for opp in captured:
        ratio = opp.get('kline_ctx_bullish_ratio', 0)
        if 0.6 <= ratio < 0.7:
            groups['0.6-0.7'].append(opp)
        elif 0.7 <= ratio < 0.8:
            groups['0.7-0.8'].append(opp)
        elif 0.8 <= ratio <= 1.0:
            groups['0.8-1.0'].append(opp)
    
    # 计算各组统计
    result = {}
    for range_name, group in groups.items():
        if len(group) > 0:
            profits = [o['actual_profit_pct'] for o in group]
            result[range_name] = {
                'count': len(group),
                'avg_profit': round(np.mean(profits), 1),
                'win_rate': round(len([p for p in profits if p > 0]) / len(profits), 2)
            }
    
    # 生成结论
    if result:
        best_range = max(result.keys(), key=lambda k: result[k]['avg_profit'])
        result['conclusion'] = f"阳线比例{best_range}时效果最好（平均利润{result[best_range]['avg_profit']:.1f}%）"
    
    return result


def analyze_market_structure_impact(captured: List[Dict]) -> Dict:
    """分析市场结构与成功率的关系"""
    # 按swing类型分组
    groups = {}
    for opp in captured:
        swing_type = opp.get('mkt_struct_swing', 'unknown')
        if swing_type not in groups:
            groups[swing_type] = []
        groups[swing_type].append(opp)
    
    # 计算各组统计
    result = {}
    for swing_type, group in groups.items():
        if len(group) > 0:
            profits = [o['actual_profit_pct'] for o in group]
            result[swing_type] = {
                'count': len(group),
                'avg_profit': round(np.mean(profits), 1)
            }
    
    # 生成结论
    if result:
        best_type = max(result.keys(), key=lambda k: result[k]['avg_profit'])
        result['conclusion'] = f"{best_type}结构效果最好（平均利润{result[best_type]['avg_profit']:.1f}%）"
    
    return result


def analyze_sr_history_impact(captured: List[Dict]) -> Dict:
    """分析S/R历史与成功率的关系"""
    # 按测试次数分组
    groups = {
        '1-2次': [],
        '3-5次': [],
        '5次+': []
    }
    
    for opp in captured:
        test_cnt = opp.get('resist_hist_test_cnt', 0) if opp['direction'] == 'short' else opp.get('support_hist_test_cnt', 0)
        
        if 1 <= test_cnt <= 2:
            groups['1-2次'].append(opp)
        elif 3 <= test_cnt <= 5:
            groups['3-5次'].append(opp)
        elif test_cnt > 5:
            groups['5次+'].append(opp)
    
    # 计算各组统计
    result = {}
    for range_name, group in groups.items():
        if len(group) > 0:
            profits = [o['actual_profit_pct'] for o in group]
            result[range_name] = {
                'count': len(group),
                'avg_profit': round(np.mean(profits), 1)
            }
    
    # 生成结论
    if result:
        best_range = max(result.keys(), key=lambda k: result[k]['avg_profit'])
        result['conclusion'] = f"S/R测试{best_range}时效果最好（平均利润{result[best_range]['avg_profit']:.1f}%）"
    
    return result


def generate_insights_from_analysis(analysis: Dict) -> List[str]:
    """从分析中生成关键洞察"""
    insights = []
    
    # K线上下文洞察
    if 'kline_context' in analysis and 'conclusion' in analysis['kline_context']:
        insights.append(f"💡 {analysis['kline_context']['conclusion']}")
    
    # 市场结构洞察
    if 'market_structure' in analysis and 'conclusion' in analysis['market_structure']:
        insights.append(f"💡 {analysis['market_structure']['conclusion']}")
    
    # S/R历史洞察
    if 'sr_history' in analysis and 'conclusion' in analysis['sr_history']:
        insights.append(f"💡 {analysis['sr_history']['conclusion']}")
    
    return insights


def detect_anomalies_local(all_results: List[Dict], param_sensitivity: Dict) -> List[Dict]:
    """
    【本地检测】异常情况
    
    基于规则检测异常，不需要AI
    """
    anomalies = []
    
    # 异常1：某个参数导致捕获率骤降
    for param_name in param_sensitivity.keys():
        # 找到该参数的极端值
        param_results = {}
        for r in all_results:
            pval = r['params'][param_name]
            if pval not in param_results:
                param_results[pval] = []
            param_results[pval].append(r['metrics'].get('capture_rate', 0))
        
        # 计算每个值的平均捕获率
        param_avg_capture = {k: np.mean(v) for k, v in param_results.items()}
        
        # 检测骤降
        values = sorted(param_avg_capture.keys())
        for i in range(len(values) - 1):
            v1, v2 = values[i], values[i+1]
            drop = param_avg_capture[v2] - param_avg_capture[v1]
            
            if drop < -0.2:  # 下降超过20%
                anomalies.append({
                    'type': 'capture_rate_drop',
                    'param': param_name,
                    'from_value': v1,
                    'to_value': v2,
                    'drop': round(drop, 2),
                    'severity': 'high' if drop < -0.3 else 'medium',
                    'description': f'{param_name}从{v1}→{v2}时，捕获率下降{abs(drop)*100:.0f}%'
                })
    
    # 异常2：整体捕获率过低
    avg_capture_rate = np.mean([r['metrics'].get('capture_rate', 0) for r in all_results])
    if avg_capture_rate < 0.3:
        anomalies.append({
            'type': 'low_capture_rate',
            'value': round(avg_capture_rate, 2),
            'severity': 'high',
            'description': f'整体捕获率过低（{avg_capture_rate*100:.0f}%），参数可能过严'
        })
    
    return anomalies


# ============================================================
# 【步骤5】评分函数和辅助函数
# ============================================================

def calculate_v8321_optimization_score(result: Dict) -> float:
    """
    【V8.3.21】多维度评分函数
    
    权重：
    - 平均利润: 40%
    - 捕获率: 35%
    - 胜率: 25%
    """
    if result['captured_count'] == 0:
        return 0.0
    
    # 归一化指标
    profit_score = min(1.0, max(0, result['avg_profit'] / 10))  # 10%为满分
    capture_score = result['capture_rate']  # 已经是0-1
    win_score = result['win_rate']  # 已经是0-1
    
    # 加权
    total_score = (
        profit_score * 0.40 +
        capture_score * 0.35 +
        win_score * 0.25
    )
    
    return total_score


def extract_key_metrics(result: Dict) -> Dict:
    """提取关键指标"""
    return {
        'capture_rate': result.get('capture_rate', 0),
        'avg_profit': result.get('avg_profit', 0),
        'win_rate': result.get('win_rate', 0),
        'time_exit_rate': result.get('time_exit_rate', 0)
    }


def calculate_score_distribution(all_results: List[Dict]) -> Dict:
    """计算分数分布"""
    scores = [r['score'] for r in all_results]
    return {
        'mean': round(np.mean(scores), 3),
        'std': round(np.std(scores), 3),
        'min': round(np.min(scores), 3),
        'max': round(np.max(scores), 3),
        'q25': round(np.percentile(scores, 25), 3),
        'q50': round(np.percentile(scores, 50), 3),
        'q75': round(np.percentile(scores, 75), 3)
    }


def compress_optimization_results(top_10: List[Dict], 
                                   param_sensitivity: Dict,
                                   context_analysis: Dict,
                                   anomalies: List[Dict]) -> Dict:
    """
    压缩优化结果（用于AI决策）
    
    将详细数据压缩成摘要
    """
    return {
        'top_3_configs': [
            {
                'rank': i + 1,
                'score': r['score'],
                'params_summary': format_params_compact(r['params']),
                'metrics': r['metrics']
            }
            for i, r in enumerate(top_10[:3])
        ],
        'param_sensitivity_summary': {
            k: v for k, v in sorted(param_sensitivity.items(), 
                                    key=lambda x: abs(x[1]['avg_impact']), 
                                    reverse=True)[:5]  # 只保留Top 5
        },
        'context_insights': context_analysis.get('key_insights', []),
        'anomalies_summary': [
            {
                'type': a['type'],
                'severity': a['severity'],
                'description': a['description']
            }
            for a in anomalies[:3]  # 只保留Top 3
        ]
    }


def format_params_compact(params: Dict) -> str:
    """紧凑格式化参数"""
    return ', '.join([f"{k}={v}" for k, v in list(params.items())[:3]]) + '...'


def estimate_token_count(data: Dict) -> int:
    """估算token数量"""
    import json
    json_str = json.dumps(data)
    # 粗略估算：每4个字符≈1 token
    return len(json_str) // 4


# ============================================================
# 主函数示例
# ============================================================

if __name__ == "__main__":
    print("V8.3.21回测优化模块")
    print("使用方法：从主程序导入 optimize_params_v8321_lightweight")

