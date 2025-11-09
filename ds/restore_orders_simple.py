#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简洁版订单恢复工具 - 从币安PAPI恢复交易历史
适配V8.3.16.8的STANDARD_COLUMNS格式
"""

import os
import time
import hmac
import hashlib
import requests
import pandas as pd
from pathlib import Path
from datetime import datetime
from urllib.parse import urlencode
from dotenv import load_dotenv


def papi_request(base_url, endpoint, api_key, api_secret, params):
    """发送PAPI请求"""
    timestamp = int(time.time() * 1000)
    params['timestamp'] = timestamp
    params['recvWindow'] = 5000
    
    query = urlencode(sorted(params.items()))
    signature = hmac.new(api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    
    url = f"{base_url}{endpoint}?{query}&signature={signature}"
    headers = {'X-MBX-APIKEY': api_key}
    
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    return response.json()


def restore_from_papi(model_name="deepseek"):
    """从PAPI恢复订单"""
    print(f"\n{'='*70}")
    print(f"🔄 恢复 {model_name.upper()} 订单历史")
    print(f"{'='*70}\n")
    
    # 加载环境变量
    script_dir = Path(__file__).parent
    env_file = script_dir / (".env.qwen" if model_name == "qwen" else ".env")
    
    if not env_file.exists():
        print(f"❌ 环境文件不存在: {env_file}")
        return None
    
    load_dotenv(env_file, override=True)  # ⚠️ 必须override=True，否则不会覆盖已有环境变量
    print(f"✓ 加载环境: {env_file}")
    
    api_key = os.getenv("BINANCE_API_KEY")
    api_secret = os.getenv("BINANCE_SECRET_KEY")
    
    if not api_key or not api_secret:
        print(f"❌ API密钥未配置")
        return None
    
    print(f"✓ API密钥已加载")
    
    # PAPI端点
    base_url = 'https://papi.binance.com'
    symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT', 'DOGEUSDT', 'LTCUSDT']
    
    # 时间范围（最近7天）
    end_time = int(time.time() * 1000)
    start_time = end_time - (7 * 24 * 60 * 60 * 1000)
    
    print(f"\n📥 获取订单（最近7天）...")
    
    all_orders = []
    for symbol in symbols:
        try:
            print(f"  - {symbol}...", end=" ", flush=True)
            orders = papi_request(
                base_url, '/papi/v1/um/allOrders', api_key, api_secret,
                {'symbol': symbol, 'startTime': start_time, 'endTime': end_time, 'limit': 1000}
            )
            filled = [o for o in orders if o['status'] == 'FILLED']
            all_orders.extend(filled)
            print(f"✓ {len(filled)}笔")
            time.sleep(0.2)
        except Exception as e:
            print(f"✗ {str(e)[:50]}")
    
    if not all_orders:
        print("\n⚠️ 未找到订单")
        return None
    
    print(f"\n✓ 共获取 {len(all_orders)} 笔订单")
    if all_orders:
        print(f"   🔍 DEBUG - 首笔: ID={all_orders[0]['orderId']}, Time={all_orders[0]['time']}")
        print(f"   🔍 DEBUG - 末笔: ID={all_orders[-1]['orderId']}, Time={all_orders[-1]['time']}")
    
    # 配对订单（单向持仓模式）
    print("\n🔄 配对订单...")
    trades = []
    
    orders_by_symbol = {}
    for order in all_orders:
        symbol = order['symbol']
        orders_by_symbol.setdefault(symbol, []).append(order)
    
    for symbol, orders in orders_by_symbol.items():
        orders.sort(key=lambda x: x['time'])
        
        i = 0
        while i < len(orders) - 1:
            current = orders[i]
            next_order = orders[i + 1]
            
            # BUY -> SELL = 做多
            if current['side'] == 'BUY' and next_order['side'] == 'SELL':
                trade = create_trade(current, next_order, '做多')
                if trade:
                    trades.append(trade)
                i += 2
            # SELL -> BUY = 做空
            elif current['side'] == 'SELL' and next_order['side'] == 'BUY':
                trade = create_trade(current, next_order, '做空')
                if trade:
                    trades.append(trade)
                i += 2
            else:
                i += 1
    
    if not trades:
        print("⚠️ 未找到完整交易对")
        return None
    
    print(f"✓ 成功配对 {len(trades)} 笔交易")
    
    # 保存
    df = pd.DataFrame(trades)
    data_dir = Path(f"trading_data/{model_name}")
    data_dir.mkdir(parents=True, exist_ok=True)
    
    output_file = data_dir / "trades_history.csv"
    # ⚠️ 不能用utf-8-sig，会导致csv.DictReader无法正确读取第一列
    df.to_csv(output_file, index=False, encoding='utf-8')  # 纯utf-8，无BOM
    
    print(f"\n✅ 已保存: {output_file}")
    print(f"📊 统计: {len(trades)}笔, 盈利{len(df[df['盈亏(U)']>0])}笔, 总盈亏{df['盈亏(U)'].sum():.2f}U")
    
    return df


def create_trade(open_order, close_order, direction):
    """创建交易记录（V8.3.16.8格式）"""
    try:
        symbol = open_order['symbol']
        coin = symbol.replace('USDT', '')
        
        open_price = float(open_order.get('avgPrice', 0))
        close_price = float(close_order.get('avgPrice', 0))
        qty = float(open_order.get('executedQty', 0))
        
        if not all([open_price, close_price, qty]):
            return None
        
        # 盈亏
        pnl = (close_price - open_price) * qty if direction == '做多' else (open_price - close_price) * qty
        
        # 时间
        open_time = datetime.fromtimestamp(open_order['time'] / 1000)
        close_time = datetime.fromtimestamp(close_order['updateTime'] / 1000)
        
        # 杠杆和仓位
        leverage = 5
        position_value = open_price * qty
        
        # V8.3.16.8 STANDARD_COLUMNS格式
        return {
            '开仓时间': open_time.strftime('%Y-%m-%d %H:%M:%S'),
            '平仓时间': close_time.strftime('%Y-%m-%d %H:%M:%S'),
            '币种': coin,
            '方向': direction,
            '数量': qty,
            '开仓价格': round(open_price, 2),
            '平仓价格': round(close_price, 2),
            '仓位(U)': round(position_value, 2),
            '杠杆率': leverage,
            '止损': 0,
            '止盈': 0,
            '盈亏比': round((pnl / position_value) * 100, 2),
            '盈亏(U)': round(pnl, 2),
            '开仓理由': '[PAPI恢复]',
            '平仓理由': '[止盈]' if pnl > 0 else '[止损]',
        }
    except Exception as e:
        print(f"\n⚠️ 创建记录失败: {e}")
        return None


if __name__ == "__main__":
    print("\n" + "="*70)
    print("📦 订单恢复工具 (V8.3.16.8)")
    print("="*70)
    
    # 恢复DeepSeek
    print("\n【1/2】DeepSeek")
    restore_from_papi("deepseek")
    
    # 恢复Qwen
    print("\n" + "-"*70)
    print("\n【2/2】Qwen")
    restore_from_papi("qwen")
    
    print("\n" + "="*70)
    print("✅ 完成！")
    print("="*70)

