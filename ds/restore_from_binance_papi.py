#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从币安统一账户(Portfolio Margin API)恢复数据
支持：
1. 获取账户余额和总资产
2. 获取当前持仓
3. 获取历史订单
4. 恢复到system_status.json和trades_history.csv
"""

import os
import sys
import json
import csv
import ccxt
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# 加载环境变量
env_file = Path(__file__).parent.parent / ".env"
if env_file.exists():
    load_dotenv(env_file)
else:
    print(f"⚠️  环境变量文件不存在: {env_file}")
    print("将尝试使用系统环境变量")

# 配置
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY", "").strip()
USE_PORTFOLIO_MARGIN = True  # 统一账户模式

if not BINANCE_API_KEY or not BINANCE_SECRET_KEY:
    print("❌ 币安API密钥未配置，请检查环境变量")
    sys.exit(1)

# 初始化交易所
exchange = ccxt.binance({
    "apiKey": BINANCE_API_KEY,
    "secret": BINANCE_SECRET_KEY,
    "options": {
        "defaultType": "future",  # 合约
        "portfolioMargin": USE_PORTFOLIO_MARGIN,  # 统一账户模式
        "recvWindow": 60000,
    },
    "timeout": 30000,
    "enableRateLimit": True,
})

print("=" * 60)
print("📊 从币安统一账户恢复数据")
print("=" * 60)
print(f"API Key: {BINANCE_API_KEY[:10]}...")
print(f"统一账户模式: {USE_PORTFOLIO_MARGIN}")
print("")


def get_account_balance():
    """获取账户余额和总资产"""
    try:
        # 对于统一账户，使用fapiPrivateV2GetAccount或直接fetch_balance
        balance = exchange.fetch_balance()
        
        print("📌 账户余额信息:")
        print(f"  总权益: {balance.get('total', {}).get('USDT', 0):.2f} USDT")
        print(f"  可用余额: {balance.get('free', {}).get('USDT', 0):.2f} USDT")
        print(f"  冻结余额: {balance.get('used', {}).get('USDT', 0):.2f} USDT")
        
        # 获取详细信息
        if 'info' in balance:
            info = balance['info']
            
            # 统一账户的字段可能不同
            total_wallet_balance = 0
            total_unrealized_profit = 0
            
            # 尝试从不同字段获取
            if 'totalWalletBalance' in info:
                total_wallet_balance = float(info['totalWalletBalance'])
            if 'totalUnrealizedProfit' in info:
                total_unrealized_profit = float(info['totalUnrealizedProfit'])
            
            # 计算总资产
            if 'totalMarginBalance' in info:
                total_assets = float(info['totalMarginBalance'])
            elif 'totalWalletBalance' in info:
                total_assets = total_wallet_balance + total_unrealized_profit
            else:
                # 备用方案：使用USDT余额
                total_assets = balance.get('total', {}).get('USDT', 0)
            
            print(f"\n💰 总资产详情:")
            print(f"  钱包余额: {total_wallet_balance:.2f} USDT")
            print(f"  未实现盈亏: {total_unrealized_profit:+.2f} USDT")
            print(f"  总资产: {total_assets:.2f} USDT")
            
            return {
                'total_assets': total_assets,
                'wallet_balance': total_wallet_balance,
                'unrealized_profit': total_unrealized_profit,
                'available_balance': balance.get('free', {}).get('USDT', 0),
                'used_balance': balance.get('used', {}).get('USDT', 0),
            }
        
        return None
        
    except Exception as e:
        print(f"❌ 获取账户余额失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def get_open_positions():
    """获取当前持仓"""
    try:
        # 使用fetch_positions获取持仓
        positions = exchange.fetch_positions()
        
        # 过滤出有持仓的
        open_positions = [p for p in positions if float(p.get('contracts', 0)) > 0]
        
        print(f"\n📋 当前持仓: {len(open_positions)} 个")
        
        formatted_positions = []
        for pos in open_positions:
            symbol = pos.get('symbol', '')
            side = pos.get('side', '')  # long/short
            contracts = float(pos.get('contracts', 0))
            entry_price = float(pos.get('entryPrice', 0))
            mark_price = float(pos.get('markPrice', 0))
            unrealized_pnl = float(pos.get('unrealizedPnl', 0))
            leverage = float(pos.get('leverage', 1))
            notional = float(pos.get('notional', 0))
            
            # 转换为中文方向
            direction_cn = "多" if side == "long" else "空"
            
            print(f"\n  {symbol} {direction_cn}")
            print(f"    数量: {contracts}")
            print(f"    开仓价: ${entry_price:.2f}")
            print(f"    标记价: ${mark_price:.2f}")
            print(f"    未实现盈亏: {unrealized_pnl:+.2f} USDT")
            print(f"    杠杆: {leverage}x")
            print(f"    仓位价值: ${notional:.2f}")
            
            formatted_positions.append({
                '币种': symbol.replace('/USDT', '').replace(':USDT', ''),
                '方向': direction_cn,
                'side': side,
                '数量': contracts,
                '开仓价格': entry_price,
                '当前价格': mark_price,
                '杠杆': int(leverage),
                '杠杆率': int(leverage),
                '盈亏': unrealized_pnl,
                '仓位(U)': abs(notional),
                '开仓时间': '',  # API不返回，需要从订单历史获取
                '止损': '',
                '止盈': '',
                '盈亏比': '',
                '开仓理由': '从币安API恢复',
            })
        
        return formatted_positions
        
    except Exception as e:
        print(f"❌ 获取持仓失败: {e}")
        import traceback
        traceback.print_exc()
        return []


def get_order_history(symbol=None, limit=500):
    """获取历史订单"""
    try:
        print(f"\n📜 获取订单历史...")
        
        # 支持的交易对
        symbols = [
            'BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT', 
            'BNB/USDT:USDT', 'XRP/USDT:USDT', 'DOGE/USDT:USDT', 'LTC/USDT:USDT'
        ]
        
        all_orders = []
        
        for sym in symbols:
            try:
                # 获取该交易对的订单
                orders = exchange.fetch_orders(sym, limit=limit)
                all_orders.extend(orders)
                print(f"  {sym}: {len(orders)} 笔订单")
            except Exception as e:
                print(f"  ⚠️  {sym}: 获取失败 - {e}")
                continue
        
        print(f"\n总计: {len(all_orders)} 笔订单")
        
        return all_orders
        
    except Exception as e:
        print(f"❌ 获取订单历史失败: {e}")
        import traceback
        traceback.print_exc()
        return []


def restore_to_system_status(model_name, account_data, positions):
    """恢复到system_status.json"""
    data_dir = Path(__file__).parent / "trading_data" / model_name
    status_file = data_dir / "system_status.json"
    
    if not status_file.exists():
        print(f"⚠️  {model_name}: system_status.json 不存在，将创建新文件")
        status = {}
    else:
        with open(status_file, 'r', encoding='utf-8') as f:
            status = json.load(f)
    
    # 更新账户数据
    if account_data:
        status['总资产'] = account_data['total_assets']
        status['total_assets'] = account_data['total_assets']
        status['USDT余额'] = account_data['available_balance']
        status['usdt_balance'] = account_data['available_balance']
        status['未实现盈亏'] = account_data['unrealized_profit']
    
    # 更新持仓
    status['持仓详情'] = positions
    status['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # 保存
    with open(status_file, 'w', encoding='utf-8') as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
    
    print(f"✅ {model_name}: system_status.json 已更新")
    return True


def restore_to_trades_history(model_name, orders, positions):
    """恢复到trades_history.csv（仅添加当前持仓的开仓记录）"""
    data_dir = Path(__file__).parent / "trading_data" / model_name
    trades_file = data_dir / "trades_history.csv"
    
    # CSV字段（根据实际文件）
    fieldnames = [
        '开仓时间', '平仓时间', '币种', '方向', '数量', '开仓价格', '平仓价格',
        '仓位(U)', '杠杆率', '止损', '止盈', '盈亏比', '盈亏(U)', 
        '开仓理由', '平仓理由', '信号分数', '共振指标数'
    ]
    
    # 读取现有订单
    existing_trades = []
    if trades_file.exists():
        with open(trades_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            existing_trades = list(reader)
            # 获取实际的字段名
            if reader.fieldnames:
                fieldnames = list(reader.fieldnames)
    
    # 查找未平仓订单
    open_trade_keys = set()
    for trade in existing_trades:
        if not trade.get('平仓时间', '').strip():
            key = f"{trade.get('币种', '')}_{trade.get('方向', '')}"
            open_trade_keys.add(key)
    
    # 需要添加的持仓
    trades_to_add = []
    for pos in positions:
        key = f"{pos.get('币种', '')}_{pos.get('方向', '')}"
        
        if key not in open_trade_keys:
            # 尝试从订单历史中获取开仓时间
            open_time = ''
            for order in orders:
                order_symbol = order.get('symbol', '').replace('/USDT:USDT', '').replace('/USDT', '')
                order_side_long = order.get('side', '') == 'buy'
                pos_side_long = pos.get('side', '') == 'long'
                
                if (order_symbol == pos.get('币种', '') and 
                    order_side_long == pos_side_long and
                    order.get('status') == 'closed'):
                    open_time = datetime.fromtimestamp(order['timestamp'] / 1000).strftime('%Y-%m-%d %H:%M:%S')
                    break
            
            if not open_time:
                open_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            trade_record = {}
            for field in fieldnames:
                field_clean = field.strip()
                
                if field_clean == '开仓时间':
                    trade_record[field] = open_time
                elif field_clean == '平仓时间':
                    trade_record[field] = ''
                elif field_clean == '币种':
                    trade_record[field] = pos.get('币种', '')
                elif field_clean == '方向':
                    trade_record[field] = pos.get('方向', '')
                elif field_clean == '数量':
                    trade_record[field] = pos.get('数量', 0)
                elif field_clean == '开仓价格':
                    trade_record[field] = pos.get('开仓价格', 0)
                elif field_clean == '平仓价格':
                    trade_record[field] = ''
                elif field_clean == '仓位(U)':
                    trade_record[field] = pos.get('仓位(U)', 0)
                elif field_clean == '杠杆率':
                    trade_record[field] = pos.get('杠杆率', 1)
                elif field_clean == '止损':
                    trade_record[field] = pos.get('止损', '')
                elif field_clean == '止盈':
                    trade_record[field] = pos.get('止盈', '')
                elif field_clean == '盈亏比':
                    trade_record[field] = pos.get('盈亏比', '')
                elif field_clean == '盈亏(U)':
                    trade_record[field] = ''
                elif field_clean == '开仓理由':
                    trade_record[field] = pos.get('开仓理由', '')
                elif field_clean == '平仓理由':
                    trade_record[field] = ''
                elif field_clean == '信号分数':
                    trade_record[field] = ''
                elif field_clean == '共振指标数':
                    trade_record[field] = ''
                else:
                    trade_record[field] = ''
            
            trades_to_add.append(trade_record)
            print(f"  + 添加: {pos.get('币种')} {pos.get('方向')}")
    
    if trades_to_add:
        # 追加到CSV
        with open(trades_file, 'a', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not existing_trades:  # 文件为空，写表头
                writer.writeheader()
            writer.writerows(trades_to_add)
        
        print(f"✅ {model_name}: 已添加 {len(trades_to_add)} 条持仓记录到 trades_history.csv")
    else:
        print(f"✓ {model_name}: 所有持仓记录已存在")
    
    return True


def main():
    """主函数"""
    # 1. 获取账户数据
    print("\n【步骤1】获取账户余额")
    account_data = get_account_balance()
    
    if not account_data:
        print("❌ 无法获取账户数据，退出")
        return
    
    # 2. 获取持仓
    print("\n【步骤2】获取当前持仓")
    positions = get_open_positions()
    
    # 3. 获取订单历史
    print("\n【步骤3】获取订单历史")
    orders = get_order_history(limit=500)
    
    # 4. 显示总结
    print("\n" + "=" * 60)
    print("📊 数据汇总")
    print("=" * 60)
    print(f"总资产: {account_data['total_assets']:.2f} USDT")
    print(f"可用余额: {account_data['available_balance']:.2f} USDT")
    print(f"未实现盈亏: {account_data['unrealized_profit']:+.2f} USDT")
    print(f"当前持仓: {len(positions)} 个")
    print(f"历史订单: {len(orders)} 笔")
    print("")
    
    # 5. 选择恢复模式
    print("请选择恢复模式:")
    print("  1) 恢复 DeepSeek")
    print("  2) 恢复 Qwen")
    print("  3) 恢复两者（DeepSeek + Qwen）")
    print("  4) 仅查看数据，不恢复")
    print("")
    
    choice = input("请选择 [1-4]: ").strip()
    
    models = []
    if choice == '1':
        models = ['deepseek']
    elif choice == '2':
        models = ['qwen']
    elif choice == '3':
        models = ['deepseek', 'qwen']
    elif choice == '4':
        print("\n✅ 数据查看完成")
        return
    else:
        print("❌ 无效选项")
        return
    
    # 6. 执行恢复
    print("\n" + "=" * 60)
    print("🔧 开始恢复数据")
    print("=" * 60)
    
    for model in models:
        print(f"\n【{model.upper()}】")
        
        # 备份
        data_dir = Path(__file__).parent / "trading_data" / model
        backup_dir = Path(__file__).parent / "data_backup" / f"before_binance_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        for file in ['system_status.json', 'trades_history.csv']:
            src = data_dir / file
            if src.exists():
                import shutil
                shutil.copy2(src, backup_dir / file)
        
        print(f"  ✓ 已备份到: {backup_dir}")
        
        # 恢复system_status.json
        restore_to_system_status(model, account_data, positions)
        
        # 恢复trades_history.csv（只添加缺失的持仓记录）
        restore_to_trades_history(model, orders, positions)
    
    print("\n" + "=" * 60)
    print("✅ 数据恢复完成！")
    print("=" * 60)
    print("\n💡 下一步:")
    print("   1. 重启后端服务")
    print("   2. 刷新前端页面")
    print("   3. 验证数据是否正确")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ 用户中断")
    except Exception as e:
        print(f"\n\n❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()

