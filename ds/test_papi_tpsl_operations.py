#!/usr/bin/env python3
"""
测试papi端点的止盈止损操作
参考官方文档: POST /papi/v1/um/conditional/order
"""

import os
import sys
import time
import hmac
import hashlib
import requests
from pathlib import Path
from dotenv import load_dotenv
from urllib.parse import urlencode

# 加载.env配置
_env_file = Path(__file__).parent / '.env'
load_dotenv(_env_file, override=True)

API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
API_SECRET = os.getenv("BINANCE_SECRET_KEY", "").strip()

print(f"✓ API密钥: {API_KEY[:10]}...")

import ccxt

exchange = ccxt.binance({
    'apiKey': API_KEY,
    'secret': API_SECRET,
    'enableRateLimit': True,
    'options': {'defaultType': 'future', 'portfolioMargin': True}
})

print("="*60)
print("测试papi端点")
print("="*60)

def sign_request(params):
    """生成签名"""
    # 按字母顺序排序
    sorted_params = sorted(params.items())
    query_string = urlencode(sorted_params)
    signature = hmac.new(
        API_SECRET.encode('utf-8'),
        query_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return query_string, signature

def create_conditional_order(symbol, side, stop_price, quantity, strategy_type):
    """
    创建条件单
    官方文档: POST /papi/v1/um/conditional/order
    STOP_MARKET/TAKE_PROFIT_MARKET 必需参数: stopPrice
    """
    params = {
        'symbol': symbol,
        'side': side,
        'strategyType': strategy_type,  # STOP_MARKET 或 TAKE_PROFIT_MARKET
        'stopPrice': str(stop_price),
        'quantity': str(quantity),
        'reduceOnly': 'true',
        'timestamp': int(time.time() * 1000)
    }
    
    query_string, signature = sign_request(params)
    url = f"https://papi.binance.com/papi/v1/um/conditional/order?{query_string}&signature={signature}"
    
    print(f"  DEBUG - strategyType: {strategy_type}")
    print(f"  DEBUG - Query: {query_string[:120]}...")
    
    headers = {'X-MBX-APIKEY': API_KEY}
    return requests.post(url, headers=headers)

def query_conditional_orders(symbol):
    """查询条件单"""
    params = {
        'symbol': symbol,
        'timestamp': int(time.time() * 1000)
    }
    
    query_string, signature = sign_request(params)
    url = f"https://papi.binance.com/papi/v1/um/conditional/openOrders?{query_string}&signature={signature}"
    
    headers = {'X-MBX-APIKEY': API_KEY}
    return requests.get(url, headers=headers)

def cancel_conditional_order(symbol, strategy_id):
    """取消条件单"""
    params = {
        'symbol': symbol,
        'strategyId': int(strategy_id),
        'timestamp': int(time.time() * 1000)
    }
    
    query_string, signature = sign_request(params)
    url = f"https://papi.binance.com/papi/v1/um/conditional/order?{query_string}&signature={signature}"
    
    headers = {'X-MBX-APIKEY': API_KEY}
    return requests.delete(url, headers=headers)

# ============================================================
# 测试开始
# ============================================================

print("\n1. 查找持仓...")
test_symbol = "BTCUSDT"
ccxt_symbol = "BTC/USDT:USDT"

try:
    positions = exchange.fetch_positions([ccxt_symbol])
    position = next((p for p in positions if abs(float(p.get('contracts', 0))) > 0), None)
    
    if not position:
        for test_sym, ccxt_sym in [("ETHUSDT", "ETH/USDT:USDT"), ("SOLUSDT", "SOL/USDT:USDT"), ("BNBUSDT", "BNB/USDT:USDT")]:
            positions = exchange.fetch_positions([ccxt_sym])
            position = next((p for p in positions if abs(float(p.get('contracts', 0))) > 0), None)
            if position:
                test_symbol = test_sym
                ccxt_symbol = ccxt_sym
                print(f"✓ 找到{test_symbol}持仓")
                break
    
    if not position:
        print("❌ 没有持仓")
        sys.exit(1)
    
    pos_size = abs(float(position.get('contracts', 0)))
    pos_side = 'long' if float(position.get('contracts', 0)) > 0 else 'short'
    mark_price = float(position.get('markPrice', 0))
    close_side = 'SELL' if pos_side == 'long' else 'BUY'
    
    print(f"✓ {test_symbol} {pos_side} {pos_size} @ ${mark_price:,.2f}")
    
except Exception as e:
    print(f"❌ 获取持仓失败: {e}")
    sys.exit(1)

# 计算测试价格
test_sl = round(mark_price * (0.98 if pos_side == 'long' else 1.02), 2)
test_tp = round(mark_price * (1.02 if pos_side == 'long' else 0.98), 2)

print("\n" + "="*60)
print("场景1: 创建止盈止损")
print("="*60)
print(f"止损: ${test_sl} | 止盈: ${test_tp}")

# 创建止损单 (STOP_MARKET)
print("\n创建止损单...")
sl_resp = create_conditional_order(test_symbol, close_side, test_sl, pos_size, 'STOP_MARKET')
print(f"HTTP {sl_resp.status_code}")
if sl_resp.status_code == 200:
    sl_id = sl_resp.json().get('strategyId')
    print(f"✓ 止损ID: {sl_id}")
else:
    print(f"❌ {sl_resp.text}")
    sys.exit(1)

time.sleep(0.5)

# 创建止盈单 (TAKE_PROFIT_MARKET)
print("\n创建止盈单...")
tp_resp = create_conditional_order(test_symbol, close_side, test_tp, pos_size, 'TAKE_PROFIT_MARKET')
print(f"HTTP {tp_resp.status_code}")
if tp_resp.status_code == 200:
    tp_id = tp_resp.json().get('strategyId')
    print(f"✓ 止盈ID: {tp_id}")
else:
    print(f"❌ {tp_resp.text}")
    cancel_conditional_order(test_symbol, sl_id)
    sys.exit(1)

print("\n" + "="*60)
print("场景2: 查询条件单")
print("="*60)
time.sleep(1)
query_resp = query_conditional_orders(test_symbol)
print(f"HTTP {query_resp.status_code}")
if query_resp.status_code == 200:
    orders = query_resp.json()
    print(f"✓ {len(orders)} 个订单")
    for o in orders:
        print(f"  {o.get('strategyType')}: ${float(o.get('stopPrice')):.2f}")

print("\n" + "="*60)
print("场景3: 调整止盈止损")
print("="*60)
new_sl = round(mark_price * (0.97 if pos_side == 'long' else 1.03), 2)
new_tp = round(mark_price * (1.03 if pos_side == 'long' else 0.97), 2)
print(f"新止损: ${new_sl} | 新止盈: ${new_tp}")

time.sleep(0.5)
print(f"取消止损: HTTP {cancel_conditional_order(test_symbol, sl_id).status_code}")
time.sleep(0.5)
print(f"取消止盈: HTTP {cancel_conditional_order(test_symbol, tp_id).status_code}")

time.sleep(1)
new_sl_resp = create_conditional_order(test_symbol, close_side, new_sl, pos_size, 'STOP_MARKET')
print(f"新止损: HTTP {new_sl_resp.status_code}")
new_sl_id = new_sl_resp.json().get('strategyId') if new_sl_resp.status_code == 200 else None

time.sleep(0.5)
new_tp_resp = create_conditional_order(test_symbol, close_side, new_tp, pos_size, 'TAKE_PROFIT_MARKET')
print(f"新止盈: HTTP {new_tp_resp.status_code}")
new_tp_id = new_tp_resp.json().get('strategyId') if new_tp_resp.status_code == 200 else None

print("\n" + "="*60)
print("场景4: 分批平仓50%并重设止盈止损")
print("="*60)

# 取消现有条件单
if new_sl_id:
    time.sleep(0.5)
    cancel_conditional_order(test_symbol, new_sl_id)
if new_tp_id:
    time.sleep(0.5)
    cancel_conditional_order(test_symbol, new_tp_id)

half_size = round(pos_size / 2, 6)
remaining_size = pos_size - half_size
print(f"原始: {pos_size} | 平仓50%: {half_size} | 剩余: {remaining_size}")

time.sleep(1)
partial_sl_resp = create_conditional_order(test_symbol, close_side, new_sl, remaining_size, 'STOP_MARKET')
print(f"剩余仓位止损: HTTP {partial_sl_resp.status_code}")

time.sleep(0.5)
partial_tp_resp = create_conditional_order(test_symbol, close_side, new_tp, remaining_size, 'TAKE_PROFIT_MARKET')
print(f"剩余仓位止盈: HTTP {partial_tp_resp.status_code}")

print("\n" + "="*60)
print("场景5: 清理所有条件单")
print("="*60)
time.sleep(1)
query_final = query_conditional_orders(test_symbol)
if query_final.status_code == 200:
    orders_final = query_final.json()
    print(f"{len(orders_final)} 个订单")
    for o in orders_final:
        time.sleep(0.5)
        resp = cancel_conditional_order(test_symbol, o.get('strategyId'))
        print(f"{'✓' if resp.status_code in [200,400] else '❌'} {o.get('strategyType')}: {resp.status_code}")

print("\n" + "="*60)
print("场景6: 不存在订单容错")
print("="*60)
fake = cancel_conditional_order(test_symbol, 999999999)
print(f"HTTP {fake.status_code} {'✓' if fake.status_code == 400 else '异常'}")

print("\n" + "="*60)
print("✅ 测试完成")
print("="*60)
print("\n如果所有场景HTTP 200，papi签名正确")
