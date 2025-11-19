#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
在服务器端导出真实历史数据到market_snapshots目录
自动生成到最新UTC时间，支持覆盖旧数据
【V7.8增强】支持计算signal_score，用于复盘分析
"""

import os
import sys
import csv
import ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv

# 【V7.8新增】导入signal_score计算函数
# 尝试从主程序导入，如果失败则使用简化版本
try:
    # 添加父目录到路径
    sys.path.insert(0, str(Path(__file__).parent))
    from deepseek_多币种智能版 import calculate_signal_score
    print("✓ 已导入 calculate_signal_score 函数")
except ImportError:
    print("⚠️  无法导入完整函数，使用简化版本")
    # 简化版本：基于趋势和指标估算
    def calculate_signal_score(market_data):
        score = 50
        try:
            # 趋势加分
            trend_4h = market_data.get("trend_4h", "")
            if "多头" in trend_4h or "空头" in trend_4h:
                score += 10
            
            # RSI健康区间
            rsi = market_data.get("rsi", {}).get("rsi_14", 50)
            if 35 < rsi < 65:
                score += 5
            
            # MACD确认
            if market_data.get("macd", {}).get("histogram", 0) > 0:
                score += 5
            
            # 连续K线（通过动能斜率估算）
            momentum = abs(market_data.get("price_action", {}).get("momentum_slope", 0))
            if momentum > 0.005:
                score += 15
            
            # EMA发散（通过价格位置估算）
            ema20 = market_data.get("moving_averages", {}).get("ema20", 0)
            ema50 = market_data.get("moving_averages", {}).get("ema50", 0)
            if ema20 > 0 and ema50 > 0:
                divergence = abs(ema20 - ema50) / ema50 * 100
                if divergence >= 5.0:
                    score += 15
                elif divergence >= 3.0:
                    score += 10
            
            score = min(100, max(0, score))
            return score, 0.30, 2
        except:
            return 50, 0.30, 2

# 加载环境变量
_env_file = Path(__file__).parent / '.env.qwen'
if _env_file.exists():
    load_dotenv(_env_file, override=True)

# 初始化币安交易所（使用公开API，无需密钥）
EXCHANGE_TYPE = os.getenv("EXCHANGE_TYPE", "binance")

if EXCHANGE_TYPE == "binance":
    exchange = ccxt.binance({
        "options": {"defaultType": "future"},
        "enableRateLimit": True,
    })
else:
    exchange = ccxt.okx({
        "options": {"defaultType": "swap"},
        "enableRateLimit": True,
    })

# 币种列表
SYMBOLS = [
    "BTC/USDT:USDT",
    "ETH/USDT:USDT",
    "SOL/USDT:USDT",
    "BNB/USDT:USDT",
    "XRP/USDT:USDT",
    "DOGE/USDT:USDT",
    "LTC/USDT:USDT",
]


# ============================================================
# 【V8.3.21】数据增强辅助函数（方案B）
# ============================================================

def get_kline_context(klines, count=10):
    """
    【V8.3.21 - 盲点1】获取K线序列上下文
    
    让AI看到最近N根K线的统计信息，理解"来龙去脉"
    
    Args:
        klines: K线列表，每个元素是dict {"open": float, "high": float, "low": float, "close": float, "volume": float}
        count: 分析最近几根K线（默认10）
    
    Returns:
        dict: K线上下文信息
    """
    try:
        if not klines or len(klines) < 2:
            return None
        
        # 取最近N根K线
        recent = klines[-min(count, len(klines)):]
        
        highs = [k['high'] for k in recent]
        lows = [k['low'] for k in recent]
        opens = [k['open'] for k in recent]
        closes = [k['close'] for k in recent]
        volumes = [k['volume'] for k in recent]
        
        # 计算K线特征
        bodies = [abs(c - o) for c, o in zip(closes, opens)]
        ranges = [h - l for h, l in zip(highs, lows)]
        
        # 阳线/阴线数量
        bullish = sum(1 for c, o in zip(closes, opens) if c > o)
        bearish = len(recent) - bullish
        
        # 价格变化
        price_change_pct = (closes[-1] - closes[0]) / closes[0] * 100 if closes[0] > 0 else 0
        
        # 趋势判断
        is_trending_up = False
        is_trending_down = False
        if len(closes) >= 5:
            is_trending_up = closes[-1] > closes[0] and closes[-1] > closes[-5]
            is_trending_down = closes[-1] < closes[0] and closes[-1] < closes[-5]
        
        return {
            "count": len(recent),
            "highest_high": max(highs),
            "lowest_low": min(lows),
            "avg_body_size": sum(bodies) / len(bodies) if bodies else 0,
            "avg_range_size": sum(ranges) / len(ranges) if ranges else 0,
            "avg_volume": sum(volumes) / len(volumes) if volumes else 0,
            "bullish_count": bullish,
            "bearish_count": bearish,
            "bullish_ratio": bullish / len(recent) if recent else 0,
            "price_change_pct": round(price_change_pct, 2),
            "is_trending_up": is_trending_up,
            "is_trending_down": is_trending_down,
            "volatility_pct": ((max(highs) - min(lows)) / min(lows) * 100) if min(lows) > 0 else 0
        }
    except Exception as e:
        print(f"⚠️ get_kline_context失败: {e}")
        return None


def analyze_market_structure(klines, timeframe_hours=0.25):
    """
    【V8.3.21 - 盲点2】分析市场结构
    
    识别高低点序列、趋势年龄、位置等结构信息
    
    Args:
        klines: K线列表
        timeframe_hours: 时间框架（小时），15m=0.25, 1h=1.0, 4h=4.0
    
    Returns:
        dict: 市场结构信息
    """
    try:
        if not klines or len(klines) < 10:
            return None
        
        closes = [k['close'] for k in klines]
        highs = [k['high'] for k in klines]
        lows = [k['low'] for k in klines]
        
        # 识别swing高低点（简化版：局部极值）
        swing_highs = []
        swing_lows = []
        
        for i in range(2, len(klines)-2):
            high = highs[i]
            low = lows[i]
            
            # Swing High: 比前后2根都高
            if high >= max(highs[i-1], highs[i-2], highs[i+1], highs[i+2]):
                swing_highs.append((i, high))
            
            # Swing Low: 比前后2根都低
            if low <= min(lows[i-1], lows[i-2], lows[i+1], lows[i+2]):
                swing_lows.append((i, low))
        
        # 判断结构类型
        structure = "unknown"
        trend_strength = "weak"
        
        if len(swing_highs) >= 2 and len(swing_lows) >= 2:
            last_2_highs = [h for _, h in swing_highs[-2:]]
            last_2_lows = [l for _, l in swing_lows[-2:]]
            
            # HH-HL (上升结构)
            if last_2_highs[-1] > last_2_highs[0] and last_2_lows[-1] > last_2_lows[0]:
                structure = "HH-HL"
                trend_strength = "strong_bullish"
            # LL-LH (下降结构)
            elif last_2_highs[-1] < last_2_highs[0] and last_2_lows[-1] < last_2_lows[0]:
                structure = "LL-LH"
                trend_strength = "strong_bearish"
            # 混乱结构
            else:
                structure = "choppy"
                trend_strength = "weak"
        
        # 计算趋势年龄（从最近的swing点开始）
        current_price = closes[-1]
        trend_age_candles = 0
        
        if swing_highs or swing_lows:
            all_swings = [(i, 'high') for i, _ in swing_highs] + [(i, 'low') for i, _ in swing_lows]
            all_swings.sort()
            if all_swings:
                last_swing_idx = all_swings[-1][0]
                trend_age_candles = len(klines) - last_swing_idx - 1
        
        # 计算趋势累计涨跌幅
        if trend_age_candles > 0 and trend_age_candles < len(closes):
            trend_start_price = closes[-(trend_age_candles+1)]
            trend_move_pct = ((current_price - trend_start_price) / trend_start_price * 100) if trend_start_price > 0 else 0
        else:
            trend_move_pct = 0
        
        # 当前价格在区间的位置（0=最低，1=最高）
        recent_high = max(highs[-20:]) if len(highs) >= 20 else max(highs)
        recent_low = min(lows[-20:]) if len(lows) >= 20 else min(lows)
        position_in_range = ((current_price - recent_low) / (recent_high - recent_low)) if (recent_high - recent_low) > 0 else 0.5
        
        # 距离高低点的距离
        distance_from_high = ((recent_high - current_price) / current_price * 100) if current_price > 0 else 0
        distance_from_low = ((current_price - recent_low) / current_price * 100) if current_price > 0 else 0
        
        return {
            "swing_structure": structure,
            "trend_strength": trend_strength,
            "trend_age_candles": trend_age_candles,
            "trend_age_hours": round(trend_age_candles * timeframe_hours, 1),
            "trend_move_pct": round(trend_move_pct, 2),
            "last_swing_high": swing_highs[-1][1] if swing_highs else 0,
            "last_swing_low": swing_lows[-1][1] if swing_lows else 0,
            "position_in_range": round(position_in_range, 2),
            "distance_from_high_pct": round(distance_from_high, 2),
            "distance_from_low_pct": round(distance_from_low, 2)
        }
    except Exception as e:
        print(f"⚠️ analyze_market_structure失败: {e}")
        return None


def analyze_sr_history(klines, sr_price, sr_type='resistance', tolerance_pct=0.5):
    """
    【V8.3.21 - 盲点3】分析支撑/阻力的历史测试情况
    
    识别这个支撑/阻力被测试过几次、反应如何
    
    Args:
        klines: K线列表（建议至少50-100根）
        sr_price: 支撑/阻力价格
        sr_type: 'support' or 'resistance'
        tolerance_pct: 容差百分比（默认0.5%，即价格在±0.5%范围内算"测试"）
    
    Returns:
        dict: S/R历史信息
    """
    try:
        if not klines or not sr_price or sr_price <= 0:
            return None
        
        test_count = 0
        reactions = []  # 记录每次测试后的价格反应
        last_test_ago_candles = None
        false_breakouts = 0
        
        for i, kline in enumerate(klines):
            high = kline['high']
            low = kline['low']
            close = kline['close']
            
            # 判断是否"测试"了S/R
            tested = False
            
            if sr_type == 'resistance':
                # 阻力测试：最高价接近或突破阻力位
                if high >= sr_price * (1 - tolerance_pct/100):
                    tested = True
                    # 记录反应：收盘价相对阻力位的距离
                    reaction_pct = ((close - sr_price) / sr_price * 100)
                    reactions.append(reaction_pct)
                    
                    # 假突破：最高价突破但收盘回落
                    if high > sr_price and close < sr_price:
                        false_breakouts += 1
            
            elif sr_type == 'support':
                # 支撑测试：最低价接近或跌破支撑位
                if low <= sr_price * (1 + tolerance_pct/100):
                    tested = True
                    # 记录反应：收盘价相对支撑位的距离
                    reaction_pct = ((close - sr_price) / sr_price * 100)
                    reactions.append(reaction_pct)
                    
                    # 假跌破：最低价跌破但收盘反弹
                    if low < sr_price and close > sr_price:
                        false_breakouts += 1
            
            if tested:
                test_count += 1
                last_test_ago_candles = len(klines) - i - 1
        
        if test_count == 0:
            return None
        
        # 计算平均/最大反应
        if sr_type == 'resistance':
            avg_reaction = sum(reactions) / len(reactions) if reactions else 0
            max_rejection = min(reactions) if reactions else 0  # 最大回调（负数）
            description = f"被测试{test_count}次"
            if false_breakouts > 0:
                description += f"，{false_breakouts}次假突破"
        else:  # support
            avg_reaction = sum(reactions) / len(reactions) if reactions else 0
            max_bounce = max(reactions) if reactions else 0  # 最大反弹（正数）
            description = f"被测试{test_count}次"
            if false_breakouts > 0:
                description += f"，{false_breakouts}次假跌破"
        
        return {
            "test_count": test_count,
            "last_test_ago_candles": last_test_ago_candles if last_test_ago_candles is not None else 999,
            "avg_reaction_pct": round(avg_reaction, 2),
            "max_rejection_pct": round(max_rejection, 2) if sr_type == 'resistance' else round(max_bounce, 2),
            "false_breakouts": false_breakouts,
            "description": description
        }
    except Exception as e:
        print(f"⚠️ analyze_sr_history失败: {e}")
        return None

def calculate_rsi(series, period=14):
    """计算RSI"""
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_macd(series, fast=12, slow=26, signal=9):
    """计算MACD"""
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    macd_signal = macd_line.ewm(span=signal, adjust=False).mean()
    macd_histogram = macd_line - macd_signal
    return macd_line, macd_signal, macd_histogram

def calculate_atr(high, low, close, period=14):
    """计算ATR"""
    high_low = high - low
    high_close = np.abs(high - close.shift())
    low_close = np.abs(low - close.shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    return true_range.rolling(period).mean()

def determine_trend(close, short=20, long=50):
    """判断趋势"""
    ema_short = close.ewm(span=short, adjust=False).mean()
    ema_long = close.ewm(span=long, adjust=False).mean()
    
    conditions = [
        (ema_short > ema_long * 1.005, "多头"),
        (ema_short < ema_long * 0.995, "空头"),
        (ema_short >= ema_long, "多头转弱"),
        (ema_short < ema_long, "空头转弱")
    ]
    
    trend = ["震荡"] * len(close)
    for i in range(len(close)):
        if i >= long:
            for condition, label in conditions:
                if isinstance(condition, tuple):
                    if condition[0].iloc[i]:
                        trend[i] = condition[1]
                        break
                else:
                    if condition.iloc[i]:
                        trend[i] = label
                        break
    
    return trend

def fetch_data_for_date(symbol, date_str):
    """获取指定日期的数据"""
    target_date = datetime.strptime(date_str, '%Y%m%d')
    start_ts = int(target_date.timestamp() * 1000)
    end_ts = int((target_date + timedelta(days=1)).timestamp() * 1000)
    
    print(f"  正在获取 {symbol} 的 {date_str} 数据...")
    
    try:
        # 获取15分钟K线，需要提前获取一些用于计算指标
        since = start_ts - (7 * 24 * 60 * 60 * 1000)  # 提前7天
        
        candles = exchange.fetch_ohlcv(
            symbol,
            timeframe='15m',
            since=since,
            limit=1500
        )
        
        if not candles:
            return None
        
        df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # 计算指标
        df['rsi_14'] = calculate_rsi(df['close'], 14)
        df['rsi_7'] = calculate_rsi(df['close'], 7)
        df['macd_line'], df['macd_signal'], df['macd_histogram'] = calculate_macd(df['close'])
        df['atr'] = calculate_atr(df['high'], df['low'], df['close'], 14)
        df['support'] = df['low'].rolling(window=20).min()
        df['resistance'] = df['high'].rolling(window=20).max()
        df['trend_15m'] = determine_trend(df['close'], 20, 50)
        df['trend_4h'] = determine_trend(df['close'], 50, 100)
        df['trend_1h'] = determine_trend(df['close'], 30, 60)
        df['ema20_1h'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema50_1h'] = df['close'].ewm(span=50, adjust=False).mean()
        df['macd_1h_line'], df['macd_1h_signal'], df['macd_1h_histogram'] = calculate_macd(df['close'], 48, 104, 36)
        df['atr_1h'] = calculate_atr(df['high'], df['low'], df['close'], 56)
        
        # 过滤目标日期（保留原始索引，用于后续访问历史数据）
        day_df = df[(df['timestamp'] >= start_ts) & (df['timestamp'] < end_ts)].copy()
        
        # 【V8.3.21.1修复】记录当天数据在原始df中的索引范围
        if len(day_df) > 0:
            day_start_idx = df.index[df['timestamp'] >= start_ts].min()
        else:
            day_start_idx = 0
        
        print(f"    获取到 {len(day_df)} 条记录（原始df索引: {day_start_idx}-{day_start_idx+len(day_df)-1}）")
        return df, day_df, day_start_idx  # 返回完整df、当天df、起始索引
        
    except Exception as e:
        print(f"    ✗ 获取失败: {e}")
        return None

def export_date(date_str, output_dirs):
    """导出指定日期的CSV到多个目录"""
    print(f"\n{'='*60}")
    print(f"导出 {date_str} 的数据")
    print(f"{'='*60}")
    
    all_rows = []
    
    for symbol in SYMBOLS:
        coin_name = symbol.split('/')[0]
        fetch_result = fetch_data_for_date(symbol, date_str)
        
        if fetch_result is None:
            continue
        
        # 【V8.3.21.1修复】解包返回值
        full_df, day_df, day_start_idx = fetch_result
        
        if day_df is None or len(day_df) == 0:
            continue
        
        for position, row in enumerate(day_df.itertuples(index=False)):
            time_str = datetime.fromtimestamp(row.timestamp / 1000).strftime('%H%M')
            
            # 【V8.2.3】增强market_data构造 - 基于历史数据判断各种形态
            ema20 = row.ema20_1h if pd.notna(row.ema20_1h) else row.close
            ema50 = row.ema50_1h if pd.notna(row.ema50_1h) else row.close
            
            # 【V8.3.21.1修复】计算前一根K线数据（使用原始df的索引）
            actual_position = day_start_idx + position  # 在原始df中的实际位置
            prev_position = max(0, actual_position - 1)
            prev_row = full_df.iloc[prev_position] if prev_position < actual_position else row
            
            # 【增强1】成交量激增判断
            volume_surge_data = None
            if actual_position >= 20:  # 需要足够的历史数据
                recent_volume = full_df.iloc[max(0, actual_position-20):actual_position]['volume'].mean()
                if recent_volume > 0:
                    surge_ratio = row.volume / recent_volume
                    if surge_ratio > 2.0:  # 2倍平均量
                        volume_surge_data = {
                            "type": "extreme_surge",  # ✅ 修复：匹配函数期望值
                            "ratio": surge_ratio  # ✅ V8.2.3.4：字段名改为ratio
                        }
                    elif surge_ratio > 1.5:  # 1.5倍平均量
                        volume_surge_data = {
                            "type": "strong_surge",  # ✅ 修复：添加_surge后缀
                            "ratio": surge_ratio  # ✅ V8.2.3.4：字段名改为ratio
                        }
            
            # 【增强2】突破判断
            breakout_data = None
            resistance = row.resistance if pd.notna(row.resistance) else 0
            support = row.support if pd.notna(row.support) else 0
            # V8.2.3.5：放宽突破条件从0.2%到0.1%（更适合15分钟K线）
            if resistance > 0 and row.close > resistance * 1.001:  # 突破阻力0.1%
                breakout_data = {
                    "level": resistance,
                    "type": "resistance",
                    "strength": (row.close - resistance) / resistance
                }
            elif support > 0 and row.close < support * 0.999:  # 突破支撑0.1%
                breakout_data = {
                    "level": support,
                    "type": "support",
                    "strength": (support - row.close) / support
                }
            
            # 【增强3】趋势启动判断
            trend_initiation_data = None
            if actual_position >= 10:
                # V8.2.3.5：调整趋势启动逻辑，适应实际trend_15m字段值
                # 实际值：多头、空头、多头转弱、空头转弱（没有"震荡"）
                prev_trends = [full_df.iloc[i]['trend_15m'] for i in range(max(0, actual_position-10), actual_position)]
                
                # 方案1：从"转弱"转为"强势"（趋势启动）
                weak_count = sum(1 for t in prev_trends if '转弱' in str(t))
                current_is_strong = ('多头' == str(row.trend_15m) or '空头' == str(row.trend_15m))
                
                if weak_count >= 5 and current_is_strong:  # 过去10根中至少5根转弱，现在转强
                    trend_initiation_data = {
                        "from_sideways": True,  # 保持字段名兼容性
                        "new_trend": row.trend_15m,
                        "strength": "strong"
                    }
                # 方案2：从震荡转趋势（如果有"震荡"字段）
                elif any('震荡' in str(t) for t in prev_trends):
                    sideways_count = sum(1 for t in prev_trends if '震荡' in str(t))
                    if sideways_count >= 7 and '头' in str(row.trend_15m):
                        trend_initiation_data = {
                            "from_sideways": True,
                            "new_trend": row.trend_15m,
                            "strength": "strong"
                        }
            
            # 【增强4】连续K线判断
            consecutive_data = None
            if actual_position >= 4:
                recent_candles = full_df.iloc[max(0, actual_position-3):actual_position+1]
                all_bullish = all((c['close'] > c['open']) for _, c in recent_candles.iterrows())
                all_bearish = all((c['close'] < c['open']) for _, c in recent_candles.iterrows())
                if all_bullish or all_bearish:
                    consecutive_data = {
                        "candles": len(recent_candles),
                        "direction": "bullish" if all_bullish else "bearish"
                    }
            
            # 【增强5】Pin Bar判断
            pin_bar_data = None
            body = abs(row.close - row.open)
            total_range = row.high - row.low
            if total_range > 0:
                upper_wick = row.high - max(row.close, row.open)
                lower_wick = min(row.close, row.open) - row.low
                if upper_wick > body * 2 and lower_wick < body * 0.5:  # 上影线长
                    pin_bar_data = "bearish_pin"  # ✅ 修复：添加_pin后缀
                elif lower_wick > body * 2 and upper_wick < body * 0.5:  # 下影线长
                    pin_bar_data = "bullish_pin"  # ✅ 修复：添加_pin后缀
            
            # 【增强6】吞没形态判断
            engulfing_data = None
            if actual_position > 0:
                prev_body = abs(prev_row['close'] - prev_row['open'])
                curr_body = abs(row.close - row.open)
                if curr_body > prev_body * 1.5:  # 当前K线实体明显大于前一根
                    if row.close > row.open and prev_row['close'] < prev_row['open']:
                        engulfing_data = "bullish_engulfing"  # ✅ 修复：添加_engulfing后缀
                    elif row.close < row.open and prev_row['close'] > prev_row['open']:
                        engulfing_data = "bearish_engulfing"  # ✅ 修复：添加_engulfing后缀
            
            market_data_for_score = {
                "price": row.close,  # ← 【修复】添加price字段
                "current_price": row.close,  # ← 【V8.2.3.4】添加current_price字段
                "price_action": {
                    "consecutive": consecutive_data,
                    "momentum_slope": (row.close - row.open) / row.open if row.open > 0 else 0,
                    "trend_exhaustion": None,  # 趋势衰竭需要更复杂的逻辑
                    "pin_bar": pin_bar_data,
                    "engulfing": engulfing_data,
                    "breakout": breakout_data,
                    "volume_surge": volume_surge_data,
                    "pullback_type": {"type": "simple_pullback"} if abs(row.close - row.open) / row.open > 0.002 else None,
                    "trend_initiation": trend_initiation_data,
                },
                "volume_analysis": volume_surge_data if volume_surge_data else {},  # ← 【V8.2.3.4】添加volume_analysis
                "ytc_signal": {},  # ← 【V8.2.3.4】添加ytc_signal占位符
                "mid_term": {},  # ← 【V8.2.3.4】添加mid_term占位符
                "long_term": {
                    "trend": row.trend_4h
                },
                "moving_averages": {
                    "ema20": ema20,
                    "ema50": ema50,
                },
                "rsi": {
                    "rsi_14": row.rsi_14 if pd.notna(row.rsi_14) else 50,
                    "rsi_7": row.rsi_7 if pd.notna(row.rsi_7) else 50,
                },
                "macd": {
                    "histogram": row.macd_histogram if pd.notna(row.macd_histogram) else 0,
                    "macd_line": row.macd_line if pd.notna(row.macd_line) else 0,
                    "signal": row.macd_signal if pd.notna(row.macd_signal) else 0,
                },
                "support_resistance": {
                    "position_status": "neutral",
                    "nearest_resistance": {
                        "price": resistance if resistance > 0 else row.close * 1.02,
                        "strength": 0.5
                    },
                    "nearest_support": {
                        "price": support if support > 0 else row.close * 0.98,
                        "strength": 0.5
                    },
                },
                "atr": row.atr if pd.notna(row.atr) and row.atr > 0 else row.close * 0.02,
                "volume": row.volume,
                "trend_4h": row.trend_4h,
                "trend_1h": row.trend_1h,
                "trend_15m": row.trend_15m,
            }
            
            # 【V8.5.2.3】只保存原始维度数据（不计算total_score）
            # 核心改进：避免预判分类错误，实时/回测时动态计算评分
            try:
                # 计算原始维度值
                momentum = abs((row.close - row.open) / row.open) if row.open > 0 else 0
                vol_ratio = 0
                if actual_position >= 20:
                    recent_avg_vol = full_df.iloc[max(0, actual_position-20):actual_position]['volume'].mean()
                    if recent_avg_vol > 0:
                        vol_ratio = row.volume / recent_avg_vol
                
                # 趋势对齐统计
                trends = [row.trend_4h, row.trend_1h, row.trend_15m]
                bull_count = sum(1 for t in trends if pd.notna(t) and '多头' in str(t))
                bear_count = sum(1 for t in trends if pd.notna(t) and '空头' in str(t))
                aligned_count = max(bull_count, bear_count)
                
                # EMA发散度
                ema_divergence_pct = round(abs(ema20 - ema50) / ema50 * 100, 2) if (ema20 > 0 and ema50 > 0) else 0
                
                # 构建原始维度字典（不包含total_score和signal_type）
                components = {
                    # ❌ 不保存预判的类型和总分
                    # 'signal_type': '...',
                    # 'total_score': 0,
                    
                    # ✅ 只保存原始维度（客观事实）
                    'momentum_value': round(momentum, 4),
                    'volume_ratio': round(vol_ratio, 2),
                    'has_breakout': bool(breakout_data),
                    'has_pin_bar': bool(pin_bar_data),
                    'has_engulfing': bool(engulfing_data),
                    'consecutive_candles': consecutive_data.get('candles', 0) if consecutive_data else 0,
                    'trend_alignment_count': aligned_count,
                    'ema_divergence_pct': ema_divergence_pct,
                    'trend_initiation_strength': trend_initiation_data.get('strength', '') if trend_initiation_data else '',
                    
                    # 保留这些字段用于兼容性（但实时计算时会用原始维度重新计算）
                    'volume_surge_type': 'extreme' if vol_ratio > 2.0 else ('strong' if vol_ratio > 1.5 else ''),
                    'pin_bar': pin_bar_data if pin_bar_data else '',
                    'engulfing': engulfing_data if engulfing_data else '',
                    'trend_4h_strength': 'strong' if ("强势" in str(row.trend_4h)) else ('normal' if ("多头" in str(row.trend_4h) or "空头" in str(row.trend_4h)) else 'weak'),
                    'pullback_type': '',
                    'volume_confirmed': vol_ratio >= 1.2,
                }
                
            except Exception as e:
                print(f"⚠️ 【V8.5.2.3】提取原始维度失败: {e}")
                import traceback
                traceback.print_exc()
                components = {
                    'momentum_value': 0,
                    'volume_ratio': 0,
                    'has_breakout': False,
                    'has_pin_bar': False,
                    'has_engulfing': False,
                    'consecutive_candles': 0,
                    'trend_alignment_count': 0,
                    'ema_divergence_pct': 0,
                    'trend_initiation_strength': '',
                    'volume_surge_type': '',
                    'pin_bar': '',
                    'engulfing': '',
                    'trend_4h_strength': '',
                    'pullback_type': '',
                    'volume_confirmed': False,
                }
            
            # 【V8.4】计算综合确认度评分（0-100分）
            # 从简单计数器升级为加权评分，包含指标、趋势、形态三大维度
            consensus_score = 0
            
            # === 第1层：指标确认（40分） ===
            # 1. EMA发散（10分）
            if ema20 > 0 and ema50 > 0:
                divergence = abs(ema20 - ema50) / ema50 * 100
                if divergence >= 5.0:
                    consensus_score += 10  # 强发散
                elif divergence >= 2.0:
                    consensus_score += 5   # 中发散
            
            # 2. MACD强度（10分）
            macd_hist = row.macd_histogram if pd.notna(row.macd_histogram) else 0
            if abs(macd_hist) >= 0.05:
                consensus_score += 10  # 强信号
            elif abs(macd_hist) >= 0.01:
                consensus_score += 5   # 中信号
            
            # 3. RSI极端值（10分）
            rsi_14 = row.rsi_14 if pd.notna(row.rsi_14) else 50
            if rsi_14 > 75 or rsi_14 < 25:
                consensus_score += 10  # 超强极端
            elif rsi_14 > 70 or rsi_14 < 30:
                consensus_score += 7   # 强极端
            elif 45 <= rsi_14 <= 55:
                consensus_score += 3   # 中性（轻微加分）
            
            # 4. 成交量放量（10分）
            if actual_position >= 20:
                recent_avg_vol = full_df.iloc[max(0, actual_position-20):actual_position]['volume'].mean()
                if recent_avg_vol > 0:
                    vol_ratio = row.volume / recent_avg_vol
                    if vol_ratio >= 2.0:
                        consensus_score += 10  # 强放量
                    elif vol_ratio >= 1.5:
                        consensus_score += 5   # 中放量
            
            # === 第2层：趋势确认（30分） ===
            # 5. 多周期趋势一致性（30分）
            is_all_bullish = ("多头" in str(row.trend_15m) and "多头" in str(row.trend_1h) and "多头" in str(row.trend_4h))
            is_all_bearish = ("空头" in str(row.trend_15m) and "空头" in str(row.trend_1h) and "空头" in str(row.trend_4h))
            
            if is_all_bullish or is_all_bearish:
                consensus_score += 30  # 三层对齐
            elif ("多头" in str(row.trend_1h) and "多头" in str(row.trend_4h)) or \
                 ("空头" in str(row.trend_1h) and "空头" in str(row.trend_4h)):
                consensus_score += 15  # 两层对齐
            
            # === 第3层：形态确认（30分） ===
            # 6. 价格形态强度（15分）- 从components中提取
            pattern_score = 0
            if components.get('pin_bar_score', 0) > 0:
                pattern_score += min(5, components['pin_bar_score'] / 2)  # Pin Bar最多5分
            if components.get('engulfing_score', 0) > 0:
                pattern_score += min(5, components['engulfing_score'] / 2)  # 吞没最多5分
            if components.get('breakout_score', 0) > 0:
                pattern_score += min(5, components['breakout_score'] / 5)  # 突破最多5分
            consensus_score += int(pattern_score)
            
            # 7. K线序列一致性（10分）
            if actual_position >= 3:
                recent_closes = full_df.iloc[actual_position-3:actual_position+1]['close'].values
                if len(recent_closes) >= 3:
                    # 检查最近3根K线的方向一致性
                    is_bullish_seq = all(recent_closes[i] < recent_closes[i+1] for i in range(len(recent_closes)-1))
                    is_bearish_seq = all(recent_closes[i] > recent_closes[i+1] for i in range(len(recent_closes)-1))
                    if is_bullish_seq or is_bearish_seq:
                        consensus_score += 10  # 强一致
                    elif (recent_closes[-1] > recent_closes[-2]) or (recent_closes[-1] < recent_closes[-2]):
                        consensus_score += 5   # 弱一致
            
            # 8. 支撑阻力明确性（5分）
            support = row.support if pd.notna(row.support) else 0
            resistance = row.resistance if pd.notna(row.resistance) else 0
            if support > 0 and resistance > 0:
                sr_gap = abs(resistance - support) / row.close * 100
                if sr_gap >= 3.0:
                    consensus_score += 5  # 支撑阻力明确
                elif sr_gap >= 1.5:
                    consensus_score += 3  # 支撑阻力较明确
            
            # 限制在0-100范围
            consensus_score = min(100, max(0, consensus_score))
            
            # 【兼容性】保留旧的indicator_consensus字段（简化版，用于向后兼容）
            # 只计算最核心的5个指标
            indicator_consensus = 0
            if ema20 > 0 and ema50 > 0 and abs(ema20 - ema50) / ema50 * 100 >= 2.0:
                indicator_consensus += 1
            if abs(macd_hist) >= 0.01:
                indicator_consensus += 1
            if rsi_14 > 70 or rsi_14 < 30 or (45 <= rsi_14 <= 55):
                indicator_consensus += 1
            if actual_position >= 20:
                recent_avg_vol = full_df.iloc[max(0, actual_position-20):actual_position]['volume'].mean()
                if recent_avg_vol > 0 and row.volume >= recent_avg_vol * 1.5:
                    indicator_consensus += 1
            if is_all_bullish or is_all_bearish:
                indicator_consensus += 1
            
            # 【V8.3.20】增强版R:R计算 - 基于趋势强度动态调整
            atr = row.atr if pd.notna(row.atr) and row.atr > 0 else 0
            price = row.close
            resistance = row.resistance if pd.notna(row.resistance) else price * 1.02
            support = row.support if pd.notna(row.support) else price * 0.98
            
            if atr > 0:
                # 止损距离：2倍ATR（与系统默认一致）
                stop_distance = atr * 2.0
                
                # 【关键修复】基于趋势强度动态调整止盈目标
                # 1. 判断趋势强度
                is_strong_trend = (
                    ("多头" in str(row.trend_15m) and "多头" in str(row.trend_1h) and "多头" in str(row.trend_4h)) or
                    ("空头" in str(row.trend_15m) and "空头" in str(row.trend_1h) and "空头" in str(row.trend_4h))
                )
                is_medium_trend = "多头" in str(row.trend_15m) or "空头" in str(row.trend_15m)
                
                # 2. 动态目标倍数
                if is_strong_trend:
                    target_multiplier = 6.0  # 强趋势：三框架一致
                elif is_medium_trend:
                    target_multiplier = 4.5  # 中等趋势：15m趋势明确
                else:
                    target_multiplier = 3.0  # 弱趋势/震荡
                
                # 3. 考虑成交量激增（进一步提高预期）
                if actual_position >= 20:
                    recent_vol = full_df.iloc[max(0, actual_position-20):actual_position]['volume'].mean()
                    if recent_vol > 0 and row.volume > recent_vol * 2.0:
                        target_multiplier *= 1.3  # 巨量额外加30%
                
                # 4. 考虑指标共振
                if indicator_consensus >= 4:
                    target_multiplier *= 1.2  # 强共振额外加20%
                
                # 5. 计算目标距离
                target_distance = atr * target_multiplier
                
                # 计算盈亏比
                risk_reward = round(target_distance / stop_distance, 2) if stop_distance > 0 else 0
            else:
                risk_reward = 0
            
            # 【V8.3.20】成交量确认（用于swing模式）
            if actual_position >= 20:
                recent_avg_vol = full_df.iloc[max(0, actual_position-20):actual_position]['volume'].mean()
                if recent_avg_vol > 0 and row.volume >= recent_avg_vol * 1.5:
                    pass  # 已在indicator_consensus中计算
            
            # 【V8.3.21】数据增强：调用新函数获取上下文数据
            kline_context_15m = None
            market_structure_15m = None
            resistance_history = None
            support_history = None
            
            # 【V8.3.21.1修复】构建标准K线格式（使用原始df的索引）
            if actual_position >= 10:  # 确保有足够的历史数据
                standard_klines = []
                start_pos = max(0, actual_position - 100)  # 取最近100根K线（用于S/R历史分析）
                for i in range(start_pos, actual_position + 1):
                    candle = full_df.iloc[i]
                    standard_klines.append({
                        'open': candle['open'],
                        'high': candle['high'],
                        'low': candle['low'],
                        'close': candle['close'],
                        'volume': candle['volume']
                    })
                
                # 调用三个数据增强函数
                if len(standard_klines) >= 10:
                    kline_context_15m = get_kline_context(standard_klines, count=10)
                if len(standard_klines) >= 20:
                    market_structure_15m = analyze_market_structure(standard_klines, timeframe_hours=0.25)
                if len(standard_klines) >= 50 and resistance > 0:
                    resistance_history = analyze_sr_history(standard_klines, resistance, sr_type='resistance')
                if len(standard_klines) >= 50 and support > 0:
                    support_history = analyze_sr_history(standard_klines, support, sr_type='support')
            
            csv_row = {
                'time': time_str,
                'coin': coin_name,
                'open': round(row.open, 8),
                'high': round(row.high, 8),
                'low': round(row.low, 8),
                'close': round(row.close, 8),
                'volume': round(row.volume, 3),
                'price': round(row.close, 8),
                'trend_4h': row.trend_4h,
                'trend_1h': row.trend_1h,  # 【V8.5.2.4.40】添加trend_1h（consensus计算需要）
                'trend_15m': row.trend_15m,
                'ema20_1h': round(row.ema20_1h, 8) if pd.notna(row.ema20_1h) else row.close,  # 【V8.5.2.4.40】添加EMA（consensus计算需要）
                'ema50_1h': round(row.ema50_1h, 8) if pd.notna(row.ema50_1h) else row.close,  # 【V8.5.2.4.40】添加EMA（consensus计算需要）
                'rsi_14': round(row.rsi_14, 8) if pd.notna(row.rsi_14) else 50,
                'rsi_7': round(row.rsi_7, 8) if pd.notna(row.rsi_7) else 50,
                'macd_line': round(row.macd_line, 8) if pd.notna(row.macd_line) else 0,
                'macd_signal': round(row.macd_signal, 8) if pd.notna(row.macd_signal) else 0,
                'macd_histogram': round(row.macd_histogram, 8) if pd.notna(row.macd_histogram) else 0,
                'atr': round(row.atr, 8) if pd.notna(row.atr) else 0,
                'support': round(row.support, 8) if pd.notna(row.support) else row.low,
                'resistance': round(row.resistance, 8) if pd.notna(row.resistance) else row.high,
                'indicator_consensus': indicator_consensus,  # 【兼容性】保留旧字段（0-5）
                'consensus_score': consensus_score,  # 【V8.4新增】综合确认度评分（0-100）
                
                # 【V8.2】信号评分维度（保存各个维度，不保存总分）
                'signal_type': components.get('signal_type', 'swing'),
                # 超短线维度
                'volume_surge_type': components.get('volume_surge_type', ''),
                'volume_surge_score': components.get('volume_surge_score', 0),
                'has_breakout': components.get('has_breakout', False),
                'breakout_score': components.get('breakout_score', 0),
                'momentum_value': components.get('momentum_value', 0),
                'momentum_score': components.get('momentum_score', 0),
                'scalp_consecutive_candles': components.get('consecutive_candles', 0) if components.get('signal_type') == 'scalping' else 0,
                'scalp_consecutive_score': components.get('consecutive_score', 0) if components.get('signal_type') == 'scalping' else 0,
                'pin_bar_detected': components.get('pin_bar', ''),
                'pin_bar_score': components.get('pin_bar_score', 0),
                'engulfing_detected': components.get('engulfing', ''),
                'engulfing_score': components.get('engulfing_score', 0),
                # 波段维度
                'trend_initiation_strength': components.get('trend_initiation_strength', ''),
                'trend_initiation_score': components.get('trend_initiation_score', 0),
                'trend_alignment_count': components.get('trend_alignment', 0),
                'trend_alignment_score': components.get('trend_alignment_score', 0),
                'trend_4h_strength': components.get('trend_4h_strength', ''),
                'trend_4h_strength_score': components.get('trend_4h_strength_score', 0),
                'ema_divergence_pct': components.get('ema_divergence_pct', 0),
                'ema_divergence_score': components.get('ema_divergence_score', 0),
                'swing_pullback_type': components.get('pullback_type', ''),
                'swing_pullback_score': components.get('pullback_score', 0),
                'swing_consecutive_candles': components.get('consecutive_candles', 0) if components.get('signal_type') == 'swing' else 0,
                'swing_consecutive_score': components.get('consecutive_score', 0) if components.get('signal_type') == 'swing' else 0,
                'volume_confirmed': components.get('volume_confirmed', False),
                'volume_confirmed_score': components.get('volume_confirmed_score', 0),
                # ❌ 不再保存signal_score（回测时动态计算）
                
                'risk_reward': risk_reward,  # 【V7.8关键修复】盈亏比
                'trend_1h': row.trend_1h,
                'ema20_1h': round(row.ema20_1h, 8) if pd.notna(row.ema20_1h) else row.close,
                'ema50_1h': round(row.ema50_1h, 8) if pd.notna(row.ema50_1h) else row.close,
                'macd_1h_line': round(row.macd_1h_line, 8) if pd.notna(row.macd_1h_line) else 0,
                'macd_1h_signal': round(row.macd_1h_signal, 8) if pd.notna(row.macd_1h_signal) else 0,
                'macd_1h_histogram': round(row.macd_1h_histogram, 8) if pd.notna(row.macd_1h_histogram) else 0,
                'atr_1h': round(row.atr_1h, 8) if pd.notna(row.atr_1h) else 0,
                'resistance_1h': round(row.resistance, 8) if pd.notna(row.resistance) else row.high,
                'resistance_1h_strength': 5,
                'support_1h': round(row.support, 8) if pd.notna(row.support) else row.low,
                'support_1h_strength': 5,
                'pin_bar': '',
                'engulfing': '',
                'pullback_type': 'simple_pullback' if abs(row.close - row.open) / row.open > 0.002 else '',
                'pullback_depth': round(abs(row.high - row.low) / row.open, 8),
                
                # === 【V8.3.19.2】信号评分维度（用于信号类型识别）===
                'volume_surge_type': components.get('volume_surge_type', ''),
                'volume_surge_score': components.get('volume_surge_score', 0),
                'has_breakout': components.get('has_breakout', False),
                'breakout_score': components.get('breakout_score', 0),
                
                'momentum_slope': round((row.close - row.open) / row.open, 8),
                'pullback_weakness_score': 0.4,
                'lwp_long': round(row.support, 8) if pd.notna(row.support) else row.low,
                'lwp_short': round(row.resistance, 8) if pd.notna(row.resistance) else row.high,
                'lwp_confidence': 'high',
                'ytc_signal_type': 'TST' if row.trend_15m in ['多头', '空头'] else 'NONE',
                'ytc_direction': 'SHORT' if row.trend_15m == '空头' else 'LONG' if row.trend_15m == '多头' else '',
                'ytc_strength': 5 if row.trend_15m in ['多头', '空头'] else 0,
                'ytc_sr_strength': 5,
                'ytc_entry_price': round(row.close, 8),
                'ytc_rationale': f"弱势测试强{'阻力' if row.trend_15m == '空头' else '支撑'}{round(row.resistance if row.trend_15m == '空头' else row.support, 2)}+动能停滞，Fading测试者" if row.trend_15m in ['多头', '空头'] else '',
                'support_strength': 5,
                'support_polarity_switched': 'True',
                'support_fast_rejection': 'True',
                'resistance_strength': 5,
                'resistance_polarity_switched': 'True',
                'resistance_fast_rejection': 'True',
                
                # === 【V8.3.21】数据增强字段（方案B）===
                # 盲点1：K线序列上下文（15m）
                'kline_ctx_count': kline_context_15m.get("count", 0) if kline_context_15m else 0,
                'kline_ctx_highest': kline_context_15m.get("highest_high", 0) if kline_context_15m else 0,
                'kline_ctx_lowest': kline_context_15m.get("lowest_low", 0) if kline_context_15m else 0,
                'kline_ctx_avg_body': kline_context_15m.get("avg_body_size", 0) if kline_context_15m else 0,
                'kline_ctx_avg_range': kline_context_15m.get("avg_range_size", 0) if kline_context_15m else 0,
                'kline_ctx_bullish_cnt': kline_context_15m.get("bullish_count", 0) if kline_context_15m else 0,
                'kline_ctx_bearish_cnt': kline_context_15m.get("bearish_count", 0) if kline_context_15m else 0,
                'kline_ctx_bullish_ratio': kline_context_15m.get("bullish_ratio", 0) if kline_context_15m else 0,
                'kline_ctx_price_chg_pct': kline_context_15m.get("price_change_pct", 0) if kline_context_15m else 0,
                'kline_ctx_is_up': kline_context_15m.get("is_trending_up", False) if kline_context_15m else False,
                'kline_ctx_is_down': kline_context_15m.get("is_trending_down", False) if kline_context_15m else False,
                'kline_ctx_volatility': kline_context_15m.get("volatility_pct", 0) if kline_context_15m else 0,
                
                # 盲点2：市场结构（15m）
                'mkt_struct_swing': market_structure_15m.get("swing_structure", "") if market_structure_15m else "",
                'mkt_struct_trend_strength': market_structure_15m.get("trend_strength", "") if market_structure_15m else "",
                'mkt_struct_age_candles': market_structure_15m.get("trend_age_candles", 0) if market_structure_15m else 0,
                'mkt_struct_age_hours': market_structure_15m.get("trend_age_hours", 0) if market_structure_15m else 0,
                'mkt_struct_move_pct': market_structure_15m.get("trend_move_pct", 0) if market_structure_15m else 0,
                'mkt_struct_last_high': market_structure_15m.get("last_swing_high", 0) if market_structure_15m else 0,
                'mkt_struct_last_low': market_structure_15m.get("last_swing_low", 0) if market_structure_15m else 0,
                'mkt_struct_pos_in_range': market_structure_15m.get("position_in_range", 0) if market_structure_15m else 0,
                'mkt_struct_dist_high_pct': market_structure_15m.get("distance_from_high_pct", 0) if market_structure_15m else 0,
                'mkt_struct_dist_low_pct': market_structure_15m.get("distance_from_low_pct", 0) if market_structure_15m else 0,
                
                # 盲点3：阻力历史
                'resist_hist_test_cnt': resistance_history.get("test_count", 0) if resistance_history else 0,
                'resist_hist_last_test_ago': resistance_history.get("last_test_ago_candles", 999) if resistance_history else 999,
                'resist_hist_avg_reaction': resistance_history.get("avg_reaction_pct", 0) if resistance_history else 0,
                'resist_hist_max_rejection': resistance_history.get("max_rejection_pct", 0) if resistance_history else 0,
                'resist_hist_false_bo': resistance_history.get("false_breakouts", 0) if resistance_history else 0,
                'resist_hist_desc': resistance_history.get("description", "") if resistance_history else "",
                
                # 盲点3：支撑历史
                'support_hist_test_cnt': support_history.get("test_count", 0) if support_history else 0,
                'support_hist_last_test_ago': support_history.get("last_test_ago_candles", 999) if support_history else 999,
                'support_hist_avg_reaction': support_history.get("avg_reaction_pct", 0) if support_history else 0,
                'support_hist_max_bounce': support_history.get("max_rejection_pct", 0) if support_history else 0,
                'support_hist_false_bd': support_history.get("false_breakouts", 0) if support_history else 0,
                'support_hist_desc': support_history.get("description", "") if support_history else "",
            }
            
            all_rows.append(csv_row)
    
    if len(all_rows) == 0:
        print(f"✗ {date_str} 没有数据")
        return
    
    # 排序
    all_rows.sort(key=lambda x: (x['time'], x['coin']))
    
    # 写入文件到多个目录
    fieldnames = list(all_rows[0].keys())
    filename = f"{date_str}.csv"  # 直接使用日期作为文件名
    
    for output_dir in output_dirs:
        output_file = output_dir / filename
        
        # 如果文件存在，先备份
        if output_file.exists():
            backup_file = output_dir / f"{date_str}_backup.csv"
            print(f"  ⚠️ 文件已存在，备份为: {backup_file.name}")
            output_file.rename(backup_file)
        
        with open(output_file, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_rows)
        
        print(f"  ✓ 已写入: {output_file} ({len(all_rows)} 条记录)")
    
    print(f"✓ {date_str} 导出完成")

def main():
    """主函数"""
    # 获取当前UTC时间
    now_utc = datetime.now(timezone.utc)
    today_str = now_utc.strftime('%Y%m%d')
    
    # 解析命令行参数
    if len(sys.argv) < 2:
        print("用法: python3 export_historical_data.py START_DATE [END_DATE]")
        print("示例: python3 export_historical_data.py 20251025")
        print("示例: python3 export_historical_data.py 20251025 20251102")
        print(f"\n如果不指定END_DATE，将自动生成到今天 ({today_str})")
        sys.exit(1)
    
    start_date = sys.argv[1]
    # 如果没有指定结束日期，使用今天
    end_date = sys.argv[2] if len(sys.argv) >= 3 else today_str
    
    # 输出目录（两个目录）
    base_dir = Path(__file__).parent / "trading_data"
    output_dirs = [
        base_dir / "deepseek" / "market_snapshots",
        base_dir / "qwen" / "market_snapshots",
    ]
    
    # 创建目录
    for output_dir in output_dirs:
        output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"\n{'='*60}")
    print(f"加密货币历史数据导出工具 (Market Snapshots)")
    print(f"{'='*60}")
    print(f"当前UTC时间: {now_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"日期范围: {start_date} ~ {end_date}")
    print(f"币种数量: {len(SYMBOLS)}")
    print(f"输出目录:")
    for output_dir in output_dirs:
        print(f"  - {output_dir}")
    print(f"{'='*60}\n")
    
    # 遍历日期
    current = datetime.strptime(start_date, '%Y%m%d')
    end = datetime.strptime(end_date, '%Y%m%d')
    
    success_count = 0
    fail_count = 0
    
    while current <= end:
        date_str = current.strftime('%Y%m%d')
        try:
            export_date(date_str, output_dirs)
            success_count += 1
        except Exception as e:
            print(f"✗ {date_str} 导出失败: {e}")
            fail_count += 1
        current += timedelta(days=1)
    
    print(f"\n{'='*60}")
    print(f"✓ 导出完成！")
    print(f"  成功: {success_count} 天")
    if fail_count > 0:
        print(f"  失败: {fail_count} 天")
    print(f"  文件位置:")
    for output_dir in output_dirs:
        print(f"    {output_dir}")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    main()

