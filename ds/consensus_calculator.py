#!/usr/bin/env python3
"""【V8.4】Consensus Score计算模块

统一的consensus_score计算逻辑，供以下模块使用：
1. export_historical_data.py - 离线数据导出
2. qwen_多币种智能版.py - 实时交易（保存快照）
3. deepseek_多币种智能版.py - 实时交易（保存快照）
"""


def calculate_consensus_score(
    # 指标数据
    ema20=0,
    ema50=0,
    macd_histogram=0,
    rsi_14=50,
    volume=0,
    avg_volume=0,
    # 趋势数据
    trend_15m="",
    trend_1h="",
    trend_4h="",
    # 形态数据（可选）
    pin_bar_score=0,
    engulfing_score=0,
    breakout_score=0,
    # K线序列数据（可选）
    recent_closes=None,
    # 支撑阻力数据（可选）
    support=0,
    resistance=0,
    current_price=0,
):
    """【V8.4】计算综合确认度评分（0-100分）

    评分结构：
    - 指标确认（40分）：EMA、MACD、RSI、成交量
    - 趋势确认（30分）：多周期趋势一致性
    - 形态确认（30分）：价格形态、K线结构、支撑阻力

    Args:
        # 指标数据
        ema20: EMA20值
        ema50: EMA50值
        macd_histogram: MACD柱状图值
        rsi_14: RSI(14)值
        volume: 当前成交量
        avg_volume: 平均成交量（最近20根）

        # 趋势数据
        trend_15m: 15分钟趋势（字符串，如"多头"/"空头"）
        trend_1h: 1小时趋势
        trend_4h: 4小时趋势

        # 形态数据（可选）
        pin_bar_score: Pin Bar评分（0-12）
        engulfing_score: 吞没形态评分（0-12）
        breakout_score: 突破评分（0-25）

        # K线序列数据（可选）
        recent_closes: 最近3-5根K线的收盘价列表

        # 支撑阻力数据（可选）
        support: 支撑位价格
        resistance: 阻力位价格
        current_price: 当前价格

    Returns:
        int: consensus_score (0-100)

    """
    consensus_score = 0

    # === 第1层：指标确认（40分） ===

    # 1. EMA发散（10分）
    if ema20 > 0 and ema50 > 0:
        divergence = abs(ema20 - ema50) / ema50 * 100
        if divergence >= 5.0:
            consensus_score += 10  # 强发散
        elif divergence >= 2.0:
            consensus_score += 5  # 中发散

    # 2. MACD强度（10分）
    if abs(macd_histogram) >= 0.05:
        consensus_score += 10  # 强信号
    elif abs(macd_histogram) >= 0.01:
        consensus_score += 5  # 中信号

    # 3. RSI极端值（10分）
    if rsi_14 > 75 or rsi_14 < 25:
        consensus_score += 10  # 超强极端
    elif rsi_14 > 70 or rsi_14 < 30:
        consensus_score += 7  # 强极端
    elif 45 <= rsi_14 <= 55:
        consensus_score += 3  # 中性（轻微加分）

    # 4. 成交量放量（10分）
    if avg_volume > 0 and volume > 0:
        vol_ratio = volume / avg_volume
        if vol_ratio >= 2.0:
            consensus_score += 10  # 强放量
        elif vol_ratio >= 1.5:
            consensus_score += 5  # 中放量

    # === 第2层：趋势确认（30分） ===

    # 5. 多周期趋势一致性（30分）
    is_all_bullish = (
        "多头" in str(trend_15m) and "多头" in str(trend_1h) and "多头" in str(trend_4h)
    )
    is_all_bearish = (
        "空头" in str(trend_15m) and "空头" in str(trend_1h) and "空头" in str(trend_4h)
    )

    if is_all_bullish or is_all_bearish:
        consensus_score += 30  # 三层对齐
    elif ("多头" in str(trend_1h) and "多头" in str(trend_4h)) or (
        "空头" in str(trend_1h) and "空头" in str(trend_4h)
    ):
        consensus_score += 15  # 两层对齐

    # === 第3层：形态确认（30分） ===

    # 6. 价格形态强度（15分）
    pattern_score = 0
    if pin_bar_score > 0:
        pattern_score += min(5, pin_bar_score / 2)  # Pin Bar最多5分
    if engulfing_score > 0:
        pattern_score += min(5, engulfing_score / 2)  # 吞没最多5分
    if breakout_score > 0:
        pattern_score += min(5, breakout_score / 5)  # 突破最多5分
    consensus_score += int(pattern_score)

    # 7. K线序列一致性（10分）
    if recent_closes is not None and len(recent_closes) >= 3:
        # 检查最近3根K线的方向一致性
        is_bullish_seq = all(
            recent_closes[i] < recent_closes[i + 1]
            for i in range(len(recent_closes) - 1)
        )
        is_bearish_seq = all(
            recent_closes[i] > recent_closes[i + 1]
            for i in range(len(recent_closes) - 1)
        )

        if is_bullish_seq or is_bearish_seq:
            consensus_score += 10  # 强一致
        elif (recent_closes[-1] > recent_closes[-2]) or (
            recent_closes[-1] < recent_closes[-2]
        ):
            consensus_score += 5  # 弱一致

    # 8. 支撑阻力明确性（5分）
    if support > 0 and resistance > 0 and current_price > 0:
        sr_gap = abs(resistance - support) / current_price * 100
        if sr_gap >= 3.0:
            consensus_score += 5  # 支撑阻力明确
        elif sr_gap >= 1.5:
            consensus_score += 3  # 支撑阻力较明确

    # 限制在0-100范围
    return min(100, max(0, consensus_score))


