"""
【V8.5.2.4.81】邮件和Bark格式化辅助函数
用于生成优化后的邮件HTML和Bark内容
"""
from typing import Dict, Any, Optional


def generate_phase_summary_table(phase_data: Dict[str, Any]) -> str:
    """
    生成Phase 1-4汇总表HTML
    
    Args:
        phase_data: {
            'phase1': {
                'scalping_count': int,
                'scalping_profit': float,  # 百分比
                'swing_count': int,
                'swing_profit': float
            },
            'phase2': {
                'scalping_capture': float,  # 百分比
                'scalping_profit': float,
                'swing_capture': float,
                'swing_profit': float,
                'scalping_count': int,
                'swing_count': int
            },
            'phase3': {
                'scalping_capture': float,
                'scalping_profit': float,
                'swing_capture': float,
                'swing_profit': float,
                'scalping_count': int,
                'swing_count': int
            },
            'phase4': {
                'scalping_capture': float,
                'scalping_profit': float,
                'swing_capture': float,
                'swing_profit': float,
                'scalping_count': int,
                'swing_count': int
            }
        }
    
    Returns:
        str: HTML表格
    """
    p1 = phase_data.get('phase1', {})
    p2 = phase_data.get('phase2', {})
    p3 = phase_data.get('phase3', {})
    p4 = phase_data.get('phase4', {})
    
    # Phase 1捕获率固定为100%（客观机会）
    p1_scalping_capture = 100.0
    p1_swing_capture = 100.0
    
    html = f"""
<div class="summary-box" style="background: #f8f9fa; border: 2px solid #6c757d; margin: 20px 0; padding: 20px; border-radius: 8px;">
    <h2 style="color: #2c3e50; margin-top: 0;">📊 各阶段情况汇总</h2>
    <table style="width: 100%; border-collapse: collapse; margin: 15px 0; font-size: 14px;">
        <thead>
            <tr style="background: #343a40; color: white;">
                <th style="padding: 12px; border: 1px solid #dee2e6; text-align: left;">指标</th>
                <th style="padding: 12px; border: 1px solid #dee2e6; text-align: center;">Phase 1<br><small style="font-weight: normal;">客观机会</small></th>
                <th style="padding: 12px; border: 1px solid #dee2e6; text-align: center;">Phase 2<br><small style="font-weight: normal;">参数探索</small></th>
                <th style="padding: 12px; border: 1px solid #dee2e6; text-align: center;">Phase 3<br><small style="font-weight: normal;">分离优化</small></th>
                <th style="padding: 12px; border: 1px solid #dee2e6; text-align: center;">Phase 4<br><small style="font-weight: normal;">最终验证</small></th>
            </tr>
        </thead>
        <tbody>
            <!-- 超短线捕获率 -->
            <tr>
                <td style="padding: 10px; border: 1px solid #dee2e6; font-weight: bold;">⚡ 超短线捕获率</td>
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: center;">
                    {p1_scalping_capture:.1f}%<br>
                    <small style="color: #6c757d;">({p1.get('scalping_count', 0)}个)</small>
                </td>
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: center;">
                    {p2.get('scalping_capture', 0):.1f}%<br>
                    <small style="color: #6c757d;">({p2.get('scalping_count', 0)}个)</small>
                </td>
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: center;">
                    {p3.get('scalping_capture', 0):.1f}%<br>
                    <small style="color: #6c757d;">({p3.get('scalping_count', 0)}个)</small>
                </td>
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: center; background: #d4edda;">
                    <strong style="font-size: 1.1em;">{p4.get('scalping_capture', 0):.1f}%</strong><br>
                    <small style="color: #6c757d;">({p4.get('scalping_count', 0)}个)</small>
                </td>
            </tr>
            
            <!-- 超短线利润率 -->
            <tr>
                <td style="padding: 10px; border: 1px solid #dee2e6; font-weight: bold;">⚡ 超短线利润率</td>
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: center;">
                    {p1.get('scalping_profit', 0):.2f}%
                </td>
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: center;">
                    {p2.get('scalping_profit', 0):.2f}%
                </td>
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: center;">
                    {p3.get('scalping_profit', 0):.2f}%
                </td>
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: center; background: #d4edda;">
                    <strong style="font-size: 1.1em;">{p4.get('scalping_profit', 0):.2f}%</strong>
                </td>
            </tr>
            
            <!-- 波段捕获率 -->
            <tr>
                <td style="padding: 10px; border: 1px solid #dee2e6; font-weight: bold;">🌊 波段捕获率</td>
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: center;">
                    {p1_swing_capture:.1f}%<br>
                    <small style="color: #6c757d;">({p1.get('swing_count', 0)}个)</small>
                </td>
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: center;">
                    {p2.get('swing_capture', 0):.1f}%<br>
                    <small style="color: #6c757d;">({p2.get('swing_count', 0)}个)</small>
                </td>
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: center;">
                    {p3.get('swing_capture', 0):.1f}%<br>
                    <small style="color: #6c757d;">({p3.get('swing_count', 0)}个)</small>
                </td>
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: center; background: #d4edda;">
                    <strong style="font-size: 1.1em;">{p4.get('swing_capture', 0):.1f}%</strong><br>
                    <small style="color: #6c757d;">({p4.get('swing_count', 0)}个)</small>
                </td>
            </tr>
            
            <!-- 波段利润率 -->
            <tr>
                <td style="padding: 10px; border: 1px solid #dee2e6; font-weight: bold;">🌊 波段利润率</td>
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: center;">
                    {p1.get('swing_profit', 0):.2f}%
                </td>
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: center;">
                    {p2.get('swing_profit', 0):.2f}%
                </td>
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: center;">
                    {p3.get('swing_profit', 0):.2f}%
                </td>
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: center; background: #d4edda;">
                    <strong style="font-size: 1.1em;">{p4.get('swing_profit', 0):.2f}%</strong>
                </td>
            </tr>
        </tbody>
    </table>
    
    <p style="margin-top: 15px; color: #6c757d; font-size: 0.9em; line-height: 1.5;">
        💡 <strong>说明</strong>：Phase 1为客观机会（理论最大潜力），Phase 2-4逐步优化参数，Phase 4为最终应用参数
    </p>
</div>
"""
    return html


