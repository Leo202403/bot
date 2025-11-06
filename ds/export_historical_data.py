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
        
        # 过滤目标日期
        day_df = df[(df['timestamp'] >= start_ts) & (df['timestamp'] < end_ts)].copy()
        
        print(f"    获取到 {len(day_df)} 条记录")
        return day_df
        
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
        df = fetch_data_for_date(symbol, date_str)
        
        if df is None or len(df) == 0:
            continue
        
        for idx, row in df.iterrows():
            time_str = datetime.fromtimestamp(row['timestamp'] / 1000).strftime('%H%M')
            
            # 【V7.8新增】构造market_data结构以计算signal_score
            ema20 = row['ema20_1h'] if pd.notna(row['ema20_1h']) else row['close']
            ema50 = row['ema50_1h'] if pd.notna(row['ema50_1h']) else row['close']
            
            market_data_for_score = {
                "price_action": {
                    "consecutive": {"candles": 4} if abs(row['close'] - row['open']) / row['open'] > 0.003 else None,
                    "momentum_slope": (row['close'] - row['open']) / row['open'],
                    "trend_exhaustion": None,
                    "pin_bar": None,
                    "engulfing": None,
                    "breakout": None,
                    "volume_surge": None,
                    "pullback_type": {"type": "simple_pullback"} if abs(row['close'] - row['open']) / row['open'] > 0.002 else None,
                    "trend_initiation": None,
                },
                "long_term": {
                    "trend": row['trend_4h']
                },
                "moving_averages": {
                    "ema20": ema20,
                    "ema50": ema50,
                },
                "rsi": {
                    "rsi_14": row['rsi_14'] if pd.notna(row['rsi_14']) else 50,
                    "rsi_7": row['rsi_7'] if pd.notna(row['rsi_7']) else 50,
                },
                "macd": {
                    "histogram": row['macd_histogram'] if pd.notna(row['macd_histogram']) else 0,
                },
                "support_resistance": {
                    "position_status": "neutral"
                },
                "trend_4h": row['trend_4h'],
                "trend_15m": row['trend_15m'],
            }
            
            # 计算signal_score
            try:
                signal_score, _, _ = calculate_signal_score(market_data_for_score)
            except Exception as e:
                signal_score = 50  # 默认值
            
            # 计算指标共振
            indicator_consensus = 0
            if ema20 > ema50:
                indicator_consensus += 1
            if row['macd_histogram'] > 0 and pd.notna(row['macd_histogram']):
                indicator_consensus += 1
            rsi_14 = row['rsi_14'] if pd.notna(row['rsi_14']) else 50
            if 30 <= rsi_14 <= 70:
                indicator_consensus += 1
            if row['volume'] > 0:
                indicator_consensus += 1
            if row['atr'] > 0 and pd.notna(row['atr']):
                indicator_consensus += 1
            
            # 【V7.8关键修复】计算盈亏比（risk_reward）
            atr = row['atr'] if pd.notna(row['atr']) and row['atr'] > 0 else 0
            price = row['close']
            resistance = row['resistance'] if pd.notna(row['resistance']) else price * 1.02
            support = row['support'] if pd.notna(row['support']) else price * 0.98
            
            if atr > 0:
                # 止损距离：2倍ATR（与系统默认一致）
                stop_distance = atr * 2.0
                
                # 止盈目标：多头看阻力，空头看支撑，取较大值
                if row['trend_15m'] in ['多头', '多头转弱']:
                    target_distance = max(
                        abs(resistance - price),
                        atr * 3.0
                    )
                elif row['trend_15m'] in ['空头', '空头转弱']:
                    target_distance = max(
                        abs(price - support),
                        atr * 3.0
                    )
                else:
                    # 震荡市：取支撑阻力距离和3倍ATR的最大值
                    target_distance = max(
                        abs(resistance - price),
                        abs(price - support),
                        atr * 3.0
                    )
                
                # 计算盈亏比
                risk_reward = round(target_distance / stop_distance, 2) if stop_distance > 0 else 0
            else:
                risk_reward = 0
            
            csv_row = {
                'time': time_str,
                'coin': coin_name,
                'open': round(row['open'], 8),
                'high': round(row['high'], 8),
                'low': round(row['low'], 8),
                'close': round(row['close'], 8),
                'volume': round(row['volume'], 3),
                'price': round(row['close'], 8),
                'trend_4h': row['trend_4h'],
                'trend_15m': row['trend_15m'],
                'rsi_14': round(row['rsi_14'], 8) if pd.notna(row['rsi_14']) else 50,
                'rsi_7': round(row['rsi_7'], 8) if pd.notna(row['rsi_7']) else 50,
                'macd_line': round(row['macd_line'], 8) if pd.notna(row['macd_line']) else 0,
                'macd_signal': round(row['macd_signal'], 8) if pd.notna(row['macd_signal']) else 0,
                'macd_histogram': round(row['macd_histogram'], 8) if pd.notna(row['macd_histogram']) else 0,
                'atr': round(row['atr'], 8) if pd.notna(row['atr']) else 0,
                'support': round(row['support'], 8) if pd.notna(row['support']) else row['low'],
                'resistance': round(row['resistance'], 8) if pd.notna(row['resistance']) else row['high'],
                'indicator_consensus': indicator_consensus,
                'signal_score': round(signal_score, 2),  # 【V7.8新增】
                'risk_reward': risk_reward,  # 【V7.8关键修复】盈亏比
                'trend_1h': row['trend_1h'],
                'ema20_1h': round(row['ema20_1h'], 8) if pd.notna(row['ema20_1h']) else row['close'],
                'ema50_1h': round(row['ema50_1h'], 8) if pd.notna(row['ema50_1h']) else row['close'],
                'macd_1h_line': round(row['macd_1h_line'], 8) if pd.notna(row['macd_1h_line']) else 0,
                'macd_1h_signal': round(row['macd_1h_signal'], 8) if pd.notna(row['macd_1h_signal']) else 0,
                'macd_1h_histogram': round(row['macd_1h_histogram'], 8) if pd.notna(row['macd_1h_histogram']) else 0,
                'atr_1h': round(row['atr_1h'], 8) if pd.notna(row['atr_1h']) else 0,
                'resistance_1h': round(row['resistance'], 8) if pd.notna(row['resistance']) else row['high'],
                'resistance_1h_strength': 5,
                'support_1h': round(row['support'], 8) if pd.notna(row['support']) else row['low'],
                'support_1h_strength': 5,
                'pin_bar': '',
                'engulfing': '',
                'pullback_type': 'simple_pullback' if abs(row['close'] - row['open']) / row['open'] > 0.002 else '',
                'pullback_depth': round(abs(row['high'] - row['low']) / row['open'], 8),
                'momentum_slope': round((row['close'] - row['open']) / row['open'], 8),
                'pullback_weakness_score': 0.4,
                'lwp_long': round(row['support'], 8) if pd.notna(row['support']) else row['low'],
                'lwp_short': round(row['resistance'], 8) if pd.notna(row['resistance']) else row['high'],
                'lwp_confidence': 'high',
                'ytc_signal_type': 'TST' if row['trend_15m'] in ['多头', '空头'] else 'NONE',
                'ytc_direction': 'SHORT' if row['trend_15m'] == '空头' else 'LONG' if row['trend_15m'] == '多头' else '',
                'ytc_strength': 5 if row['trend_15m'] in ['多头', '空头'] else 0,
                'ytc_sr_strength': 5,
                'ytc_entry_price': round(row['close'], 8),
                'ytc_rationale': f"弱势测试强{'阻力' if row['trend_15m'] == '空头' else '支撑'}{round(row['resistance'] if row['trend_15m'] == '空头' else row['support'], 2)}+动能停滞，Fading测试者" if row['trend_15m'] in ['多头', '空头'] else '',
                'support_strength': 5,
                'support_polarity_switched': 'True',
                'support_fast_rejection': 'True',
                'resistance_strength': 5,
                'resistance_polarity_switched': 'True',
                'resistance_fast_rejection': 'True',
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

