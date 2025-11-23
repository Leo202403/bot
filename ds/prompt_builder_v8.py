"""🆕 V8.8: 精简版Prompt构建器（基于交易员建议）

核心改进：
1. Python算价格，AI选策略
2. 删除冲突规则，统一逻辑
3. 动态注入，减少上下文
4. 聚焦决策，删除教科书

交易员建议：从3000+ tokens优化到1000 tokens
"""

from typing import Any


class PromptBuilderV8:
    """V8.8 精简版Prompt构建器"""

    @staticmethod
    def build_market_summary(market_data: dict[str, Any]) -> str:
        """构建市场摘要（只提供数据，不提供定义）"""
        coin = market_data["symbol"].split("/")[0]
        price = market_data["price"]

        # 趋势状态（Python预判断）
        trend_4h = market_data.get("trend_4h", "")
        trend_1h = market_data.get("trend_1h", "")
        trend_15m = market_data.get("trend_15m", "")

        # 关键位置
        sr = market_data.get("support_resistance", {})

        # 处理可能是dict的support/resistance
        nearest_support_data = sr.get("nearest_support", {})
        if isinstance(nearest_support_data, dict):
            nearest_support = nearest_support_data.get("price", price * 0.98)
        else:
            nearest_support = (
                nearest_support_data if nearest_support_data else price * 0.98
            )

        nearest_resistance_data = sr.get("nearest_resistance", {})
        if isinstance(nearest_resistance_data, dict):
            nearest_resistance = nearest_resistance_data.get("price", price * 1.02)
        else:
            nearest_resistance = (
                nearest_resistance_data if nearest_resistance_data else price * 1.02
            )

        # 检测到的形态（Python检测）
        pattern = market_data.get("pattern", "")
        pattern_desc = ""
        if pattern == "PIN_BAR":
            pattern_desc = "Pin Bar detected (reversal signal)"
        elif pattern == "BREAKOUT":
            pattern_desc = "Breakout confirmed (continuation)"
        elif pattern:
            pattern_desc = f"Pattern: {pattern}"

        # ATR（嵌套在atr字典中）
        atr_data = market_data.get("atr", {})
        if isinstance(atr_data, dict):
            atr = atr_data.get("atr_14", 0)
        else:
            atr = 0

        # 信号分数
        signal_score = market_data.get("signal_score", 0)

        return f"""
{coin}:
  Price: ${price:.2f}
  Trend: 4H({trend_4h}) | 1H({trend_1h}) | 15m({trend_15m})
  Support: ${nearest_support:.2f} | Resistance: ${nearest_resistance:.2f}
  ATR: {atr:.2f}
  {pattern_desc}
  Signal Score: {signal_score}
"""

    @staticmethod
    def build_optimized_prompt(
        market_data_list: list[dict[str, Any]],
        current_positions: list[dict[str, Any]],
        tpsl_options_map: dict[str, dict[str, Any]],  # 预计算的TP/SL选项
        balance: float,
        signal_type: str = "swing",
    ) -> str:
        """构建优化后的Prompt（精简版）

        Args:
            market_data_list: 市场数据列表
            current_positions: 当前持仓
            tpsl_options_map: {symbol: {atr: {...}, structure: {...}}}
            balance: 可用余额
            signal_type: scalping or swing

        """
        # 1. 角色定义（简洁）
        role = "Quantitative Crypto Trader (Price Action + Trend Following)"

        # 2. 当前状态
        pos_summary = (
            ", ".join([
                f"{p['symbol'].split('/')[0]}({p['side']})" for p in current_positions
            ])
            if current_positions
            else "Empty"
        )

        current_state = f"""# CURRENT STATE
- Balance: ${balance:.2f} USDT
- Positions: {pos_summary}
- Strategy: {signal_type.upper()}"""

        # 3. 市场数据（只提供数据）
        market_section = "# MARKET DATA\n"
        for data in market_data_list[:5]:  # 最多5个币种
            if data:
                market_section += PromptBuilderV8.build_market_summary(data)

        # 4. TP/SL选项（Python预计算）
        tpsl_section = "# TP/SL OPTIONS (Pre-calculated by Python)\n\n"
        tpsl_section += (
            "Python has calculated TWO stop-loss strategies for each symbol:\n\n"
        )

        for symbol, options in tpsl_options_map.items():
            coin = symbol.split("/")[0]
            atr_opt = options["atr"]
            struct_opt = options["structure"]

            # 提取变量避免f-string中的字典访问问题
            atr_sl = atr_opt["sl_price"]
            atr_sl_pct = atr_opt["sl_pct"]
            atr_tp = atr_opt["tp_price"]
            atr_rr = atr_opt["rr_ratio"]

            struct_sl = struct_opt["sl_price"]
            struct_sl_pct = struct_opt["sl_pct"]
            struct_tp = struct_opt["tp_price"]
            struct_rr = struct_opt["rr_ratio"]

            tpsl_section += f"""{coin}:
  Option A (ATR - Mathematical):
    SL: ${atr_sl} ({atr_sl_pct}% away)
    TP: ${atr_tp}
    R:R: 1:{atr_rr}
    
  Option B (Structure - Price Action):
    SL: ${struct_sl} ({struct_sl_pct}% away)
    TP: ${struct_tp}
    R:R: 1:{struct_rr}

"""

        # 5. 决策规则（简化，无冲突）
        if signal_type == "scalping":
            rules = """# RULES (Scalping)
1. ⚠️ Only ONE position per symbol - if already holding, must HOLD or use a different symbol
2. Only trade if Signal Score > 80
3. Choose TP/SL strategy with better R:R (min 1.5)
4. Exit if holding > 2 hours
5. Leverage: 5-8x"""
        else:  # swing
            rules = """# RULES (Swing)
1. ⚠️ Only ONE position per symbol - if already holding, must HOLD or use a different symbol
2. Only trade if Signal Score > 75
3. Prefer STRUCTURE strategy if R:R > 2.0
4. Exit if holding > 24 hours with no profit
5. Leverage: 3-5x"""

        # 6. 输出格式（完整格式，包含中文字段用于前端展示）
        output_format = """# OUTPUT FORMAT (JSON only, no markdown)

{
  "思考过程": "基于3层框架分析各币种...",
  "analysis": "市场处于XX趋势，推荐XX策略...",
  "risk_assessment": "总体风险可控：1) ... 2) ... 主要风险：...",
  "actions": [
    {
      "symbol": "BTC/USDT:USDT",
      "action": "OPEN_LONG",
      "tpsl_strategy": "STRUCTURE",
      "confidence": 85,
      "leverage": 5,
      "reason": "4H多头趋势+高信号分+R:R>3"
    }
  ],
  "trade_management_plan": {
    "part1_target": "...",
    "part2_target": "...",
    "scaling_strategy": "..."
  }
}

**IMPORTANT**:
- 思考过程: 中文，简要说明分析思路
- analysis: 中文，市场状况和策略建议
- risk_assessment: 中文，风险评估
- actions: 交易动作列表（可以为空表示HOLD）
- tpsl_strategy: Choose "ATR" or "STRUCTURE" (Python will apply actual prices)
- trade_management_plan: 可选，仓位管理计划
"""

        # 组合所有部分
        prompt = f"""# ROLE
{role}

{current_state}

{market_section}

{tpsl_section}

{rules}

{output_format}

# DECISION REQUEST
Analyze the data above. Decide: OPEN_LONG, OPEN_SHORT, or HOLD.
Focus on: trend alignment, R:R quality, and signal strength."""

        return prompt

    @staticmethod
    def build_dynamic_context(market_data: dict[str, Any]) -> str:
        """动态注入相关规则（只注入检测到的形态）"""
        context_parts = []

        # 只有检测到形态时才注入说明
        pattern = market_data.get("pattern", "")
        if pattern == "PIN_BAR":
            context_parts.append(
                "Pin Bar: Long wick + small body = reversal signal. "
                "Strong if at support."
            )
        elif pattern == "BREAKOUT":
            context_parts.append(
                "Breakout: Price above resistance with volume = continuation. "
                "Watch for false breakout."
            )

        # 趋势对齐度
        trend_align = market_data.get("trend_align", 0)
        if trend_align >= 2:
            context_parts.append("Strong trend alignment across timeframes.")

        return " ".join(context_parts) if context_parts else ""