def generate_params_comparison_table(
    scalping_params: Optional[Dict[str, Any]],
    swing_params: Optional[Dict[str, Any]],
    learned_features: Optional[Dict[str, Any]] = None
) -> str:
    """
    【V8.5.2.4.89.6】生成超短线/波段参数对比表HTML（包含密度信息+处理None）
    
    Args:
        scalping_params: dict, 超短线参数（可能为None）
        swing_params: dict, 波段参数
        learned_features: dict, Phase 2学习成果（包含密度信息）
    
    Returns:
        str: HTML表格
    """
    # 【V8.5.2.4.89.6】处理None情况
    if scalping_params is None:
        scalping_params = {}
    if swing_params is None:
        swing_params = {}
    
    # 安全获取参数值
    def safe_get(params: Optional[Dict[str, Any]], key: str, default: str = 'N/A') -> str:
        if not params:  # 如果params为空字典
            return default
        value = params.get(key, default)
        if isinstance(value, float):
            return f"{value:.1f}"
        return str(value)
    
    # 移动止损图标
    scalping_trailing = "✅" if scalping_params and scalping_params.get('trailing_stop_enabled') else "❌"
    swing_trailing = "✅" if swing_params and swing_params.get('trailing_stop_enabled') else "❌"
    
    # 【V8.5.2.4.89.64】从learned_features提取密度信息（修复显示错误）
    if learned_features is None:
        learned_features = {}
    
    # 【DEBUG】输出learned_features内容用于调试
    print(f"  📊 【DEBUG】learned_features: {learned_features}")
    
    # 直接获取原始数值进行判断，而不是使用safe_get转换后的字符串
    scalping_density_val = learned_features.get('scalping_avg_density')
    swing_density_val = learned_features.get('swing_avg_density')
    high_density_threshold = safe_get(learned_features, 'high_density_threshold', 'N/A')
    
    # 【修复】格式化逻辑
    if isinstance(scalping_density_val, (int, float)):
        if scalping_density_val < 2:
            scalping_density = f"⚠️ {scalping_density_val:.2f} (异常低，请检查Phase 1统计)"
        else:
            scalping_density = f"{scalping_density_val:.2f}"
    else:
        scalping_density = str(scalping_density_val) if scalping_density_val is not None else 'N/A'
    
    if isinstance(swing_density_val, (int, float)):
        if swing_density_val < 0.5:
            swing_density = f"⚠️ {swing_density_val:.2f} (异常低，请检查Phase 1统计)"
        else:
            swing_density = f"{swing_density_val:.2f}"
    else:
        swing_density = str(swing_density_val) if swing_density_val is not None else 'N/A'
    
    html = f"""
<div class="summary-box" style="background: #fff3e0; border: 2px solid #ff9800; margin: 20px 0; padding: 20px; border-radius: 8px;">
    <h2 style="color: #e65100; margin-top: 0;">⚡🌊 超短线/波段 参数配置</h2>
    
    <table style="width: 100%; border-collapse: collapse; margin: 15px 0; font-size: 14px;">
        <thead>
            <tr style="background: #ff9800; color: white;">
                <th style="padding: 12px; border: 1px solid #dee2e6; text-align: left;">参数</th>
                <th style="padding: 12px; border: 1px solid #dee2e6; text-align: center;">⚡ 超短线</th>
                <th style="padding: 12px; border: 1px solid #dee2e6; text-align: center;">🌊 波段</th>
            </tr>
        </thead>
        <tbody>
            <tr style="background: #e3f2fd;">
                <td style="padding: 10px; border: 1px solid #dee2e6; font-weight: bold;">📊 平均利润密度</td>
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: center; font-size: 1.1em; color: #1976d2; font-weight: bold;">
                    {scalping_density}
                </td>
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: center; font-size: 1.1em; color: #1976d2; font-weight: bold;">
                    {swing_density}
                </td>
            </tr>
            <tr>
                <td style="padding: 10px; border: 1px solid #dee2e6; font-weight: bold;">最小盈亏比</td>
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: center; font-size: 1.1em;">
                    {safe_get(scalping_params, 'min_risk_reward', 'N/A')}
                </td>
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: center; font-size: 1.1em;">
                    {safe_get(swing_params, 'min_risk_reward', 'N/A')}
                </td>
            </tr>
            <tr>
                <td style="padding: 10px; border: 1px solid #dee2e6; font-weight: bold;">最低信号分数</td>
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: center; font-size: 1.1em;">
                    {safe_get(scalping_params, 'min_signal_score', 'N/A')}
                </td>
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: center; font-size: 1.1em;">
                    {safe_get(swing_params, 'min_signal_score', 'N/A')}
                </td>
            </tr>
            <tr>
                <td style="padding: 10px; border: 1px solid #dee2e6; font-weight: bold;">最长持仓(小时)</td>
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: center; font-size: 1.1em;">
                    {safe_get(scalping_params, 'max_holding_hours', 'N/A')}h
                </td>
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: center; font-size: 1.1em;">
                    {safe_get(swing_params, 'max_holding_hours', 'N/A')}h
                </td>
            </tr>
            <tr>
                <td style="padding: 10px; border: 1px solid #dee2e6; font-weight: bold;">止盈ATR倍数</td>
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: center; font-size: 1.1em; color: #28a745; font-weight: bold;">
                    {safe_get(scalping_params, 'atr_tp_multiplier', 'N/A')}x
                </td>
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: center; font-size: 1.1em; color: #28a745; font-weight: bold;">
                    {safe_get(swing_params, 'atr_tp_multiplier', 'N/A')}x
                </td>
            </tr>
            <tr>
                <td style="padding: 10px; border: 1px solid #dee2e6; font-weight: bold;">止损ATR倍数</td>
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: center; font-size: 1.1em; color: #dc3545; font-weight: bold;">
                    {safe_get(scalping_params, 'atr_stop_multiplier', 'N/A')}x
                </td>
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: center; font-size: 1.1em; color: #dc3545; font-weight: bold;">
                    {safe_get(swing_params, 'atr_stop_multiplier', 'N/A')}x
                </td>
            </tr>
            <tr>
                <td style="padding: 10px; border: 1px solid #dee2e6; font-weight: bold;">最小共振指标数</td>
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: center; font-size: 1.1em;">
                    {safe_get(scalping_params, 'min_indicator_consensus', 'N/A')}
                </td>
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: center; font-size: 1.1em;">
                    {safe_get(swing_params, 'min_indicator_consensus', 'N/A')}
                </td>
            </tr>
            <tr>
                <td style="padding: 10px; border: 1px solid #dee2e6; font-weight: bold;">移动止损</td>
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: center; font-size: 1.3em;">
                    {scalping_trailing}
                </td>
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: center; font-size: 1.3em;">
                    {swing_trailing}
                </td>
            </tr>
        </tbody>
    </table>
    
    <div style="margin-top: 15px; padding: 12px; background: #e3f2fd; border-left: 4px solid #1976d2; border-radius: 4px;">
        <p style="margin: 0; font-size: 13px; color: #0d47a1;">
            <strong>🎯 分类规则：</strong>密度 &gt; {high_density_threshold} → 超短线 | 密度 ≤ {high_density_threshold} → 波段
        </p>
    </div>
</div>
"""
    return html


