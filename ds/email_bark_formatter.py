"""
【V8.5.2.4.81】邮件和Bark格式化辅助函数
用于生成优化后的邮件HTML和Bark内容
"""

def generate_phase_summary_table(phase_data):
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


def generate_params_comparison_table(scalping_params, swing_params, learned_features=None):
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
    def safe_get(params, key, default='N/A'):
        if not params:  # 如果params为空字典
            return default
        value = params.get(key, default)
        if isinstance(value, float):
            return f"{value:.1f}"
        return str(value)
    
    # 移动止损图标
    scalping_trailing = "✅" if scalping_params and scalping_params.get('trailing_stop_enabled') else "❌"
    swing_trailing = "✅" if swing_params and swing_params.get('trailing_stop_enabled') else "❌"
    
    # 【V8.5.2.4.83】从learned_features提取密度信息
    if learned_features is None:
        learned_features = {}
    scalping_density = safe_get(learned_features, 'scalping_avg_density', 'N/A')
    swing_density = safe_get(learned_features, 'swing_avg_density', 'N/A')
    high_density_threshold = safe_get(learned_features, 'high_density_threshold', 'N/A')
    
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


def generate_profit_comparison_table(phase_data):
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
    
    html = f"""
<div class="summary-box" style="background: #e8f5e9; border: 2px solid #4caf50; margin: 20px 0; padding: 20px; border-radius: 8px;">
    <h2 style="color: #1b5e20; margin-top: 0;">💰 累计收益率对比分析</h2>
    
    <table style="width: 100%; border-collapse: collapse; margin: 15px 0; font-size: 14px;">
        <thead>
            <tr style="background: #4caf50; color: white;">
                <th style="padding: 12px; border: 1px solid #dee2e6; text-align: left;">阶段</th>
                <th style="padding: 12px; border: 1px solid #dee2e6; text-align: right;">超短线累计收益率</th>
                <th style="padding: 12px; border: 1px solid #dee2e6; text-align: right;">波段累计收益率</th>
                <th style="padding: 12px; border: 1px solid #dee2e6; text-align: right;">合计</th>
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
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: right; font-weight: bold; font-family: monospace;">
                    +{p1_total:.2f}%
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
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: right; font-weight: bold; font-family: monospace;">
                    +{p2_total:.2f}%
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
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: right; font-weight: bold; font-family: monospace;">
                    +{p3_total:.2f}%
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
                <td style="padding: 10px; border: 1px solid #dee2e6; text-align: right; font-weight: bold; font-size: 1.1em; font-family: monospace;">
                    +{p4_total:.2f}%
                </td>
            </tr>
        </tbody>
    </table>
    
    <div style="margin-top: 15px; padding: 15px; background: white; border-radius: 5px; border-left: 4px solid {improvement_color};">
        <p style="margin: 5px 0; font-size: 1.05em;">
            {improvement_icon} <strong>Phase 2 → Phase 4提升</strong>: 
            <span style="color: {improvement_color}; font-weight: bold; font-size: 1.1em;">
                {improvement_amount:+.2f}% ({improvement_pct:+.1f}%)
            </span>
        </p>
        <p style="margin: 5px 0; color: #6c757d; font-size: 0.9em;">
            💡 累计收益率 = 捕获机会数 × 平均单笔收益率（理论值）
        </p>
        <p style="margin: 5px 0; color: #6c757d; font-size: 0.9em;">
            💡 Phase 1为理论最大值，Phase 4为实际可捕获利润
        </p>
    </div>
</div>
"""
    return html


def generate_optimized_bark_content(yesterday_data, phase2_data, phase4_data):
    """
    【V8.5.2.4.89.5】生成优化后的Bark推送内容（增强容错+调试）
    
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
        str: Bark内容
    """
    # 【V8.5.2.4.89.5】调试：打印参数类型
    print(f"[Bark Debug] yesterday_data type: {type(yesterday_data)}")
    print(f"[Bark Debug] phase2_data type: {type(phase2_data)}")
    print(f"[Bark Debug] phase4_data type: {type(phase4_data)}")
    
    # 【V8.5.2.4.89.5】确保所有参数都是字典类型（增强版）
    if not isinstance(yesterday_data, dict):
        print(f"[Bark Debug] yesterday_data is not dict: {yesterday_data}")
        yesterday_data = {}
    if not isinstance(phase2_data, dict):
        print(f"[Bark Debug] phase2_data is not dict: {phase2_data}")
        phase2_data = {}
    if not isinstance(phase4_data, dict):
        print(f"[Bark Debug] phase4_data is not dict: {phase4_data}")
        phase4_data = {}
    
    yesterday_data = yesterday_data or {}
    phase2_data = phase2_data or {}
    phase4_data = phase4_data or {}
    
    lines = []
    
    # 1️⃣ 前一天情况总结
    yesterday_winrate = yesterday_data.get('winrate', 0) * 100
    yesterday_profit = yesterday_data.get('profit', 0)
    # 【修复】移除冒号避免Bark URL解析错误
    lines.append(f"📊 昨日-胜率{yesterday_winrate:.0f}% 利润{yesterday_profit:+.1f}U")
    
    # 2️⃣ 当前重点信息（Phase 4最终结果）
    lines.append(f"\n🎯 Phase 4最终-")
    lines.append(f"⚡超短线-{phase4_data.get('scalping_capture', 0):.0f}% / {phase4_data.get('scalping_profit', 0):.1f}%")
    lines.append(f"🌊波段-{phase4_data.get('swing_capture', 0):.0f}% / {phase4_data.get('swing_profit', 0):.1f}%")
    
    # 3️⃣ 对比信息（Phase 2 → Phase 4）
    scalping_capture_change = phase4_data.get('scalping_capture', 0) - phase2_data.get('scalping_capture', 0)
    scalping_profit_change = phase4_data.get('scalping_profit', 0) - phase2_data.get('scalping_profit', 0)
    swing_capture_change = phase4_data.get('swing_capture', 0) - phase2_data.get('swing_capture', 0)
    swing_profit_change = phase4_data.get('swing_profit', 0) - phase2_data.get('swing_profit', 0)
    
    lines.append(f"\n📈 优化效果-")
    
    # 超短线变化
    scalping_capture_sign = "+" if scalping_capture_change > 0 else ""
    scalping_profit_sign = "+" if scalping_profit_change > 0 else ""
    lines.append(f"⚡捕获率{scalping_capture_sign}{scalping_capture_change:.1f}% 利润{scalping_profit_sign}{scalping_profit_change:.1f}%")
    
    # 波段变化
    swing_capture_sign = "+" if swing_capture_change > 0 else ""
    swing_profit_sign = "+" if swing_profit_change > 0 else ""
    lines.append(f"🌊捕获率{swing_capture_sign}{swing_capture_change:.1f}% 利润{swing_profit_sign}{swing_profit_change:.1f}%")
    
    return "\n".join(lines)

