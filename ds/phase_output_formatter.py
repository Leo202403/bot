#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阶段输出格式化模块

目的：为Phase 1-4提供统一、清晰的输出格式
"""

def print_phase1_summary(scalping_opps, swing_opps, phase1_baseline):
    """
    Phase 1：客观机会识别 - 阶段总结
    
    Args:
        scalping_opps: 超短线机会列表
        swing_opps: 波段机会列表
        phase1_baseline: Phase 1基准数据
    """
    print(f"\n{'='*70}")
    print(f"✅ Phase 1 完成：客观机会识别")
    print(f"{'='*70}")
    
    # 超短线统计
    scalping_count = len(scalping_opps) if scalping_opps else 0
    scalping_profitable = len([o for o in scalping_opps if o.get('objective_profit', 0) > 0]) if scalping_opps else 0
    
    # 从baseline或直接计算平均利润
    if phase1_baseline and phase1_baseline.get('scalping', {}).get('avg_objective_profit', 0) > 0:
        scalping_avg_profit = phase1_baseline['scalping']['avg_objective_profit']
    elif scalping_opps:
        profits = [o.get('objective_profit', 0) for o in scalping_opps if o.get('objective_profit', 0) > 0]
        scalping_avg_profit = sum(profits) / len(profits) if profits else 0
    else:
        scalping_avg_profit = 0
    
    # 计算平均持仓时间（超短线）
    if scalping_opps:
        holding_times = [o.get('holding_hours', 0) for o in scalping_opps if o.get('holding_hours')]
        scalping_avg_holding = sum(holding_times) / len(holding_times) if holding_times else 0
    else:
        scalping_avg_holding = 0
    
    print(f"\n📊 超短线机会:")
    print(f"   - 总数: {scalping_count}个")
    print(f"   - 平均最大利润: {scalping_avg_profit:.2f}%")
    print(f"   - 平均持仓时间: {scalping_avg_holding:.1f}小时")
    print(f"   - 盈利机会: {scalping_profitable}个 ({scalping_profitable/scalping_count*100 if scalping_count > 0 else 0:.1f}%)")
    
    # 波段统计
    swing_count = len(swing_opps) if swing_opps else 0
    swing_profitable = len([o for o in swing_opps if o.get('objective_profit', 0) > 0]) if swing_opps else 0
    
    # 从baseline或直接计算平均利润
    if phase1_baseline and phase1_baseline.get('swing', {}).get('avg_objective_profit', 0) > 0:
        swing_avg_profit = phase1_baseline['swing']['avg_objective_profit']
    elif swing_opps:
        profits = [o.get('objective_profit', 0) for o in swing_opps if o.get('objective_profit', 0) > 0]
        swing_avg_profit = sum(profits) / len(profits) if profits else 0
    else:
        swing_avg_profit = 0
    
    # 计算平均持仓时间（波段）
    if swing_opps:
        holding_times = [o.get('holding_hours', 0) for o in swing_opps if o.get('holding_hours')]
        swing_avg_holding = sum(holding_times) / len(holding_times) if holding_times else 0
    else:
        swing_avg_holding = 0
    
    print(f"\n📊 波段机会:")
    print(f"   - 总数: {swing_count}个")
    print(f"   - 平均最大利润: {swing_avg_profit:.2f}%")
    print(f"   - 平均持仓时间: {swing_avg_holding:.1f}小时")
    print(f"   - 盈利机会: {swing_profitable}个 ({swing_profitable/swing_count*100 if swing_count > 0 else 0:.1f}%)")
    
    # 总计
    total_count = scalping_count + swing_count
    print(f"\n💡 关键发现:")
    print(f"   - 总机会数: {total_count}个")
    print(f"   - 平均最大利润: {(scalping_avg_profit + swing_avg_profit) / 2:.2f}%")
    print(f"   - 超短线/波段比例: {scalping_count}:{swing_count}")
    
    print(f"\n{'='*70}\n")
    
    return {
        'scalping_count': scalping_count,
        'swing_count': swing_count,
        'total_count': total_count,
        'scalping_avg_profit': scalping_avg_profit,
        'swing_avg_profit': swing_avg_profit
    }


def print_phase2_summary(best_params, phase2_baseline, validation_result=None):
    """
    Phase 2：参数优化 - 阶段总结
    
    Args:
        best_params: 最优参数配置
        phase2_baseline: Phase 2基准数据
        validation_result: 前向验证结果（可选）
    """
    print(f"\n{'='*70}")
    print(f"✅ Phase 2 完成：参数优化（捕获最大化）")
    print(f"{'='*70}")
    
    # 最优参数
    print(f"\n🎯 最优参数配置:")
    print(f"   - min_risk_reward: {best_params.get('min_risk_reward', 0)}")
    print(f"   - min_indicator_consensus: {best_params.get('min_indicator_consensus', 0)}")
    print(f"   - atr_stop_multiplier: {best_params.get('atr_stop_multiplier', 0):.2f}")
    print(f"   - atr_tp_multiplier: {best_params.get('atr_tp_multiplier', 0):.2f}")
    print(f"   - max_holding_hours: {best_params.get('max_holding_hours', 0)}")
    print(f"   - min_signal_score: {best_params.get('min_signal_score', 0)}")
    
    # Phase 2 baseline（如果有）
    if phase2_baseline:
        captured_count = phase2_baseline.get('captured_count', 0)
        capture_rate = phase2_baseline.get('capture_rate', 0)
        avg_profit = phase2_baseline.get('avg_profit', 0)
        
        print(f"\n📊 捕获表现:")
        print(f"   - 捕获机会: {captured_count}个")
        print(f"   - 捕获率: {capture_rate*100:.1f}%")
        print(f"   - 平均利润: {avg_profit:.2f}%（已扣除0.14%交易成本）")
    
    # 前向验证（如果有）
    if validation_result:
        train_profit = validation_result.get('train_profit', 0)
        val_profit = validation_result.get('val_profit', 0)
        degradation = validation_result.get('degradation', 0)
        
        print(f"\n🔍 前向验证:")
        print(f"   - 训练集表现: {train_profit:.2f}%")
        print(f"   - 验证集表现: {val_profit:.2f}%")
        print(f"   - 性能衰减: {degradation*100:+.1f}%")
        
        if abs(degradation) < 0.15:
            print(f"   - 判定: ✅ 通过（衰减<15%）")
        elif abs(degradation) < 0.30:
            print(f"   - 判定: ⚠️ 轻微过拟合（衰减15-30%）")
        else:
            print(f"   - 判定: ❌ 严重过拟合（衰减>30%）")
    
    print(f"\n💡 Phase 2 → Phase 3: 将在此基础上进行风险控制优化")
    print(f"{'='*70}\n")


def print_phase3_summary(phase2_params, phase3_params, comparison_data):
    """
    Phase 3：风险控制优化 - 阶段总结
    
    Args:
        phase2_params: Phase 2参数
        phase3_params: Phase 3优化后的参数
        comparison_data: 对比数据
    """
    print(f"\n{'='*70}")
    print(f"✅ Phase 3 完成：风险控制优化")
    print(f"{'='*70}")
    
    # 参数对比
    print(f"\n🎯 优化后参数（vs Phase 2）:")
    for key in ['min_risk_reward', 'min_indicator_consensus', 'atr_stop_multiplier', 'min_signal_score']:
        old_val = phase2_params.get(key, 0)
        new_val = phase3_params.get(key, 0)
        if isinstance(old_val, float):
            change = ((new_val - old_val) / old_val * 100) if old_val != 0 else 0
            print(f"   - {key}: {old_val:.2f} → {new_val:.2f} ({change:+.1f}%)")
        else:
            print(f"   - {key}: {old_val} → {new_val}")
    
    # 超短线对比
    if 'scalping' in comparison_data:
        scalp = comparison_data['scalping']
        print(f"\n⚡ 超短线:")
        print(f"   指标           Phase 2    Phase 3    变化")
        print(f"   ────────────────────────────────────────")
        print(f"   捕获率         {scalp.get('phase2_capture_rate', 0)*100:.1f}%      {scalp.get('phase3_capture_rate', 0)*100:.1f}%      {(scalp.get('phase3_capture_rate', 0)-scalp.get('phase2_capture_rate', 0))*100:+.1f}%")
        print(f"   平均利润       {scalp.get('phase2_profit', 0):.2f}%      {scalp.get('phase3_profit', 0):.2f}%      {(scalp.get('phase3_profit', 0)-scalp.get('phase2_profit', 0)):.2f}%")
        print(f"   胜率           {scalp.get('phase2_winrate', 0)*100:.1f}%      {scalp.get('phase3_winrate', 0)*100:.1f}%      {(scalp.get('phase3_winrate', 0)-scalp.get('phase2_winrate', 0))*100:+.1f}%")
    
    # 波段对比
    if 'swing' in comparison_data:
        swing = comparison_data['swing']
        print(f"\n🌊 波段:")
        print(f"   指标           Phase 2    Phase 3    变化")
        print(f"   ────────────────────────────────────────")
        print(f"   捕获率         {swing.get('phase2_capture_rate', 0)*100:.1f}%      {swing.get('phase3_capture_rate', 0)*100:.1f}%      {(swing.get('phase3_capture_rate', 0)-swing.get('phase2_capture_rate', 0))*100:+.1f}%")
        print(f"   平均利润       {swing.get('phase2_profit', 0):.2f}%      {swing.get('phase3_profit', 0):.2f}%      {(swing.get('phase3_profit', 0)-swing.get('phase2_profit', 0)):.2f}%")
        print(f"   胜率           {swing.get('phase2_winrate', 0)*100:.1f}%      {swing.get('phase3_winrate', 0)*100:.1f}%      {(swing.get('phase3_winrate', 0)-swing.get('phase2_winrate', 0))*100:+.1f}%")
    
    # 决策判断
    print(f"\n💡 Phase 3判定:")
    capture_change = comparison_data.get('capture_rate_change', 0)
    profit_change = comparison_data.get('profit_change', 0)
    
    if capture_change >= -0.10:
        print(f"   - 捕获率下降: {abs(capture_change)*100:.1f}%（✅ <10%，符合约束）")
    else:
        print(f"   - 捕获率下降: {abs(capture_change)*100:.1f}%（⚠️ >10%，牺牲较多机会）")
    
    if profit_change > 0:
        print(f"   - 平均利润提升: {profit_change*100:+.1f}%（✅ 良好）")
    else:
        print(f"   - 平均利润下降: {profit_change*100:+.1f}%（⚠️ 需关注）")
    
    use_phase3 = capture_change >= -0.10 and profit_change >= 0
    if use_phase3:
        print(f"   - 最终决策: ✅ 采用Phase 3参数")
    else:
        print(f"   - 最终决策: ⚠️ 保留Phase 2参数")
    
    print(f"\n💡 Phase 3 → Phase 4: 将进行全量历史数据验证")
    print(f"{'='*70}\n")


def print_phase4_summary(validation_result, final_params):
    """
    Phase 4：参数验证与过拟合检测 - 阶段总结
    
    Args:
        validation_result: 验证结果
        final_params: 最终参数配置
    """
    print(f"\n{'='*70}")
    print(f"✅ Phase 4 完成：参数验证与过拟合检测")
    print(f"{'='*70}")
    
    # 全量数据测试
    full_test = validation_result.get('full_test', {})
    print(f"\n📊 1️⃣ 全量数据测试（14天）:")
    print(f"   - 捕获: {full_test.get('captured_count', 0)}个 ({full_test.get('capture_rate', 0)*100:.1f}%)")
    print(f"   - 平均利润: {full_test.get('avg_profit', 0):.2f}%")
    print(f"   - 胜率: {full_test.get('win_rate', 0)*100:.1f}%")
    
    # 分段测试
    early = validation_result.get('early_period', {})
    late = validation_result.get('late_period', {})
    print(f"\n📊 2️⃣ 分段测试:")
    print(f"   前期（{early.get('sample_count', 0)}个样本）:")
    print(f"   - 捕获: {early.get('captured', 0)}个，利润: {early.get('avg_profit', 0):.2f}%，胜率: {early.get('win_rate', 0)*100:.1f}%")
    print(f"   ")
    print(f"   后期（{late.get('sample_count', 0)}个样本）:")
    print(f"   - 捕获: {late.get('captured', 0)}个，利润: {late.get('avg_profit', 0):.2f}%，胜率: {late.get('win_rate', 0)*100:.1f}%")
    
    # 过拟合检测
    print(f"\n🔍 3️⃣ 过拟合检测:")
    profit_diff = validation_result.get('profit_degradation', 0)
    winrate_ratio = validation_result.get('winrate_ratio', 1.0)
    
    if abs(profit_diff) < 0.30:
        print(f"   - 利润差异: {abs(profit_diff)*100:.1f}% ✅ （<30%）")
    else:
        print(f"   - 利润差异: {abs(profit_diff)*100:.1f}% ❌ （>30%）")
    
    if winrate_ratio > 0.80:
        print(f"   - 胜率比例: {winrate_ratio*100:.1f}% ✅ （>80%）")
    else:
        print(f"   - 胜率比例: {winrate_ratio*100:.1f}% ❌ （<80%）")
    
    status = validation_result.get('status', 'UNKNOWN')
    print(f"   - 判定: {status}")
    
    # 稳定性评分
    stability = validation_result.get('stability', {})
    if stability:
        score = stability.get('score', 0)
        print(f"\n📈 4️⃣ 稳定性评分:")
        print(f"   - 最终稳定性得分: {score:.1f}/100")
    
    # 最终参数
    print(f"\n🎯 最终可用参数:")
    print(f"\n⚡ 超短线参数:")
    scalping_params = final_params.get('scalping', {})
    for key in ['min_risk_reward', 'min_indicator_consensus', 'atr_stop_multiplier', 
                'atr_tp_multiplier', 'max_holding_hours', 'min_signal_score']:
        val = scalping_params.get(key, 0)
        if isinstance(val, float):
            print(f"   {key}: {val:.2f}")
        else:
            print(f"   {key}: {val}")
    
    print(f"\n🌊 波段参数:")
    swing_params = final_params.get('swing', {})
    for key in ['min_risk_reward', 'min_indicator_consensus', 'atr_stop_multiplier', 
                'atr_tp_multiplier', 'max_holding_hours', 'min_signal_score']:
        val = swing_params.get(key, 0)
        if isinstance(val, float):
            print(f"   {key}: {val:.2f}")
        else:
            print(f"   {key}: {val}")
    
    # 最终判定
    print(f"\n🎯 5️⃣ 最终判定:")
    print(f"   - 状态: {status}")
    print(f"   - 建议: {validation_result.get('recommendation', '使用优化后的参数')}")
    print(f"   - 预期表现: 捕获率{full_test.get('capture_rate', 0)*100:.1f}%，利润{full_test.get('avg_profit', 0):.2f}%，胜率{full_test.get('win_rate', 0)*100:.1f}%")
    
    print(f"\n💡 参数优化完成，可应用于实盘交易！")
    print(f"{'='*70}\n")


def generate_phase_summary_html(phase1_data, phase2_data, phase3_data, phase4_data):
    """
    生成分阶段的HTML邮件内容
    
    Returns:
        HTML字符串
    """
    html = """
    <div style="font-family: Arial, sans-serif; max-width: 1000px; margin: 0 auto; background: #f5f5f5; padding: 20px;">
        <h1 style="color: #1976d2; text-align: center; border-bottom: 3px solid #1976d2; padding-bottom: 10px;">
            🤖 AI参数优化报告 - 分阶段详情
        </h1>
    """
    
    # Phase 1
    if phase1_data:
        html += f"""
        <div style="background: #fff; padding: 20px; margin: 20px 0; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
            <h2 style="color: #4caf50; margin-top: 0;">📊 Phase 1: 客观机会识别</h2>
            <table style="width: 100%; border-collapse: collapse;">
                <tr style="background: #e8f5e9;">
                    <th style="padding: 10px; border: 1px solid #ddd; text-align: left;">指标</th>
                    <th style="padding: 10px; border: 1px solid #ddd; text-align: center;">超短线</th>
                    <th style="padding: 10px; border: 1px solid #ddd; text-align: center;">波段</th>
                </tr>
                <tr>
                    <td style="padding: 10px; border: 1px solid #ddd;">总机会数</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: center;">{phase1_data.get('scalping_count', 0)}个</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: center;">{phase1_data.get('swing_count', 0)}个</td>
                </tr>
                <tr>
                    <td style="padding: 10px; border: 1px solid #ddd;">平均最大利润</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: center;">{phase1_data.get('scalping_avg_profit', 0):.2f}%</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: center;">{phase1_data.get('swing_avg_profit', 0):.2f}%</td>
                </tr>
            </table>
            <p style="margin-top: 15px; padding: 10px; background: #fff3e0; border-left: 4px solid #ff9800;">
                <strong>💡 关键发现：</strong>识别到{phase1_data.get('total_count', 0)}个客观机会，为后续优化提供基准。
            </p>
        </div>
        """
    
    # Phase 2
    if phase2_data:
        html += f"""
        <div style="background: #fff; padding: 20px; margin: 20px 0; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
            <h2 style="color: #2196f3; margin-top: 0;">🎯 Phase 2: 参数优化（捕获最大化）</h2>
            <h3>最优参数配置</h3>
            <table style="width: 100%; border-collapse: collapse; margin-bottom: 15px;">
                <tr style="background: #bbdefb;">
                    <th style="padding: 8px; border: 1px solid #ddd; text-align: left;">参数</th>
                    <th style="padding: 8px; border: 1px solid #ddd; text-align: center;">值</th>
                </tr>
                <tr>
                    <td style="padding: 8px; border: 1px solid #ddd;">min_risk_reward</td>
                    <td style="padding: 8px; border: 1px solid #ddd; text-align: center;">{phase2_data.get('min_risk_reward', 0)}</td>
                </tr>
                <tr>
                    <td style="padding: 8px; border: 1px solid #ddd;">min_indicator_consensus</td>
                    <td style="padding: 8px; border: 1px solid #ddd; text-align: center;">{phase2_data.get('min_indicator_consensus', 0)}</td>
                </tr>
                <tr>
                    <td style="padding: 8px; border: 1px solid #ddd;">atr_stop_multiplier</td>
                    <td style="padding: 8px; border: 1px solid #ddd; text-align: center;">{phase2_data.get('atr_stop_multiplier', 0):.2f}</td>
                </tr>
                <tr>
                    <td style="padding: 8px; border: 1px solid #ddd;">min_signal_score</td>
                    <td style="padding: 8px; border: 1px solid #ddd; text-align: center;">{phase2_data.get('min_signal_score', 0)}</td>
                </tr>
            </table>
            <h3>捕获表现</h3>
            <table style="width: 100%; border-collapse: collapse;">
                <tr style="background: #e3f2fd;">
                    <th style="padding: 8px; border: 1px solid #ddd; text-align: left;">指标</th>
                    <th style="padding: 8px; border: 1px solid #ddd; text-align: center;">值</th>
                </tr>
                <tr>
                    <td style="padding: 8px; border: 1px solid #ddd;">捕获机会数</td>
                    <td style="padding: 8px; border: 1px solid #ddd; text-align: center;">{phase2_data.get('captured_count', 0)}个</td>
                </tr>
                <tr>
                    <td style="padding: 8px; border: 1px solid #ddd;">捕获率</td>
                    <td style="padding: 8px; border: 1px solid #ddd; text-align: center;">{phase2_data.get('capture_rate', 0)*100:.1f}%</td>
                </tr>
                <tr>
                    <td style="padding: 8px; border: 1px solid #ddd;">平均利润</td>
                    <td style="padding: 8px; border: 1px solid #ddd; text-align: center;">{phase2_data.get('avg_profit', 0):.2f}%</td>
                </tr>
            </table>
            <p style="margin-top: 15px; padding: 10px; background: #e8f5e9; border-left: 4px solid #4caf50;">
                <strong>✅ Phase 2完成：</strong>找到最优参数，捕获率{phase2_data.get('capture_rate', 0)*100:.1f}%
            </p>
        </div>
        """
    
    # Phase 3
    if phase3_data:
        html += f"""
        <div style="background: #fff; padding: 20px; margin: 20px 0; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
            <h2 style="color: #ff9800; margin-top: 0;">🛡️ Phase 3: 风险控制优化</h2>
            <table style="width: 100%; border-collapse: collapse;">
                <tr style="background: #fff3e0;">
                    <th style="padding: 10px; border: 1px solid #ddd; text-align: left;">指标</th>
                    <th style="padding: 10px; border: 1px solid #ddd; text-align: center;">Phase 2</th>
                    <th style="padding: 10px; border: 1px solid #ddd; text-align: center;">Phase 3</th>
                    <th style="padding: 10px; border: 1px solid #ddd; text-align: center;">变化</th>
                </tr>
                <tr>
                    <td style="padding: 10px; border: 1px solid #ddd;">捕获率</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: center;">{phase3_data.get('phase2_capture_rate', 0)*100:.1f}%</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: center;">{phase3_data.get('phase3_capture_rate', 0)*100:.1f}%</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: center;">{(phase3_data.get('phase3_capture_rate', 0) - phase3_data.get('phase2_capture_rate', 0))*100:+.1f}%</td>
                </tr>
                <tr>
                    <td style="padding: 10px; border: 1px solid #ddd;">平均利润</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: center;">{phase3_data.get('phase2_profit', 0):.2f}%</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: center;">{phase3_data.get('phase3_profit', 0):.2f}%</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: center;">{(phase3_data.get('phase3_profit', 0) - phase3_data.get('phase2_profit', 0)):+.2f}%</td>
                </tr>
                <tr>
                    <td style="padding: 10px; border: 1px solid #ddd;">胜率</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: center;">{phase3_data.get('phase2_winrate', 0)*100:.1f}%</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: center;">{phase3_data.get('phase3_winrate', 0)*100:.1f}%</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: center;">{(phase3_data.get('phase3_winrate', 0) - phase3_data.get('phase2_winrate', 0))*100:+.1f}%</td>
                </tr>
            </table>
            <p style="margin-top: 15px; padding: 10px; background: #fff3e0; border-left: 4px solid #ff9800;">
                <strong>💡 Phase 3判定：</strong>{phase3_data.get('decision', '采用Phase 3参数')}
            </p>
        </div>
        """
    
    # Phase 4
    if phase4_data:
        status_color = '#4caf50' if phase4_data.get('status') == 'PASSED' else '#ff9800'
        html += f"""
        <div style="background: #fff; padding: 20px; margin: 20px 0; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
            <h2 style="color: #9c27b0; margin-top: 0;">🔍 Phase 4: 参数验证与过拟合检测</h2>
            <h3>全量数据测试</h3>
            <table style="width: 100%; border-collapse: collapse; margin-bottom: 15px;">
                <tr style="background: #f3e5f5;">
                    <th style="padding: 8px; border: 1px solid #ddd; text-align: left;">指标</th>
                    <th style="padding: 8px; border: 1px solid #ddd; text-align: center;">值</th>
                </tr>
                <tr>
                    <td style="padding: 8px; border: 1px solid #ddd;">捕获数</td>
                    <td style="padding: 8px; border: 1px solid #ddd; text-align: center;">{phase4_data.get('captured_count', 0)}个</td>
                </tr>
                <tr>
                    <td style="padding: 8px; border: 1px solid #ddd;">平均利润</td>
                    <td style="padding: 8px; border: 1px solid #ddd; text-align: center;">{phase4_data.get('avg_profit', 0):.2f}%</td>
                </tr>
                <tr>
                    <td style="padding: 8px; border: 1px solid #ddd;">胜率</td>
                    <td style="padding: 8px; border: 1px solid #ddd; text-align: center;">{phase4_data.get('win_rate', 0)*100:.1f}%</td>
                </tr>
                <tr>
                    <td style="padding: 8px; border: 1px solid #ddd;">稳定性得分</td>
                    <td style="padding: 8px; border: 1px solid #ddd; text-align: center;">{phase4_data.get('stability_score', 0):.1f}/100</td>
                </tr>
            </table>
            <div style="padding: 15px; background: {status_color}; color: white; text-align: center; border-radius: 5px; font-size: 1.2em;">
                <strong>最终判定：{phase4_data.get('status', 'UNKNOWN')}</strong>
            </div>
            <p style="margin-top: 15px; padding: 10px; background: #e8f5e9; border-left: 4px solid #4caf50;">
                <strong>🎯 建议：</strong>{phase4_data.get('recommendation', '使用优化后的参数')}
            </p>
        </div>
        """
    
    html += """
    </div>
    """
    
    return html


if __name__ == "__main__":
    # 测试输出格式
    print("阶段输出格式化模块加载完成")

