#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V8.9.1 Prompt优化器
实现分级Prompt策略和确定性判断
"""

from datetime import datetime
from typing import Dict, List, Optional, Tuple


def check_deterministic_exit(position: dict, current_price: float) -> Tuple[bool, Optional[str]]:
    """
    检查确定性的EXIT条件（TP/SL/Time），不需要AI判断
    
    Args:
        position: 持仓信息
        current_price: 当前价格
        
    Returns:
        (should_exit, reason): 是否应该退出和原因
    """
    try:
        side = position.get('side', '')
        entry_price = position.get('entry_price', 0)
        tp_price = position.get('take_profit', 0)
        sl_price = position.get('stop_loss', 0)
        open_time = position.get('open_time', '')
        
        # 1. TP检查
        if tp_price > 0:
            if side == 'LONG' and current_price >= tp_price:
                return True, "TP_REACHED"
            elif side == 'SHORT' and current_price <= tp_price:
                return True, "TP_REACHED"
        
        # 2. SL检查
        if sl_price > 0:
            if side == 'LONG' and current_price <= sl_price:
                return True, "SL_HIT"
            elif side == 'SHORT' and current_price >= sl_price:
                return True, "SL_HIT"
        
        # 3. Time Stop检查
        if open_time:
            try:
                entry_time_dt = datetime.strptime(open_time, "%Y-%m-%d %H:%M:%S")
                holding_hours = (datetime.now() - entry_time_dt).total_seconds() / 3600
                
                # 获取max_holding_hours（如果有）
                max_hours = position.get('max_holding_hours', 72)  # 默认72小时
                
                if holding_hours > max_hours:
                    return True, "TIME_STOP"
            except Exception:
                pass
        
        return False, None
        
    except Exception as e:
        print(f"⚠️ 确定性EXIT检查异常: {e}")
        return False, None


def build_reversal_check_prompt(
    position: dict,
    market_data: dict,
    learning_config: dict
) -> str:
    """
    构建市场反转检查Prompt（精简版，~100 tokens）
    用于有持仓时，只需要AI判断市场是否反转
    
    Args:
        position: 持仓信息
        market_data: 市场数据
        learning_config: 学习配置
        
    Returns:
        精简的Prompt字符串
    """
    symbol = position.get('symbol', '')
    side = position.get('side', '')
    entry_price = position.get('entry_price', 0)
    current_price = market_data.get('price', 0)
    
    # 入场时的趋势
    entry_4h = position.get('entry_4h_trend', 'UNKNOWN')
    entry_1h = position.get('entry_1h_trend', 'UNKNOWN')
    
    # 当前趋势
    current_4h = market_data.get('4h_trend', {}).get('trend', 'UNKNOWN')
    current_1h = market_data.get('1h_trend', {}).get('trend', 'UNKNOWN')
    current_15m = market_data.get('15m_trend', {}).get('trend', 'UNKNOWN')
    
    # 持仓时间
    open_time = position.get('open_time', '')
    try:
        entry_time_dt = datetime.strptime(open_time, "%Y-%m-%d %H:%M:%S")
        holding_hours = (datetime.now() - entry_time_dt).total_seconds() / 3600
    except Exception:
        holding_hours = 0
    
    prompt = f"""
**[Reply in Chinese]** Market Reversal Check | {symbol}

╔══════════════════════════════════════════════════════════════════════════════╗
║ POSITION SNAPSHOT                                                            ║
╚══════════════════════════════════════════════════════════════════════════════╝
Position: {side} from ${entry_price:.2f} | Current: ${current_price:.2f} | Holding: {holding_hours:.1f}h
P&L: {((current_price - entry_price) / entry_price * 100 if side == 'LONG' else (entry_price - current_price) / entry_price * 100):.2f}%

Trends at Entry:
- 4H: {entry_4h}
- 1H: {entry_1h}

Trends NOW:
- 4H: {current_4h}
- 1H: {current_1h}
- 15m: {current_15m}

╔══════════════════════════════════════════════════════════════════════════════╗
║ YOUR TASK: Check Market Reversal                                            ║
╚══════════════════════════════════════════════════════════════════════════════╝

Reversal Rule: (4H changed) OR (1H+15m both changed)

Question: Has market reversed against our position?

Output JSON:
{{
    "decision": "MARKET_REVERSED" or "CONTINUE_HOLDING",
    "reason": "Brief explanation of trend analysis"
}}

