#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从币安API智能合并和补充订单数据
功能：
1. 补充丢失的开仓时间
2. 修正错误的时间信息
3. 添加完全丢失的订单
4. 保留原有的本地特有字段（开仓理由、平仓理由等）

重要：DeepSeek和Qwen使用不同的币安账户
"""

import os
import sys
import json
import csv
import ccxt
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

def init_exchange(model_name):
    """初始化指定模型的交易所实例"""
    if model_name == 'deepseek':
        env_file = Path(__file__).parent / ".env"
    elif model_name == 'qwen':
        env_file = Path(__file__).parent / ".env.qwen"
    else:
        print(f"❌ 未知的模型: {model_name}")
        return None
    
    if not env_file.exists():
        print(f"❌ 环境变量文件不存在: {env_file}")
        return None
    
    # 加载环境变量
    load_dotenv(env_file, override=True)
    
    # 获取API密钥
    api_key = os.getenv("BINANCE_API_KEY", "").strip()
    secret_key = os.getenv("BINANCE_SECRET_KEY", "").strip()
    use_portfolio = os.getenv("USE_PORTFOLIO_MARGIN", "true").lower() == "true"
    
    if not api_key or not secret_key:
        print(f"❌ {model_name}: 币安API密钥未配置")
        return None
    
    # 初始化交易所
    exchange = ccxt.binance({
        "apiKey": api_key,
        "secret": secret_key,
        "options": {
            "defaultType": "future",
            "portfolioMargin": use_portfolio,
            "recvWindow": 60000,
        },
        "timeout": 30000,
        "enableRateLimit": True,
    })
    
    print(f"✅ {model_name}: 已连接到币安API")
    return exchange


def fetch_all_orders(exchange, days=30, limit=500):
    """获取指定天数内的所有订单"""
    symbols = [
        'BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT', 
        'BNB/USDT:USDT', 'XRP/USDT:USDT', 'DOGE/USDT:USDT', 'LTC/USDT:USDT'
    ]
    
    all_orders = []
    
    for sym in symbols:
        try:
            orders = exchange.fetch_orders(sym, limit=limit)
            all_orders.extend(orders)
            print(f"  {sym}: {len(orders)} 笔订单")
        except Exception as e:
            print(f"  ⚠️  {sym}: {e}")
            continue
    
    print(f"✅ 总计获取: {len(all_orders)} 笔订单")
    return all_orders


def parse_binance_order(order):
    """解析币安订单为标准格式"""
    symbol = order.get('symbol', '').replace('/USDT:USDT', '').replace('/USDT', '')
    side = order.get('side', '')  # 'buy' or 'sell'
    position_side = order.get('info', {}).get('positionSide', 'BOTH')
    
    # 判断方向：多/空
    # 在单向持仓模式下，buy=开多/平空，sell=开空/平多
    # 在双向持仓模式下，positionSide明确指示
    if position_side == 'LONG' or (position_side == 'BOTH' and side == 'buy'):
        direction = '多'
    elif position_side == 'SHORT' or (position_side == 'BOTH' and side == 'sell'):
        direction = '空'
    else:
        direction = '多' if side == 'buy' else '空'
    
    return {
        '币种': symbol,
        '方向': direction,
        '数量': float(order.get('amount', 0)),
        '价格': float(order.get('price', 0) or order.get('average', 0) or 0),
        '时间': datetime.fromtimestamp(order.get('timestamp', 0) / 1000).strftime('%Y-%m-%d %H:%M:%S') if order.get('timestamp') else '',
        '状态': order.get('status', ''),
        '类型': order.get('type', ''),
        '成交金额': float(order.get('cost', 0)),
    }


def match_order(local_trade, binance_orders, tolerance_price=0.01, tolerance_qty=0.1):
    """
    尝试为本地订单匹配币安订单
    
    匹配条件：
    1. 币种相同
    2. 方向相同
    3. 价格相近（允许tolerance_price的误差，默认1%）
    4. 数量相近（允许tolerance_qty的误差，默认10%）
    
    返回：最佳匹配的币安订单，或None
    """
    coin = local_trade.get('币种', '').strip()
    direction = local_trade.get('方向', '').strip()
    
    # 尝试获取本地价格和数量
    try:
        local_price = float(local_trade.get('开仓价格', 0) or 0)
        local_qty = float(local_trade.get('数量', 0) or 0)
    except:
        return None
    
    if not coin or not direction or local_price == 0:
        return None
    
    # 过滤候选订单
    candidates = []
    for bo in binance_orders:
        if bo['币种'] != coin or bo['方向'] != direction:
            continue
        
        # 检查价格匹配
        if local_price > 0 and bo['价格'] > 0:
            price_diff = abs(bo['价格'] - local_price) / local_price
            if price_diff > tolerance_price:
                continue
        
        # 检查数量匹配（如果本地有数量）
        if local_qty > 0 and bo['数量'] > 0:
            qty_diff = abs(bo['数量'] - local_qty) / local_qty
            if qty_diff > tolerance_qty:
                continue
        
        # 计算匹配度（价格和数量的加权误差）
        score = 0
        if bo['价格'] > 0 and local_price > 0:
            price_diff = abs(bo['价格'] - local_price) / local_price
            score += price_diff
        if bo['数量'] > 0 and local_qty > 0:
            qty_diff = abs(bo['数量'] - local_qty) / local_qty
            score += qty_diff * 0.5  # 数量权重降低
        
        candidates.append((score, bo))
    
    if not candidates:
        return None
    
    # 返回匹配度最高的（score最小）
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


def merge_trades_for_model(model_name, dry_run=False):
    """为指定模型合并订单数据"""
    print("\n" + "=" * 70)
    print(f"🔄 处理 {model_name.upper()} 数据")
    print("=" * 70)
    
    # 1. 初始化交易所
    exchange = init_exchange(model_name)
    if not exchange:
        return False
    
    # 2. 获取币安订单
    print(f"\n📡 从币安API获取订单...")
    binance_orders_raw = fetch_all_orders(exchange, days=30)
    binance_orders = [parse_binance_order(o) for o in binance_orders_raw]
    
    # 3. 读取本地CSV
    data_dir = Path(__file__).parent / "trading_data" / model_name
    trades_file = data_dir / "trades_history.csv"
    
    if not trades_file.exists():
        print(f"❌ 本地文件不存在: {trades_file}")
        return False
    
    # 备份
    if not dry_run:
        backup_file = trades_file.parent / f"trades_history.csv.before_merge_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        import shutil
        shutil.copy(trades_file, backup_file)
        print(f"✅ 已备份到: {backup_file.name}")
    
    # 读取现有数据
    with open(trades_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames)
        local_trades = list(reader)
    
    print(f"\n📊 本地记录: {len(local_trades)} 条")
    
    # 4. 分析和修复
    fixed_count = 0
    missing_time_count = 0
    added_count = 0
    
    # 统计缺失开仓时间的记录
    for trade in local_trades:
        if not trade.get('开仓时间', '').strip():
            missing_time_count += 1
    
    print(f"⚠️  缺失开仓时间: {missing_time_count} 条")
    
    # 5. 补充开仓时间
    print(f"\n🔧 开始补充和修复...")
    
    for i, trade in enumerate(local_trades):
        open_time = trade.get('开仓时间', '').strip()
        
        # 如果开仓时间缺失，尝试匹配
        if not open_time:
            matched = match_order(trade, binance_orders)
            if matched:
                trade['开仓时间'] = matched['时间']
                fixed_count += 1
                coin = trade.get('币种', '')
                direction = trade.get('方向', '')
                price = trade.get('开仓价格', '')
                print(f"  ✓ 修复 {coin} {direction} @ {price} → {matched['时间']}")
    
    # 6. 保存结果
    if dry_run:
        print(f"\n🔍 试运行模式 - 未写入文件")
        print(f"   将修复: {fixed_count} 条记录")
    else:
        with open(trades_file, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(local_trades)
        
        print(f"\n✅ 已保存到: {trades_file}")
        print(f"   ✓ 修复记录: {fixed_count} 条")
        print(f"   ✓ 总记录数: {len(local_trades)} 条")
    
    return True


def main():
    """主函数"""
    print("=" * 70)
    print("🔄 智能合并币安订单数据")
    print("=" * 70)
    print("功能：补充缺失的开仓时间、修正错误数据")
    print("")
    
    # 询问是否试运行
    dry_run_input = input("是否试运行（只检查不修改）？[y/N]: ").strip().lower()
    dry_run = dry_run_input == 'y'
    
    if dry_run:
        print("🔍 试运行模式：将检查但不会修改文件\n")
    else:
        print("⚠️  实际运行模式：将修改文件（会先备份）\n")
    
    # 询问处理哪个模型
    model_input = input("处理哪个模型？[deepseek/qwen/both]: ").strip().lower()
    
    if model_input in ['deepseek', 'd', '1']:
        merge_trades_for_model('deepseek', dry_run)
    elif model_input in ['qwen', 'q', '2']:
        merge_trades_for_model('qwen', dry_run)
    elif model_input in ['both', 'b', 'all', '']:
        merge_trades_for_model('deepseek', dry_run)
        merge_trades_for_model('qwen', dry_run)
    else:
        print("❌ 无效的选择")
        return
    
    print("\n" + "=" * 70)
    print("✅ 完成！")
    print("=" * 70)


if __name__ == "__main__":
    main()