def example_usage():
    """使用示例"""
    from ds.qwen_多币种智能版 import TPSLCalculator

    # 1. 准备市场数据
    market_data = {
        "symbol": "BTC/USDT",
        "price": 65000,
        "trend_4h": "Bull",
        "trend_1h": "Bull",
        "trend_15m": "Bull",
        "support_resistance": {"nearest_support": 64500, "nearest_resistance": 66000},
        "atr_14": 500,
        "signal_score": 85,
        "pattern": "BREAKOUT",
    }

    # 2. Python预计算TP/SL选项
    tpsl_options = TPSLCalculator.calculate_tpsl_options(
        entry_price=65000,
        side="long",
        atr=500,
        nearest_support=64500,
        nearest_resistance=66000,
        atr_tp_mult=4.0,
        atr_sl_mult=1.5,
        signal_type="swing",
    )

    # 3. 构建Prompt
    builder = PromptBuilderV8()
    prompt = builder.build_optimized_prompt(
        market_data_list=[market_data],
        current_positions=[],
        tpsl_options_map={"BTC/USDT": tpsl_options},
        balance=1000,
        signal_type="swing",
    )

    print(prompt)
    print(
        f"\n📊 Token估算: {len(prompt.split())} words (~{len(prompt) / 4:.0f} tokens)"
    )


if __name__ == "__main__":
    example_usage()