⚠️ CRITICAL: Historical data shows premature exits destroy R:R. Only exit if CLEAR reversal!
"""
    
    return prompt


def build_entry_scan_prompt(
    market_data_list: List[dict],
    current_positions: List[dict],
    learning_config: dict,
    scalping_params: dict,
    swing_params: dict,
    trades_count: int,
    max_total_position: float
) -> str:
    """
    构建Entry扫描Prompt（完整版，~500 tokens）
    用于无持仓或需要扫描新机会时
    
    Args:
        market_data_list: 所有币种的市场数据
        current_positions: 当前持仓
        learning_config: 学习配置
        scalping_params: Scalping参数
        swing_params: Swing参数
        trades_count: 历史交易数
        max_total_position: 最大持仓金额
        
    Returns:
        完整的Prompt字符串
    """
    # 生成市场概况
    market_overview = ""
    for data in market_data_list:
        if not data:
            continue
        
        symbol = data.get('symbol', '')
        price = data.get('price', 0)
        price_change = data.get('price_change', 0)
        
        # 趋势
        trend_4h = data.get('4h_trend', {}).get('trend', 'N/A')
        trend_1h = data.get('1h_trend', {}).get('trend', 'N/A')
        trend_15m = data.get('15m_trend', {}).get('trend', 'N/A')
        
        # 指标
        indicators = data.get('indicators', {})
        consensus = indicators.get('consensus', 0)
        
        # PA模式
        pa_pattern = data.get('pa_pattern', {}).get('pattern_name', 'None')
        
        market_overview += f"""
{symbol}:
- Price: ${price:.2f} ({price_change:+.2f}%) | Trends: 4H={trend_4h}, 1H={trend_1h}, 15m={trend_15m}
- Consensus: {consensus}/5 | PA: {pa_pattern}
"""
    
    # 持仓信息
    position_info = ""
    if current_positions:
        position_info = f"Current Positions: {len(current_positions)}\n"
        for pos in current_positions:
            position_info += f"- {pos.get('symbol')}: {pos.get('side')} from ${pos.get('entry_price', 0):.2f}\n"
    else:
        position_info = "No current positions\n"
    
    prompt = f"""
**[Reply in Chinese]** Entry Signal Scan | Multi-Asset Analysis

╔══════════════════════════════════════════════════════════════════════════════╗
║ FRAMEWORK: 4H(40%) Trend → 1H(30%) TP/SL → 15m(20%) Entry                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

╔══════════════════════════════════════════════════════════════════════════════╗
║ MARKET DATA                                                                  ║
╚══════════════════════════════════════════════════════════════════════════════╝
{market_overview}

╔══════════════════════════════════════════════════════════════════════════════╗
║ ACCOUNT                                                                      ║
╚══════════════════════════════════════════════════════════════════════════════╝
{position_info}
Available Capital: {max_total_position:.0f}U

╔══════════════════════════════════════════════════════════════════════════════╗
║ ADAPTIVE PARAMS | Based on {trades_count} trades                            ║
╚══════════════════════════════════════════════════════════════════════════════╝
R:R={learning_config['global']['min_risk_reward']:.1f}:1 | SL=ATR×{learning_config['global']['atr_stop_multiplier']:.1f} | Consensus={learning_config['global']['min_indicator_consensus']}/5

╔══════════════════════════════════════════════════════════════════════════════╗
║ TP/SL RULES | V8.5 CRITICAL                                                  ║
╚══════════════════════════════════════════════════════════════════════════════╝
Scalp: TP=Entry±15m_ATR×{scalping_params.get('atr_tp_multiplier', 2.5):.1f} | SL=Entry∓15m_ATR×{scalping_params.get('atr_stop_multiplier', 1.5):.1f}
Swing: TP=Entry±1H_ATR×{swing_params.get('atr_tp_multiplier', 4.0):.1f} | SL=Entry∓1H_ATR×{swing_params.get('atr_stop_multiplier', 1.5):.1f}

╔══════════════════════════════════════════════════════════════════════════════╗
║ DECISION TREE                                                                ║
╚══════════════════════════════════════════════════════════════════════════════╝
1. Check 4H trend alignment → Bull/Bear/Neutral
2. Check PA confirmation → Inception/Pullback/Exhaustion
3. Check Consensus → X/5
4. Calculate TP/SL → Validate R:R≥{learning_config['global']['min_risk_reward']:.1f}

IF all pass:
  Output: {{"decision": "OPEN_LONG/OPEN_SHORT", "symbol": "...", "tp": ..., "sl": ..., "leverage": ...}}
ELSE:
  Output: {{"decision": "HOLD", "reason": "..."}}

⚠️ EXIT RULES reminder: Only exit on TP/SL/Time/Reversal. NO premature exits!

╔══════════════════════════════════════════════════════════════════════════════╗
║ OUTPUT JSON FORMAT                                                           ║
╚══════════════════════════════════════════════════════════════════════════════╝
{{
    "思考过程": "Brief 3-layer analysis",
    "analysis": "Decision summary",
    "actions": [
        {{
            "symbol": "BTC/USDT:USDT",
            "action": "OPEN_LONG|OPEN_SHORT|HOLD",
            "reason": "Mode(Scalp/Swing) + Rationale",
            "signal_mode": "scalping|swing",
            "stop_loss_price": 108375.00,
            "take_profit_price": 110125.00,
            "leverage": 5
        }}
    ]
}}
"""
    
    return prompt

