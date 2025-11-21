#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
【V8.5.2.4.42】Phase 4参数验证与过拟合检测

核心功能:
1. 使用Phase 1的全量14天数据进行验证
2. 分段测试（前50% vs 后50%样本）
3. 过拟合检测（利润差异、胜率比例）
4. 稳定性评分（0-100分）
5. 使用移动止盈止损计算利润
6. 分别验证超短线和波段参数
"""

from typing import Dict, List, Any, Tuple
from trailing_stop_calculator import batch_calculate_profits


def phase4_validation_and_overfitting_detection(
    phase3_result: Dict,
    all_opportunities: List[Dict],
    phase1_baseline: Dict = None
) -> Dict:
    """
    【V8.5.2.4.42】Phase 4：参数验证与过拟合检测
    
    使用Phase 1识别的全量14天数据验证Phase 3优化的参数
    
    Args:
        phase3_result: Phase 3的输出（包含scalping和swing参数）
        all_opportunities: Phase 1识别的所有机会（14天全量数据）
        phase1_baseline: Phase 1的统计基线
    
    Returns:
        validation_result: {
            'scalping': {...},
            'swing': {...},
            'overall_status': str
        }
    """
    print(f"\n{'='*70}")
    print(f"✅ Phase 4：参数验证与过拟合检测")
    print(f"{'='*70}")
    print(f"  数据范围: Phase 1全量数据（14天）")
    print(f"  验证方法: 分段测试 + 移动止损计算")
    print(f"{'='*70}")
    
    # 提取Phase 3的参数
    scalping_params = phase3_result.get('scalping', {}).get('params', {})
    swing_params = phase3_result.get('swing', {}).get('params', {})
    
    # 分离数据
    scalping_opps = [o for o in all_opportunities if o.get('signal_type') == 'scalping']
    swing_opps = [o for o in all_opportunities if o.get('signal_type') == 'swing']
    
    print(f"\n  📊 数据分布:")
    print(f"     总机会数: {len(all_opportunities)}个")
    print(f"     超短线: {len(scalping_opps)}个")
    print(f"     波段: {len(swing_opps)}个")
    
    # 验证超短线参数
    scalping_validation = validate_signal_type(
        opportunities=scalping_opps,
        params=scalping_params,
        signal_type='scalping',
        phase1_stats=phase1_baseline.get('scalping', {}) if phase1_baseline else {}
    )
    
    # 验证波段参数
    swing_validation = validate_signal_type(
        opportunities=swing_opps,
        params=swing_params,
        signal_type='swing',
        phase1_stats=phase1_baseline.get('swing', {}) if phase1_baseline else {}
    )
    
    # 综合判定
    overall_status = determine_overall_status(scalping_validation, swing_validation)
    
    print(f"\n{'='*70}")
    print(f"🎉 Phase 4验证完成！")
    print(f"   超短线: {scalping_validation['status']}")
    print(f"   波段: {swing_validation['status']}")
    print(f"   综合判定: {overall_status}")
    print(f"{'='*70}")
    
    return {
        'scalping': scalping_validation,
        'swing': swing_validation,
        'overall_status': overall_status
    }


def validate_signal_type(
    opportunities: List[Dict],
    params: Dict,
    signal_type: str,
    phase1_stats: Dict = None
) -> Dict:
    """
    验证特定信号类型的参数
    
    Returns:
        validation: {
            'full_test': {...},
            'early_period': {...},
            'late_period': {...},
            'overfitting': {...},
            'stability_score': float,
            'status': str
        }
    """
    print(f"\n  📊 【{signal_type.upper()}参数验证】")
    
    if not opportunities or not params:
        # 【V8.5.2.4.89.3】更友好的提示，明确区分两种跳过情况
        if not opportunities:
            print(f"     ⚠️  无{signal_type}机会数据，跳过验证")
            print(f"     💡 可能原因: 当前数据量较小或市场条件不符合{signal_type}特征")
        elif not params:
            print(f"     ℹ️  {signal_type}参数已跳过（机会数不足，使用全局参数）")
        else:
            print(f"     ⚠️  跳过{signal_type}验证（原因未知）")
        return {
            'full_test': {},
            'early_period': {},
            'late_period': {},
            'overfitting': {},
            'stability_score': 0,
            'status': 'SKIPPED'
        }
    
    # 1️⃣ 全量数据测试
    full_test = test_params_on_data(opportunities, params, "全量数据（14天）")
    
    # 2️⃣ 分段测试（前50% vs 后50%样本）
    early_period, late_period = split_and_test(opportunities, params)
    
    # 3️⃣ 过拟合检测
    overfitting = detect_overfitting(early_period, late_period)
    
    # 4️⃣ 稳定性评分
    stability_score = calculate_stability_score(full_test, overfitting)
    
    # 5️⃣ 最终判定（传入Phase 1的baseline利润）
    phase2_baseline = phase1_stats.get('avg_profit', 0)
    status = determine_status(full_test, overfitting, stability_score, phase2_baseline)
    
    return {
        'full_test': full_test,
        'early_period': early_period,
        'late_period': late_period,
        'overfitting': overfitting,
        'stability_score': stability_score,
        'status': status,
        'phase2_baseline_profit': phase2_baseline
    }


def test_params_on_data(
    opportunities: List[Dict],
    params: Dict,
    label: str
) -> Dict:
    """
    在指定数据上测试参数（使用移动止损）
    
    Returns:
        result: {
            'captured_count': int,
            'capture_rate': float,
            'avg_profit': float,
            'win_rate': float,
            'total_profit': float
        }
    """
    # 筛选机会
    filtered_opps = [
        opp for opp in opportunities
        if (opp.get('indicator_consensus', 0) >= params.get('min_indicator_consensus', 2) and
            opp.get('signal_score', 0) >= params.get('min_signal_score', 85))
    ]
    
    if not filtered_opps:
        return {
            'captured_count': 0,
            'capture_rate': 0.0,
            'avg_profit': 0.0,
            'win_rate': 0.0,
            'total_profit': 0.0,
            'sample_count': len(opportunities)
        }
    
    # 使用移动止损计算利润
    profit_results = batch_calculate_profits(filtered_opps, params)
    
    # 统计
    captured_count = len(filtered_opps)
    capture_rate = captured_count / len(opportunities) if opportunities else 0
    total_profit = sum(r['profit'] for r in profit_results)
    avg_profit = total_profit / captured_count if captured_count > 0 else 0
    
    # 计算胜率
    profitable_trades = [r for r in profit_results if r['profit'] > 0]
    win_rate = len(profitable_trades) / captured_count if captured_count > 0 else 0
    
    print(f"\n  1️⃣ {label}:")
    print(f"     捕获: {captured_count}个 ({capture_rate*100:.1f}%)")
    print(f"     平均利润: {avg_profit:.2f}%")
    print(f"     胜率: {win_rate*100:.1f}%")
    print(f"     总利润: {total_profit:.1f}%")
    
    return {
        'captured_count': captured_count,
        'capture_rate': capture_rate,
        'avg_profit': avg_profit,
        'win_rate': win_rate,
        'total_profit': total_profit,
        'sample_count': len(opportunities)
    }


def split_and_test(
    opportunities: List[Dict],
    params: Dict
) -> Tuple[Dict, Dict]:
    """
    分段测试（前50% vs 后50%样本）
    
    Returns:
        (early_result, late_result)
    """
    # 按timestamp排序
    sorted_opps = sorted(opportunities, key=lambda x: x.get('timestamp', ''))
    
    # 分割点（50%）
    split_point = len(sorted_opps) // 2
    
    early_opps = sorted_opps[:split_point]
    late_opps = sorted_opps[split_point:]
    
    print(f"\n  2️⃣ 分段测试:")
    print(f"     前期样本: {len(early_opps)}个")
    print(f"     后期样本: {len(late_opps)}个")
    
    # 测试前期
    early_result = test_params_on_data(early_opps, params, "   前期")
    
    # 测试后期
    late_result = test_params_on_data(late_opps, params, "   后期")
    
    return early_result, late_result


def detect_overfitting(
    early_result: Dict,
    late_result: Dict
) -> Dict:
    """
    过拟合检测
    
    Returns:
        overfitting: {
            'profit_degradation': float,
            'winrate_ratio': float,
            'overfitting_score': int,
            'is_overfitted': bool
        }
    """
    early_profit = early_result.get('avg_profit', 0)
    late_profit = late_result.get('avg_profit', 0)
    early_winrate = early_result.get('win_rate', 0)
    late_winrate = late_result.get('win_rate', 0)
    
    # 计算差异
    if early_profit != 0:
        profit_degradation = abs(late_profit - early_profit) / abs(early_profit)
    else:
        profit_degradation = 0 if late_profit == 0 else 1.0
    
    if early_winrate != 0:
        winrate_ratio = late_winrate / early_winrate
    else:
        winrate_ratio = 1.0
    
    # 过拟合评分（0-3）
    overfitting_score = 0
    
    # 检查1：后期利润大幅下降（>30%）
    if profit_degradation > 0.3:
        overfitting_score += 1
    
    # 检查2：后期胜率大幅下降（<80%）
    if winrate_ratio < 0.8:
        overfitting_score += 1
    
    # 检查3：后期出现亏损
    if late_profit < 0:
        overfitting_score += 2  # 严重问题，加2分
    
    is_overfitted = overfitting_score >= 2
    
    print(f"\n  3️⃣ 过拟合检测:")
    if profit_degradation < 0.30:
        print(f"     利润差异: {profit_degradation*100:.1f}% ✅ （<30%）")
    else:
        print(f"     利润差异: {profit_degradation*100:.1f}% ❌ （>30%）")
    
    if winrate_ratio > 0.80:
        print(f"     胜率比例: {winrate_ratio*100:.1f}% ✅ （>80%）")
    else:
        print(f"     胜率比例: {winrate_ratio*100:.1f}% ❌ （<80%）")
    
    print(f"     过拟合得分: {overfitting_score}/3")
    
    return {
        'profit_degradation': profit_degradation,
        'winrate_ratio': winrate_ratio,
        'overfitting_score': overfitting_score,
        'is_overfitted': is_overfitted
    }


def calculate_stability_score(
    full_test: Dict,
    overfitting: Dict
) -> float:
    """
    稳定性评分（0-100）
    
    Returns:
        stability_score: float
    """
    stability_score = 100.0
    
    # 扣分1：利润差异
    profit_deg = overfitting.get('profit_degradation', 0)
    if profit_deg > 0.1:
        stability_score -= min(50, 20 * profit_deg)  # 最多扣50分
    
    # 扣分2：胜率下降
    winrate_ratio = overfitting.get('winrate_ratio', 1.0)
    if winrate_ratio < 0.9:
        stability_score -= min(30, 30 * (1 - winrate_ratio))  # 最多扣30分
    
    # 扣分3：后期亏损（严重问题）
    late_profit = full_test.get('avg_profit', 0)
    if late_profit < 0:
        stability_score = 0  # 直接归零
    
    stability_score = max(0, stability_score)
    
    print(f"\n  4️⃣ 稳定性评分: {stability_score:.0f}/100", end="")
    if stability_score >= 70:
        print(" ✅")
    elif stability_score >= 50:
        print(" ⚠️")
    else:
        print(" ❌")
    
    return stability_score


def determine_status(
    full_test: Dict,
    overfitting: Dict,
    stability_score: float,
    phase2_baseline_profit: float = 0
) -> str:
    """
    【V8.5.2.4.74】最终判定（优化版）
    
    允许Phase 3利润略低于Phase 2（容忍-10%），只有严重下降才回退
    
    Returns:
        status: 'PASSED', 'WARNING', 'OVERFITTED', 'FAILED', 'UNSTABLE'
    """
    avg_profit = full_test.get('avg_profit', 0)
    is_overfitted = overfitting.get('is_overfitted', False)
    
    # 计算相对Phase 2的利润变化
    if phase2_baseline_profit > 0:
        profit_change = (avg_profit - phase2_baseline_profit) / phase2_baseline_profit
    else:
        profit_change = 0
    
    # 【V8.5.2.4.74】新判定逻辑
    reason = ""
    
    if avg_profit < 0:
        # 绝对亏损
        status = "FAILED"
        reason = f"参数测试出现亏损（{avg_profit:.2f}%）"
    elif phase2_baseline_profit > 0 and profit_change < -0.2:
        # 相对Phase 2下降超过20%
        status = "FAILED"
        reason = f"相对Phase 2下降{abs(profit_change)*100:.1f}%（超过20%阈值）"
    elif is_overfitted:
        status = "OVERFITTED"
        reason = "参数过拟合（前后期差异过大）"
    elif phase2_baseline_profit > 0 and -0.2 <= profit_change < -0.1:
        # 下降10-20%，警告但不回退
        status = "WARNING"
        reason = f"相对Phase 2下降{abs(profit_change)*100:.1f}%（10-20%，可接受）"
    elif stability_score >= 70:
        status = "PASSED"
        if phase2_baseline_profit > 0 and profit_change > 0:
            reason = f"参数泛化能力良好，利润提升{profit_change*100:.1f}%"
        else:
            reason = "参数泛化能力良好"
    elif stability_score >= 50:
        status = "WARNING"
        reason = "稳定性一般，建议监控"
    else:
        status = "UNSTABLE"
        reason = "稳定性不足"
    
    print(f"\n  5️⃣ 最终判定: {status}", end="")
    if status == "PASSED":
        print(" ✅")
    elif status == "WARNING":
        print(" ⚠️")
    else:
        print(" ❌")
    print(f"     原因: {reason}")
    
    return status


def determine_overall_status(
    scalping_validation: Dict,
    swing_validation: Dict
) -> str:
    """
    综合判定
    
    Returns:
        overall_status: str
    """
    scalping_status = scalping_validation.get('status', 'FAILED')
    swing_status = swing_validation.get('status', 'FAILED')
    
    # 优先级：FAILED > OVERFITTED > UNSTABLE > WARNING > PASSED
    status_priority = {
        'FAILED': 5,
        'OVERFITTED': 4,
        'UNSTABLE': 3,
        'WARNING': 2,
        'PASSED': 1,
        'SKIPPED': 0
    }
    
    scalping_priority = status_priority.get(scalping_status, 0)
    swing_priority = status_priority.get(swing_status, 0)
    
    # 取最差的状态
    if scalping_priority >= swing_priority:
        return scalping_status
    else:
        return swing_status