def generate_profit_comparison_table(phase_data: Dict[str, Any]) -> str:
    """
    生成总利润对比分析表HTML
    
    Args:
        phase_data: 同generate_phase_summary_table的参数
    
    Returns:
        str: HTML表格
    """
    p1 = phase_data.get('phase1', {})
    p2 = phase_data.get('phase2', {})
    p3 = phase_data.get('phase3', {})
    p4 = phase_data.get('phase4', {})
    
    # 计算总利润（假设每个机会的平均利润 * 捕获数量）
    # 注意：这里需要实际的总利润数据，如果没有，用占位符
    p1_scalping_total = p1.get('scalping_total_profit', 0)
    p1_swing_total = p1.get('swing_total_profit', 0)
    p1_total = p1_scalping_total + p1_swing_total
    
    p2_scalping_total = p2.get('scalping_total_profit', 0)
    p2_swing_total = p2.get('swing_total_profit', 0)
    p2_total = p2_scalping_total + p2_swing_total
    
    p3_scalping_total = p3.get('scalping_total_profit', 0)
    p3_swing_total = p3.get('swing_total_profit', 0)
    p3_total = p3_scalping_total + p3_swing_total
    
    p4_scalping_total = p4.get('scalping_total_profit', 0)
    p4_swing_total = p4.get('swing_total_profit', 0)
    p4_total = p4_scalping_total + p4_swing_total
    
    # 计算提升
    if p2_total > 0:
        improvement_amount = p4_total - p2_total
        improvement_pct = (improvement_amount / p2_total) * 100
    else:
        improvement_amount = p4_total
        improvement_pct = 0
    
    improvement_icon = "📈" if improvement_amount > 0 else "📉" if improvement_amount < 0 else "➡️"
    improvement_color = "#28a745" if improvement_amount > 0 else "#dc3545" if improvement_amount < 0 else "#6c757d"
    
    # 【V8.5.2.4.89.65】计算分类提升（去掉合计列，只显示分类利润）
    scalping_improvement = p4_scalping_total - p2_scalping_total
    scalping_improvement_pct = (scalping_improvement / p2_scalping_total * 100) if p2_scalping_total > 0 else 0
    swing_improvement = p4_swing_total - p2_swing_total
    swing_improvement_pct = (swing_improvement / p2_swing_total * 100) if p2_swing_total > 0 else 0
    
    scalping_icon = "📈" if scalping_improvement > 0 else "📉" if scalping_improvement < 0 else "➡️"
    scalping_color = "#28a745" if scalping_improvement > 0 else "#dc3545" if scalping_improvement < 0 else "#6c757d"
    swing_icon = "📈" if swing_improvement > 0 else "📉" if swing_improvement < 0 else "➡️"
    swing_color = "#28a745" if swing_improvement > 0 else "#dc3545" if swing_improvement < 0 else "#6c757d"
    
    html = f"""
<div class="summary-box" style="background: #e8f5e9; border: 2px solid #4caf50; margin: 20px 0; padding: 20px; border-radius: 8px;">
    <h2 style="color: #1b5e20; margin-top: 0;">💰 分类累计收益率对比分析</h2>
    
    <table style="width: 100%; border-collapse: collapse; margin: 15px 0; font-size: 14px;">
        <thead>
            <tr style="background: #4caf50; color: white;">
                <th style="padding: 12px; border: 1px solid #dee2e6; text-align: left;">阶段</th>
                <th style="padding: 12px; border: 1px solid #dee2e6; text-align: right;">⚡ 超短线累计收益率</th>
                <th style="padding: 12px; border: 1px solid #dee2e6; text-align: right;">🌊 波段累计收益率</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td style="padding: 10px; border: 1px solid #dee2e6;">Phase 1 (客观)</td>
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: right; font-family: monospace;">
                    +{p1_scalping_total:.2f}%
                </td>
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: right; font-family: monospace;">
                    +{p1_swing_total:.2f}%
                </td>
            </tr>
            <tr>
                <td style="padding: 10px; border: 1px solid #dee2e6;">Phase 2 (探索)</td>
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: right; font-family: monospace;">
                    +{p2_scalping_total:.2f}%
                </td>
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: right; font-family: monospace;">
                    +{p2_swing_total:.2f}%
                </td>
            </tr>
            <tr>
                <td style="padding: 10px; border: 1px solid #dee2e6;">Phase 3 (优化)</td>
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: right; font-family: monospace;">
                    +{p3_scalping_total:.2f}%
                </td>
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: right; font-family: monospace;">
                    +{p3_swing_total:.2f}%
                </td>
            </tr>
            <tr style="background: #d4edda;">
                <td style="padding: 10px; border: 1px solid #dee2e6; font-weight: bold;">Phase 4 (最终)</td>
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: right; font-weight: bold; font-family: monospace;">
                    +{p4_scalping_total:.2f}%
                </td>
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: right; font-weight: bold; font-family: monospace;">
                    +{p4_swing_total:.2f}%
                </td>
            </tr>
        </tbody>
    </table>
    
    <div style="margin-top: 15px; padding: 15px; background: white; border-radius: 5px;">
        <p style="margin: 5px 0; font-size: 1.05em;">
            {scalping_icon} <strong>⚡ 超短线 Phase 2 → Phase 4提升</strong>: 
            <span style="color: {scalping_color}; font-weight: bold; font-size: 1.1em;">
                {scalping_improvement:+.2f}% ({scalping_improvement_pct:+.1f}%)
            </span>
        </p>
        <p style="margin: 5px 0; font-size: 1.05em;">
            {swing_icon} <strong>🌊 波段 Phase 2 → Phase 4提升</strong>: 
            <span style="color: {swing_color}; font-weight: bold; font-size: 1.1em;">
                {swing_improvement:+.2f}% ({swing_improvement_pct:+.1f}%)
            </span>
        </p>
        <p style="margin: 10px 0 5px 0; color: #6c757d; font-size: 0.9em;">
            💡 累计收益率 = 捕获机会数 × 平均单笔收益率（理论值）
        </p>
        <p style="margin: 5px 0; color: #6c757d; font-size: 0.9em;">
            💡 Phase 1为理论最大值，Phase 4为实际可捕获利润
        </p>
    </div>
</div>
"""
    return html