def calculate_indicator_consensus_legacy(
    ema20=0,
    ema50=0,
    macd_histogram=0,
    rsi_14=50,
    volume=0,
    avg_volume=0,
    trend_15m="",
    trend_1h="",
    trend_4h="",
):
    """【兼容性】计算旧版indicator_consensus（0-5）

    用于向后兼容，只统计最核心的5个指标。
    """
    indicator_consensus = 0

    # 1. EMA发散
    if ema20 > 0 and ema50 > 0:
        divergence = abs(ema20 - ema50) / ema50 * 100
        if divergence >= 2.0:
            indicator_consensus += 1

    # 2. MACD
    if abs(macd_histogram) >= 0.01:
        indicator_consensus += 1

    # 3. RSI
    if rsi_14 > 70 or rsi_14 < 30 or (45 <= rsi_14 <= 55):
        indicator_consensus += 1

    # 4. 成交量
    if avg_volume > 0 and volume > 0:
        vol_ratio = volume / avg_volume
        if vol_ratio >= 1.5:
            indicator_consensus += 1

    # 5. 多周期趋势一致
    is_all_bullish = (
        "多头" in str(trend_15m) and "多头" in str(trend_1h) and "多头" in str(trend_4h)
    )
    is_all_bearish = (
        "空头" in str(trend_15m) and "空头" in str(trend_1h) and "空头" in str(trend_4h)
    )
    if is_all_bullish or is_all_bearish:
        indicator_consensus += 1

    return indicator_consensus


# 测试代码
if __name__ == "__main__":
    # 测试案例1：强信号
    print("测试案例1：强信号（高EMA发散+强MACD+超买RSI+三层对齐）")
    score = calculate_consensus_score(
        ema20=10000,
        ema50=9500,  # 5.3%发散
        macd_histogram=0.08,  # 强MACD
        rsi_14=78,  # 超买
        volume=1000000,
        avg_volume=400000,  # 2.5倍放量
        trend_15m="多头",
        trend_1h="多头",
        trend_4h="多头",
    )
    print(f"consensus_score = {score} (预期: 70-80分)")
    print()

    # 测试案例2：形态驱动（高形态分+低指标分）
    print("测试案例2：形态驱动（pin bar+突破，但指标弱）")
    score = calculate_consensus_score(
        ema20=10000,
        ema50=9980,  # 0.2%发散（弱）
        macd_histogram=0.005,  # 弱MACD
        rsi_14=55,  # 中性
        volume=500000,
        avg_volume=500000,  # 无放量
        trend_15m="多头",
        trend_1h="震荡",
        trend_4h="震荡",
        pin_bar_score=12,  # 强pin bar
        breakout_score=25,  # 强突破
        recent_closes=[9900, 9950, 10000],  # 强K线序列
    )
    print(f"consensus_score = {score} (预期: 20-35分)")
    print()

    # 测试案例3：低质量信号
    print("测试案例3：低质量信号（各维度都弱）")
    score = calculate_consensus_score(
        ema20=10000,
        ema50=9990,  # 0.1%发散
        macd_histogram=0.001,  # 弱MACD
        rsi_14=50,  # 中性
        volume=500000,
        avg_volume=500000,  # 无放量
        trend_15m="震荡",
        trend_1h="震荡",
        trend_4h="震荡",
    )
    print(f"consensus_score = {score} (预期: 0-10分)")
