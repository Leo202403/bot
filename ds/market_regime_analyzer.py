"""
【V8.5.2.4.89.63】市场状态分析模块
Market Regime Analyzer - Comprehensive Market State Assessment

功能：
1. 分析整体市场状态（震荡/趋势）
2. 评估市场波动性（高波/低波）
3. 识别市场情绪（牛市/熊市/盘整）
4. 为AI提供策略调整建议

Author: Trading System V8.5.2
Date: 2025-11-21
"""

from typing import Dict, List, Any
import statistics


def analyze_market_regime(market_data_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    综合分析当前市场状态
    
    Args:
        market_data_list: 所有币种的市场数据列表
    
    Returns:
        market_regime: {
            'overall_trend': 'bullish' | 'bearish' | 'ranging',  # 整体趋势
            'market_type': 'trending' | 'choppy' | 'neutral',    # 市场类型
            'volatility': 'high' | 'medium' | 'low',             # 波动性
            'trend_strength': 0-100,                              # 趋势强度
            'recommended_strategy': 'scalping' | 'swing' | 'hold', # 推荐策略
            'confidence': 0-1,                                     # 判断置信度
            'details': {...}                                       # 详细分析
        }
    """
    
    if not market_data_list or all(d is None for d in market_data_list):
        return _get_neutral_regime()
    
    # 过滤无效数据
    valid_data = [d for d in market_data_list if d is not None]
    
    # 1. 分析整体趋势方向
    trend_analysis = _analyze_overall_trend(valid_data)
    
    # 2. 分析市场类型（趋势/震荡）
    market_type_analysis = _analyze_market_type(valid_data)
    
    # 3. 分析波动性
    volatility_analysis = _analyze_volatility(valid_data)
    
    # 4. 综合判断推荐策略
    strategy_recommendation = _recommend_strategy(
        trend_analysis,
        market_type_analysis,
        volatility_analysis
    )
    
    return {
        'overall_trend': trend_analysis['direction'],
        'market_type': market_type_analysis['type'],
        'volatility': volatility_analysis['level'],
        'trend_strength': trend_analysis['strength'],
        'recommended_strategy': strategy_recommendation['strategy'],
        'confidence': strategy_recommendation['confidence'],
        'details': {
            'bullish_count': trend_analysis['bullish_count'],
            'bearish_count': trend_analysis['bearish_count'],
            'ranging_count': trend_analysis['ranging_count'],
            'avg_volatility': volatility_analysis['avg_volatility'],
            'trending_coins': market_type_analysis['trending_coins'],
            'choppy_coins': market_type_analysis['choppy_coins'],
            'reasoning': strategy_recommendation['reasoning']
        }
    }


def _analyze_overall_trend(data_list: List[Dict]) -> Dict:
    """分析整体趋势方向"""
    
    bullish_4h = 0
    bearish_4h = 0
    bullish_1h = 0
    bearish_1h = 0
    ranging = 0
    
    for data in data_list:
        trend_4h = data.get('trend_4h', '')
        trend_1h = data.get('mid_term', {}).get('trend', '')
        
        # 4H趋势统计
        if '多头' in trend_4h or 'Bull' in trend_4h:
            bullish_4h += 1
        elif '空头' in trend_4h or 'Bear' in trend_4h:
            bearish_4h += 1
        else:
            ranging += 1
        
        # 1H趋势统计
        if '多头' in trend_1h or 'Bull' in trend_1h:
            bullish_1h += 1
        elif '空头' in trend_1h or 'Bear' in trend_1h:
            bearish_1h += 1
    
    total = len(data_list)
    
    # 计算多头占比（4H权重0.6 + 1H权重0.4）
    bullish_score = (bullish_4h * 0.6 + bullish_1h * 0.4) / total * 100
    bearish_score = (bearish_4h * 0.6 + bearish_1h * 0.4) / total * 100
    
    # 判断方向
    if bullish_score > 60:
        direction = 'bullish'
        strength = bullish_score
    elif bearish_score > 60:
        direction = 'bearish'
        strength = bearish_score
    else:
        direction = 'ranging'
        strength = 100 - max(bullish_score, bearish_score)
    
    return {
        'direction': direction,
        'strength': int(strength),
        'bullish_count': bullish_4h,
        'bearish_count': bearish_4h,
        'ranging_count': ranging
    }


def _analyze_market_type(data_list: List[Dict]) -> Dict:
    """分析市场类型（趋势/震荡）"""
    
    trending_coins = []
    choppy_coins = []
    
    for data in data_list:
        coin_name = data.get('symbol', '').split('/')[0]
        trend_4h = data.get('trend_4h', '')
        trend_1h = data.get('mid_term', {}).get('trend', '')
        trend_15m = data.get('trend_15m', '')
        
        # 判断是否趋势一致
        trends = [trend_4h, trend_1h, trend_15m]
        bullish_count = sum(1 for t in trends if '多头' in t or 'Bull' in t)
        bearish_count = sum(1 for t in trends if '空头' in t or 'Bear' in t)
        
        # 三层趋势一致 = 强趋势
        if bullish_count >= 2 or bearish_count >= 2:
            trending_coins.append(coin_name)
        else:
            choppy_coins.append(coin_name)
    
    total = len(data_list)
    trending_pct = len(trending_coins) / total * 100
    
    # 判断市场类型
    if trending_pct >= 60:
        market_type = 'trending'  # 趋势市
    elif trending_pct <= 30:
        market_type = 'choppy'    # 震荡市
    else:
        market_type = 'neutral'   # 中性市
    
    return {
        'type': market_type,
        'trending_pct': trending_pct,
        'trending_coins': trending_coins,
        'choppy_coins': choppy_coins
    }


def _analyze_volatility(data_list: List[Dict]) -> Dict:
    """分析市场波动性"""
    
    volatilities = []
    
    for data in data_list:
        # 使用ATR/价格比例衡量波动性
        atr_data = data.get('atr', {})
        # 【修复】atr是嵌套字典，需要获取atr_14值
        atr = atr_data.get('atr_14', 0) if isinstance(atr_data, dict) else atr_data
        price = data.get('price', 1)
        
        if atr > 0 and price > 0:
            volatility_pct = (atr / price) * 100
            volatilities.append(volatility_pct)
        
        # 也可以使用价格变化率
        price_change = abs(data.get('price_change', 0))
        volatilities.append(price_change)
    
    if not volatilities:
        return {'level': 'medium', 'avg_volatility': 0}
    
    avg_vol = statistics.mean(volatilities)
    
    # 判断波动性等级
    if avg_vol >= 3.0:
        level = 'high'      # 高波动（≥3%）
    elif avg_vol >= 1.5:
        level = 'medium'    # 中等波动（1.5-3%）
    else:
        level = 'low'       # 低波动（<1.5%）
    
    return {
        'level': level,
        'avg_volatility': round(avg_vol, 2)
    }


def _recommend_strategy(
    trend_analysis: Dict,
    market_type_analysis: Dict,
    volatility_analysis: Dict
) -> Dict:
    """根据市场状态推荐策略"""
    
    direction = trend_analysis['direction']
    market_type = market_type_analysis['type']
    volatility = volatility_analysis['level']
    strength = trend_analysis['strength']
    
    # 策略推荐逻辑
    reasoning_parts = []
    
    # 1. 趋势市 + 高波动 → 波段交易
    if market_type == 'trending' and strength > 70:
        strategy = 'swing'
        confidence = 0.85
        reasoning_parts.append(f"Strong {direction} trend ({strength}%)")
        reasoning_parts.append(f"Trending market ({market_type_analysis['trending_pct']:.0f}% coins aligned)")
        reasoning_parts.append("→ Swing trading recommended for trend-following")
    
    # 2. 震荡市 + 高波动 → 超短线
    elif market_type == 'choppy' and volatility in ['high', 'medium']:
        strategy = 'scalping'
        confidence = 0.80
        reasoning_parts.append(f"Choppy market ({100 - market_type_analysis['trending_pct']:.0f}% coins ranging)")
        reasoning_parts.append(f"{volatility.capitalize()} volatility ({volatility_analysis['avg_volatility']:.1f}%)")
        reasoning_parts.append("→ Scalping recommended for quick in-out")
    
    # 3. 低波动 → 观望
    elif volatility == 'low':
        strategy = 'hold'
        confidence = 0.75
        reasoning_parts.append(f"Low volatility ({volatility_analysis['avg_volatility']:.1f}%)")
        reasoning_parts.append("→ Market too quiet, wait for better setup")
    
    # 4. 中性市 → 根据波动性选择
    else:
        if volatility == 'high':
            strategy = 'scalping'
            confidence = 0.70
            reasoning_parts.append("Neutral market with high volatility")
            reasoning_parts.append("→ Scalping for short-term opportunities")
        else:
            strategy = 'swing'
            confidence = 0.65
            reasoning_parts.append(f"Neutral market, {direction} bias")
            reasoning_parts.append("→ Swing for selective opportunities")
    
    return {
        'strategy': strategy,
        'confidence': confidence,
        'reasoning': ' | '.join(reasoning_parts)
    }


def _get_neutral_regime() -> Dict:
    """返回中性市场状态（数据不足时的默认值）"""
    return {
        'overall_trend': 'ranging',
        'market_type': 'neutral',
        'volatility': 'medium',
        'trend_strength': 50,
        'recommended_strategy': 'hold',
        'confidence': 0.5,
        'details': {
            'bullish_count': 0,
            'bearish_count': 0,
            'ranging_count': 0,
            'avg_volatility': 0,
            'trending_coins': [],
            'choppy_coins': [],
            'reasoning': 'Insufficient data for market regime analysis'
        }
    }


def format_market_regime_for_ai(regime: Dict) -> str:
    """
    将市场状态格式化为AI可读的文本
    
    Args:
        regime: analyze_market_regime()的返回结果
    
    Returns:
        formatted_text: 格式化后的市场状态描述
    """
    
    # 趋势方向的emoji
    trend_emoji = {
        'bullish': '📈',
        'bearish': '📉',
        'ranging': '↔️'
    }
    
    # 市场类型的描述
    market_type_desc = {
        'trending': 'Trending Market (Clear direction)',
        'choppy': 'Choppy Market (Range-bound)',
        'neutral': 'Neutral Market (Mixed signals)'
    }
    
    # 波动性的emoji
    volatility_emoji = {
        'high': '🔥',
        'medium': '📊',
        'low': '💤'
    }
    
    # 策略推荐的emoji
    strategy_emoji = {
        'swing': '🌊',
        'scalping': '⚡',
        'hold': '⏸️'
    }
    
    text = f"""
=== 📊 MARKET REGIME ANALYSIS ===

{trend_emoji[regime['overall_trend']]} Overall Trend: {regime['overall_trend'].upper()} (Strength: {regime['trend_strength']}%)
  • Bullish: {regime['details']['bullish_count']} coins
  • Bearish: {regime['details']['bearish_count']} coins
  • Ranging: {regime['details']['ranging_count']} coins

🎯 Market Type: {market_type_desc[regime['market_type']]}
  • Trending: {len(regime['details']['trending_coins'])} coins
  • Choppy: {len(regime['details']['choppy_coins'])} coins

{volatility_emoji[regime['volatility']]} Volatility: {regime['volatility'].upper()} ({regime['details']['avg_volatility']}% avg)

{strategy_emoji[regime['recommended_strategy']]} Recommended Strategy: {regime['recommended_strategy'].upper()} (Confidence: {regime['confidence'] * 100:.0f}%)

📝 Reasoning: {regime['details']['reasoning']}

🎯 STRATEGY ADJUSTMENT SUGGESTIONS:

"""
    
    # 根据市场状态给出具体建议
    if regime['recommended_strategy'] == 'scalping':
        text += """
→ SCALPING MODE ACTIVE:
  • Focus on short-term setups (15m-1H)
  • Tighten stop loss (use ATR×1.0)
  • Quick profit targets (R:R 1:1 acceptable)
  • Increase position turnover
  • Avoid holding overnight
"""
    elif regime['recommended_strategy'] == 'swing':
        text += """
→ SWING MODE ACTIVE:
  • Focus on 4H trend alignment
  • Wider stop loss (use ATR×2.0)
  • Higher profit targets (R:R ≥2:1)
  • Patience for TP
  • Allow multi-day holdings
"""
    else:  # hold
        text += """
→ HOLD MODE ACTIVE:
  • Market conditions not ideal
  • Wait for clearer signals
  • Raise entry thresholds
  • Consider closing marginal positions
  • Preserve capital for better opportunities
"""
    
    return text


# 测试代码
if __name__ == "__main__":
    # 模拟市场数据
    test_data = [
        {
            'symbol': 'BTC/USDT',
            'trend_4h': '多头',
            'mid_term': {'trend': '多头'},
            'trend_15m': '多头',
            'atr': 500,
            'price': 50000,
            'price_change': 2.5
        },
        {
            'symbol': 'ETH/USDT',
            'trend_4h': '多头',
            'mid_term': {'trend': '震荡'},
            'trend_15m': '多头',
            'atr': 50,
            'price': 2500,
            'price_change': 1.8
        },
        {
            'symbol': 'SOL/USDT',
            'trend_4h': '震荡',
            'mid_term': {'trend': '空头'},
            'trend_15m': '空头',
            'atr': 3,
            'price': 100,
            'price_change': -1.2
        }
    ]
    
    regime = analyze_market_regime(test_data)
    print(format_market_regime_for_ai(regime))