def generate_signal_weights_comparison_table(
    scalping_weights: Optional[Dict[str, Any]],
    swing_weights: Optional[Dict[str, Any]],
    old_scalping_weights: Optional[Dict[str, Any]] = None,
    old_swing_weights: Optional[Dict[str, Any]] = None
) -> str:
    """
    生成信号分权重对比表HTML
    
    Args:
        scalping_weights: dict, 超短线最优权重 {'name': str, 'weights': {...}}
        swing_weights: dict, 波段最优权重
        old_scalping_weights: dict, 旧超短线权重（可选，用于对比）
        old_swing_weights: dict, 旧波段权重（可选）
    
    Returns:
        str: HTML表格
    """
    # 处理None
    if scalping_weights is None:
        scalping_weights = {}
    if swing_weights is None:
        swing_weights = {}
    
    # 【V8.5.2.4.89.58】兼容两种权重结构：
    # 1. {'weights': {...}, 'name': '...'} (旧格式)
    # 2. {'momentum': 20, ..., 'name': '...'} (新格式，直接包含权重)
    def extract_weights(weight_dict):
        """提取权重，兼容新旧两种格式"""
        if not weight_dict:
            return {}
        # 如果有'weights'键，使用它（旧格式）
        if 'weights' in weight_dict:
            return weight_dict['weights']
        # 否则，直接使用字典本身（新格式），但排除'name'键
        return {k: v for k, v in weight_dict.items() if k != 'name'}
    
    # 提取权重字典
    scalp_w = extract_weights(scalping_weights)
    swing_w = extract_weights(swing_weights)
    
    # 旧权重（用于显示变化）
    old_scalp_w = extract_weights(old_scalping_weights)
    old_swing_w = extract_weights(old_swing_weights)
    
    # 【V8.5.2.4.89.61】定义权重项（超短线 - 新增3个专属维度）
    scalping_items = [
        ('momentum', '动量评分', scalp_w.get('momentum', 0)),
        ('volume', '成交量评分', scalp_w.get('volume', 0)),
        ('breakout', '突破评分', scalp_w.get('breakout', 0)),
        ('pattern', '形态评分', scalp_w.get('pattern', 0)),
        ('trend_align', '趋势对齐', scalp_w.get('trend_align', 0)),
        ('volatility', '短期波动率', scalp_w.get('volatility', 0)),
        ('volume_pulse', '成交量脉冲', scalp_w.get('volume_pulse', 0)),
        ('momentum_accel', '动量加速', scalp_w.get('momentum_accel', 0))
    ]
    
    # 定义权重项（波段）
    swing_items = [
        ('momentum', '动量评分', swing_w.get('momentum', 0)),
        ('volume', '成交量评分', swing_w.get('volume', 0)),
        ('breakout', '突破评分', swing_w.get('breakout', 0)),
        ('trend_align', '趋势对齐', swing_w.get('trend_align', 0)),
        ('ema_divergence', 'EMA发散', swing_w.get('ema_divergence', 0)),
        ('trend_4h_strength', '4h趋势强度', swing_w.get('trend_4h_strength', 0))
    ]
    
    # 生成超短线权重行
    scalping_rows = ""
    for key, label, value in scalping_items:
        old_value = old_scalp_w.get(key, 0)
        change = value - old_value if old_value > 0 else 0
        change_html = ""
        if change != 0 and old_value > 0:
            change_color = "#28a745" if change > 0 else "#dc3545"
            change_html = f'<br><small style="color: {change_color};">({change:+.0f})</small>'
        
        scalping_rows += f"""
            <tr>
                <td style="padding: 10px; border: 1px solid #dee2e6;">{label}</td>
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: center; font-size: 1.1em; font-weight: bold;">
                    {value:.0f}{change_html}
                </td>
            </tr>"""
    
    # 生成波段权重行
    swing_rows = ""
    for key, label, value in swing_items:
        old_value = old_swing_w.get(key, 0)
        change = value - old_value if old_value > 0 else 0
        change_html = ""
        if change != 0 and old_value > 0:
            change_color = "#28a745" if change > 0 else "#dc3545"
            change_html = f'<br><small style="color: {change_color};">({change:+.0f})</small>'
        
        swing_rows += f"""
            <tr>
                <td style="padding: 10px; border: 1px solid #dee2e6;">{label}</td>
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: center; font-size: 1.1em; font-weight: bold;">
                    {value:.0f}{change_html}
                </td>
            </tr>"""
    
    # 获取权重名称
    scalp_name = scalping_weights.get('name', 'N/A')
    swing_name = swing_weights.get('name', 'N/A')
    
    html = f"""
<div class="summary-box" style="background: #e3f2fd; border: 2px solid #1976d2; margin: 20px 0; padding: 20px; border-radius: 8px;">
    <h2 style="color: #0d47a1; margin-top: 0;">🎯 信号分权重配置</h2>
    
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin: 15px 0;">
        <!-- 超短线权重 -->
        <div>
            <h3 style="color: #ff6f00; margin: 0 0 10px 0;">⚡ 超短线权重</h3>
            <div style="background: #fff3e0; padding: 8px; border-radius: 4px; margin-bottom: 10px;">
                <strong>权重组合：</strong>{scalp_name}
            </div>
            <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                <thead>
                    <tr style="background: #ff9800; color: white;">
                        <th style="padding: 8px; border: 1px solid #dee2e6; text-align: left;">维度</th>
                        <th style="padding: 8px; border: 1px solid #dee2e6; text-align: center;">权重</th>
                    </tr>
                </thead>
                <tbody>
                    {scalping_rows}
                </tbody>
            </table>
        </div>
        
        <!-- 波段权重 -->
        <div>
            <h3 style="color: #0288d1; margin: 0 0 10px 0;">🌊 波段权重</h3>
            <div style="background: #e1f5fe; padding: 8px; border-radius: 4px; margin-bottom: 10px;">
                <strong>权重组合：</strong>{swing_name}
            </div>
            <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                <thead>
                    <tr style="background: #0288d1; color: white;">
                        <th style="padding: 8px; border: 1px solid #dee2e6; text-align: left;">维度</th>
                        <th style="padding: 8px; border: 1px solid #dee2e6; text-align: center;">权重</th>
                    </tr>
                </thead>
                <tbody>
                    {swing_rows}
                </tbody>
            </table>
        </div>
    </div>
    
    <div style="margin-top: 15px; padding: 12px; background: white; border-left: 4px solid #1976d2; border-radius: 4px;">
        <p style="margin: 0; font-size: 13px; color: #0d47a1;">
            <strong>💡 说明：</strong>权重值越高表示该维度在信号评分中的影响越大。绿色(+)表示相比旧值增加，红色(-)表示减少。
        </p>
    </div>
</div>
"""
    return html


def generate_optimized_bark_content(
    yesterday_data: Dict[str, Any],
    phase2_data: Dict[str, Any],
    phase4_data: Dict[str, Any]
) -> str:
    """
    【V8.5.2.4.89.27】生成优化后的Bark推送内容（多行清晰版）
    
    Args:
        yesterday_data: {
            'winrate': float,  # 0-1
            'profit': float    # U
        }
        phase2_data: {
            'scalping_capture': float,  # 百分比
            'scalping_profit': float,
            'swing_capture': float,
            'swing_profit': float
        }
        phase4_data: {
            'scalping_capture': float,
            'scalping_profit': float,
            'swing_capture': float,
            'swing_profit': float
        }
    
    Returns:
        str: Bark内容（多行格式）
    """
    # 确保所有参数都是字典类型
    if not isinstance(yesterday_data, dict):
        yesterday_data = {}
    if not isinstance(phase2_data, dict):
        phase2_data = {}
    if not isinstance(phase4_data, dict):
        phase4_data = {}
    
    yesterday_data = yesterday_data or {}
    phase2_data = phase2_data or {}
    phase4_data = phase4_data or {}
    
    # 提取数据
    yesterday_winrate = yesterday_data.get('winrate', 0) * 100
    yesterday_profit = yesterday_data.get('profit', 0)
    
    # Phase 4数据
    p4_scalping_cap = phase4_data.get('scalping_capture', 0)
    p4_scalping_prof = phase4_data.get('scalping_profit', 0)
    p4_swing_cap = phase4_data.get('swing_capture', 0)
    p4_swing_prof = phase4_data.get('swing_profit', 0)
    
    # 优化效果
    scalping_cap_change = p4_scalping_cap - phase2_data.get('scalping_capture', 0)
    scalping_prof_change = p4_scalping_prof - phase2_data.get('scalping_profit', 0)
    swing_cap_change = p4_swing_cap - phase2_data.get('swing_capture', 0)
    swing_prof_change = p4_swing_prof - phase2_data.get('swing_profit', 0)
    
    # 多行格式：每行一个主题
    content = (
        f"📊 昨日表现：{yesterday_winrate:.0f}%胜率 {yesterday_profit:+.1f}U\n"
        f"\n"
        f"⚡ 超短线P4：{p4_scalping_cap:.0f}%捕获 {p4_scalping_prof:.1f}%利润\n"
        f"🌊 波段P4：{p4_swing_cap:.0f}%捕获 {p4_swing_prof:.1f}%利润\n"
        f"\n"
        f"🎯 优化提升：\n"
        f"  超短线 {scalping_cap_change:+.0f}%捕 {scalping_prof_change:+.1f}%利\n"
        f"  波段 {swing_cap_change:+.0f}%捕 {swing_prof_change:+.1f}%利"
    )
    
    print(f"[Bark] 内容长度: {len(content)}字符")
    return content

